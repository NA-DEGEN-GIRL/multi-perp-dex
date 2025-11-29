# hyperliquid with treadfi (order by treadfi front api)
# price and get position directly by hyperliquid ws (to do)
from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from importlib import resources
import aiohttp
from aiohttp import web
from aiohttp import TCPConnector
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any
from eth_account import Account  
from eth_account.messages import encode_defunct  

class TreadfiHlExchange(MultiPerpDexMixin, MultiPerpDex):
	def __init__(
        self,
        session_cookies: Optional[Dict[str, str]] = None,
        evm_private_key: Optional[str] = None,
		main_wallet_address: str = None, # required
        sub_wallet_address: str = None, # optional
        account_name: str = None, # required
		options: Any = None, # options
    ):
		# used for signing
		self.main_wallet_address = main_wallet_address

		# sub_wallet_address will be used for get_position, get_collateral from HL ws
		# if not given -> same as main_wallet
		self.sub_wallet_address = sub_wallet_address if sub_wallet_address else main_wallet_address

		self.walletAddress = None # ccxt style

		self.account_name = account_name
		self.url_base = "https://app.tread.fi/"
		self._http: Optional[aiohttp.ClientSession] = None
		self._logged_in = False
		self._cookies = session_cookies or {}
		self._pk = evm_private_key
		self._login_event: Optional[asyncio.Event] = None

		self._http: Optional[aiohttp.ClientSession] = None

		self.options = None # for purpose

		self.login_html_path = os.environ.get(
            "TREADFI_LOGIN_HTML",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "wrappers/", "treadfi_login.html")),
        )
		
		# 쿠키 유효성 정리: "", None 은 없는 것으로 간주
		self._normalize_or_clear_cookies()  # 빈 문자열/None -> 제거

		# 세션 쿠키가 유효하지 않다면 로컬 캐시에서 우선 로드
		if not self._has_valid_cookies():
			print("No cookies are in given. Checking cached cookies in local dir..")
			self._load_cached_cookies()
	
	def _session(self) -> aiohttp.ClientSession:
		if self._http is None or self._http.closed:
			# [CHANGED] SSL 소켓 정리 강화 + keep-alive 강제 해제
			self._http = aiohttp.ClientSession(
				connector=TCPConnector(
					force_close=True,             # 매 요청 후 소켓 닫기 → 종료 시 잔여 소켓 최소화
					enable_cleanup_closed=True,   # 종료 중인 SSL 소켓 정리 보조 (로그 억제)
				)
			)
		return self._http
	
	async def aclose(self):  # [ADDED]
		if self._http and not self._http.closed:
			await self._http.close()

	# 4) 컨텍스트 매니저(선택) 추가: async with TreadfiHlExchange(...) as ex:
	async def __aenter__(self):  # [ADDED]
		return self

	async def __aexit__(self, exc_type, exc, tb):  # [ADDED]
		await self.aclose()

    # ----------------------------
    # HTML (브라우저 지갑 서명 UI)
    # ----------------------------
	def _login_html(self) -> str:
		"""
		최소 UI: 계정 요청 -> 메시지 수신 -> personal_sign -> 제출
		"""
		return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>TreadFi Sign-In</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 24px; }}
