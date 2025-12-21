from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from .hyperliquid_ws_client import HLWSClientRaw, WS_POOL
from mpdex.utils.common_hyperliquid import (
	parse_hip3_symbol, 
	round_to_tick, 
	format_price, 
	format_size,
	#init_spot_token_map,
	#get_dex_list,
	#init_perp_meta_cache,
	init_shared_hl_cache,
	get_shared_hl_cache,
	extract_order_id,
	extract_cancel_status,
	STABLES,
	STABLES_DISPLAY
)
from typing import Dict, Optional, List, Tuple, Any
import aiohttp
from aiohttp import TCPConnector
import asyncio
import time

BASE_URL = "https://api.hyperliquid.xyz"
BASE_WS = "wss://api.hyperliquid.xyz/ws"

# to do: signing method 수정

DEFAULT_BASE_URL = "https://wallet-service.superstack.xyz"
DEFAULT_HEADERS = {
	"Accept": "application/json",
	"User-Agent": "superstack-aiohttp/0.1",
}

async def get_superstack_payload(
	api_key: str,
	action: Dict[str, Any],
	vault_address: str,
	base_url: str = DEFAULT_BASE_URL,
) -> Dict[str, Any]:
	async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
		return await _perform_payload_request(api_key, action, vault_address, base_url, session)

async def _perform_payload_request(
	api_key: str,
	action: Dict[str, Any],
	vault_address: str,
	base_url: str,
	session: aiohttp.ClientSession
) -> Dict[str, Any]:
	"""get_superstack_payload의 핵심 로직을 수행합니다."""
	url = f"{base_url.rstrip('/')}/api/exchange"
	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json"
	}
	req = {"action": action}
	if vault_address:
		req["vaultAddress"] = vault_address

	async with session.post(url, headers=headers, json=req) as response:
		await _raise_if_bad_response(response)
		exchange_resp = await response.json()
	
	payload = exchange_resp.get("payload")
	if payload is None:
		raise ValueError("superstack API 응답에서 'payload'를 찾을 수 없습니다.")

	return payload

async def _raise_if_bad_response(resp: aiohttp.ClientResponse) -> None:
	"""HTTP 응답 상태 코드가 2xx가 아닐 경우 예외를 발생시킵니다."""
	if 200 <= resp.status < 300:
		return
	
	ctype = resp.headers.get("content-type", "")
	text = await resp.text()

	if "text/html" in ctype.lower():
		# HTML 응답은 보통 WAF나 IP 차단 문제일 가능성이 높음
		raise RuntimeError(f"Request blocked (HTTP {resp.status} HTML). Likely WAF/IP whitelist issue. Body preview: {text[:300]}...")
	
	# JSON 에러 포맷이 일정치 않으므로 원문을 그대로 노출
	raise RuntimeError(f"HTTP {resp.status}: {text[:400]}...")

