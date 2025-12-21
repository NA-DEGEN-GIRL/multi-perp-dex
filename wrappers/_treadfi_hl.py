from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from mpdex.utils.common_hyperliquid import (
	parse_hip3_symbol,
	#init_spot_token_map,
	#get_dex_list,
	#init_perp_meta_cache,
	init_shared_hl_cache,
	get_shared_hl_cache,
	STABLES,
	STABLES_DISPLAY
)
from .hyperliquid_ws_client import HLWSClientRaw, WS_POOL
import aiohttp
from aiohttp import web, TCPConnector
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from eth_account import Account  
from eth_account.messages import encode_defunct  

HL_BASE_URL = "https://api.hyperliquid.xyz"
BASE_WS = "wss://api.hyperliquid.xyz/ws"

class TreadfiHlExchange(MultiPerpDexMixin, MultiPerpDex):
	# To do: hyperliquid의 ws를 사용해서 position과 가격을 fetch하도록 수정할것
	# tread.fi는 자체 front api를 사용하여 주문을 넣기때문에 builder code와 fee를 따로 설정안해도댐.
	def __init__(
		self,
		session_cookies: Optional[Dict[str, str]] = None,
		login_wallet_address: str = None, 	# required
		login_wallet_private_key: Optional[str] = None,
		trading_wallet_address: str = None, # optional, 만약 로그인 주소랑 다르면 넣어야함
		account_name: str = None, # required
		fetch_by_ws: bool = True, # price and position
		options: Any = None, # options
	):
		# used for signing
		self.login_wallet_address = login_wallet_address

		# trading_wallet_address will be used for get_position, get_collateral from HL ws
		# if not given -> same as main_wallet
		self.trading_wallet_address = trading_wallet_address if trading_wallet_address else login_wallet_address

		self.walletAddress = None # ccxt style

		self.account_name = account_name
		self.account_id = None
		self.fetch_by_ws = fetch_by_ws # use WS_POOL

		self.url_base = "https://app.tread.fi/"
		self._http: Optional[aiohttp.ClientSession] = None
		self._logged_in = False
		self._cookies = session_cookies or {}
		self._login_pk = login_wallet_private_key
		self._login_event: Optional[asyncio.Event] = None

		self._http: Optional[aiohttp.ClientSession] = None
		
		self.ws_base = BASE_WS
		self.spot_index_to_name = {}
		self.spot_name_to_index = {}
		self.spot_asset_index_to_pair = {}
		self.spot_asset_pair_to_index = {}
		self.spot_asset_index_to_bq = {}
		self.spot_prices = None
		self.dex_list = ['hl', 'xyz', 'flx', 'vntl', 'hyna'] # default

		self.spot_token_sz_decimals: Dict[str, int] = {}
		self._perp_meta_inited: bool = False
		self.perp_metas_raw: Optional[List[dict]] = []
		# 키 → (asset_id, szDecimals, maxLeverage, onlyIsolated, collateralToken)
		#  - 메인(HL): 'BTC' (대문자)
		#  - HIP-3:    'xyz:XYZ100' (원문 그대로)
		self.perp_asset_map: Dict[str, Tuple[int, int, int, bool, int]] = {}

		self._leverage_updated_to_max = False
	
		# WS 관련 내부 상태
		self.ws_client: Optional[HLWSClientRaw] = None  # WS_POOL에서
		self._ws_pool_key = None                        # comment: release 시 사용
		
		#self._ws_init_lock = asyncio.Lock()             # comment: create_ws_client 중복 호출 방지
		self.fetch_by_ws = fetch_by_ws

		self.options = options

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
	
	async def init(self):
		login_md = await self.login()
		if not self._logged_in:
			raise RuntimeError(f"not logged-in {login_md}")
		
		self.account_id = await self.get_account_id()

		s = self._session()
		cache = await init_shared_hl_cache(session=s)
		#print(get_shared_hl_cache())
		# [CHANGED] 인스턴스 필드에 공유 캐시 참조 연결(복사 아님, 같은 dict 공유)
		self.dex_list = cache["dex_list"]
		self.spot_index_to_name = cache["spot_index_to_name"]
		self.spot_name_to_index = cache["spot_name_to_index"]
		self.spot_asset_index_to_pair = cache["spot_asset_index_to_pair"]
		self.spot_asset_pair_to_index = cache["spot_asset_pair_to_index"]
		self.spot_asset_index_to_bq = cache["spot_asset_index_to_bq"]
		self.spot_token_sz_decimals = cache["spot_token_sz_decimals"]
		self.perp_metas_raw = cache["perp_metas_raw"]
		self.perp_asset_map = cache["perp_asset_map"]

		"""
		await init_spot_token_map(
			s,
			self.spot_index_to_name,
			self.spot_name_to_index,
			self.spot_asset_index_to_pair,
			self.spot_asset_index_to_bq,
			self.spot_token_sz_decimals,
			) # spot meta
		self.dex_list = await get_dex_list(s)        # perpDexs 리스트 (webData3 순서)

		try:
			await init_perp_meta_cache(
				s, 
				self.perp_metas_raw,
				self.perp_asset_map
				)
		except Exception:
			pass
		"""
		try:
			await WS_POOL.prime_shared_meta(
				dex_order=self.dex_list or ['hl', 'xyz', 'flx', 'vntl', 'hyna'],
				idx2name=self.spot_index_to_name or {},
				name2idx=self.spot_name_to_index or {},
				pair_by_index=self.spot_asset_index_to_pair or {},
				bq_by_index=self.spot_asset_index_to_bq or {},
			)
		except Exception:
			pass
		
		# reverse id
		self.spot_asset_pair_to_index = {
			v: k for k, v in (self.spot_asset_index_to_pair or {}).items()
		}
		
		if self.fetch_by_ws:
			await self._create_ws_client()

		return self
	
	def get_perp_quote(self, symbol, need_to_convert=False):
		
		if need_to_convert:
			raw = str(self._symbol_convert_for_ws(symbol)).strip()
		else:
			raw = str(symbol).strip()

		dex, coin_key = parse_hip3_symbol(raw)
		_, _, _, _, quote_id = self.perp_asset_map.get(coin_key,(None, 0, 1, False, 0))
		quote = self.spot_index_to_name.get(quote_id,'USDC')
		return quote

	def _symbol_convert_for_ws(self, symbol:str):
		# perp -> BTC:PERP-USDC / xyz_XYZ100:PERP-USDC
		# spot -> BTC-USDC
		if ':' in symbol:
			is_spot = False
		else:
			is_spot = True

		if is_spot:
			base = symbol.split('-')[0]
			quote = symbol.split('-')[1]
			return f"{base}/{quote}" # ex) BTC/USDC
		else:
			front = symbol.split(':')[0]
			end = symbol.split(':')[1]
			
			dex = f"{front.split('_')[0]}:" if '_' in front else ""
			base = front.split('_')[1] if '_' in front else front

			quote = end.split('-')[1]

			return f"{dex}{base}" # ex) xyz:XYZ100, BTC

	async def _create_ws_client(self):
		"""
		WS 커넥션을 '1회 연결 + 다중 구독'으로 운용.
		- 전역 풀(WS_POOL)에서 (ws_url,address) 키로 하나를 획득하여 공유
		- 인스턴스 내부에서 중복 acquire를 방지
		"""
		#async with self._ws_init_lock:
		#if self.ws_client is not None:
		#	return self.ws_client
		
		address = self.trading_wallet_address
		# acquire에 메타를 전달(풀 내부에서 최초 1회만 반영)
		client = await WS_POOL.acquire(
			ws_url=self.ws_base,
			http_base=HL_BASE_URL,
			address=address,
			dex=None,
			dex_order=self.dex_list or ['hl', 'xyz', 'flx', 'vntl', 'hyna'],
			idx2name=self.spot_index_to_name or {},
			name2idx=self.spot_name_to_index or {},
			pair_by_index=self.spot_asset_index_to_pair or {},
			bq_by_index=self.spot_asset_index_to_bq or {},
		)
		# 추가 DEX 구독
		for dex in (self.dex_list or []):
			if dex != "hl":
				await client.ensure_allmids_for(dex)

		self.ws_client = client
		self._ws_pool_key = (self.ws_base, (address or "").lower())
		#print(self._ws_pool_key)
		#return self.ws_client

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
	
	async def close(self):
		if self._http and not self._http.closed:
			await self._http.close()
		if self._ws_pool_key and self.ws_client:
			ws_url, addr = self._ws_pool_key
			try:
				# comment: 특정 소켓을 명시적으로 해제
				await WS_POOL.release(ws_url=ws_url, address=addr, client=self.ws_client)
			except Exception:
				pass
			finally:
				self._ws_pool_key = None
				self.ws_client = None


	# 4) 컨텍스트 매니저(선택) 추가: async with TreadfiHlExchange(...) as ex:
	#async def __aenter__(self):  # [ADDED]
	#	return self

	#async def __aexit__(self, exc_type, exc, tb):  # [ADDED]
	#	await self.aclose()

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
		if self._login_pk:
			if Account is None or encode_defunct is None:
				raise RuntimeError("eth_account 미설치. pip install eth-account")
			nonce = await self._get_nonce()
			msg = f"Sign in to Tread with nonce: {nonce}"
			acct = Account.from_key(self._login_pk)
			sign = Account.sign_message(encode_defunct(text=msg), private_key=self._login_pk).signature.hex()
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
		self.login_wallet_address = self._addr_lower(address)
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
		addr = (self.login_wallet_address or "default").lower()
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
			if not self.login_wallet_address:
				return
			payload = {
				"csrftoken": self._cookies["csrftoken"],
				"sessionid": self._cookies["sessionid"],
				"login_wallet_address": self.login_wallet_address,
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
	

	async def get_account_id(self) -> str | None:
		"""
		GET https://app.tread.fi/internal/sor/get_cached_account_balance
		- query: account_names=<self.account_name>
		- 응답의 balances[*].account_name == self.account_name 인 항목의 account_id 반환
		- 없으면 None
		"""
		if not self._has_valid_cookies():
			raise RuntimeError("not logged in: missing session cookies")

		if not self.account_name:
			raise ValueError("self.account_name is empty")

		s = self._session()
		url = self.url_base + "internal/sor/get_cached_account_balance"

		params = {"account_names": self.account_name}
		headers = {
			"Accept": "*/*",
			"X-CSRFToken": self._cookies["csrftoken"],
			"Origin": self.url_base.rstrip("/"),
			"Referer": self.url_base,
			**self._cookie_header(),  # comment: 세션 쿠키 포함
		}

		async with s.get(url, params=params, headers=headers) as r:
			r.raise_for_status()
			# comment: content-type이 json이 아닐 수도 있어 예외 처리
			try:
				data = await r.json()
			except Exception:
				text = await r.text()
				raise RuntimeError(f"get_account_id: unexpected response ({r.status}): {text[:200]}")

		# 기대 구조: {"balances":[{...,"account_name":"...", "account_id":"..."}], ...}
		balances = data.get("balances") or []
		if not isinstance(balances, list):
			return None

		for item in balances:
			if not isinstance(item, dict):
				continue
			if item.get("account_name") == self.account_name:
				acc_id = item.get("account_id")
				if isinstance(acc_id, str) and acc_id:
					return acc_id

		return None

	async def update_leverage(self, symbol, leverage=None):
		
		if self._leverage_updated_to_max:
			return {"message":"already updated!"}

		symbol_ws = self._symbol_convert_for_ws(symbol)
		_, _, max_leverage, only_isolated, _ = self.perp_asset_map.get(symbol_ws, (None,None,1,False))
		margin_mode = "ISOLATED" if only_isolated else "CROSS"
		
		if not leverage:
			leverage = max_leverage

		payload = {
			"account_ids": [self.account_id],
			"margin_mode": margin_mode,
			"pair": symbol,
			"leverage":leverage
		}
		#print(payload)
		
		headers = {
			"Content-Type": "*/*",
			"X-CSRFToken": self._cookies["csrftoken"],
			"Origin": self.url_base.rstrip("/"),
			"Referer": self.url_base,
			**self._cookie_header(),
		}

		s = self._session()
		async with s.post(self.url_base + "internal/sor/set_leverage", data=json.dumps(payload), headers=headers) as r:
			txt = await r.text()
			try:
				data = json.loads(txt)
			except Exception:
				data = {"status": r.status, "text": txt}
			
			if data.get("message") == "Leverage changed successfully.":
				self._leverage_updated_to_max = True
			return data			
			

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

	async def create_order(self, symbol, side, amount, price=None, order_type='market', *, is_reduce_only=False):
		"""
		symbol: 변환돼서 들어옴
		side: 'buy' | 'sell'
		amount: base_asset_qty (예: 0.002)
		price: limit 주문시에만 사용
		order_type: 'market' | 'limit'
		"""
		#if not self._logged_in:
		#print("Need login...")
		#await self.login()
		if not self._has_valid_cookies():
			raise RuntimeError("not logged in: missing session cookies")

		res = await self.update_leverage(symbol)
		#print(res)

		s = self._session()

		# 전략 ID 간단 상수
		limit_order_st = "c94f84c7-72ef-4bc6-b13c-d2ff10bbd8eb"
		market_order_st = "847de9f1-8310-4a79-b76e-8559cdfe7b81"

		if price:
			order_type = "limit" # auto redirecting to limit order

		if order_type == "market":
			order_st = market_order_st
			st_param = {"reduce_only": is_reduce_only, "ool_pause": False, "entry": False, "max_clip_size": None}
		else:
			if price is None:
				raise ValueError("limit order requires price")
			order_st = limit_order_st
			st_param = {"reduce_only": is_reduce_only, "ool_pause": True, "entry": False, "max_clip_size": None}

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
		"""
		주어진 perp 심볼에 대한 단일 포지션 요약을 반환합니다.
		반환 스키마:
		  {"entry_price": float|None, "unrealized_pnl": float|None, "side": "long"|"short"|"flat", "size": float}
		"""
		symbol_ws = self._symbol_convert_for_ws(symbol)
		if self.fetch_by_ws:
			try:
				pos = await self.get_position_ws(symbol_ws, timeout=2.0)
				if pos is not None:
					return pos
			except Exception:
				pass
		
		return await self.get_position_rest(symbol_ws)

	async def get_position_ws(self, symbol: str, timeout: float = 2.0, dex: str | None = None) -> dict:
		"""
		webData3(WS 캐시)에서 조회. 스냅샷 미도착 시 timeout까지 짧게 대기합니다.
		dex를 지정하지 않으면 self.dex_list 순서대로 검색합니다.
		"""
		address = self.trading_wallet_address
		if not address:
			return None
		if not self.ws_client:
			await self._create_ws_client()
		deadline = time.monotonic() + timeout
		while time.monotonic() < deadline:
			if self.ws_client.get_positions_norm_for_user(address):
				break
			await asyncio.sleep(0.05)
		pos_by_dex = self.ws_client.get_positions_norm_for_user(address)
		sym = str(symbol).upper().strip()
		# dex 지정시 우선
		if dex:
			pm = pos_by_dex.get(dex.lower(), {})
			pos = pm.get(sym)
			if pos:
				parsed = self._parse_position_core(pos)
				if parsed["size"] and parsed["side"] != "flat":
					return parsed
			return None
		# 전체 DEX 검색
		for pm in pos_by_dex.values():
			pos = pm.get(sym)
			if pos:
				parsed = self._parse_position_core(pos)
				if parsed["size"] and parsed["side"] != "flat":
					return parsed
		return None
	
	async def get_position_rest(self, symbol: str, dex: str | None = None) -> dict:
		"""
		REST clearinghouseState를 dex별로 조회하여 포지션을 찾습니다.
		dex를 지정하지 않으면 self.dex_list 순서대로 검색합니다.
		"""
		address = self.trading_wallet_address
		if not address:
			return None

		url = f"{HL_BASE_URL}/info"
		headers = {"Content-Type": "application/json"}
		s = self._session()

		def _dex_param(name: Optional[str]) -> str:
			k = (name or "").strip().lower()
			return "" if (k == "" or k == "hl") else k

		sym = str(symbol).strip().upper()
		dex_iter = [dex] if dex else list(dict.fromkeys(self.dex_list or ["hl"]))

		for d in dex_iter:
			payload = {"type": "clearinghouseState", "user": address, "dex": _dex_param(d)}
			try:
				async with s.post(url, json=payload, headers=headers) as r:
					data = await r.json()
			except aiohttp.ContentTypeError:
				continue
			except Exception:
				continue

			aps = (data or {}).get("assetPositions") or []
			for ap in aps:
				pos = (ap or {}).get("position") or {}
				coin = str(pos.get("coin") or "").upper()
				if coin != sym:
					continue
				parsed = self._parse_position_core(pos)
				if parsed["size"] and parsed["side"] != "flat":
					return parsed

		return None

	def _parse_position_core(self, pos: dict) -> dict:
		"""
		clearinghouseState.assetPositions[*].position 또는 WS 정규화 포맷을
		표준 스키마로 변환합니다.
		반환 스키마:
		{"entry_price": float|None, "unrealized_pnl": float|None, "side": "long"|"short"|"flat", "size": float}
		"""
		def fnum(x, default=None):
			try:
				return float(x)
			except Exception:
				return default

		# WS 정규화 포맷(이미 float) 대응
		if "entry_px" in pos or "upnl" in pos or "size" in pos:
			size = fnum(pos.get("size"), 0.0) or 0.0
			side = pos.get("side") or ("long" if size > 0 else ("short" if size < 0 else "flat"))
			return {
				"entry_price": fnum(pos.get("entry_px")),
				"unrealized_pnl": fnum(pos.get("upnl"), 0.0),
				"side": side,
				"size": abs(size),
			}

		# REST 원본 포맷 대응
		size_signed = fnum(pos.get("szi"), 0.0) or 0.0
		side = "long" if size_signed > 0 else ("short" if size_signed < 0 else "flat")
		return {
			"entry_price": fnum(pos.get("entryPx")),
			"unrealized_pnl": fnum(pos.get("unrealizedPnl"), 0.0),
			"side": side,
			"size": abs(size_signed),
		}

	async def close_position(self, symbol, position):
		return await super().close_position(symbol, position, is_reduce_only=True)
	
	async def get_collateral(self):
		if self.fetch_by_ws:
			try:
				return await self.get_collateral_ws()
			except:
				pass
		
		# fall back to rest api
		try:
			return await self.get_collateral_rest()
		except:
			return {
				"available_collateral":None,
				"total_collateral": None,
				"spot": {disp: None for disp in STABLES_DISPLAY},
			}
	
	async def get_collateral_rest(self):
		"""
		REST 기반 담보 조회(WS 폴백용):
		- Perp: POST {http_base}/info {"type":"clearinghouseState", "user": <addr>, "dex": <""|name>}
				 → marginSummary.accountValue, withdrawable 합산
		- Spot: POST {http_base}/info {"type":"spotClearinghouseState", "user": <addr>}
				 → balances[].total 중 스테이블만 추출(USDC, USDT/USDT0, USDH)

		반환: {
		  "available_collateral": float|None,
		  "total_collateral": float|None,
		  "spot": {"USDH": float|None, "USDC": float|None, "USDT": float|None}
		}
		"""
		address = self.trading_wallet_address
		if not address:
			return {
				"available_collateral": None,
				"total_collateral": None,
				"spot": {disp: None for disp in STABLES_DISPLAY},
			}

		url = f"{HL_BASE_URL}/info"
		headers = {"Content-Type": "application/json"}
		s = self._session()

		# ---------------- Perp: clearinghouseState 집계 ----------------
		def _dex_param(name: Optional[str]) -> str:
			k = (name or "").strip().lower()
			return "" if (k == "" or k == "hl") else k

		dex_order = list(dict.fromkeys(self.dex_list or ["hl"]))  # 순서 유지 + 중복 제거

		async def _fetch_ch(dex_name: str) -> tuple[float, float]:
			payload = {"type": "clearinghouseState", "user": address, "dex": _dex_param(dex_name)}
			try:
				async with s.post(url, json=payload, headers=headers) as r:
					data = await r.json()
			except aiohttp.ContentTypeError:
				return (0.0, 0.0)
			except Exception:
				return (0.0, 0.0)
			try:
				ms = (data or {}).get("marginSummary") or {}
				av = float(ms.get("accountValue") or 0.0)
			except Exception:
				av = 0.0
			try:
				wd = float((data or {}).get("withdrawable") or 0.0)
			except Exception:
				wd = 0.0
			return (av, wd)

		# 병렬 호출
		perp_results = await asyncio.gather(*[_fetch_ch(d) for d in dex_order], return_exceptions=False)
		av_sum = sum(av for av, _ in perp_results)
		wd_sum = sum(wd for _, wd in perp_results)

		total_collateral = av_sum if av_sum != 0.0 else None
		available_collateral = wd_sum if wd_sum != 0.0 else None

		# ---------------- Spot: spotClearinghouseState ----------------
		spot_map = {disp: 0.0 for disp in STABLES_DISPLAY}  # 기본 0.0, 표기는 DISPLAY
		try:
			payload_spot = {"type": "spotClearinghouseState", "user": address}
			async with s.post(url, json=payload_spot, headers=headers) as r:
				spot_resp = await r.json()
			balances_list = (spot_resp or {}).get("balances") or []
			balances = {}
			for b in balances_list:
				if not isinstance(b, dict):
					continue
				name = str(b.get("coin") or b.get("tokenName") or b.get("token") or "").upper()
				try:
					total = float(b.get("total") or 0.0)
				except Exception:
					continue
				if name:
					balances[name] = total

			for onchain, disp in zip(STABLES, STABLES_DISPLAY):
				spot_map[disp] = float(balances.get(onchain, 0.0))

		except aiohttp.ContentTypeError:
			pass
		except Exception:
			pass

		return {
			"available_collateral": available_collateral,
			"total_collateral": total_collateral,
			"spot": spot_map,
		}
	
	async def get_collateral_ws(self, timeout: float = 2.0):
		"""
		WS(webData3/spotState) 기반 담보 조회.
		- 주소가 설정되어 있어야 하며, 첫 스냅샷이 도착할 때까지 최대 timeout 초 대기.
		"""
		address = self.trading_wallet_address
		if not address:
			return {
				"available_collateral": None,
				"total_collateral": None,
				"spot": {disp: None for disp in STABLES_DISPLAY},
			}
		
		if not self.ws_client:
			await self._create_ws_client()
		# 최초 스냅샷 폴링
		deadline = time.monotonic() + timeout
		while time.monotonic() < deadline:
			if self.ws_client.get_margin_by_dex_for_user(address):
				break
			await asyncio.sleep(0.05)

		margin = self.ws_client.get_margin_by_dex_for_user(address)
		av_sum = sum((m or {}).get("accountValue", 0.0) for m in margin.values())
		wd_sum = sum((m or {}).get("withdrawable", 0.0) for m in margin.values())

		balances = self.ws_client.get_balances_by_user(address)
		spot_map = {}
		for onchain, disp in zip(STABLES, STABLES_DISPLAY):
			spot_map[disp] = float(balances.get(onchain, 0.0))

		return {
			"available_collateral": (wd_sum if wd_sum != 0.0 else None),
			"total_collateral": (av_sum if av_sum != 0.0 else None),
			"spot": spot_map,
		}
	
	async def get_open_orders(self, symbol):
		"""
		GET https://app.tread.fi/internal/ems/get_order_table_rows

		쿼리:
		  - status=ACTIVE
		  - type=
		  - page_size=10 (필요 시 조정 가능)
		  - market_type=spot,perp,future
		  - market_type_filter_exception=true
		  - pair=<symbol>  # 인자로 받은 symbol을 그대로 사용

		반환: [{"id": str, "pair": str, "side": "buy"|"sell", "limit_price": str|None}, ...]
		"""
		if not self._has_valid_cookies():
			raise RuntimeError("not logged in: missing session cookies")
		
		s = self._session()
		url = self.url_base + "internal/ems/get_order_table_rows"
		params = {
			"status": "ACTIVE",
			"type": "",
			"page_size": "10",
			"market_type": "spot,perp,future",
			"market_type_filter_exception": "true",
			"pair": symbol,  # 그대로 사용
		}
		headers = {
			"Accept": "application/json",
			"Origin": self.url_base.rstrip("/"),
			"Referer": self.url_base,
			**self._cookie_header(),
		}

		async with s.get(url, params=params, headers=headers) as r:
			# JSON 파싱 실패 시 에러 메시지 노출
			try:
				data = await r.json()
			except Exception:
				text = await r.text()
				raise RuntimeError(f"get_open_orders bad response: {r.status} {text}")
		
		orders = data.get("orders") or []
		if not isinstance(orders, list):
			return []
		
		# account_names에 self.account_name이 포함된 주문만 파싱
		results = []
		for o in orders:
			if not isinstance(o, dict):
				continue
			acc_names = o.get("account_names") or []
			if self.account_name and self.account_name not in acc_names:
				continue

			if o.get("limit_price"): # only if there is limit_price info
				results.append({
					"id": o.get("id"),
					"pair": o.get("pair"),
					"side": (o.get("side") or "").lower() or None,
					"limit_price": o.get("limit_price"),  # 문자열 또는 None
				})

		return results

	async def cancel_orders(self, symbol, open_orders = None):
		if open_orders is None:
			open_orders = await self.get_open_orders(symbol)
			
		if not open_orders:
			#print(f"[cancel_orders] No open orders for {symbol}")
			return []
		if not self._has_valid_cookies():
			raise RuntimeError("not logged in: missing session cookies")
		
		results = []
		for o in open_orders:
			oid = o.get("id",None)

			s = self._session()
			if oid:
				url = self.url_base + "internal/oms/cancel_order/"+oid
				headers = {
					"Accept": "*/*",
					"X-CSRFToken": self._cookies["csrftoken"],
					"Origin": self.url_base.rstrip("/"),
					"Referer": self.url_base,
					**self._cookie_header(),
				}
				payload = {}
				s = self._session()
				async with s.post(url, json=payload, headers=headers) as r:
					status = r.status
					try:
						resp = await r.json()
						msg = resp.get("message") or resp.get("detail")
						
						if msg == "Successfully canceled order.":
							results.append({
								"id": oid,
								"status": "SUCCESS",
								"message": str(msg)
							})
						else:
							results.append({
								"id": oid,
								"status": "FAILED",
								"message": str(msg)
							})

					except Exception as e:
						results.append({
							"id": oid,
							"status": "FAILED",
							"message": str(e)
						})
		return results


	async def get_mark_price(self,symbol,*,is_spot=False):
		symbol_ws = self._symbol_convert_for_ws(symbol)
		raw = str(symbol_ws).strip()
		if "/" in raw:
			is_spot = True # auto redirect

		if self.fetch_by_ws:
			try:
				px = await self.get_mark_price_ws(symbol_ws, is_spot=is_spot, timeout=2)
				return float(px)
			except Exception as e:
				pass
		
		# default rest api
		try:
			px = await self.get_mark_price_rest(symbol_ws, is_spot=is_spot)
			return float(px) if px is not None else None
		except Exception as e:
			return None
	
	async def get_mark_price_rest(self,symbol,*,is_spot=False):
		dex = None
		if ":" in symbol:
			dex = symbol.split(":")[0].lower()
		
		url = f"{HL_BASE_URL}/info"
		headers = {"Content-Type": "application/json"}

		if is_spot:
			payload = {"type":"spotMetaAndAssetCtxs"}
		else:
			payload = {"type":"metaAndAssetCtxs"}
			if dex:
				payload["dex"] = dex
		
		
		s = self._session()
		async with s.post(url, json=payload, headers=headers) as r:
			status = r.status
			try:
				resp = await r.json()
			except aiohttp.ContentTypeError:
				# 비-JSON이면 폴백 불가 → None
				return None

		universe = resp[0].get("universe") if isinstance(resp, list) and len(resp) >= 2 and isinstance(resp[0], dict) else None
		meta = resp[1] if isinstance(resp, list) and len(resp) >= 2 else None
		
		if universe is None or meta is None:
			return None

		if is_spot:
			for pair in self._spot_pair_candidates(symbol.upper()):
				spot_idx = self.spot_asset_pair_to_index.get(pair)
				if spot_idx is None:
					# UBTC, UETH, ..., 외부에서 pair 검증해도 이 부분은 유지
					spot_idx = self.spot_asset_pair_to_index.get(f"U{pair}")
				try:
					price = meta[spot_idx].get('markPx')
					#print(price, pair)
					return price # USDC, USDT, USDH 순으로 찾아서 먼저 나오는거
				except:
					continue

			return None
				
		else:
			for idx, value in enumerate(universe):
				if value.get('name').upper() == symbol.upper():
					#print(idx, value.get('name'), symbol)
					price = meta[idx].get('markPx')
					return price
		
		return None
	
	async def get_mark_price_ws(self, symbol, *, is_spot=False, timeout: float = 3.0):
		"""
		WS 캐시 기반 마크 프라이스 조회.
		- is_spot=True 이면 'BASE/QUOTE' 페어 가격을 조회
		- is_spot=False 이면 perp(예: 'BTC') 가격을 조회
		- 첫 틱이 아직 도착하지 않은 경우 wait_price_ready가 있으면 timeout까지 대기
		- 값을 얻지 못하면 예외를 던져 상위(get_mark_price)에서 REST 폴백하게 한다.
		"""
		if not self.ws_client:
			await self._create_ws_client()

		raw = str(symbol).strip()
		#if "/" in raw:
		#    is_spot = True

		if is_spot:
			for pair in self._spot_pair_candidates(raw.upper()):
				# spot_pair로 명시
				if hasattr(self.ws_client, "wait_price_ready"):
					try:
						ready = await asyncio.wait_for(
							self.ws_client.wait_price_ready(pair, timeout=timeout, kind="spot_pair"),
							timeout=timeout
						)
						if not ready:
							continue
					except Exception:
						continue
				
				px = self.ws_client.get_spot_pair_px(pair)
				if px is not None:
					return float(px)

			# 모든 후보 실패
			raise TimeoutError(f"WS spot price not ready. tried={self._spot_pair_candidates(raw.upper())}")

		# Perp 경로
		key = raw.upper()
		# perp로 명시
		try:
			await asyncio.wait_for(
				self.ws_client.wait_price_ready(key, timeout=timeout, kind="perp"),
				timeout=timeout
			)
		except Exception:
			pass

		px = self.ws_client.get_price(key)
		if px is None:
			raise TimeoutError(f"WS perp price not ready for {key}")
		return float(px)
	
	def _spot_pair_candidates(self, raw_symbol: str) -> list[str]:
		"""
		'BASE/QUOTE'면 그대로 1개, 아니면 STABLES 우선순위로 BASE/QUOTE 후보를 만든다.
		"""
		rs = str(raw_symbol).strip()
		if "/" in rs:
			return [rs.upper()]
		base = rs.upper()
		return [f"{base}/{q}" for q in STABLES]