"""
omni.variational.io 로그인의 Cloudflare Turnstile 자동 해결.

배경
----
Variational 웹이 ``POST /api/auth/login`` 앞에 Cloudflare 챌린지를 붙였다. 서명만 만들어
POST하면 ``403 cf-mitigated: challenge`` ("Just a moment...")로 막힌다. 웹 프론트엔드는
로그인 요청에 Turnstile 토큰을 붙여 통과한다(번들에서 확인):

  - 헤더: ``cf-turnstile-token: <token>``, ``cf-turnstile-interactive: true``
  - 바디: ``{"address", "signed_message", "nonce", "captchaToken"}``

이 모듈이 그 토큰을 브라우저로 자동 발급한다.

레시피(실측으로 확정)
---------------------
1. Chrome을 playwright가 아니라 **직접** Popen으로 띄운다(``--remote-debugging-port``).
   playwright가 launch하면 ``--enable-automation`` 등 때문에 챌린지가 안 풀리거나 매우 느리다.
   직접 띄운 프로세스는 통과한다.
2. ``connect_over_cdp``로 붙는다(``--remote-allow-origins=*`` 필요).
3. omni.variational.io 가 챌린지 인터스티셜이면 체크박스를 **좌표 클릭**해 ``cf_clearance``를
   받고, 앱 문서가 뜰 때까지 기다린다.
4. 앱 페이지에서 Turnstile 위젯을 명시적으로 렌더해 토큰을 받는다. (챌린지 문서 안에서
   렌더하면 600010으로 실패하므로 반드시 앱 문서에서 렌더한다.)
5. 토큰 + ``cf_clearance``/``__cf_bm`` + UA를 돌려준다. 요청은 curl_cffi가 같은 IP에서 보낸다.

프로필을 재사용(user_data_dir)하므로 한 번 통과하면 이후 로그인은 챌린지 없이 빠르다.

모드(옵션 ``turnstile_mode`` / 환경변수 ``VARIATIONAL_TURNSTILE_MODE``)
  - ``auto``    : 수동 토큰 → 외부 명령 → 브라우저 (기본)
  - ``browser`` : 브라우저만
  - ``cmd``     : 외부 명령만 (``turnstile_cmd`` / ``VARIATIONAL_TURNSTILE_CMD``)
  - ``manual``  : ``turnstile_token`` / ``VARIATIONAL_TURNSTILE_TOKEN`` 만
  - ``none``    : 해결 안 함

수동/외부 폴백
  - ``VARIATIONAL_TURNSTILE_TOKEN``: DevTools에서 ``cf-turnstile-token`` 헤더 값을 복사(1회용).
  - ``VARIATIONAL_TURNSTILE_CMD``: capsolver/2captcha 스크립트. ``{sitekey}``/``{url}``/``{action}``
    치환 지원, stdout 마지막 줄을 토큰으로 사용.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

ORIGIN = "https://omni.variational.io"
LOGIN_PAGE = f"{ORIGIN}/login"
TURNSTILE_SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
SITEKEY = "0x4AAAAAAA2uzUXt_KvBDwd3"
LOGIN_ACTION = "login"

ENV_TOKEN = "VARIATIONAL_TURNSTILE_TOKEN"
ENV_CMD = "VARIATIONAL_TURNSTILE_CMD"
ENV_MODE = "VARIATIONAL_TURNSTILE_MODE"
ENV_CHROME = "VARIATIONAL_CHROME_PATH"
ENV_VERBOSE = "VARIATIONAL_TURNSTILE_VERBOSE"


def _log(*args: Any) -> None:
    if os.environ.get(ENV_VERBOSE):
        print("[turnstile]", *args, flush=True)

#: curl_cffi 쪽으로 넘길 쿠키(엣지 챌린지 통과용)
_COOKIE_NAMES = ("cf_clearance", "__cf_bm")

_CHROME_CANDIDATES = (
    ENV_CHROME and os.environ.get(ENV_CHROME),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


class TurnstileError(RuntimeError):
    """Turnstile 토큰을 못 뽑았을 때."""


@dataclass
class CaptchaSolution:
    token: str
    cookies: Dict[str, str] = field(default_factory=dict)
    user_agent: Optional[str] = None
    mode: str = "browser"


# ----------------------------------------------------------------------------
# 공개 API
# ----------------------------------------------------------------------------
async def solve(
    options: Optional[Dict[str, Any]] = None,
    *,
    action: str = LOGIN_ACTION,
    profile_dir: Optional[str | Path] = None,
) -> CaptchaSolution:
    """
    Turnstile 토큰(+통과용 쿠키/UA)을 반환. 실패하면 :class:`TurnstileError`.

    options
      turnstile_mode        : auto|browser|cmd|manual|none
      turnstile_token       : 수동 토큰. 키가 있으면 env보다 우선(빈 문자열이면 env 무시)
      turnstile_cmd         : 외부 해결 명령 템플릿
      turnstile_headless    : 기본 False(headful). True면 headless 시도 후 실패 시 headful 폴백
      turnstile_timeout_s   : 전체 시한(기본 240)
      turnstile_profile_dir : 프로필 경로 재정의
    """
    opts = options or {}
    mode = str(opts.get("turnstile_mode") or os.environ.get(ENV_MODE) or "auto").strip().lower()

    if mode == "none":
        raise TurnstileError("turnstile_mode=none")

    raw_tok = opts["turnstile_token"] if "turnstile_token" in opts else os.environ.get(ENV_TOKEN)
    token = (raw_tok or "").strip()
    if token and mode in ("auto", "manual"):
        return CaptchaSolution(token=token, mode="manual")
    if mode == "manual":
        raise TurnstileError(
            f"수동 토큰 없음: {ENV_TOKEN} 또는 options['turnstile_token']을 설정하세요."
        )

    cmd = (opts.get("turnstile_cmd") or os.environ.get(ENV_CMD) or "").strip()
    if mode == "cmd" and not cmd:
        raise TurnstileError(f"외부 해결 명령 없음: {ENV_CMD} 또는 options['turnstile_cmd']을 설정하세요.")
    if cmd and mode in ("auto", "cmd"):
        try:
            return await _solve_cmd(cmd, action=action)
        except Exception as e:  # noqa: BLE001
            if mode == "cmd":
                raise TurnstileError(f"turnstile_cmd 실패: {e}") from e
            print(f"[variational] turnstile_cmd 실패({e}) → 브라우저로 폴백")

    headless = bool(opts.get("turnstile_headless", False))
    timeout_s = float(opts.get("turnstile_timeout_s", 240))
    pdir = profile_dir or opts.get("turnstile_profile_dir")

    if headless:
        try:
            return await _solve_browser(headless=True, timeout_s=timeout_s, profile_dir=pdir, action=action)
        except Exception as e:  # noqa: BLE001
            print(f"[variational] turnstile headless 실패({e}) → headful 재시도")
    return await _solve_browser(headless=False, timeout_s=timeout_s, profile_dir=pdir, action=action)


def available() -> bool:
    """브라우저 해결기가 이 환경에서 돌 수 있는지."""
    try:
        import patchright  # noqa: F401
    except Exception:
        return False
    return _chrome_path() is not None


def describe_unavailable() -> str:
    missing = []
    try:
        import patchright  # noqa: F401
    except Exception:
        missing.append("patchright 미설치(pip install patchright)")
    if _chrome_path() is None:
        missing.append(f"Chrome 실행 파일 못 찾음({ENV_CHROME}로 지정 가능)")
    return (
        "; ".join(missing)
        + f". 브라우저 없이 쓰려면 {ENV_CMD}(외부 해결 명령) 또는 {ENV_TOKEN}(수동 토큰)."
    )


# ----------------------------------------------------------------------------
# 실행 파일 / 프로필
# ----------------------------------------------------------------------------
def _chrome_path() -> Optional[str]:
    for c in _CHROME_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def _default_profile_dir() -> Path:
    base = Path.cwd() / ".cache"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        base = Path.home() / ".cache" / "mpdex"
        base.mkdir(parents=True, exist_ok=True)
    return base / "variational_browser"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _kill(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


def _launch_chrome(port: int, profile: Path, headless: bool) -> subprocess.Popen:
    exe = _chrome_path()
    if not exe:
        raise TurnstileError(describe_unavailable())
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,900",
    ]
    if headless:
        args.append("--headless=new")
    args.append("about:blank")
    kw: Dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.Popen(args, **kw)  # type: ignore[arg-type]


def _read_debugger_url(port: int) -> str:
    # 로컬 CDP 조회가 HTTP_PROXY 등의 영향을 받지 않게 한다.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
        data = json.load(response)
    endpoint = data.get("webSocketDebuggerUrl")
    if not isinstance(endpoint, str) or not endpoint.startswith("ws://"):
        raise TurnstileError("Chrome 응답에 webSocketDebuggerUrl이 없습니다")
    return endpoint


async def _start_chrome(
    port: int, profile: Path, headless: bool, deadline: float
) -> Tuple[subprocess.Popen, str]:
    """실행/포트 확인은 이벤트 루프 밖에서 처리하고 실패/취소 시 자식 프로세스를 회수한다."""
    loop = asyncio.get_running_loop()
    launch = loop.run_in_executor(None, _launch_chrome, port, profile, headless)
    proc = None
    try:
        # 취소돼도 실행 스레드가 반환하는 Popen을 받아 정리할 수 있어야 한다.
        proc = await asyncio.shield(launch)
        startup_deadline = min(deadline, time.monotonic() + 30.0)
        last_err: Optional[Exception] = None
        while time.monotonic() < startup_deadline:
            if proc.poll() is not None:
                raise TurnstileError(f"Chrome이 디버그 포트를 열기 전에 종료됨(code={proc.returncode})")
            try:
                endpoint = await loop.run_in_executor(None, _read_debugger_url, port)
                return proc, endpoint
            except Exception as e:
                last_err = e
            await asyncio.sleep(0.2)
        raise TurnstileError(f"Chrome 디버그 포트 응답 시간 초과: {last_err}")
    except BaseException:
        if proc is None:
            try:
                proc = await launch
            except Exception:
                pass
        await loop.run_in_executor(None, _kill, proc)
        raise


# ----------------------------------------------------------------------------
# 외부 명령 해결기
# ----------------------------------------------------------------------------
async def _solve_cmd(cmd: str, *, action: str) -> CaptchaSolution:
    subst = {"sitekey": SITEKEY, "url": LOGIN_PAGE, "action": action, "pageurl": quote(LOGIN_PAGE, safe="")}
    argv = [a.format(**subst) for a in shlex.split(cmd, posix=os.name != "nt")]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()
        if isinstance(e, asyncio.TimeoutError):
            raise TurnstileError("turnstile_cmd 시간초과(180s)") from None
        raise
    if proc.returncode != 0:
        tail = (err or b"").decode("utf-8", "replace").strip()[-300:]
        raise TurnstileError(f"turnstile_cmd 종료코드 {proc.returncode}: {tail}")
    lines = [ln.strip() for ln in (out or b"").decode("utf-8", "replace").splitlines() if ln.strip()]
    if not lines:
        raise TurnstileError("turnstile_cmd 출력이 비었습니다")
    return CaptchaSolution(token=lines[-1], mode="cmd")


# ----------------------------------------------------------------------------
# 브라우저 해결기
# ----------------------------------------------------------------------------
async def _solve_browser(
    *, headless: bool, timeout_s: float, profile_dir: Optional[str | Path] = None, action: str = LOGIN_ACTION
) -> CaptchaSolution:
    if not available():
        raise TurnstileError(describe_unavailable())
    from patchright.async_api import async_playwright

    deadline = time.monotonic() + max(1.0, timeout_s)
    pdir = (Path(profile_dir) if profile_dir else _default_profile_dir()).resolve()
    loop = asyncio.get_running_loop()
    last_err: Optional[BaseException] = None

    for attempt in range(2):
        if time.monotonic() >= deadline:
            break
        # 점유된 공용 프로필의 Chrome은 건드리지 않는다. 재시도는 호출마다 고유한 프로필로 한다.
        isolated_dir = tempfile.mkdtemp(prefix="mpdex-turnstile-") if attempt else None
        prof = Path(isolated_dir) if isolated_dir else pdir
        proc = None
        try:
            proc, endpoint = await _start_chrome(_free_port(), prof, headless, deadline)
            async with async_playwright() as p:
                browser = None
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TurnstileError("CDP 연결 전 전체 제한시간 초과")
                    try:
                        # 드라이버 자체의 timeout으로 연결을 종료한다. wait_for로 Python 대기만
                        # 취소한 뒤 같은 드라이버에 연결 요청을 여섯 번 중첩시키지 않는다.
                        browser = await p.chromium.connect_over_cdp(
                            endpoint, timeout=min(30.0, remaining) * 1000
                        )
                    except Exception as e:  # noqa: BLE001
                        raise TurnstileError(f"CDP 연결 실패: {type(e).__name__}: {e}") from e
                    ctx = browser.contexts[0]
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TurnstileError("CDP 연결 후 전체 제한시간 초과")
                    page = await asyncio.wait_for(ctx.new_page(), timeout=remaining)
                    page.set_default_timeout(20_000)
                    return await asyncio.wait_for(
                        _harvest(page, ctx, deadline, action),
                        timeout=max(0.001, deadline - time.monotonic()),
                    )
                finally:
                    if browser is not None:
                        try:
                            await asyncio.wait_for(browser.close(), timeout=5)
                        except Exception:
                            pass
        except Exception as e:  # noqa: BLE001
            last_err = e
            _log("attempt failed:", type(e).__name__, e)
            if attempt == 0:
                print(f"[variational] turnstile 시도 실패({e}) → 1회 재시도")
        finally:
            await loop.run_in_executor(None, _kill, proc)
            if isolated_dir:
                # 이번 호출에서 만든 임시 디렉터리만 제거한다.
                await loop.run_in_executor(None, shutil.rmtree, isolated_dir, True)
    raise TurnstileError(f"Turnstile 해결 실패: {last_err}")


def _ok(v: Any) -> bool:
    return isinstance(v, str) and len(v) > 20 and not v.startswith('<EVAL')


async def _ev(page, js: str, arg: Any = None, timeout: float = 20) -> Any:
    try:
        return await asyncio.wait_for(page.evaluate(js, arg, isolated_context=False), timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return f"<EVAL {type(e).__name__}: {str(e)[:60]}>"


async def _screenshot(page, tag: str) -> None:
    try:
        await page.screenshot(path=str(Path.cwd() / ".cache" / f"turnstile_{tag}.png"))
    except Exception:
        pass


async def _is_app(page) -> bool:
    """앱 문서가 떴는지(챌린지 인터스티셜 탈출 여부)."""
    v = await _ev(
        page,
        "() => !window._cf_chl_opt && (!!document.querySelector('script[type=module][src]')"
        " || location.pathname !== '/login')",
        timeout=8,
    )
    if v is True:
        return True
    try:
        return any((f.url or "").startswith(ORIGIN) and "/perpetual/" in (f.url or "") for f in page.frames)
    except Exception:
        return False


async def _harvest(page, ctx, deadline: float, action: str) -> CaptchaSolution:
    await page.goto(LOGIN_PAGE, wait_until="commit")
    await asyncio.sleep(2)
    _log("navigated:", page.url[:80])

    # 챌린지 인터스티셜이면 체크박스를 좌표 클릭해서 cf_clearance를 받는다.
    clicked = 0
    while True:
        if await _is_app(page):
            _log("app reached")
            break
        if time.monotonic() >= deadline:
            await _screenshot(page, "timeout")
            raise TurnstileError("챌린지 통과 시간 초과")
        if clicked < 4:
            for f in page.frames:
                if "challenges.cloudflare.com" not in (f.url or ""):
                    continue
                for sel in ("input[type=checkbox]", "label", "#challenge-stage"):
                    try:
                        box = await asyncio.wait_for(f.locator(sel).first.bounding_box(timeout=1000), timeout=8)
                    except Exception:
                        box = None
                    if box:
                        try:
                            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                            clicked += 1
                            _log(f"clicked {sel} at", box, "clicked=", clicked)
                        except Exception as e:  # noqa: BLE001
                            _log("click err", e)
                        break
                break
        else:
            _log("no cf frame to click; frames=", [f.url[:50] for f in page.frames])
        await asyncio.sleep(1.5)

    await asyncio.sleep(2)
    # 앱 문서 확보(가끔 바로 안 뜬다 → 재이동)
    for _ in range(3):
        if await _is_app(page):
            break
        try:
            await page.goto(LOGIN_PAGE, wait_until="commit")
        except Exception:
            pass
        await asyncio.sleep(4)

    token = await _read_app_widget(page)
    if not token:
        token = await _render_own_widget(page, deadline, action)
    if not token:
        raise TurnstileError("Turnstile 토큰 콜백 없음")

    cookies: Dict[str, str] = {}
    try:
        for c in await ctx.cookies(ORIGIN):
            if c.get("name") in _COOKIE_NAMES and c.get("value"):
                cookies[c["name"]] = c["value"]
    except Exception:
        pass
    ua = await _ev(page, "() => navigator.userAgent", timeout=8)
    return CaptchaSolution(
        token=token,
        cookies=cookies,
        user_agent=ua if isinstance(ua, str) else None,
        mode="browser",
    )


async def _read_app_widget(page) -> Optional[str]:
    """사이트가 이미 렌더한 위젯이 통과했으면 그 토큰을 회수(0.5초×10)."""
    js = """() => {
      const ts = window.turnstile;
      if (!ts || typeof ts.getResponse !== 'function') return null;
      const el = document.querySelector('[id^="cf-ch"], .cf-turnstile');
      try { return (el && el.id ? ts.getResponse(el.id) : ts.getResponse()) || null; } catch (e) { return null; }
    }"""
    for _ in range(10):
        v = await _ev(page, js, timeout=8)
        if _ok(v):
            return v
        await asyncio.sleep(0.5)
    return None


async def _click_cf(page) -> bool:
    """challenges.cloudflare.com 프레임의 체크박스를 좌표 클릭(인터랙티브 강제 시)."""
    clicked = False
    try:
        frames = [f for f in page.frames if "challenges.cloudflare.com" in (f.url or "")]
    except Exception:
        return False
    for f in frames:
        for sel in ("input[type=checkbox]", "label", "#challenge-stage"):
            try:
                box = await asyncio.wait_for(f.locator(sel).first.bounding_box(timeout=800), timeout=6)
            except Exception:
                box = None
            if box:
                try:
                    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    _log("clicked widget", sel)
                    clicked = True
                except Exception:
                    pass
                break
    return clicked


_RENDER_JS = """
async ([sitekey, action, src, appearance, execution]) => {
  if (!document.getElementById('__ts_api')) {
    const s = document.createElement('script');
    s.id = '__ts_api'; s.src = src; s.async = true;
    document.head.appendChild(s);
  }
  for (let i = 0; i < 60; i++) {
    if (window.turnstile && typeof window.turnstile.render === 'function') break;
    await new Promise(r => setTimeout(r, 250));
  }
  if (!window.turnstile || typeof window.turnstile.render !== 'function') return 'no-lib';
  const old = document.getElementById('__ts_host');
  if (old) old.remove();
  const host = document.createElement('div');
  host.id = '__ts_host';
  host.style.cssText = 'position:fixed;left:8px;top:8px;z-index:2147483647;background:#fff;width:320px;height:90px';
  document.body.appendChild(host);
  window.__ts_t = null;
  window.__ts_e = null;
  const opts = {
    sitekey, action,
    callback: (t) => { window.__ts_t = t; },
    'error-callback': (e) => { window.__ts_e = String(e); },
  };
  if (appearance) opts.appearance = appearance;
  if (execution) opts.execution = execution;
  window.__ts_id = window.turnstile.render(host, opts);
  return 'rendered';
}
"""


async def _render_own_widget(page, deadline: float, action: str) -> Optional[str]:
    """
    앱 문서(같은 origin)에서 위젯을 직접 렌더해 토큰을 받는다.

    실측: 위젯이 렌더되고 토큰은 대략 10~20초 뒤에 온다(느린 경우 40초+).
    그래서 전략당 45초를 기다리고, 토큰이 늦으면 클릭도 함께 시도한다.
    """
    strategies = ((None, "render"), ("always", "render"), ("interaction-only", "execute"))
    for appearance, execution in strategies:
        r = await _ev(page, _RENDER_JS, [SITEKEY, action, TURNSTILE_SCRIPT, appearance, execution], timeout=60)
        _log("render:", r, appearance, execution)
        if r == "no-lib":
            return None
        if execution == "execute" and r == "rendered":
            await _ev(page, "() => { try { window.turnstile.execute(window.__ts_id); } catch (e) {} }", timeout=10)
        sub_deadline = min(deadline, time.monotonic() + 45)
        last_click = 0.0
        while time.monotonic() < sub_deadline:
            tok = await _ev(page, "() => window.__ts_t", timeout=10)
            if _ok(tok):
                return tok
            err = await _ev(page, "() => window.__ts_e", timeout=10)
            if isinstance(err, str) and err and not err.startswith("<EVAL"):
                _log("widget error:", err)
            if time.monotonic() - last_click > 4:
                last_click = time.monotonic()
                await _click_cf(page)
            await asyncio.sleep(0.8)
    return None