class SuperstackExchange(MultiPerpDexMixin, MultiPerpDex):
	# superstack은 hyperliquid perp를 사용하지만, 자체 지갑 provider를 사용하여
	# signing 방식은 지갑 api를 사용해야함
	# 즉 builder code와 fee는 따로 설정해야함
	def __init__(self, 
			  wallet_address = None,        # required
			  api_key = None,               # required
			  vault_address = None,         # optional, sub-account address
			  #builder_code = None, 하드코딩
			  builder_fee_pair: dict = None,     # {"base","dex"# optional,"xyz" # optional,"vntl" #optional,"flx" #optional}
			  *,
			  fetch_by_ws = False, # fetch pos, balance, and price by ws client
			  FrontendMarket = False,
			  # ws_client의 경우 WS_POOL 하나를 공유 (hyperliquid의 것)
			  ):

		self.wallet_address = wallet_address
		self.api_key = api_key
		self.vault_address = vault_address

		self.builder_code = "0xcdb943570bcb48a6f1d3228d0175598fea19e87b"
		self.builder_fee_pair = builder_fee_pair
		
		self.http_base = BASE_URL
		self.ws_base = BASE_WS
		self.spot_index_to_name = {}
		self.spot_name_to_index = {}
		self.spot_asset_index_to_pair = {}
		self.spot_asset_pair_to_index = {}
		self.spot_asset_index_to_bq = {}
		self.spot_prices = None
		self.dex_list = ['hl', 'xyz', 'flx', 'vntl', 'hyna'] # default

		self.spot_token_sz_decimals: Dict[str, int] = {}
		self.perp_metas_raw: Optional[List[dict]] = []
		# 키 → (asset_id, szDecimals, maxLeverage, onlyIsolated, collateralToken)
		#  - 메인(HL): 'BTC' (대문자)
		#  - HIP-3:    'xyz:XYZ100' (원문 그대로)
		self.perp_asset_map: Dict[str, Tuple[int, int, int, bool, int]] = {}
		self._leverage_updated_to_max = False
		self._http =  None

		# WS 관련 내부 상태
		self.ws_client: Optional[HLWSClientRaw] = None  # WS_POOL에서
		self._ws_pool_key = None                        # comment: release 시 사용
		
		#self._ws_init_lock = asyncio.Lock()             # comment: create_ws_client 중복 호출 방지
		self.fetch_by_ws = fetch_by_ws
		self.FrontendMarket = FrontendMarket

	def _parse_fee_pair(self, raw) -> tuple[int, int]:
		if raw is None:
			return (0, 0)
		
		if isinstance(raw, (tuple, list)):
			try:
				if len(raw) == 1:
					v = int(float(raw[0]))
					return (v, v)
				a = int(float(raw[0]))
				b = int(float(raw[1]))
				return (a, b)
			except Exception:
				return (0, 0)
		
		# int 한개만 받는 경우, limit와 market 동일
		if isinstance(raw, int):
			return (raw, raw)
			
		# string인 경우 "10,20" "10/20" "10|20" 형태
		# 혹은 단일의 string인 경우 limit=market
		s = str(raw).replace(",", " ").replace("/", " ").replace("|", " ").strip()
		toks = [t for t in s.split() if t]
		if len(toks) == 1:
			try:
				v = int(float(toks[0]))
				return (v, v)
			except Exception:
				return (0, 0)
		try:
			a = int(float(toks[0]))
			b = int(float(toks[1]))
			return (a, b)
		except Exception:
			return (0, 0)

	# 빌더 fee 선택: dex별 → "dex"(공통) → "base" 순
	def _pick_builder_fee_int(self, dex: Optional[str], order_type: str) -> Optional[int]:
		try:
			pair_src = None
			idx = 0 if str(order_type).lower() == "limit" else 1
			m = self.builder_fee_pair or {}

			# 1) 개별 DEX(hip3) 키
			if dex and dex in m:
				a, b = self._parse_fee_pair(m[dex])
				pair_src = (a, b)
				return int(pair_src[idx])

			# 2) 공통 DEX 키
			if dex and "dex" in m:
				a, b = self._parse_fee_pair(m["dex"])
				pair_src = (a, b)
				return int(pair_src[idx])
			
			# 3) 메인/기본 키
			if "base" in m:
				a, b = self._parse_fee_pair(m["base"])
				pair_src = (a, b)
				return int(pair_src[idx])

			return None
		
		except Exception as e:
			return None
	
	def _session(self) -> aiohttp.ClientSession:
		if self._http is None or self._http.closed:
			self._http = aiohttp.ClientSession(
				connector=TCPConnector(
					force_close=True,             # 매 요청 후 소켓 닫기 → 종료 시 잔여 소켓 최소화
					enable_cleanup_closed=True,   # 종료 중인 SSL 소켓 정리 보조 (로그 억제)
				)
			)
		return self._http
	
	async def close(self):
		# HTTP 세션 종료 + WS 풀 release
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

	async def init(self):
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
				dex_order=self.dex_list or ["hl"],
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
	
	def get_perp_quote(self, symbol):
		raw = str(symbol).strip()
		dex, coin_key = parse_hip3_symbol(raw)
		_, _, _, _, quote_id = self.perp_asset_map.get(coin_key,(None, 0, 1, False, 0))
		quote = self.spot_index_to_name.get(quote_id,'USDC')
		return quote
	
	# 캐시 조회로 변경
	async def _resolve_perp_asset_and_szdec(self, dex: Optional[str], coin_key: str) -> tuple[Optional[int], int]:
		"""
		캐시에서 Perp asset_id와 szDecimals, maxLeverage, onlyIsolated 반환
		- dex=None(메인):     key = coin_key.upper()
		- dex='xyz'(HIP-3):   key = coin_key(원문 'xyz:COIN')
		"""
		key = coin_key if dex else coin_key.upper()
		return self.perp_asset_map.get(key, (None, 0, 1, False, 0))

	# 심볼 → asset id 해석(spot/perp 공용)
	async def _resolve_asset_id_for_symbol(self, symbol: str, *, is_spot: bool) -> int:
		raw = str(symbol).strip()
		if is_spot or ("/" in raw):
			pair = raw.upper()
			if not self.spot_asset_pair_to_index:
				raise RuntimeError("spot meta not initialized")
			pair_idx = self.spot_asset_pair_to_index.get(pair)
			if pair_idx is None:
				raise RuntimeError(f"unknown spot pair: {pair}")
			return 10000 + int(pair_idx)
		# perp (HL/HIP-3)
		dex, coin_key = parse_hip3_symbol(raw)
		asset_id, *_ = await self._resolve_perp_asset_and_szdec(dex, coin_key)
		if asset_id is None:
			raise RuntimeError(f"asset index not found for {raw}")
		return int(asset_id)

	def _spot_base_sz_decimals(self, pair: str) -> int:
		"""
		pair: 'BASE/QUOTE'
		return: BASE 토큰의 szDecimals (없으면 0)
		"""
		if not self.spot_asset_pair_to_index or not self.spot_asset_index_to_bq:
			return 0
		pair_u = str(pair).upper()
		idx = self.spot_asset_pair_to_index.get(pair_u)
		if idx is None:
			return 0
		bq = self.spot_asset_index_to_bq.get(idx)
		if not bq:
			return 0
		base = (bq[0] or "").upper()
		return int((self.spot_token_sz_decimals or {}).get(base, 0))
	
	def _spot_price_tick_decimals(self, pair: str) -> int:
		base_sz = self._spot_base_sz_decimals(pair)
		tick = 6 - int(base_sz)
		return tick if tick > 0 else 0

	async def _create_ws_client(self):
		"""
		WS 커넥션을 '1회 연결 + 다중 구독'으로 운용.
		- 전역 풀(WS_POOL)에서 (ws_url,address) 키로 하나를 획득하여 공유
		- 인스턴스 내부에서 중복 acquire를 방지
		"""
		#async with self._ws_init_lock:
		if self.ws_client is not None:
			return self.ws_client
		
		address = self.vault_address if self.vault_address else self.wallet_address
		# acquire에 메타를 전달(풀 내부에서 최초 1회만 반영)
		client = await WS_POOL.acquire(
			ws_url=self.ws_base,
			http_base=self.http_base,
			address=address,
			dex=None,
			dex_order=self.dex_list or ["hl"],
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
		#return self.ws_client

	async def update_leverage(
			self,
			symbol,
			leverage=None,
			*,
			prefer_ws: bool = True,
			timeout: float = 5.0,
		):
		# use max leverage all the time
		if self._leverage_updated_to_max:
			return {'status':'ok','response':'already updated!'}
		
		raw = str(symbol).strip()
		dex, coin_key = parse_hip3_symbol(raw)
		asset_id, _, max_leverage, only_isolated, _ = await self._resolve_perp_asset_and_szdec(dex, coin_key)
		if asset_id is None:
			return "asset not found"
		
		lev = int(leverage or max_leverage or 1)
		is_cross = (not bool(only_isolated))
		action = {
			"type": "updateLeverage",
			"asset": asset_id,
			"isCross": is_cross,
			"leverage": lev,
		}
		payload = await get_superstack_payload(api_key=self.api_key, action=action, vault_address=self.vault_address)
		if self.vault_address:
			payload["vaultAddress"] = self.vault_address
		
		if prefer_ws:
			# {"status":"ok","response":{...}}
			try:
				if not self.ws_client and self.fetch_by_ws:
					await self._create_ws_client()
				if self.ws_client:
					resp = await self.ws_client.post_action(payload, timeout=timeout)
					# resp 예: {"type":"action"|"error","payload": {... or str}}
					rtype = str(resp.get("type") or "")
					pl = resp.get("payload")
					if rtype == "error":
						raise RuntimeError(str(pl))
					status = (pl or {}).get("status")
					if str(status).lower() == "ok":
						self._leverage_updated_to_max = True
						return pl  # {"status":"ok", "response": {...}}
					# 모호한 응답이면 그대로 반환
					return pl or {"status": "unknown"}
			except Exception as e:
				print(f"superstack: update_leverage falling back to rest api / symbol {symbol} / leverage {leverage} / error in ws {e}")
				pass
		
		try:
			url = f"{self.http_base}/exchange"
			s = self._session()
			async with s.post(url, json=payload, headers={"Content-Type": "application/json"}) as r:
				r.raise_for_status()
				resp = await r.json()
				# {'status': 'ok', 'response': {'type': 'default'}}
				if resp.get("status") == 'ok':
					self._leverage_updated_to_max = True
			return resp
		except Exception as e:
			return str(e)

	async def create_order(
		self,
		symbol,
		side,
		amount,
		price=None,
		order_type='market',
		*,
		is_reduce_only = False,
		is_spot: bool = False,
		tif: Optional[str] = None,
		client_id: Optional[str] = None,
		slippage: Optional[float] = 0.05,
		prefer_ws: bool = True,
		timeout: float = 5.0,
	):
		"""
		HL REST 주문(Perp/Spot 겸용).
		- price=None → 시장가(FrontendMarket), price 지정 → 지정가(Gtc 기본)
		- HIP-3(dex:COIN) 자동 처리, Spot 주문 지원
		반환: {"id": "<oid>", "info": <원문응답>}
		"""
		#print(res)
		# 0) 공통
		is_buy = str(side).lower() == "buy"
		raw = str(symbol).strip()

		# 1) Spot 여부 판단
		if is_spot or ("/" in raw):
			dex = None
			pair = raw.upper() if "/" in raw else raw.upper()
			if self.spot_asset_pair_to_index is None:
				raise RuntimeError("spot meta not initialized")
			pair_idx = self.spot_asset_pair_to_index.get(pair)
			if pair_idx is None:
				raise RuntimeError(f"unknown spot pair: {pair}")
			asset_id = 10000 + int(pair_idx)

			# BASE szDecimals, tickDecimals
			base_sz_dec = self._spot_base_sz_decimals(pair)               # 수량 자릿수
			tick_decimals = self._spot_price_tick_decimals(pair)               # 가격 틱 자릿수

			if price is None:
				ord_type = "market"
				tif_final = "FrontendMarket" if self.FrontendMarket else (tif or "Gtc")
				base_px = await self.get_mark_price(pair, is_spot=True)
				if base_px is None:
					price_str = "0"
				else:
					eff = float(base_px) * (1.0 + slippage) if is_buy else float(base_px) * (1.0 - slippage)
					d_tick = round_to_tick(eff, tick_decimals, up=is_buy)
					price_str = format_price(float(d_tick), tick_decimals)
					if not price_str:
						price_str = "0"
			else:
				ord_type = "limit"
				tif_final = (tif or "Gtc")
				# 틱에 맞춰 BUY: 올림, SELL: 내림
				d_tick = round_to_tick(float(price), tick_decimals, up=is_buy)
				price_str = format_price(float(d_tick), tick_decimals)
			# 수량 포맷: BASE szDecimals 기준
			size_str = format_size(float(amount), int(base_sz_dec))
		else:
			try:
				await self.update_leverage(symbol)
			except Exception:
				pass
			# ---------- Perp 주문 ----------
			dex, coin_key = parse_hip3_symbol(raw)
			asset_id, sz_dec, *_ = await self._resolve_perp_asset_and_szdec(dex, coin_key)
			if asset_id is None:
				raise RuntimeError(f"asset index not found for {raw}")

			tick_decimals = max(0, 6 - int(sz_dec))
			if price is None:
				ord_type = "market"
				tif_final = "FrontendMarket" if self.FrontendMarket else (tif or "Gtc")
				base_px = await self.get_mark_price(coin_key, is_spot=False)
				if base_px is None:
					price_str = "0"
				else:
					eff = float(base_px) * (1.0 + slippage) if is_buy else float(base_px) * (1.0 - slippage)
					d_tick = round_to_tick(eff, tick_decimals, up=is_buy)
					price_str = format_price(float(d_tick), tick_decimals)
					if not price_str:
						price_str = "0"
			else:
				ord_type = "limit"
				tif_final = (tif or "Gtc")
				d_tick = round_to_tick(float(price), tick_decimals, up=is_buy)
				price_str = format_price(float(d_tick), tick_decimals)

			size_str = format_size(float(amount), int(sz_dec))
		
		# 공통 부분
		order_obj = {
			"a": int(asset_id),
			"b": bool(is_buy),
			"p": price_str,
			"s": size_str,
			"r": bool(is_reduce_only),
			"t": {"limit": {"tif": tif_final}},
		}
		if client_id:
			order_obj["c"] = str(client_id)

		action = {"type": "order", "orders": [order_obj], "grouping": "na"}

		if self.builder_code:
			fee_int = self._pick_builder_fee_int(dex, ord_type)
			builder_payload = {"b": str(self.builder_code).lower()}
			if isinstance(fee_int, int):
				builder_payload["f"] = int(fee_int)
			action["builder"] = builder_payload
		
		payload = await get_superstack_payload(api_key=self.api_key, action=action, vault_address=self.vault_address)
		if self.vault_address:
			payload["vaultAddress"] = self.vault_address

		# WS post
		if prefer_ws and self.fetch_by_ws:
			try:
				if not self.ws_client:
					await self._create_ws_client()
				if self.ws_client:
					resp = await self.ws_client.post_action(payload, timeout=timeout)
				# resp 예: {"type":"action"|"error","payload": {... or str}}
				rtype = str(resp.get("type") or "")
				pl = resp.get("payload")
				if rtype == "error":
					raise RuntimeError(str(pl))
				status = (pl or {}).get("status")
				if str(status).lower() == "ok":
					#print(pl)
					return extract_order_id(pl)
				return pl or {"status": "unknown"}
			except Exception as e:
				print(f"superstack: create_order falling back to rest api / symbol {symbol} / error in ws {e}")
				pass # fallback to rest api
		
		# WS 실패시 rest api
		url = f"{self.http_base}/exchange"
		s = self._session()
		async with s.post(url, json=payload, headers={"Content-Type": "application/json"}) as r:
			r.raise_for_status()
			resp = await r.json()
		try:
			return extract_order_id(resp) # only id
		except Exception as e:
			return str(e)

	# 포지션 파싱 공통 헬퍼
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
	
	async def get_position(self, symbol):
		"""
		주어진 perp 심볼에 대한 단일 포지션 요약을 반환합니다.
		반환 스키마:
		  {"entry_price": float|None, "unrealized_pnl": float|None, "side": "long"|"short"|"flat", "size": float}
		"""
		if self.fetch_by_ws:
			try:
				pos = await self.get_position_ws(symbol, timeout=2.0)
				if pos is not None:
					return pos
			except Exception as e:
				print(f"superstack: get_position falling back to rest api / symbol {symbol} / error in ws {e}")
				pass
		return await self.get_position_rest(symbol)
	
	async def get_position_ws(self, symbol: str, timeout: float = 2.0, dex: str | None = None) -> dict:
		"""
		webData3(WS 캐시)에서 조회. 스냅샷 미도착 시 timeout까지 짧게 대기합니다.
		dex를 지정하지 않으면 self.dex_list 순서대로 검색합니다.
		"""
		address = (self.vault_address or self.wallet_address or "").lower()
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
		address = self.vault_address or self.wallet_address
		if not address:
			return None

		url = f"{self.http_base}/info"
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
	
	async def close_position(self, symbol, position):
		return await super().close_position(symbol, position, is_reduce_only=True)
	
	async def get_collateral(self):
		if self.fetch_by_ws:
			try:
				return await self.get_collateral_ws()
			except Exception as e:
				print(f"superstack: get_collateral falling back to rest api / error in ws {e}")
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
		address = self.vault_address or self.wallet_address
		if not address:
			return {
				"available_collateral": None,
				"total_collateral": None,
				"spot": {disp: None for disp in STABLES_DISPLAY},
			}

		url = f"{self.http_base}/info"
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
		address = (self.vault_address or self.wallet_address or "").lower()
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

	def _normalize_open_order_rest(self, o: dict) -> Optional[dict]:
		if not isinstance(o, dict):
			return None
		coin_raw = str(o.get("coin") or "")
		# 스팟 페어 인덱스 → 'BASE/QUOTE'
		if coin_raw.startswith("@"):
			try:
				pair_idx = int(coin_raw[1:])
			except Exception:
				return None
			pair = (self.spot_asset_index_to_pair or {}).get(pair_idx)
			if not pair:
				return None
			symbol = str(pair).upper()
		else:
			symbol = coin_raw.upper()

		def fnum(x, default=None):
			try:
				return float(x)
			except Exception:
				return default

		out = {
			"order_id": o.get("oid"),
			"symbol": symbol,
			"side": "short" if o.get("side") == 'A' else 'long',
			"price": fnum(o.get("limitPx")),
			"size": fnum(o.get("sz")),
			#"timestamp": int(o.get("timestamp")) if o.get("timestamp") is not None else None,
			#"raw": o,
		}
		return out if out["order_id"] is not None and out["symbol"] else None

	async def get_open_orders_ws(self, symbol: str, timeout: float = 2.0) -> Optional[List[dict]]:
		"""
		WS openOrders 캐시에서 주어진 심볼의 미체결 주문을 반환.
		- 구독이 없으면 subscribe를 보장하고, 초기 스냅샷을 timeout까지 대기(폴링).
		- 없으면 None.
		"""
		address = (self.vault_address or self.wallet_address or "").lower()
		if not address:
			return None
		if not self.ws_client:
			await self._create_ws_client()

		await self.ws_client.ensure_user_streams(address)  # 보장
		await self.ws_client.wait_open_orders_ready(timeout=timeout, address=address)

		orders = self.ws_client.get_open_orders_for_user(address)
		if not orders:
			return None
		sym = str(symbol).upper().strip()
		filtered = [o for o in orders if (o.get("symbol") or "").upper() == sym]
		return filtered or None
	
	async def get_open_orders_rest(self, symbol: str, dex: str = "ALL_DEXS") -> Optional[List[dict]]:
		"""
		REST openOrders 조회 후 주어진 심볼로 필터링하여 반환.
		- 없으면 None.
		"""
		address = self.vault_address or self.wallet_address
		if not address:
			return None

		url = f"{self.http_base}/info"
		headers = {"Content-Type": "application/json"}
		payload = {"type": "openOrders", "user": address, "dex": dex}

		s = self._session()
		try:
			async with s.post(url, json=payload, headers=headers) as r:
				resp = await r.json()
		except aiohttp.ContentTypeError:
			return None
		except Exception:
			return None

		# 응답 포맷: {"orders":[...]} 또는 바로 리스트([...]) 케이스 방어
		orders_raw = []
		if isinstance(resp, dict) and isinstance(resp.get("orders"), list):
			orders_raw = resp.get("orders")
		elif isinstance(resp, list):
			orders_raw = resp
		else:
			return None

		normalized = []
		for o in orders_raw:
			no = self._normalize_open_order_rest(o)
			if no:
				normalized.append(no)
		if not normalized:
			return None

		sym = str(symbol).upper().strip()
		filtered = [o for o in normalized if (o.get("symbol") or "").upper() == sym]
		return filtered or None

	async def get_open_orders(self, symbol: str) -> Optional[List[dict]]:
		if self.fetch_by_ws:
			try:
				res = await self.get_open_orders_ws(symbol, timeout=2.0)
				if res:
					return res
			except Exception as e:
				print(f"superstack: get_open_orders falling back to rest api / symbol {symbol} / error in ws {e}")
				pass
		return await self.get_open_orders_rest(symbol, dex="ALL_DEXS")

	async def cancel_orders(
		self,
		symbol,
		open_orders=None,
		*,
		is_spot: bool = False,
		prefer_ws: bool = True,
		timeout: float = 5.0,
	):
		"""
		open_orders가 주어지면 그 목록을, 없으면 get_open_orders(symbol)로 조회한 목록을 취소합니다.
		반환: List[{"order_id": ..., "symbol": ..., "ok": bool, "error": Optional[str]}]
		"""
		if open_orders is None:
			open_orders = await self.get_open_orders(symbol)
			
		if not open_orders:
			#print(f"[cancel_orders] No open orders for {symbol}")
			return []
		
		asset_cache: dict[str, int] = {}

		cancels = []
		results = []
		for od in open_orders:
			oid = od.get("order_id")
			sym = od.get("symbol") or symbol
			if oid is None:
				results.append({"order_id": oid, "symbol": sym, "ok": False, "error": "missing order_id"})
				continue
			# 심볼 기준으로 spot/perp 판별
			sym_is_spot = is_spot or ("/" in str(sym))
			try:
				if sym not in asset_cache:
					asset_cache[sym] = await self._resolve_asset_id_for_symbol(sym, is_spot=sym_is_spot)
				cancels.append({"a": int(asset_cache[sym]), "o": int(oid)})
				# 임시 결과(성공 가정), 실패 시 나중에 덮어씀
				results.append({"order_id": int(oid), "symbol": sym, "ok": None, "error": None})
			except Exception as e:
				results.append({"order_id": oid, "symbol": sym, "ok": False, "error": str(e)})

		# 취소할 게 없으면 조기 반환
		pending = [r for r in results if r["ok"] is None]
		if not pending:
			return results

		action = {"type": "cancel", "cancels": cancels}
		#nonce, sig = self._sign_hl_action(action)
		#payload = {"action": action, "nonce": nonce, "signature": sig}
		payload = await get_superstack_payload(api_key=self.api_key, action=action, vault_address=self.vault_address)
		if self.vault_address:
			payload["vaultAddress"] = self.vault_address

		# WS 우선 → HTTP 폴백
		ws_success = False
		if prefer_ws and self.fetch_by_ws:
			try:
				if not self.ws_client:
					await self._create_ws_client()
				if self.ws_client:
					resp = await self.ws_client.post_action(payload, timeout=timeout)
					rtype = str(resp.get("type") or "")
					pl = resp.get("payload")
					if rtype == "error":
						raise RuntimeError(str(pl))
					extract_cancel_status(pl)
					ws_success = True
			except Exception as e:
				print(f"superstack: cancel_orders falling back to rest api / error in ws {e}")
				pass

		if not ws_success:
			# HTTP 폴백
			try:
				url = f"{self.http_base}/exchange"
				s = self._session()
				async with s.post(url, json=payload, headers={"Content-Type": "application/json"}) as r:
					r.raise_for_status()
					resp = await r.json()
				extract_cancel_status(resp)
			except Exception as e:
				# 배치 전체 실패
				for r in results:
					if r["ok"] is None:
						r["ok"] = False
						r["error"] = str(e)
				return results

		# 성공 시 모든 pending을 ok=True로
		for r in results:
			if r["ok"] is None:
				r["ok"] = True

		return results

	# 내부 헬퍼: Spot 후보 페어 생성(우선순위 고정)
	def _spot_pair_candidates(self, raw_symbol: str) -> list[str]:
		"""
		'BASE/QUOTE'면 그대로 1개, 아니면 STABLES 우선순위로 BASE/QUOTE 후보를 만든다.
		"""
		rs = str(raw_symbol).strip()
		if "/" in rs:
			return [rs.upper()]
		base = rs.upper()
		return [f"{base}/{q}" for q in STABLES]

	async def get_mark_price(self,symbol,*,is_spot=False):
		raw = str(symbol).strip()
		if "/" in raw:
			is_spot = True # auto redirect

		if self.fetch_by_ws:
			try:
				px = await self.get_mark_price_ws(symbol, is_spot=is_spot, timeout=2)
				return float(px)
			except Exception as e:
				pass
		
		# default rest api
		try:
			px = await self.get_mark_price_rest(symbol, is_spot=is_spot)
			return float(px) if px is not None else None
		except Exception as e:
			return None
	
	async def get_mark_price_rest(self,symbol,*,is_spot=False):
		dex = None
		if ":" in symbol:
			dex = symbol.split(":")[0].lower()
		
		url = f"{self.http_base}/info"
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
					if price is not None:
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
	
	async def get_mark_price_ws(self,symbol, *, is_spot=False, timeout: float = 3.0):
		"""
		WS 캐시 기반 마크 프라이스 조회.
		- is_spot=True 이면 'BASE/QUOTE' 페어 가격을 조회
		- is_spot=False 이면 perp(예: 'BTC') 가격을 조회
		- 첫 틱이 아직 도착하지 않은 경우 wait_price_ready가 있으면 timeout까지 대기
		- 값을 얻지 못하면 예외를 던져 상위(get_mark_price)에서 REST 폴백하게 한다.
		"""
		#if not self.ws_client:
		#    await self.create_ws_client()

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