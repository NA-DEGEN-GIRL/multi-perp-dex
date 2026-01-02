"""
StandX WebSocket Client

Provides real-time data fetching for:
- price (mark_price, index_price, last_price)
- depth_book (orderbook)
- position (user positions) - requires auth
- balance (user balance) - requires auth
"""
import asyncio
import logging
import time
from typing import Optional, Dict, Any, Set

from wrappers.base_ws_client import BaseWSClient, _json_dumps

logger = logging.getLogger(__name__)


STANDX_WS_URL = "wss://perps.standx.com/ws-stream/v1"


class StandXWSClient(BaseWSClient):
    """
    StandX WebSocket 클라이언트.
    BaseWSClient를 상속하여 연결/재연결 로직 공유.
    """

    WS_URL = STANDX_WS_URL
    PING_INTERVAL = None  # StandX는 ping 사용 안 함
    RECONNECT_MIN = 0.2
    RECONNECT_MAX = 30.0

    def __init__(self, jwt_token: Optional[str] = None):
        super().__init__()
        self.jwt_token = jwt_token

        # Subscriptions
        self._price_subs: Set[str] = set()
        self._orderbook_subs: Set[str] = set()
        self._user_subs: Set[str] = set()  # position, balance, order, trade

        # Cached data
        self._prices: Dict[str, Dict[str, Any]] = {}
        self._orderbooks: Dict[str, Dict[str, Any]] = {}
        self._positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position
        self._collateral: Optional[Dict[str, Any]] = None

        # Events for waiting
        self._price_events: Dict[str, asyncio.Event] = {}
        self._orderbook_events: Dict[str, asyncio.Event] = {}
        self._position_event: asyncio.Event = asyncio.Event()
        self._collateral_event: asyncio.Event = asyncio.Event()

        # Auth state
        self._authenticated: bool = False

        # Reconnect event (for _send to wait)
        self._reconnect_event: asyncio.Event = asyncio.Event()
        self._reconnect_event.set()  # Initially not reconnecting

    # ==================== Abstract Method Implementations ====================

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket message"""
        channel = data.get("channel")
        symbol = data.get("symbol")
        payload = data.get("data", {})

        if channel == "auth":
            code = payload.get("code")
            if code == 0:  # 0 = success
                self._authenticated = True
            else:
                msg = f"[StandXWS] auth failed: {payload}"
                print(msg)
                logger.error(msg)
            return

        if channel == "price":
            self._prices[symbol] = payload
            if symbol in self._price_events:
                self._price_events[symbol].set()

        elif channel == "depth_book":
            self._orderbooks[symbol] = self._parse_orderbook(payload)
            if symbol in self._orderbook_events:
                self._orderbook_events[symbol].set()

        elif channel == "position":
            logger.debug(f"[StandXWS] position update: {payload}")
            pos_symbol = payload.get("symbol")
            if pos_symbol:
                self._positions[pos_symbol] = payload
            self._position_event.set()

        elif channel == "balance":
            free = payload.get("free", "0")
            total = payload.get("total", "0")
            locked = payload.get("locked", "0")

            self._collateral = {
                "cross_available": free,
                "balance": total,
                "equity": total,
                "upnl": "0",
                "cross_balance": total,
                "isolated_balance": "0",
                "locked": locked,
                "_raw": payload,
            }
            self._collateral_event.set()

    async def _resubscribe(self) -> None:
        """Resubscribe to all channels after reconnect"""
        # Re-authenticate if we had a token
        if self.jwt_token:
            auth_msg: Dict[str, Any] = {
                "auth": {
                    "token": self.jwt_token,
                    "streams": [
                        {"channel": "balance"},
                    ]
                }
            }
            await self._ws.send(_json_dumps(auth_msg))
            # Wait for auth
            for _ in range(50):
                if self._authenticated:
                    break
                await asyncio.sleep(0.1)

        # Resubscribe to price channels
        for symbol in self._price_subs:
            await self._ws.send(_json_dumps({"subscribe": {"channel": "price", "symbol": symbol}}))

        # Resubscribe to orderbook channels
        for symbol in self._orderbook_subs:
            await self._ws.send(_json_dumps({"subscribe": {"channel": "depth_book", "symbol": symbol}}))

    def _build_ping_message(self) -> Optional[str]:
        """StandX doesn't use ping"""
        return None

    # ==================== Connection Management ====================

    async def connect(self) -> bool:
        """WS 연결 (base class 사용)"""
        return await super().connect()

    async def close(self) -> None:
        """연결 종료 및 상태 초기화"""
        await super().close()
        self._authenticated = False
        self._price_subs.clear()
        self._orderbook_subs.clear()
        self._user_subs.clear()

    async def _handle_disconnect(self) -> None:
        """연결 끊김 처리 - reconnect event 관리 추가"""
        self._reconnect_event.clear()
        self._authenticated = False
        await super()._handle_disconnect()
        self._reconnect_event.set()

    # ==================== StandX-specific Methods ====================

    async def _send_msg(self, msg: Dict[str, Any]) -> None:
        """Send message to WebSocket (with reconnect wait)"""
        if self._reconnecting:
            try:
                await asyncio.wait_for(self._reconnect_event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                raise RuntimeError("[standx_ws] reconnect timeout")

        if not self._ws or not self._running:
            await self.connect()
        if self._ws:
            try:
                await self._ws.send(_json_dumps(msg))
            except Exception:
                if self._reconnecting:
                    await asyncio.wait_for(self._reconnect_event.wait(), timeout=60.0)
                    if self._ws:
                        await self._ws.send(_json_dumps(msg))

    # ----------------------------
    # Authentication
    # ----------------------------
    async def authenticate(self, jwt_token: str, streams: Optional[list] = None) -> bool:
        """
        Authenticate with JWT token

        Args:
            jwt_token: JWT access token
            streams: Optional list of channels to subscribe on auth
                     e.g., [{"channel": "order"}, {"channel": "position"}]
        """
        self.jwt_token = jwt_token
        auth_msg: Dict[str, Any] = {
            "auth": {
                "token": jwt_token,
            }
        }
        if streams:
            auth_msg["auth"]["streams"] = streams
            for stream in streams:
                self._user_subs.add(stream["channel"])

        await self._send_msg(auth_msg)

        # Wait for auth response
        for _ in range(50):  # 5 seconds
            if self._authenticated:
                return True
            await asyncio.sleep(0.1)
        return False

    # ----------------------------
    # Public Subscriptions
    # ----------------------------
    async def subscribe_price(self, symbol: str) -> None:
        """Subscribe to price channel for symbol"""
        if symbol in self._price_subs:
            return
        await self._send_msg({"subscribe": {"channel": "price", "symbol": symbol}})
        self._price_subs.add(symbol)
        if symbol not in self._price_events:
            self._price_events[symbol] = asyncio.Event()

    async def unsubscribe_price(self, symbol: str) -> None:
        """Unsubscribe from price channel"""
        if symbol not in self._price_subs:
            return
        await self._send_msg({"unsubscribe": {"channel": "price", "symbol": symbol}})
        self._price_subs.discard(symbol)

    async def subscribe_orderbook(self, symbol: str) -> None:
        """Subscribe to orderbook (depth_book) channel for symbol"""
        if symbol in self._orderbook_subs:
            return
        await self._send_msg({"subscribe": {"channel": "depth_book", "symbol": symbol}})
        self._orderbook_subs.add(symbol)
        if symbol not in self._orderbook_events:
            self._orderbook_events[symbol] = asyncio.Event()

    async def unsubscribe_orderbook(self, symbol: str) -> None:
        """Unsubscribe from orderbook (depth_book) channel"""
        if symbol not in self._orderbook_subs:
            return
        await self._send_msg({"unsubscribe": {"channel": "depth_book", "symbol": symbol}})
        self._orderbook_subs.discard(symbol)

    # ----------------------------
    # User Subscriptions (requires auth)
    # ----------------------------
    async def subscribe_position(self) -> None:
        """Subscribe to position channel (requires auth)"""
        if "position" in self._user_subs:
            return
        await self._send_msg({"subscribe": {"channel": "position"}})
        self._user_subs.add("position")

    async def subscribe_balance(self) -> None:
        """Subscribe to balance channel (requires auth)"""
        if "balance" in self._user_subs:
            return
        await self._send_msg({"subscribe": {"channel": "balance"}})
        self._user_subs.add("balance")

    async def subscribe_user_channels(self) -> None:
        """Subscribe to all user channels"""
        await self.subscribe_position()
        await self.subscribe_balance()

    # ----------------------------
    # Data Getters
    # ----------------------------
    def get_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached price data for symbol"""
        return self._prices.get(symbol)

    def get_mark_price(self, symbol: str) -> Optional[str]:
        """Get mark price for symbol"""
        price_data = self._prices.get(symbol)
        if price_data:
            return price_data.get("mark_price")
        return None

    def get_orderbook(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached orderbook for symbol"""
        return self._orderbooks.get(symbol)

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

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached position for symbol"""
        return self._positions.get(symbol)

    def get_collateral(self) -> Optional[Dict[str, Any]]:
        """Get cached collateral/balance"""
        return self._collateral

    # ----------------------------
    # Wait for data
    # ----------------------------
    async def wait_price_ready(self, symbol: str, timeout: float = 5.0) -> bool:
        """Wait until price data is available"""
        if symbol in self._prices:
            return True

        if symbol not in self._price_events:
            self._price_events[symbol] = asyncio.Event()

        try:
            await asyncio.wait_for(self._price_events[symbol].wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_orderbook_ready(self, symbol: str, timeout: float = 5.0) -> bool:
        """Wait until orderbook data is available"""
        if symbol in self._orderbooks:
            return True

        if symbol not in self._orderbook_events:
            self._orderbook_events[symbol] = asyncio.Event()

        try:
            await asyncio.wait_for(self._orderbook_events[symbol].wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_position_ready(self, timeout: float = 5.0) -> bool:
        """Wait until position data is available"""
        if self._positions:
            return True
        try:
            await asyncio.wait_for(self._position_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_collateral_ready(self, timeout: float = 0.1) -> bool:
        """Wait until collateral/balance data is available"""
        if self._collateral:
            return True
        try:
            await asyncio.wait_for(self._collateral_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# ----------------------------
# WebSocket Pool (Singleton)
# ----------------------------
class StandXWSPool:
    """
    Singleton pool for StandX WebSocket connections.
    Shares connections across multiple exchange instances.
    """

    def __init__(self):
        self._clients: Dict[str, StandXWSClient] = {}  # key: wallet_address
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        wallet_address: str,
        jwt_token: Optional[str] = None,
    ) -> StandXWSClient:
        """
        Get or create a WebSocket client for the given wallet.
        """
        key = wallet_address.lower()

        async with self._lock:
            if key in self._clients:
                client = self._clients[key]
                # Reconnect if needed
                if not client._running:
                    await client.connect()
                return client

            # Create new client
            client = StandXWSClient(jwt_token=jwt_token)
            await client.connect()

            # Authenticate if token provided
            if jwt_token:
                auth = await client.authenticate(jwt_token, streams=[
                    {"channel": "balance"},
                ])
                if not auth:
                    msg = f"[StandXWSPool] auth failed for wallet {wallet_address}"
                    print(msg)
                    logger.error(msg)

            self._clients[key] = client
            return client

    async def release(self, wallet_address: str) -> None:
        """Release a client (does not close, just marks as available)"""
        pass  # Keep connection alive for reuse

    async def close_all(self) -> None:
        """Close all connections"""
        async with self._lock:
            for client in self._clients.values():
                await client.close()
            self._clients.clear()


# Global singleton
WS_POOL = StandXWSPool()
