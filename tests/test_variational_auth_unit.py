"""Offline authentication lifecycle tests; no wallet or exchange API is used."""

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, web

from mpdex.exchanges import variational as exchange_module
from mpdex.exchanges import variational_auth as auth_module
from mpdex.exchanges import variational_turnstile as turnstile


ADDRESS = "0x" + "1" * 40
LOGIN_RESPONSE = {"json": {"token": "offline-token"}, "cookies": {"vr-token": "offline-token"}}


class AuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mpdex-auth-test-")
        self.addCleanup(directory.cleanup)
        for name in ("_cache_path", "_home_cache_path"):
            mocked = patch.object(auth_module.VariationalAuth, name, return_value=str(Path(directory.name) / name))
            mocked.start()
            self.addCleanup(mocked.stop)
        env = patch.dict(os.environ, {
            turnstile.ENV_TOKEN: "", turnstile.ENV_CMD: "", turnstile.ENV_MODE: "",
        })
        env.start()
        self.addCleanup(env.stop)

    async def start_flow(self, prepare):
        auth = auth_module.VariationalAuth(ADDRESS)
        auth._prepare_captcha = prepare
        auth._generate_signing_data_async = AsyncMock(return_value={"message": "offline-message", "nonce": "nonce"})
        auth._login_request = AsyncMock(return_value=LOGIN_RESPONSE)
        ready = asyncio.Event()
        sites = []

        class CapturedSite(web.TCPSite):
            async def start(self):
                await super().start()
                sites.append(self)
                ready.set()

        mocked = patch.object(auth_module.web, "TCPSite", CapturedSite)
        mocked.start()
        self.addCleanup(mocked.stop)
        flow = asyncio.create_task(auth._browser_login_flow(0, open_browser=False))

        async def stop_flow():
            if not flow.done():
                flow.cancel()
            await asyncio.gather(flow, return_exceptions=True)

        self.addAsyncCleanup(stop_flow)
        await asyncio.wait_for(ready.wait(), timeout=2)
        site = sites[0]
        port = site._server.sockets[0].getsockname()[1]
        client = ClientSession()
        self.addAsyncCleanup(client.close)
        return auth, flow, client, f"http://127.0.0.1:{port}", site

    async def test_background_and_signing_request_share_solver(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def solve():
            started.set()
            await release.wait()
            return "offline-captcha"

        prepare = AsyncMock(side_effect=solve)
        auth, flow, client, url, _ = await self.start_flow(prepare)
        await asyncio.wait_for(started.wait(), 1)
        request = asyncio.create_task(client.get(url + "/signing-data", params={"address": ADDRESS}))
        try:
            await asyncio.sleep(0.05)
            self.assertEqual(prepare.await_count, 1)
            self.assertIsNotNone(auth._pre_task)
        finally:
            release.set()
        async with await request as response:
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["nonce"], "nonce")

        # Crossing the warm-up threshold while signing must not start another solver.
        auth._pre_token_at = time.monotonic() - 190
        async with client.post(url + "/submit", json={"address": ADDRESS, "signed_message": "signature"}) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue((await response.json())["ok"])
        await asyncio.wait_for(flow, 2)
        self.assertEqual(prepare.await_count, 1)
        self.assertEqual(auth._login_request.await_args.kwargs["token"], "offline-captcha")
        self.assertIsNone(auth._pre_task)

    async def test_cancel_login_drains_solver_and_closes_server(self):
        started, stopped = asyncio.Event(), asyncio.Event()

        async def solve():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        auth, flow, _, _, site = await self.start_flow(AsyncMock(side_effect=solve))
        await asyncio.wait_for(started.wait(), 1)
        flow.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await flow
        self.assertTrue(stopped.is_set())
        self.assertIsNone(auth._pre_task)
        self.assertFalse(site._server.is_serving())
        self.assertFalse(site._server.sockets)

    async def test_failed_solver_does_not_issue_short_lived_message(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def solve():
            started.set()
            await release.wait()
            raise turnstile.TurnstileError("offline solver failed")

        prepare = AsyncMock(side_effect=solve)
        auth, _, client, url, _ = await self.start_flow(prepare)
        await asyncio.wait_for(started.wait(), 1)
        request = asyncio.create_task(client.get(url + "/signing-data", params={"address": ADDRESS}))
        await asyncio.sleep(0.05)
        release.set()
        async with await request as response:
            self.assertEqual(response.status, 500)
            self.assertIn("offline solver failed", (await response.json())["error"])
        self.assertEqual(prepare.await_count, 1)
        auth._generate_signing_data_async.assert_not_awaited()

    async def test_none_mode_allows_private_key_login_without_solver(self):
        auth = auth_module.VariationalAuth(ADDRESS, evm_private_key="offline", options={"turnstile_mode": "none"})
        auth._generate_signing_data_async = AsyncMock(return_value={"message": "offline", "nonce": "nonce"})
        auth._personal_sign_local = lambda *args: "signature"
        auth._login_request = AsyncMock(return_value=LOGIN_RESPONSE)
        with patch.object(turnstile, "solve", new_callable=AsyncMock) as solver:
            response = await auth.login()
        self.assertTrue(response["ok"])
        solver.assert_not_awaited()
        self.assertIsNone(auth._login_request.await_args.kwargs["token"])

    async def test_exchange_honors_environment_mode(self):
        with patch.dict(os.environ, {turnstile.ENV_MODE: "manual"}), \
             patch.object(exchange_module, "_load_vr_ll_token_from_cache", return_value=None), \
             patch.object(turnstile, "_solve_browser", new_callable=AsyncMock) as browser:
            exchange = exchange_module.VariationalExchange(evm_wallet_address=ADDRESS)
            with self.assertRaisesRegex(turnstile.TurnstileError, "수동 토큰 없음"):
                await exchange._auth._prepare_captcha()
            browser.assert_not_awaited()

    async def test_explicit_browser_mode_does_not_reuse_manual_token(self):
        auth = auth_module.VariationalAuth(ADDRESS, options={"turnstile_mode": "browser"})
        with patch.dict(os.environ, {turnstile.ENV_TOKEN: "stale-manual-token"}), \
             patch.object(turnstile, "_solve_browser", new=AsyncMock(
                 return_value=turnstile.CaptchaSolution("new-token"))) as browser:
            self.assertEqual(await auth._prepare_captcha(), "new-token")
            browser.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
