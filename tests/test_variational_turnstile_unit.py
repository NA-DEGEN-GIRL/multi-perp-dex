"""Offline Chrome lifecycle tests; subprocesses and browser I/O are mocked."""

import asyncio
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from mpdex.exchanges import variational_turnstile as turnstile


ENDPOINT = "ws://127.0.0.1:12345/devtools/browser/offline"


class TurnstileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mpdex-chrome-test-")
        self.addCleanup(directory.cleanup)
        self.cache = Path(directory.name)
        self.profile = self.cache / "persistent-profile"
        self.profile.mkdir()

    async def test_startup_io_does_not_block_event_loop(self):
        proc = MagicMock()
        proc.poll.return_value = None

        def launch(*args):
            time.sleep(0.1)
            return proc

        def read(*args):
            time.sleep(0.1)
            return ENDPOINT

        ticks = []

        async def heartbeat():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.01)

        beat = asyncio.create_task(heartbeat())
        try:
            with patch.object(turnstile, "_launch_chrome", side_effect=launch), \
                 patch.object(turnstile, "_read_debugger_url", side_effect=read):
                got_proc, endpoint = await turnstile._start_chrome(12345, self.profile, True, time.monotonic() + 2)
            self.assertIs(got_proc, proc)
            self.assertEqual(endpoint, ENDPOINT)
            self.assertGreater(len(ticks), 5)
        finally:
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)

    async def test_cancel_during_launch_still_reaps_process(self):
        proc = MagicMock()
        proc.poll.return_value = None
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def launch(*args):
            loop.call_soon_threadsafe(started.set)
            release.wait(timeout=2)
            return proc

        with patch.object(turnstile, "_launch_chrome", side_effect=launch):
            task = asyncio.create_task(turnstile._start_chrome(12345, self.profile, True, time.monotonic() + 5))
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()

    async def test_startup_timeout_reaps_process(self):
        proc = MagicMock()
        proc.poll.return_value = None
        with patch.object(turnstile, "_launch_chrome", return_value=proc), \
             patch.object(turnstile, "_read_debugger_url", side_effect=OSError("offline refused")):
            with self.assertRaisesRegex(turnstile.TurnstileError, "디버그 포트 응답 시간 초과"):
                await turnstile._start_chrome(12345, self.profile, True, time.monotonic() + 0.03)
        proc.terminate.assert_called_once()

    def fake_playwright(self, connect):
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=SimpleNamespace(
            chromium=SimpleNamespace(connect_over_cdp=connect)))
        manager.__aexit__ = AsyncMock(return_value=False)
        return manager

    async def test_cdp_failure_preserves_cause_and_retries_isolated_profile(self):
        connect = AsyncMock(side_effect=RuntimeError("ECONNREFUSED offline"))
        manager = self.fake_playwright(connect)
        proc = MagicMock()
        start = AsyncMock(return_value=(proc, ENDPOINT))
        with patch.object(turnstile, "available", return_value=True), \
             patch.object(turnstile, "_start_chrome", new=start), \
             patch.object(turnstile, "_kill") as kill, \
             patch("patchright.async_api.async_playwright", return_value=manager):
            with self.assertRaisesRegex(turnstile.TurnstileError, "ECONNREFUSED offline"):
                await turnstile._solve_browser(headless=True, timeout_s=5, profile_dir=self.profile)
        self.assertEqual(connect.await_count, 2)
        self.assertEqual(kill.call_count, 2)
        first_profile = start.await_args_list[0].args[1]
        second_profile = start.await_args_list[1].args[1]
        self.assertEqual(first_profile, self.profile.resolve())
        self.assertNotEqual(first_profile, second_profile)
        self.assertFalse(second_profile.exists())
        for call in connect.await_args_list:
            self.assertEqual(call.args[0], ENDPOINT)
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 30000)
        self.assertEqual(list(self.cache.iterdir()), [self.profile])

    async def test_cdp_and_retry_work_without_system_temp(self):
        page = MagicMock()
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        browser = SimpleNamespace(contexts=[context], close=AsyncMock())
        artifacts = []
        marker = self.profile / "keep.txt"
        marker.write_text("persistent profile", encoding="utf-8")

        async def connect(endpoint, *, artifacts_dir, timeout):
            path = Path(artifacts_dir)
            self.assertTrue(path.is_dir())
            self.assertEqual(path.parent.parent, self.cache.resolve())
            (path / "trace.txt").write_text("temporary artifact", encoding="utf-8")
            artifacts.append(path)
            if len(artifacts) == 1:
                raise RuntimeError("retry with a separate profile")
            return browser

        manager = self.fake_playwright(AsyncMock(side_effect=connect))
        start = AsyncMock(return_value=(MagicMock(), ENDPOINT))
        with patch.object(turnstile, "available", return_value=True), \
             patch.object(turnstile, "_start_chrome", new=start), \
             patch.object(turnstile, "_kill"), \
             patch.object(turnstile, "_harvest", new=AsyncMock(return_value=turnstile.CaptchaSolution("offline"))), \
             patch("tempfile.gettempdir", side_effect=PermissionError("system TEMP is unavailable")), \
             patch("patchright.async_api.async_playwright", return_value=manager):
            result = await turnstile._solve_browser(headless=True, timeout_s=5, profile_dir=self.profile)

        self.assertEqual(result.token, "offline")
        self.assertEqual(len(artifacts), 2)
        self.assertNotEqual(artifacts[0], artifacts[1])
        self.assertEqual(start.await_args_list[1].args[1].parent, artifacts[1].parent)
        self.assertTrue(all(not path.parent.exists() for path in artifacts))
        self.assertEqual(marker.read_text(encoding="utf-8"), "persistent profile")
        self.assertEqual(list(self.cache.iterdir()), [self.profile])
        browser.close.assert_awaited_once()

    async def test_cancel_harvest_closes_browser_and_reaps_process(self):
        page = MagicMock()
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        browser = SimpleNamespace(contexts=[context], close=AsyncMock())
        manager = self.fake_playwright(AsyncMock(return_value=browser))
        started = asyncio.Event()

        async def harvest(*args):
            started.set()
            await asyncio.Event().wait()

        proc = MagicMock()
        with patch.object(turnstile, "available", return_value=True), \
             patch.object(turnstile, "_start_chrome", new=AsyncMock(return_value=(proc, ENDPOINT))), \
             patch.object(turnstile, "_harvest", side_effect=harvest), \
             patch.object(turnstile, "_kill") as kill, \
             patch("patchright.async_api.async_playwright", return_value=manager):
            task = asyncio.create_task(turnstile._solve_browser(headless=True, timeout_s=5, profile_dir=self.profile))
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        browser.close.assert_awaited_once()
        manager.__aexit__.assert_awaited_once()
        kill.assert_called_once_with(proc)
        self.assertEqual(list(self.cache.iterdir()), [self.profile])

    async def test_command_cancellation_kills_and_drains_child(self):
        started = asyncio.Event()
        calls = 0

        async def communicate():
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await asyncio.Event().wait()
            return b"", b""

        proc = SimpleNamespace(returncode=None, kill=MagicMock(), communicate=AsyncMock(side_effect=communicate))
        with patch.object(asyncio, "create_subprocess_exec", new=AsyncMock(return_value=proc)):
            task = asyncio.create_task(turnstile._solve_cmd("offline-command", action="login"))
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        proc.kill.assert_called_once()
        self.assertEqual(proc.communicate.await_count, 2)

    async def test_command_mode_without_command_does_not_launch_browser(self):
        with patch.dict(os.environ, {turnstile.ENV_CMD: ""}), \
             patch.object(turnstile, "_solve_browser", new_callable=AsyncMock) as browser:
            with self.assertRaisesRegex(turnstile.TurnstileError, "외부 해결 명령 없음"):
                await turnstile.solve({"turnstile_mode": "cmd"})
            browser.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
