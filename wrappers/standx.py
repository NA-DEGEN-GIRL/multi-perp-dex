"""
StandX Perps Exchange Wrapper

Implements MultiPerpDex interface for StandX perpetual trading.
"""
import json
import time
import aiohttp
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Any, List

from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from .standx_auth import StandXAuth


STANDX_PERPS_BASE = "https://perps.standx.com"


class StandXExchange(MultiPerpDexMixin, MultiPerpDex):
    """
    StandX Perps Exchange Wrapper

    Usage:
        # With private key (auto sign)
        ex = StandXExchange(
            wallet_address="0x...",
            chain="bsc",
            evm_private_key="0x...",
            fetch_by_ws=True  # Enable WebSocket for price/position/balance
        )
        await ex.init()

        # With browser signing
        ex = StandXExchange(
            wallet_address="0x...",
            chain="bsc"
        )
        await ex.init(login_port=7081)
    """

    def __init__(
        self,
        wallet_address: str,
        chain: str = "bsc",
        evm_private_key: Optional[str] = None,
        session_token: Optional[str] = None,
        http_timeout: float = 30.0,
        fetch_by_ws: bool = False,
    ):
        super().__init__()
        self.has_spot = False
        self.wallet_address = wallet_address
        self.chain = chain
        self._http_timeout = http_timeout
        self.fetch_by_ws = fetch_by_ws # partially... 현재 position과 balance는 ws 구독은 되나 서버에서 데이터를 안줌
        self.fetch_by_ws_partial = True

        # Auth handler
        self._auth = StandXAuth(
            wallet_address=wallet_address,
            chain=chain,
            evm_private_key=evm_private_key,
            session_token=session_token,
            http_timeout=http_timeout,
        )

        # Symbol info cache
        self._symbol_info: Dict[str, Dict] = {}

        # Collateral symbol
        self.COLLATERAL_SYMBOL = "DUSD"

        # WebSocket client
        self.ws_client = None

    async def init(self, login_port: Optional[int] = None, open_browser: bool = True) -> "StandXExchange":
        """
        Initialize exchange: login and fetch symbol info

        Args:
            login_port: Port for browser signing (None = use private key)
            open_browser: Auto open browser for signing
        """
        await self._auth.login(port=login_port, open_browser=open_browser)
        await self._update_available_symbols()

        # Initialize WebSocket if enabled
        if self.fetch_by_ws or self.fetch_by_ws_partial:
            await self._create_ws_client()

        return self

    async def _create_ws_client(self):
        """Create and authenticate WebSocket client"""
        if self.ws_client is not None:
            return

        from .standx_ws_client import WS_POOL

        self.ws_client = await WS_POOL.acquire(
            wallet_address=self.wallet_address,
            jwt_token=self._auth.token,
        )

    async def _reauth(self) -> bool:
        """Re-authenticate when token expires"""
        print("[standx] token expired, re-authenticating...")
        try:
            self._auth._token = None
            self._auth._logged_in = False
            await self._auth.login()

            # Update WS client token if exists
            if self.ws_client:
                self.ws_client.jwt_token = self._auth.token
                self.ws_client._authenticated = False
                if self.ws_client._ws and self.ws_client._running:
                    await self.ws_client.authenticate(self._auth.token)

            print("[standx] re-authentication successful")
            return True
        except Exception as e:
            print(f"[standx] re-authentication failed: {e}")
            return False

    async def _auth_get(self, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> aiohttp.ClientResponse:
        """GET request with auto re-auth on 401/403"""
        if headers is None:
            headers = {}
        headers.update(self._auth.get_auth_headers())

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status in (401, 403):
                    if await self._reauth():
                        headers.update(self._auth.get_auth_headers())
                        async with session.get(url, headers=headers, params=params) as retry_resp:
                            return await self._handle_response(retry_resp)
                return await self._handle_response(resp)

    async def _auth_post(self, url: str, data: Optional[str] = None, headers: Optional[Dict] = None) -> Dict[str, Any]:
        """POST request with auto re-auth on 401/403"""
        if headers is None:
            headers = {}
        headers.update(self._auth.get_auth_headers())

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.post(url, data=data, headers=headers) as resp:
                if resp.status in (401, 403):
                    if await self._reauth():
                        # Re-sign the request if needed
                        if data and "x-request-signature" in headers:
                            headers.update(self._auth.sign_request(data))
                        headers.update(self._auth.get_auth_headers())
                        async with session.post(url, data=data, headers=headers) as retry_resp:
                            return await self._handle_response(retry_resp)
                return await self._handle_response(resp)

    async def _handle_response(self, resp: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Handle response and return JSON"""
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"Request failed: {resp.status} {text}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    async def close(self):
        """Cleanup (no persistent session to close)"""
        pass

    # ----------------------------
    # Symbol Info
    # ----------------------------
    async def _update_available_symbols(self):
        """Fetch available trading symbols"""
        self.available_symbols["perp"] = []

        # Get all symbol info
        symbols = await self._query_symbol_info()
        for info in symbols:
            symbol = info.get("symbol")
            # status == "trading" means the symbol is active
            if symbol and info.get("status") == "trading":
                self.available_symbols["perp"].append(symbol)
                self._symbol_info[symbol] = info

    async def _query_symbol_info(self, symbol: Optional[str] = None) -> List[Dict]:
        """GET /api/query_symbol_info"""
        url = f"{STANDX_PERPS_BASE}/api/query_symbol_info"
        params = {}
        if symbol:
            params["symbol"] = symbol
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"query_symbol_info failed: {resp.status} {text}")
                return await resp.json()

    def _get_symbol_info(self, symbol: str) -> Dict:
        """Get cached symbol info"""
        if symbol not in self._symbol_info:
            raise ValueError(f"Unknown symbol: {symbol}")
        return self._symbol_info[symbol]

    # ----------------------------
    # Price
    # ----------------------------
    async def get_mark_price(self, symbol: str) -> str:
        """Get mark price (WS first, REST fallback)"""
        if self.fetch_by_ws or self.fetch_by_ws_partial:
            try:
                return await self.get_mark_price_ws(symbol)
            except Exception as e:
                print(f"[standx] get_mark_price falling back to REST: {e}")
        print("[standx] get_mark_price via REST")
        return await self.get_mark_price_rest(symbol)

    async def get_mark_price_ws(self, symbol: str, timeout: float = 5.0) -> str:
        """Get mark price via WebSocket"""
        if not self.ws_client:
            await self._create_ws_client()

        # Subscribe if not already
        await self.ws_client.subscribe_price(symbol)

        # Wait for data
        ready = await self.ws_client.wait_price_ready(symbol, timeout=timeout)
        if not ready:
            raise TimeoutError(f"WS price not ready for {symbol}")

        price = self.ws_client.get_mark_price(symbol)
        if price is None:
            raise ValueError(f"No price data for {symbol}")

        return price

    async def get_mark_price_rest(self, symbol: str) -> str:
        """GET /api/query_symbol_price"""
        url = f"{STANDX_PERPS_BASE}/api/query_symbol_price"
        params = {"symbol": symbol}

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"query_symbol_price failed: {resp.status} {text}")
                data = await resp.json()
                return data.get("mark_price", "0")

    # ----------------------------
    # Collateral / Balance
    # ----------------------------
    async def get_collateral(self) -> Dict[str, Any]:
        """
        Get collateral/balance (WS first, REST fallback)

        Returns:
            {
                "available_collateral": float,
                "total_collateral": float,
                "equity": float,
                "upnl": float,
            }
        """
        if self.fetch_by_ws:
            try:
                return await self.get_collateral_ws()
            except Exception as e:
                print(f"[standx] get_collateral falling back to REST: {e}")

        return await self.get_collateral_rest()

    async def get_collateral_ws(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Get collateral via WebSocket"""
        if not self.ws_client:
            await self._create_ws_client()

        # Subscribe if not already
        await self.ws_client.subscribe_balance()

        # Wait for data
        ready = await self.ws_client.wait_balance_ready(timeout=timeout)
        if not ready:
            raise TimeoutError("WS balance not ready")

        balance = self.ws_client.get_balance()
        if balance is None:
            raise ValueError("No balance data available")

        return self._parse_collateral(balance)

    async def get_collateral_rest(self) -> Dict[str, Any]:
        """GET /api/query_balance"""
        url = f"{STANDX_PERPS_BASE}/api/query_balance"
        data = await self._auth_get(url)
        return self._parse_collateral(data)

    def _parse_collateral(self, data: Dict) -> Dict[str, Any]:
        """Parse balance response"""
        return {
            "available_collateral": float(data.get("cross_available", 0)),
            "total_collateral": float(data.get("balance", 0)),
            "equity": float(data.get("equity", 0)),
            "upnl": float(data.get("upnl", 0)),
            "cross_balance": float(data.get("cross_balance", 0)),
            "isolated_balance": float(data.get("isolated_balance", 0)),
        }

    # ----------------------------
    # Position
    # ----------------------------
    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get position (WS first, REST fallback)

        Returns position dict or None if no position
        """
        if self.fetch_by_ws:
            try:
                return await self.get_position_ws(symbol)
            except Exception as e:
                print(f"[standx] get_position falling back to REST: {e}")

        return await self.get_position_rest(symbol)

    async def get_position_ws(self, symbol: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Get position via WebSocket"""
        if not self.ws_client:
            await self._create_ws_client()

        # Subscribe if not already
        await self.ws_client.subscribe_position()

        # Wait for data
        ready = await self.ws_client.wait_position_ready(timeout=timeout)
        if not ready:
            raise TimeoutError(f"WS position not ready for {symbol}")

        pos = self.ws_client.get_position(symbol)
        if pos is None:
            return None

        return self._parse_position(pos)

    async def get_position_rest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """GET /api/query_positions"""
        url = f"{STANDX_PERPS_BASE}/api/query_positions"
        params = {"symbol": symbol}
        positions = await self._auth_get(url, params=params)

        for pos in positions:
            if pos.get("symbol") == symbol and pos.get("status") == "open":
                return self._parse_position(pos)
        return None

    def _parse_position(self, pos: Dict) -> Dict[str, Any]:
        """Parse position response"""
        """StnadX는 qty가 0이여도 position 정보를 줌"""
        qty = Decimal(pos.get("qty", "0"))
        if qty == 0:
            return None
        side = "long" if qty > 0 else "short"
        size = str(abs(qty))

        return {
            "symbol": pos.get("symbol"),
            "side": side,
            "size": size,
            "entry_price": pos.get("entry_price", "0"),
            "mark_price": pos.get("mark_price", "0"),
            "unrealized_pnl": pos.get("upnl", "0"),
            "realized_pnl": pos.get("realized_pnl", "0"),
            "leverage": pos.get("leverage", "1"),
            "margin_mode": pos.get("margin_mode", "cross"),
            "liq_price": pos.get("liq_price", "0"),
        }

    # ----------------------------
    # Orders
    # ----------------------------
    async def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
        reduce_only: bool = False,
        time_in_force: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /api/new_order

        Args:
            symbol: Trading pair (e.g., "BTC-USD")
            side: "buy" or "sell"
            amount: Order quantity
            price: Order price (required for limit orders)
            order_type: "market" or "limit"
            reduce_only: Only reduce position
            time_in_force: "gtc", "ioc", or "alo"
            client_order_id: Custom order ID
        """
        # Determine order type
        if price is not None:
            order_type = "limit"

        # Get symbol info for formatting
        info = self._get_symbol_info(symbol)
        qty_decimals = info.get("qty_tick_decimals", 3)
        price_decimals = info.get("price_tick_decimals", 2)
        min_order_qty = float(info.get("min_order_qty", 0))
        max_order_qty = float(info.get("max_order_qty", float("inf")))

        # Validate order quantity
        if amount < min_order_qty:
            raise ValueError(f"Order quantity {amount} is below minimum {min_order_qty} for {symbol}")
        if amount > max_order_qty:
            raise ValueError(f"Order quantity {amount} exceeds maximum {max_order_qty} for {symbol}")

        # Format quantity
        qty_str = self._format_decimal(amount, qty_decimals)

        # Build payload
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.lower(),
            "order_type": order_type.lower(),
            "qty": qty_str,
            "reduce_only": reduce_only,
        }

        # Time in force
        if time_in_force:
            payload["time_in_force"] = time_in_force.lower()
        else:
            payload["time_in_force"] = "ioc" if order_type == "market" else "gtc"

        # Price for limit orders
        if order_type == "limit" and price is not None:
            payload["price"] = self._format_decimal(price, price_decimals)

        # Client order ID
        if client_order_id:
            payload["cl_ord_id"] = client_order_id

        return await self._post_signed("/api/new_order", payload)

    async def cancel_orders(self, symbol: str, open_orders: Optional[List] = None) -> Dict[str, Any]:
        """
        Cancel all open orders for symbol

        POST /api/cancel_orders
        """
        # First get open orders
        if open_orders is None:
            open_orders = await self.get_open_orders(symbol)

        if not open_orders:
            return {"canceled": 0}

        # Extract order IDs
        order_ids = [o.get("id") for o in open_orders if o.get("id")]

        if not order_ids:
            return {"canceled": 0}

        payload = {"order_id_list": order_ids}
        result = await self._post_signed("/api/cancel_orders", payload)

        return {"canceled": len(order_ids), "result": result}

    async def cancel_order(self, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Cancel single order

        POST /api/cancel_order
        """
        payload: Dict[str, Any] = {}
        if order_id:
            payload["order_id"] = order_id
        if client_order_id:
            payload["cl_ord_id"] = client_order_id

        if not payload:
            raise ValueError("order_id or client_order_id required")

        return await self._post_signed("/api/cancel_order", payload)

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        GET /api/query_open_orders
        """
        url = f"{STANDX_PERPS_BASE}/api/query_open_orders"
        params = {"symbol": symbol} if symbol else {}
        data = await self._auth_get(url, params=params)
        orders = data.get("result", [])
        return [self._parse_order(o) for o in orders]

    def _parse_order(self, order: Dict) -> Dict[str, Any]:
        """Parse order response"""
        return {
            "id": order.get("id"),
            "cl_ord_id": order.get("cl_ord_id"),
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "order_type": order.get("order_type"),
            "price": order.get("price"),
            "qty": order.get("qty"),
            "filled_qty": order.get("fill_qty", "0"),
            "status": order.get("status"),
            "reduce_only": order.get("reduce_only", False),
            "time_in_force": order.get("time_in_force"),
            "created_at": order.get("created_at"),
        }

    # ----------------------------
    # Close Position
    # ----------------------------
    async def close_position(self, symbol: str, position: Optional[Dict] = None, reduce_only: bool = True) -> Optional[Dict]:
        """Close position with market order"""
        if position is None:
            position = await self.get_position(symbol)

        if not position:
            return None

        size = position.get("size", "0")
        if float(size) == 0:
            return None

        side = "sell" if position.get("side") == "long" else "buy"

        return await self.create_order(
            symbol=symbol,
            side=side,
            amount=float(size),
            order_type="market",
            reduce_only=reduce_only,
        )

    # ----------------------------
    # Leverage / Margin
    # ----------------------------
    async def change_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """POST /api/change_leverage"""
        payload = {
            "symbol": symbol,
            "leverage": leverage,
        }
        return await self._post_signed("/api/change_leverage", payload)

    async def change_margin_mode(self, symbol: str, margin_mode: str) -> Dict[str, Any]:
        """
        POST /api/change_margin_mode

        Args:
            margin_mode: "cross" or "isolated"
        """
        payload = {
            "symbol": symbol,
            "margin_mode": margin_mode.lower(),
        }
        return await self._post_signed("/api/change_margin_mode", payload)

    async def get_position_config(self, symbol: str) -> Dict[str, Any]:
        """GET /api/query_position_config"""
        url = f"{STANDX_PERPS_BASE}/api/query_position_config"
        params = {"symbol": symbol}
        return await self._auth_get(url, params=params)

    # ----------------------------
    # Market Data
    # ----------------------------
    async def get_orderbook(self, symbol: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Get orderbook (WS only when fetch_by_ws=True, REST otherwise)

        When fetch_by_ws=True, orderbook is fetched via WebSocket only (no REST fallback).
        """
        if self.fetch_by_ws or self.fetch_by_ws_partial:
            return await self.get_orderbook_ws(symbol, timeout=timeout)
        print("[standx] get_orderbook via REST")

        return await self.get_orderbook_rest(symbol)

    async def get_orderbook_ws(self, symbol: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Get orderbook via WebSocket (no REST fallback)"""
        if not self.ws_client:
            await self._create_ws_client()

        # Subscribe if not already
        await self.ws_client.subscribe_depth(symbol)

        # Wait for data
        ready = await self.ws_client.wait_depth_ready(symbol, timeout=timeout)
        if not ready:
            raise TimeoutError(f"WS orderbook not ready for {symbol}")

        orderbook = self.ws_client.get_orderbook(symbol)
        if orderbook is None:
            raise ValueError(f"No orderbook data for {symbol}")

        return orderbook

    async def get_orderbook_rest(self, symbol: str) -> Dict[str, Any]:
        """GET /api/query_depth_book"""
        url = f"{STANDX_PERPS_BASE}/api/query_depth_book"
        params = {"symbol": symbol}

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"query_depth_book failed: {resp.status} {text}")
                data = await resp.json()
                return self._parse_orderbook(data)

    @staticmethod
    def _parse_orderbook(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse StandX orderbook to standard format.

        StandX: {"asks": [["price", "size"], ...], "bids": [...]}
        Output: {"asks": [[price, size], ...], "bids": [...], "time": int}
        """
        def parse_levels(levels: list) -> list:
            result = []
            for item in levels:
                try:
                    px = float(item[0])
                    sz = float(item[1])
                    result.append([px, sz])
                except (IndexError, ValueError, TypeError):
                    continue
            return result

        asks = parse_levels(data.get("asks", []))
        bids = parse_levels(data.get("bids", []))

        # 표준 정렬: asks 오름차순, bids 내림차순
        asks.sort(key=lambda x: x[0])
        bids.sort(key=lambda x: x[0], reverse=True)

        return {
            "asks": asks,
            "bids": bids,
            "time": int(time.time() * 1000),
        }

    async def unsubscribe_orderbook(self, symbol: str):
        #return # 오더북 하나니깐 그냥 놔둠
        """Unsubscribe from orderbook WebSocket channel"""
        if self.ws_client:
            await self.ws_client.unsubscribe_depth(symbol)

    async def get_recent_trades(self, symbol: str) -> List[Dict]:
        """GET /api/query_recent_trades"""
        url = f"{STANDX_PERPS_BASE}/api/query_recent_trades"
        params = {"symbol": symbol}

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"query_recent_trades failed: {resp.status} {text}")
                return await resp.json()

    async def get_symbol_market(self, symbol: str) -> Dict[str, Any]:
        """GET /api/query_symbol_market"""
        url = f"{STANDX_PERPS_BASE}/api/query_symbol_market"
        params = {"symbol": symbol}

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"query_symbol_market failed: {resp.status} {text}")
                return await resp.json()

    # ----------------------------
    # User Trades
    # ----------------------------
    async def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """GET /api/query_trades"""
        url = f"{STANDX_PERPS_BASE}/api/query_trades"
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        data = await self._auth_get(url, params=params)
        return data.get("result", [])

    # ----------------------------
    # Internal Helpers
    # ----------------------------
    async def _post_signed(self, endpoint: str, payload: Dict) -> Dict[str, Any]:
        """POST request with body signature and auto re-auth on 401/403"""
        url = f"{STANDX_PERPS_BASE}{endpoint}"
        payload_str = json.dumps(payload, separators=(",", ":"))

        # Get auth and signature headers
        headers = {
            "Content-Type": "application/json",
            **self._auth.get_auth_headers(),
            **self._auth.sign_request(payload_str),
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.post(url, data=payload_str, headers=headers) as resp:
                text = await resp.text()

                # Re-auth on 401/403
                if resp.status in (401, 403):
                    if await self._reauth():
                        # Re-sign with new auth
                        headers = {
                            "Content-Type": "application/json",
                            **self._auth.get_auth_headers(),
                            **self._auth.sign_request(payload_str),
                        }
                        async with session.post(url, data=payload_str, headers=headers) as retry_resp:
                            retry_text = await retry_resp.text()
                            if retry_resp.status != 200:
                                raise RuntimeError(f"{endpoint} failed: {retry_resp.status} {retry_text}")
                            try:
                                return json.loads(retry_text)
                            except json.JSONDecodeError:
                                return {"raw": retry_text}

                if resp.status != 200:
                    raise RuntimeError(f"{endpoint} failed: {resp.status} {text}")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"raw": text}

    @staticmethod
    def _format_decimal(value: float, decimals: int) -> str:
        """Format number with specific decimal places"""
        d = Decimal(str(value))
        quantizer = Decimal(10) ** -decimals
        d = d.quantize(quantizer, rounding=ROUND_DOWN)
        return format(d, "f").rstrip("0").rstrip(".")

    def get_perp_quote(self, symbol: str, *, is_basic_coll: bool = False) -> str:
        """Get quote currency for perp"""
        return "DUSD"
