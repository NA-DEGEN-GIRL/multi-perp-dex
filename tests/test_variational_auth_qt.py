"""Offline regression for Windows browser launching inside a qasync task."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


@unittest.skipUnless(
    sys.platform == "win32" and importlib.util.find_spec("qasync"),
    "requires Windows and qasync with a Qt binding",
)
class QtAuthTests(unittest.TestCase):
    def run_probe(self, mode):
        # A regression can discard task callbacks, including asyncio timeouts.
        # Isolate the Qt loop so the test runner can always enforce its deadline.
        result = subprocess.run(
            [sys.executable, "-m", "tests.test_variational_auth_qt", "--probe", mode],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_first_login_finishes_after_native_browser_event_pump(self):
        self.run_probe("login")

    def test_cancellation_finishes_after_native_browser_event_pump(self):
        self.run_probe("cancel")


def _run_probe(mode):
    import asyncio
    import gc
    import tempfile
    import warnings
    from unittest.mock import AsyncMock, patch

    from aiohttp import ClientSession, web
    from qasync import QEventLoop, QtCore
    from mpdex.exchanges import variational_auth as auth_module

    app = QtCore.QCoreApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    errors = []
    loop.set_exception_handler(lambda _, ctx: errors.append(str(ctx.get("exception", ctx.get("message")))))

    def native_browser_open(url):
        # Model ShellExecute dispatching Windows/Qt events before it returns.
        nested = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(40, nested.quit)
        nested.exec()
        return True

    async def exercise():
        auth = auth_module.VariationalAuth("0x" + "1" * 40)
        auth._prepare_captcha = AsyncMock(return_value="offline-captcha")
        auth._generate_signing_data_async = AsyncMock(return_value={"message": "offline", "nonce": "nonce"})
        auth._login_request = AsyncMock(return_value={"json": {"token": "offline-token"}})
        ready, sites = asyncio.Event(), []

        class Site(web.TCPSite):
            async def start(self):
                await super().start()
                sites.append(self)
                ready.set()

        with patch.object(auth_module.web, "TCPSite", Site):
            flow = asyncio.create_task(auth._browser_login_flow(0, open_browser=True))
            try:
                # Let the native browser launcher pump its event queue first.
                await asyncio.sleep(0.1)
                await ready.wait()
                if mode == "cancel":
                    flow.cancel()
                    try:
                        await flow
                    except asyncio.CancelledError:
                        pass
                    else:
                        raise AssertionError("login cancellation did not propagate")
                else:
                    port = sites[0]._server.sockets[0].getsockname()[1]
                    url = f"http://127.0.0.1:{port}"
                    async with ClientSession() as client:
                        async with client.get(url + "/signing-data", params={"address": auth.wallet_address}) as response:
                            assert response.status == 200, await response.text()
                        async with client.post(url + "/submit", json={
                            "address": auth.wallet_address, "signed_message": "offline-signature",
                        }) as response:
                            assert response.status == 200, await response.text()
                            assert (await response.json())["ok"]
                    print("[probe] login response received; waiting for cleanup", flush=True)
                    assert (await flow)["ok"]
                auth._prepare_captcha.assert_awaited_once()
                assert auth._pre_task is None
                assert not sites[0]._server.is_serving()
            finally:
                if not flow.done():
                    flow.cancel()
                await asyncio.gather(flow, return_exceptions=True)

    # A native timer still runs even if a nested event loop discards asyncio tasks.
    watchdog = QtCore.QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.stop)
    watchdog.start(5000)
    with tempfile.TemporaryDirectory(prefix="mpdex-qt-auth-") as directory, \
         patch.object(auth_module.VariationalAuth, "_cache_path", return_value=str(Path(directory) / "session.json")), \
         patch.object(auth_module.VariationalAuth, "_home_cache_path", return_value=str(Path(directory) / "home-session.json")), \
         patch.object(auth_module.webbrowser, "open", side_effect=native_browser_open), \
         warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", RuntimeWarning)
        with loop:
            task = loop.create_task(exercise())
            task.add_done_callback(lambda _: loop.stop())
            loop.run_forever()
            watchdog.stop()
            if not task.done():
                for pending in asyncio.all_tasks(loop):
                    pending.cancel()
                raise AssertionError(f"Qt login did not finish: {errors}")
            task.result()
        gc.collect()
        assert not errors, errors
        runtime_warnings = [str(w.message) for w in seen if issubclass(w.category, RuntimeWarning)]
        assert not runtime_warnings, runtime_warnings


if __name__ == "__main__":
    if sys.argv[1:2] == ["--probe"]:
        _run_probe(sys.argv[2])
    else:
        unittest.main()
