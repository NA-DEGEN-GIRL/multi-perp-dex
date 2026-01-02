"""
StandX WebSocket Client

Provides real-time data fetching for:
- price (mark_price, index_price, last_price)
- depth_book (orderbook)
- position (user positions) - requires auth
- balance (user balance) - requires auth
"""
import asyncio
import json
import time
from typing import Optional, Dict, Any, Set, Callable
from dataclasses import dataclass, field

import websockets
from websockets.client import WebSocketClientProtocol


STANDX_WS_URL = "wss://perps.standx.com/ws-stream/v1"


@dataclass
class StandXWSClient:
    """
    Single WebSocket connection to StandX.
    Manages subscriptions and caches data.
    """
    ws_url: str = STANDX_WS_URL
    jwt_token: Optional[str] = None

    # Connection
    _ws: Optional[WebSocketClientProtocol] = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)
    _recv_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    # Subscriptions
    _price_subs: Set[str] = field(default_factory=set, repr=False)
    _depth_subs: Set[str] = field(default_factory=set, repr=False)
    _user_subs: Set[str] = field(default_factory=set, repr=False)  # position, balance, order, trade

    # Cached data
    _prices: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)
    _orderbooks: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)
    _positions: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)  # symbol -> position
    _balance: Optional[Dict[str, Any]] = field(default=None, repr=False)

    # Events for waiting
    _price_events: Dict[str, asyncio.Event] = field(default_factory=dict, repr=False)
    _depth_events: Dict[str, asyncio.Event] = field(default_factory=dict, repr=False)
    _position_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _balance_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    # Auth state
    _authenticated: bool = field(default=False, repr=False)

    # Reconnect state
    _reconnecting: bool = field(default=False, repr=False)
    _reconnect_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    async def connect(self) -> bool:
        """Connect to WebSocket"""
        async with self._lock:
            if self._ws is not None and self._running:
                return True

            try:
                self._ws = await websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                )
                self._running = True
                self._recv_task = asyncio.create_task(self._recv_loop())
                return True
            except Exception as e:
                print(f"[standx_ws] connect failed: {e}")
                return False

    async def close(self):
        """Close WebSocket connection"""
        self._running = False
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._authenticated = False

    async def _recv_loop(self):
        """Background task to receive messages"""
        while self._running:
            if not self._ws:
                await asyncio.sleep(0.1)
                continue
            try:
                msg = await self._ws.recv()
                data = json.loads(msg)
                await self._handle_message(data)
            except websockets.ConnectionClosed:
                print("[standx_ws] connection closed, reconnecting...")
                await self._reconnect_with_backoff()
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[standx_ws] recv error: {e}")
                await asyncio.sleep(0.1)

    async def _reconnect_with_backoff(self) -> None:
        """Reconnect with exponential backoff"""
        self._reconnecting = True
        self._reconnect_event.clear()
        self._ws = None
        self._authenticated = False
        delay = 1.0
        max_delay = 30.0
        max_attempts = 10

        try:
            for attempt in range(max_attempts):
                if not self._running:
                    return
                print(f"[standx_ws] reconnect attempt {attempt + 1}/{max_attempts} in {delay:.1f}s...")
                await asyncio.sleep(delay)

                try:
                    self._ws = await websockets.connect(
                        self.ws_url,
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=5,
                    )
                    print("[standx_ws] reconnected successfully")
                    await self._resubscribe()
                    return
                except Exception as e:
                    print(f"[standx_ws] reconnect failed: {e}")
                    delay = min(max_delay, delay * 2)

            print(f"[standx_ws] reconnect failed after {max_attempts} attempts")
        finally:
            self._reconnecting = False
            self._reconnect_event.set()

    async def _resubscribe(self) -> None:
        """Resubscribe to all channels after reconnect"""
        # Re-authenticate if we had a token
        if self.jwt_token:
            auth_msg: Dict[str, Any] = {
                "auth": {
                    "token": self.jwt_token,
                    "streams": [
                        {"channel": "position"},
                        {"channel": "balance"},
                    ]
                }
            }
            await self._ws.send(json.dumps(auth_msg))
            # Wait for auth
            for _ in range(50):
                if self._authenticated:
                    break
                await asyncio.sleep(0.1)

        # Resubscribe to price channels
        for symbol in self._price_subs:
            await self._ws.send(json.dumps({"subscribe": {"channel": "price", "symbol": symbol}}))

        # Resubscribe to depth channels
        for symbol in self._depth_subs:
            await self._ws.send(json.dumps({"subscribe": {"channel": "depth_book", "symbol": symbol}}))

        # Resubscribe to user channels
        for channel in self._user_subs:
            await self._ws.send(json.dumps({"subscribe": {"channel": channel}}))

    async def _handle_message(self, data: Dict[str, Any]):
        """Handle incoming WebSocket message"""
        channel = data.get("channel")
        symbol = data.get("symbol")
        payload = data.get("data", {})

        if channel == "auth":
            # Auth response
            #print(payload)
            code = payload.get("code")
            if code == 0: # 확인해보니 0 이 성공 코드임
                self._authenticated = True
            else:
                print(f"[standx_ws] auth failed: {payload}")
            return

        if channel == "price":
            self._prices[symbol] = payload
            if symbol in self._price_events:
                self._price_events[symbol].set()

        elif channel == "depth_book":
            self._orderbooks[symbol] = self._parse_orderbook(payload)
            if symbol in self._depth_events:
                self._depth_events[symbol].set()

        elif channel == "position":
            print("[standx_ws] position update:", payload)
            # Position update
            pos_symbol = payload.get("symbol")
            if pos_symbol:
                self._positions[pos_symbol] = payload
            self._position_event.set()

        elif channel == "balance":
            print("[standx_ws] balance update:", payload)
            self._balance = payload
            self._balance_event.set()

    async def _send(self, msg: Dict[str, Any]):
        """Send message to WebSocket"""
        # Wait for reconnect if in progress
        if self._reconnecting:
            try:
                await asyncio.wait_for(self._reconnect_event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                raise RuntimeError("[standx_ws] reconnect timeout")

        if not self._ws or not self._running:
            await self.connect()
        if self._ws:
            try:
                await self._ws.send(json.dumps(msg))
            except websockets.ConnectionClosed:
                # Connection closed during send, wait for reconnect
                if self._reconnecting:
                    await asyncio.wait_for(self._reconnect_event.wait(), timeout=60.0)
                    if self._ws:
                        await self._ws.send(json.dumps(msg))

    # ----------------------------
    # Authentication
    # ----------------------------
    async def authenticate(self, jwt_token: str, streams: Optional[list] = None):
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

        await self._send(auth_msg)

        # Wait for auth response
        for _ in range(50):  # 5 seconds
            if self._authenticated:
                return True
            await asyncio.sleep(0.1)
        return False

    # ----------------------------
    # Public Subscriptions
    # ----------------------------
    async def subscribe_price(self, symbol: str):
        """Subscribe to price channel for symbol"""
        if symbol in self._price_subs:
            return
        await self._send({"subscribe": {"channel": "price", "symbol": symbol}})
        self._price_subs.add(symbol)
        if symbol not in self._price_events:
            self._price_events[symbol] = asyncio.Event()

    async def unsubscribe_price(self, symbol: str):
        """Unsubscribe from price channel"""
        if symbol not in self._price_subs:
            return
        await self._send({"unsubscribe": {"channel": "price", "symbol": symbol}})
        self._price_subs.discard(symbol)

    async def subscribe_depth(self, symbol: str):
        """Subscribe to depth_book channel for symbol"""
        if symbol in self._depth_subs:
            return
        await self._send({"subscribe": {"channel": "depth_book", "symbol": symbol}})
        self._depth_subs.add(symbol)
        if symbol not in self._depth_events:
            self._depth_events[symbol] = asyncio.Event()

    async def unsubscribe_depth(self, symbol: str):
        """Unsubscribe from depth_book channel"""
        if symbol not in self._depth_subs:
            return
        await self._send({"unsubscribe": {"channel": "depth_book", "symbol": symbol}})
        self._depth_subs.discard(symbol)

    # ----------------------------
    # User Subscriptions (requires auth)
    # ----------------------------
    async def subscribe_position(self):
        """Subscribe to position channel (requires auth)"""
        if "position" in self._user_subs:
            return
        await self._send({"subscribe": {"channel": "position"}})
        self._user_subs.add("position")

    async def subscribe_balance(self):
        """Subscribe to balance channel (requires auth)"""
        if "balance" in self._user_subs:
            return
        await self._send({"subscribe": {"channel": "balance"}})
        self._user_subs.add("balance")

    async def subscribe_user_channels(self):
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

    def get_balance(self) -> Optional[Dict[str, Any]]:
        """Get cached balance"""
        return self._balance

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

    async def wait_depth_ready(self, symbol: str, timeout: float = 5.0) -> bool:
        """Wait until orderbook data is available"""
        if symbol in self._orderbooks:
            return True

        if symbol not in self._depth_events:
            self._depth_events[symbol] = asyncio.Event()

        try:
            await asyncio.wait_for(self._depth_events[symbol].wait(), timeout=timeout)
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

    async def wait_balance_ready(self, timeout: float = 5.0) -> bool:
        """Wait until balance data is available"""
        if self._balance:
            return True
        try:
            await asyncio.wait_for(self._balance_event.wait(), timeout=timeout)
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
            client = StandXWSClient()
            await client.connect()

            # Authenticate if token provided
            if jwt_token:
                auth = await client.authenticate(jwt_token, streams=[
                    #{"channel": "position"}, 일단 미사용
                    {"channel": "balance"},
                ])
                if not auth:
                    print(f"[standx_ws_pool] auth failed for wallet {wallet_address}")

            self._clients[key] = client
            return client

    async def release(self, wallet_address: str):
        """Release a client (does not close, just marks as available)"""
        pass  # Keep connection alive for reuse

    async def close_all(self):
        """Close all connections"""
        async with self._lock:
            for client in self._clients.values():
                await client.close()
            self._clients.clear()


# Global singleton
WS_POOL = StandXWSPool()