.row {{ margin: 8px 0; }}
input, textarea, button {{ font-size: 14px; }}
input, textarea {{ width: 100%; max-width: 560px; }}
.addr {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
</style>
</head>
<body>
<h2>TreadFi Login</h2>
<div class="row"><button id="connect">Connect Wallet</button></div>
<div class="row addr" id="address"></div>
<div class="row"><input id="msg" placeholder="Message to sign" /></div>
<div class="row"><button id="sign">Sign & Login</button></div>
<div class="row">Result:</div>
<div class="row"><textarea id="result" rows="3"></textarea></div>
<script>
let account = null, lastNonce = null;

async function fetchNonce() {{
const r = await fetch('/nonce');
const j = await r.json();
if (j.error) throw new Error(j.error);
lastNonce = j.nonce;
document.getElementById('msg').value = j.message;
}}
window.addEventListener('load', () => {{
fetchNonce().catch(e => alert('Failed to get nonce: ' + e.message));
}});

document.getElementById('connect').onclick = async () => {{
if (!window.ethereum) {{ alert('Please install Rabby or MetaMask'); return; }}
const acc = await window.ethereum.request({{ method: 'eth_requestAccounts' }});
account = acc[0];
document.getElementById('address').innerText = 'Wallet: ' + account;
}};

document.getElementById('sign').onclick = async () => {{
if (!account) return alert('Please connect your wallet first.');
const msg = document.getElementById('msg').value;
if (!msg) return alert('No message to sign.');
try {{
const sign = await window.ethereum.request({{
method: 'personal_sign',
params: [msg, account],
}});
document.getElementById('result').value = sign;

const resp = await fetch('/submit', {{
method: 'POST',
headers: {{ 'Content-Type': 'application/json' }},
body: JSON.stringify({{ address: account, signature: sign, nonce: lastNonce }})
}});
const text = await resp.text();
if (!resp.ok) throw new Error(text);
alert(text);
}} catch (e) {{
alert('Signing/Submit failed: ' + e.message);
}}
}};
</script>
</body>
</html>
"""

	async def login(self):
		"""
		1) session cookies가 있을경우 get_user_metadata 를 통해 정상 session인지 확인, 아닐시 2)->3)
		2) private key가 있을경우 msg 서명 -> signature 생성 -> session cookies udpate
		3) 1, 2둘다 없을 경우 webserver를 간단히 구동하여 msg 서명하게함 -> 서명시 signature 값 받아서 -> session cookies update
		2) or 3)의 경우도 get_user_metadata를 통해 data 확인후 "is_authenticated" 가 True면 login 확정
		서명 메시지
		"Sign in to Tread with nonce: {nonce}"
		"""

		# 1) 캐시/입력 쿠키로 바로 검증
		if self._has_valid_cookies():
			md = await self._get_user_metadata()
			if md.get("is_authenticated"):
				print("Login authenticated!")
				self._logged_in = True
				self._save_cached_cookies()
				return md
			else:
				print(f"Cache is outdated...{md}")
				print(f"Auto redirecting to PK signing or Web signing")
		
		# 2) 프라이빗키로 서명
		if self._pk:
			if Account is None or encode_defunct is None:
				raise RuntimeError("eth_account 미설치. pip install eth-account")
			nonce = await self._get_nonce()
			msg = f"Sign in to Tread with nonce: {nonce}"
			acct = Account.from_key(self._pk)
			sign = Account.sign_message(encode_defunct(text=msg), private_key=self._pk).signature.hex()
			await self._wallet_auth(acct.address, sign, nonce)
			md = await self._get_user_metadata()
			if not md.get("is_authenticated"):
				raise RuntimeError("login failed with private key")
			else:
				print("Login authenticated!")
			self._logged_in = True
			self._save_cached_cookies()
			return md

		# 3) 브라우저 서명 (포트 6974)
		self._login_event = asyncio.Event()

		async def handle_index(_req: web.Request):
			return web.Response(text=self._login_html(), content_type="text/html")

		async def handle_nonce(_req):
			try:
				nonce = await self._get_nonce()
				msg = f"Sign in to Tread with nonce: {nonce}"
				return web.json_response({"nonce": nonce, "message": msg})
			except Exception as e:
				return web.json_response({"error": str(e)}, status=500)

		async def handle_submit(req):
			try:
				body = await req.json()
				address = body.get("address")
				signature = body.get("signature")
				nonce = body.get("nonce")
				if not (address and signature and nonce):
					return web.Response(status=400, text="missing address/signature/nonce")

				await self._wallet_auth(address, signature, nonce)

				md = await self._get_user_metadata()
				if not md.get("is_authenticated"):
					return web.Response(status=400, text="login failed")

				self._logged_in = True
				self._login_event.set()
				return web.Response(text="Login success. You can close this tab.")
			except Exception as e:
				# 프론트에서 alert로 보는 메시지
				return web.Response(status=500, text=f"submit error: {e}")

		app = web.Application()
		app.router.add_get("/", handle_index)
		app.router.add_get("/nonce", handle_nonce)
		app.router.add_post("/submit", handle_submit)

		runner = web.AppRunner(app)
		await runner.setup()
		site = web.TCPSite(runner, "127.0.0.1", 6974)
		await site.start()

		print("[treadfi_hl] Open http://127.0.0.1:6974 in your browser to sign the message")
		await self._login_event.wait()
		await runner.cleanup()

		md = await self._get_user_metadata()
		if not md.get("is_authenticated"):
			raise RuntimeError("login failed after browser sign")
		else:
			print("Login authenticated!")
		self._logged_in = True
		self._save_cached_cookies()
		return md

	def _addr_lower(self, address: str) -> str:  
		return "0x" + address[2:].lower()

	async def _get_nonce(self) -> str:  
		s = self._session()
		headers = {"Origin": self.url_base.rstrip("/"), "Referer": self.url_base, **self._cookie_header()}
		async with s.get(self.url_base + "internal/account/get_nonce/", headers=headers) as r:
			data = await r.json()
			nonce = data.get("nonce")
			if not nonce:
				raise RuntimeError(f"failed to get nonce: {data}")
			return nonce

	async def _wallet_auth(self, address: str, signature: str, nonce: str) -> Dict[str, str]:  
		s = self._session()
		payload = {
			"address": self._addr_lower(address),
			"signature": signature,
			"nonce": nonce,
			"wallet_type": "evm",
		}
		headers = {"Origin": self.url_base.rstrip("/"), "Referer": self.url_base, "Content-Type": "application/json"}
		async with s.post(self.url_base + "internal/account/wallet_auth/", json=payload, headers=headers) as r:
			text = await r.text()
			if r.status != 200:
				raise RuntimeError(f"wallet_auth failed: {r.status} {text}")

			# Set-Cookie 직접 수집 (redirect 포함)
			def _collect(resp: aiohttp.ClientResponse):
				out = {}
				for res in list(resp.history) + [resp]:
					for k, morsel in (res.cookies or {}).items():
						out[k] = morsel.value
				return out

			setcookies = _collect(r)
			ct_val = setcookies.get("csrftoken")
			sid_val = setcookies.get("sessionid")

		if not ct_val or not sid_val:
			raise RuntimeError("missing csrftoken/sessionid after wallet_auth")

		self._cookies = {"csrftoken": ct_val, "sessionid": sid_val}
		self._normalize_or_clear_cookies()
		self.main_wallet_address = self._addr_lower(address)
		self._save_cached_cookies()
		return self._cookies

	# ---------------------------
    # 로컬 캐시 유틸
    # ---------------------------
	def _find_project_root_from_cwd(self) -> Path:
		"""
		현재 작업 디렉터리에서 시작해 상위로 올라가며
		프로젝트 루트(marker 파일/폴더) 후보를 탐색한다.
		"""
		markers = {"pyproject.toml", "setup.cfg", "setup.py", ".git"}
		p = Path.cwd().resolve()
		try:
			for parent in [p] + list(p.parents):
				for name in markers:
					if (parent / name).exists():
						return parent
		except Exception:
			pass
		return Path.cwd().resolve()

	def _resolve_cache_base(self) -> Path:
		"""
		캐시 베이스 디렉터리 결정 순서:
		CWD 기준 프로젝트 루트(상위로 스캔)
		"""
		# CWD에서 프로젝트 루트 추정
		return self._find_project_root_from_cwd()

	def _cache_dir(self) -> str:
		"""
		최종 캐시 디렉터리 경로 반환.
		- 기본: <프로젝트루트>/.cache
		- 쓰기 권한 실패 시: ~/.cache/mpdex
		"""
		# [CHANGED] 패키지 폴더 기준 → 프로젝트 루트 기준으로 변경
		base = self._resolve_cache_base()
		target = (base / ".cache")

		try:
			target.mkdir(parents=True, exist_ok=True)
			return str(target)
		except Exception:
			# 권한/컨테이너 등 이슈 시 사용자 홈 캐시로 fallback
			home_fallback = Path.home() / ".cache" / "mpdex"
			home_fallback.mkdir(parents=True, exist_ok=True)
			return str(home_fallback)

	def _cache_path(self) -> str:
		# signing for mainwallet
		addr = (self.main_wallet_address or "default").lower()
		if addr and not addr.startswith("0x"):
			addr = f"0x{addr}"
		safe = addr.replace(":", "_")
		return os.path.join(self._cache_dir(), f"treadfi_session_{safe}.json")

	def _load_cached_cookies(self) -> bool:
		try:
			path = self._cache_path()
			if not os.path.exists(path):
				return False
			with open(path, "r", encoding="utf-8") as f:
				data = json.load(f)
			csrftoken, sessionid = data.get("csrftoken"), data.get("sessionid")
			if csrftoken and sessionid:
				self._cookies = {"csrftoken": csrftoken, "sessionid": sessionid}
				return True
			return False
		except Exception:
			return False

	def _save_cached_cookies(self) -> None:
		try:
			if not (self._cookies.get("csrftoken") and self._cookies.get("sessionid")):
				return
			if not self.main_wallet_address:
				return
			payload = {
				"csrftoken": self._cookies["csrftoken"],
				"sessionid": self._cookies["sessionid"],
				"main_wallet_address": self.main_wallet_address,
				"saved_at": int(time.time()),
			}
			with open(self._cache_path(), "w", encoding="utf-8") as f:
				json.dump(payload, f, ensure_ascii=False, indent=2)
		except Exception:
			pass

	def _clear_cached_cookies(self) -> None:
		try:
			p = self._cache_path()
			if os.path.exists(p):
				os.remove(p)
		except Exception:
			pass

	# ---------------------------
	# 쿠키 유효성/정리 헬퍼
	# ---------------------------
	def _has_valid_cookies(self, cookies: Optional[Dict[str, str]] = None) -> bool:
		"""
		True if csrftoken, sessionid 둘 다 존재하고 빈 문자열/None이 아님.
		"""
		c = (cookies if cookies is not None else self._cookies) or {}
		ct = c.get("csrftoken")
		sid = c.get("sessionid")
		return bool(ct) and bool(sid)

	def _normalize_or_clear_cookies(self) -> None:
		"""
		빈 문자열("")/None은 제거하여 '없는 것'으로 처리.
		"""
		c = self._cookies or {}
		ct = c.get("csrftoken")
		sid = c.get("sessionid")
		# 둘 중 하나라도 비어 있으면 전체를 비움(부분 유효는 의미 없음)
		if not ct or not sid:
			self._cookies = {}

	def _cookie_header(self) -> Dict[str, str]:
		# 모든 요청에서 Cookie 헤더를 직접 구성
		if not self._has_valid_cookies():
			return {}
		return {"Cookie": f"csrftoken={self._cookies['csrftoken']}; sessionid={self._cookies['sessionid']}"}

	async def _get_user_metadata(self) -> dict:
		s = self._session()
		headers = {"Origin": self.url_base.rstrip("/"), "Referer": self.url_base, **self._cookie_header()}
		async with s.get(self.url_base + "internal/account/user_metadata/", headers=headers) as r:
			# 상태/본문을 그대로 반환(디버그가 쉬움)
			try:
				data = await r.json()
			except Exception:
				text = await r.text()
				raise RuntimeError(f"user_metadata bad response: {r.status} {text}")
			return data

	async def logout(self):
		if not self._has_valid_cookies():
			self._clear_cached_cookies()
			return {"ok": True, "detail": "already logged out"}

		s = self._session()
		url = self.url_base + "account/logout/"

		headers = {
			"X-CSRFToken": self._cookies.get("csrftoken", ""),   # <- CSRF 헤더
			"Origin": self.url_base.rstrip("/"),
			"Referer": self.url_base,                  # <- .dev/treadfi_logout.py와 동일(루트)
			"Content-Type": "application/json",
			"Accept": "*/*",
			"User-Agent": "Mozilla/5.0",
			**self._cookie_header(),                             # <- 쿠키는 수동 첨부
		}

		# 본문 없이 POST, 리다이렉트 미추적
		async with s.post(url, headers=headers, allow_redirects=False) as r:
			text = await r.text()
			status = r.status

		# 성공으로 간주할 범위(로그아웃은 종종 302로 리다이렉트됨)
		success_status = {200, 302}
		# Django 계열이 이미 세션을 끊은 후 403 CSRF HTML을 보내는 경우도 성공으로 간주
		if status in success_status or ("CSRF verification failed" in text and status == 403):  # [ADDED]
			result = {"ok": True, "status": int(status), "text": text}
		else:
			result = {"ok": False, "status": int(status), "text": text}

		# 세션/쿠키 정리는 로컬에서 항상 수행
		self._logged_in = False
		self._cookies = {}
		self._clear_cached_cookies()
		# (선택) 세션을 여기서 닫고 싶다면 aclose가 있다면 호출
		if hasattr(self, "aclose"):
			await self.aclose()
		return result
	
	def parse_orders(self, orders):
		if not orders:
			return []

		# 단일 dict일 경우 리스트로 감싸기
		if isinstance(orders, dict):
			orders = [orders]

		parsed = []
		for order in orders:
			parsed.append({
				"id": order.get("id"),
				"symbol": order.get("pair"),
				"type": order.get("super_strategy").lower(),
				"side": order.get("side").lower(),
				"amount": order.get("target_order_qty"),
				"price": order.get("limit_price")
			})

		return parsed

	async def create_order(self, symbol, side, amount, price=None, order_type='market'):
		"""
		symbol: 변환돼서 들어옴
		side: 'buy' | 'sell'
		amount: base_asset_qty (예: 0.002)
		price: limit 주문시에만 사용
		order_type: 'market' | 'limit'
		"""
		if not self._logged_in:
			print("Need login...")
			await self.login()
		if not self._has_valid_cookies():
			raise RuntimeError("not logged in: missing session cookies")

		s = self._session()

		# 전략 ID 간단 상수
		limit_order_st = "c94f84c7-72ef-4bc6-b13c-d2ff10bbd8eb"
		market_order_st = "847de9f1-8310-4a79-b76e-8559cdfe7b81"

		if price:
			order_type = "limit" # auto redirecting to limit order

		if order_type == "market":
			order_st = market_order_st
			st_param = {"reduce_only": False, "ool_pause": False, "entry": False, "max_clip_size": None}
		else:
			if price is None:
				raise ValueError("limit order requires price")
			order_st = limit_order_st
			st_param = {"reduce_only": False, "ool_pause": True, "entry": False, "max_clip_size": None}

		payload = {
			"accounts": [self.account_name],
			"base_asset_qty": amount,
			"pair": symbol,
			"side": side,
			"strategy": order_st,
			"strategy_params": st_param,
			"duration": 86400,
			"engine_passiveness": 0.02,
			"schedule_discretion": 0.06,
			"order_slices": 2,
			"alpha_tilt": 0,
		}
		
		if order_type == "limit":
			payload["limit_price"] = price
		
		headers = {
			"Content-Type": "application/json",
			"X-CSRFToken": self._cookies["csrftoken"],
			"Origin": self.url_base.rstrip("/"),
			"Referer": self.url_base,
			**self._cookie_header(),
		}
		
		async with s.post(self.url_base + "api/orders/", data=json.dumps(payload), headers=headers) as r:
			txt = await r.text()
			try:
				data = json.loads(txt)
			except Exception:
				data = {"status": r.status, "text": txt}
			return self.parse_orders(data)

	async def get_position(self, symbol):
		# to do, using ws
		pass
	
	async def close_position(self, symbol, position):
		return await super().close_position(symbol, position)
	
	async def get_collateral(self):
		# to do, using ws
		pass
	
	async def get_open_orders(self, symbol):
		pass
	
	async def cancel_orders(self, symbol):
		pass

	async def get_mark_price(self,symbol):
		# to do
		pass