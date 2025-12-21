from multi_perp_dex import MultiPerpDexMixin, MultiPerpDex
from mpdex.utils.common_pacifica import sign_message
import time
import uuid
import requests
from solders.keypair import Keypair
import aiohttp
from aiohttp import TCPConnector
from typing import Optional, Dict, Any, List
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, getcontext
import json

BASE_URL = "https://api.pacifica.fi/api/v1"
WS_URL = "wss://ws.pacifica.fi/ws"

getcontext().prec = 36  # [ADDED] 충분한 정밀도 확보

def _get_signature_header_and_url(req_type:str):
    if req_type == "create_market_order": # market order
        req_url = f"{BASE_URL}/orders/create_market"

    elif req_type == "create_order": # limit order
        req_url = f"{BASE_URL}/orders/create"

    elif req_type == "cancel_order":
        req_url = f"{BASE_URL}/orders/cancel"

    else:
        raise Exception(f"no such request type {req_type}")

    return {
        "timestamp": int(time.time() * 1_000),
        "expiry_window": 5_000,
        "type": f"{req_type}",
    }, req_url

class PacificaExchange(MultiPerpDexMixin, MultiPerpDex):
    # no use of private key, but use agent wallets instead (api)
    def __init__(self, public_key, agent_public_key, agent_private_key):
        super().__init__()
        if not (public_key and agent_public_key and agent_private_key):
            raise ValueError("Pacifica required, pub key, agent pub key, and agent private key")
        self.public_key = public_key                # required
        self.agent_public_key = agent_public_key    # required
        self.agent_private_key = agent_private_key  # required
        self.agent_keypair = Keypair.from_base58_string(agent_private_key)
        self._http: Optional[aiohttp.ClientSession] = None

        # { "BTC": {"tick_size": "1", "lot_size": "0.00001", ...}, ... }
        self._symbol_meta: Dict[str, Dict[str, Any]] = {}
        self._symbol_list: List[str] = []
        self._initialized: bool = False

        # 가격 런타임 캐시: { "BTC": {"mark": Decimal, "mid": Decimal|None, "oracle": Decimal|None, "ts": int} }
        self._price_cache: Dict[str, Dict[str, Any]] = {}


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
        if self._http and not self._http.closed:
            await self._http.close()
    
    def get_perp_quote(self, symbol):
        return 'USD'
    
    async def init(self) -> Dict[str, Any]:
        """
        GET /info → 심볼 목록과 tick_size/lot_size 등을 런타임 캐시에 저장
        """
        if self._initialized:
            return {"ok": True, "cached": True, "symbols": list(self._symbol_list)}

        url = f"{BASE_URL}/info"
        s = self._session()
        async with s.get(url) as r:
            r.raise_for_status()
            data = await r.json()

        # 기대 형태: {"success": true, "data": [ {symbol, tick_size, lot_size, ...}, ... ]}
        items = data.get("data") or []
        meta: Dict[str, Dict[str, Any]] = {}
        symbols: List[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "").upper()
            if not sym:
                continue
            # 필요한 값만 보관(문자열로 유지, 계산 시 Decimal로 변환)
            meta[sym] = {
                "tick_size": str(it.get("tick_size") or "1"),
                "lot_size": str(it.get("lot_size") or "1"),
                "min_tick": str(it.get("min_tick") or "0"),
                "max_tick": str(it.get("max_tick") or "0"),
                "min_order_size": str(it.get("min_order_size") or "0"),
                "max_order_size": str(it.get("max_order_size") or "0"),
            }
            symbols.append(sym)

        self._symbol_meta = meta
        self._symbol_list = sorted(set(symbols))
        self._initialized = True
        #return {"ok": True, "meta":self._symbol_meta, "symbols": list(self._symbol_list) }
        return self
    
    async def initialize_if_needed(self):  # [ADDED]
        if not self._initialized:
            await self.initialize()

    # ---------------------------
    # 수치 보정 유틸
    # ---------------------------
    def _dec(self, x) -> Decimal:  # [ADDED]
        return x if isinstance(x, Decimal) else Decimal(str(x))

    def _format_with_step(self, value: Decimal, step: Decimal) -> str:  # [ADDED]
        """
        step의 소수자릿수에 맞춰 trailing zeros 포함 문자열로 변환
        """
        q = value.quantize(step)  # 소수자릿수 강제
        return format(q, "f")     # '1.2300' 유지

    def _get_meta(self, symbol: str) -> Dict[str, Any]:  # [ADDED]
        sym = str(symbol).upper()
        meta = self._symbol_meta.get(sym)
        if not meta:
            # 초기화 누락/미지원 심볼 → 안전 기본값
            return {
                "tick_size": "1",
                "lot_size": "1",
                "min_tick": "0",
                "max_tick": "0",
                "min_order_size": "0",
                "max_order_size": "0",
            }
        return meta

    def _adjust_price_tick(self, symbol: str, price, *, rounding=ROUND_HALF_UP) -> str:  # [ADDED]
        """
        tick_size에 맞춰 가격을 반올림하여 문자열로 반환.
        - 기본 반올림: HALF_UP (일반적인 가격 반올림)
        - 필요 시 rounding=ROUND_DOWN/ROUND_UP 등으로 조정 가능
        """
        meta = self._get_meta(symbol)
        step = self._dec(meta["tick_size"])
        p = self._dec(price)
        # step 배수로 반올림
        units = (p / step).to_integral_value(rounding=rounding)
        adjusted = (units * step).quantize(step)
        # min/max tick 범위가 유효하면 보정
        try:
            min_tick = self._dec(meta.get("min_tick", "0"))
            max_tick = self._dec(meta.get("max_tick", "0"))
            if max_tick > 0:
                if adjusted < min_tick:
                    adjusted = min_tick
                if adjusted > max_tick:
                    adjusted = max_tick
        except Exception:
            pass
        return self._format_with_step(adjusted, step)

    def _adjust_amount_lot(self, symbol: str, amount, *, rounding=ROUND_DOWN) -> str:  # [ADDED]
        """
        lot_size 배수로 수량을 반올림하여 문자열로 반환.
        - 기본은 DOWN(절삭): 과다 수량 전송 방지 목적
        """
        meta = self._get_meta(symbol)
        step = self._dec(meta["lot_size"])
        a = self._dec(amount)
        if step <= 0:
            return str(amount)
        units = (a / step).to_integral_value(rounding=rounding)
        adjusted = (units * step).quantize(step)
        return self._format_with_step(adjusted, step)

    async def create_order(self, symbol, side, amount, price=None, order_type='market', *, is_reduce_only=False, slippage = "0.1"):
        symbol = symbol.upper()
        amount = self._adjust_amount_lot(symbol, amount, rounding=ROUND_DOWN)

        side = "bid" if side.lower() == "buy" else "ask"
        
        # price가 있냐 없냐로 사실상 정함
        if not price:
            order_type = "market"
        else:
            order_type = "limit"
            price = self._adjust_price_tick(symbol, price, rounding=ROUND_HALF_UP)

        # common payload
        signature_payload = {
                "symbol": symbol,
                "reduce_only": False, # make it false
                "amount": amount,
                "side": side,
                "client_order_id": str(uuid.uuid4()),
        }
        if order_type == "market":
            signature_payload["reduce_only"] = is_reduce_only
            signature_payload["slippage_percent"] = str(slippage)
            signature_header, req_url = _get_signature_header_and_url("create_market_order")
        else:
            signature_payload["price"] = price
            signature_payload["tif"] = "GTC"
            signature_header, req_url = _get_signature_header_and_url("create_order")
        
        message, signature = sign_message(
            signature_header, signature_payload, self.agent_keypair
        )
        request_header = {
            "account": self.public_key,
            "agent_wallet": self.agent_public_key,
            "signature": signature,
            "timestamp": signature_header["timestamp"],
            "expiry_window": signature_header["expiry_window"],
        }
        # Send the request
        headers = {"Content-Type": "application/json"}

        request = {
            **request_header,
            **signature_payload,
        }

        s = self._session()
        async with s.post(req_url, json=request, headers=headers) as r:
            status = r.status
            try:
                data = await r.json()
            except aiohttp.ContentTypeError:
                data = await r.text()

        try:
            return (data or {}).get("data", {}).get("order_id")
        except Exception:
            return None

    async def get_position(self, symbol):
        """
        GET /positions
        """
        url = f"{BASE_URL}/positions"
        
        s = self._session()
        params = {"account":self.public_key}
        
        async with s.get(url, params=params) as r:
            r.raise_for_status()
            data = await r.json()
        
        data = data.get('data',{})
        results = []
        for pos in data:
            if pos.get("symbol") == symbol:
                return {
                    "symbol": symbol,
                    "side": "buy" if pos.get("side")=="bid" else "ask",
                    "price": pos.get("entry_price"),
                    "size":pos.get("amount"),
                }
    
    
    async def get_collateral(self):
        """
        GET /account
        """
        url = f"{BASE_URL}/account"
        s = self._session()
        params = {"account":self.public_key}
        async with s.get(url, params=params) as r:
            r.raise_for_status()
            data = await r.json()
        
        data = data.get('data',{})

        try:        
            return {
                "total_collateral": data.get("account_equity"),
                "available_collateral": data.get("available_to_spend"),
            }
        except:
            return {
                "total_collateral": None,
                "available_collateral": None,
            }
    
    async def get_open_orders(self, symbol):
        """
        GET /orders
        """
        url = f"{BASE_URL}/orders"
        
        s = self._session()
        params = {"account":self.public_key}
        
        async with s.get(url, params=params) as r:
            r.raise_for_status()
            data = await r.json()
        
        data = data.get('data',{})
        results = []
        for pos in data:
            if pos.get("symbol") == symbol:
                results.append({
                    "id": pos.get("order_id"),
                    "symbol": symbol,
                    "side": "buy" if pos.get("side")=="bid" else "ask",
                    "price": pos.get("price"),
                    "quantity":pos.get("initial_amount"),
                    "fileed_quantity":pos.get("filled_amount"),
                    "order_type":pos.get("order_type")
                })
        return results

    async def cancel_orders(self, symbol, open_orders = None):
        if open_orders is None:
            open_orders = await self.get_open_orders(symbol)

        if not open_orders:
            return []
        
        results = []
        for order in open_orders:
            order_id = order["id"]
            signature_payload = {
                "symbol": symbol,
                "order_id": order_id,
            }
            signature_header, req_url = _get_signature_header_and_url("cancel_order")
            message, signature = sign_message(
                signature_header, signature_payload, self.agent_keypair
            )
            request_header = {
                "account": self.public_key,
                "agent_wallet": self.agent_public_key,
                "signature": signature,
                "timestamp": signature_header["timestamp"],
                "expiry_window": signature_header["expiry_window"],
            }
            # Send the request
            headers = {"Content-Type": "application/json"}

            request = {
                **request_header,
                **signature_payload,
            }

            s = self._session()
            async with s.post(req_url, json=request, headers=headers) as r:
                status = r.status
                try:
                    data = await r.json()
                except aiohttp.ContentTypeError:
                    data = await r.text()
            try:
                results.append({
                    "id": order_id,
                    "status": data.get("success")
                })
            except Exception as e:
                results.append({
                    "id": order_id,
                    "status": "FAILED",
                    "message": str(e)
                })
        return results
            
            


    async def refresh_prices(self) -> Dict[str, float]:
        """
        GET /info/prices → 런타임 캐시(self._price_cache) 갱신 후 {symbol: mark(float)} 반환
        """
        url = f"{BASE_URL}/info/prices"
        s = self._session()
        async with s.get(url) as r:
            r.raise_for_status()
            data = await r.json()

        items = data.get("data") or []
        ts_now = int(time.time() * 1000)
        out: Dict[str, float] = {}

        for it in items:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "").upper()
            if not sym:
                continue

            # 문자열 숫자 → Decimal → float 변환
            def _f(k):
                v = it.get(k)
                try:
                    return float(Decimal(str(v))) if v is not None else None
                except Exception:
                    return None

            mark = _f("mark")
            mid = _f("mid")
            oracle = _f("oracle")
            ts = int(it.get("timestamp") or ts_now)

            self._price_cache[sym] = {
                "mark": mark,
                "mid": mid,
                "oracle": oracle,
                "ts": ts,
            }
            if mark is not None:
                out[sym] = mark

        return out

    async def get_mark_price(self, symbol: str, *, force_refresh: bool = True, fallback: str = "mark") -> Optional[float]:
        """
        - 기본: 원격 갱신(force_refresh=True) 후 캐시에서 반환
        - force_refresh=False이면 캐시 우선, 없으면 원격 갱신 시도
        - fallback: 캐시에 mark가 없으면 mid→oracle 순으로 대체할 때 사용하는 키 우선순위
        """
        symbol = str(symbol).upper()

        if force_refresh:
            await self.refresh_prices()

        entry = self._price_cache.get(symbol)
        if entry:
            # mark가 없을 수 있어 보강
            val = entry.get("mark")
            if val is None:
                # fallback 체인 구성
                order = ["mark", "mid", "oracle"]
                # 사용자가 지정한 fallback을 맨 앞으로
                if fallback in order:
                    order.remove(fallback)
                    order.insert(0, fallback)
                for k in order:
                    v = entry.get(k)
                    if isinstance(v, (int, float)):
                        return float(v)
            return float(val) if isinstance(val, (int, float)) else None

        # 캐시에 없으면 한 번 더 갱신 시도
        prices = await self.refresh_prices()
        return prices.get(symbol)

    async def close_position(self, symbol, position, *, is_reduce_only=False):
        return await super().close_position(symbol, position, is_reduce_only=is_reduce_only)
        