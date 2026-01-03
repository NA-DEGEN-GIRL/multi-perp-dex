"""
Backpack WebSocket Client

Provides real-time data:
- depth (orderbook) via incremental updates
- markPrice (mark price, index price, funding rate)
"""
import asyncio
import logging
import time
from typing import Optional, Dict, Any, Set

import aiohttp

from wrappers.base_ws_client import BaseWSClient, _json_dumps

logger = logging.getLogger(__name__)


BACKPACK_WS_URL = "wss://ws.backpack.exchange"
BACKPACK_REST_URL = "https://api.backpack.exchange/api/v1"
ORDERBOOK_MAX_LEVELS = 50  # Limit orderbook depth (Backpack sends ~5000 levels)


class BackpackWSClient(BaseWSClient):
    """
    Backpack WebSocket 클라이언트.
    BaseWSClient를 상속하여 연결/재연결 로직 공유.
    """

    WS_URL = BACKPACK_WS_URL
    PING_INTERVAL = None  # Server sends Ping every 60s, client must respond with Pong (handled by websockets lib)
    RECV_TIMEOUT = 90.0  # 90초간 메시지 없으면 재연결 (server ping 60s + margin)
    RECONNECT_MIN = 0.5
    RECONNECT_MAX = 30.0

    def __init__(self):
        super().__init__()

        # Subscriptions
        self._orderbook_subs: Set[str] = set()
        self._price_subs: Set[str] = set()

        # Cached data
        self._orderbooks: Dict[str, Dict[str, Any]] = {}
        self._prices: Dict[str, Dict[str, Any]] = {}

        # Track update IDs for delta validation
        self._orderbook_last_u: Dict[str, int] = {}

        # Events for waiting
        self._orderbook_events: Dict[str, asyncio.Event] = {}
        self._price_events: Dict[str, asyncio.Event] = {}

        # Reconnect event (for _send to wait)
        self._reconnect_event: asyncio.Event = asyncio.Event()
        self._reconnect_event.set()

        # HTTP session for REST calls
        self._http_session: Optional[aiohttp.ClientSession] = None

    # ==================== Abstract Method Implementations ====================

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket message"""
        stream = data.get("stream", "")
        payload = data.get("data", {})

        # depth.{symbol} stream
        if stream.startswith("depth."):
            symbol = payload.get("s")
            if symbol:
                await self._handle_depth_update(symbol, payload)

        # markPrice.{symbol} stream
        elif stream.startswith("markPrice."):
            symbol = payload.get("s")
            if symbol:
                self._handle_mark_price_update(symbol, payload)

    async def _handle_depth_update(self, symbol: str, data: Dict[str, Any]) -> None:
        """
        Handle depth update.
        Backpack sends incremental updates.
        Format: {"e": "depth", "s": "SOL_USDC", "a": [...], "b": [...], "U": firstId, "u": lastId}
        """
        first_update_id = data.get("U", 0)
        last_update_id = data.get("u", 0)

        if symbol not in self._orderbooks:
            # First update - need to fetch snapshot
            await self._fetch_orderbook_snapshot(symbol)
            if symbol not in self._orderbooks:
                return

        # Check if update is sequential
        last_u = self._orderbook_last_u.get(symbol, 0)
        if last_u > 0 and first_update_id != last_u + 1:
            # Gap detected - refetch snapshot
            logger.warning(f"[BackpackWS] orderbook gap detected for {symbol}: expected {last_u + 1}, got {first_update_id}")
            await self._fetch_orderbook_snapshot(symbol)
            if symbol not in self._orderbooks:
                return

        # Apply delta updates
        self._apply_depth_delta(symbol, data)
        self._orderbook_last_u[symbol] = last_update_id

        # Signal data ready
        if symbol in self._orderbook_events:
            self._orderbook_events[symbol].set()

    def _handle_mark_price_update(self, symbol: str, data: Dict[str, Any]) -> None:
        """
        Handle mark price update.
        Format: {"e": "markPrice", "s": "SOL_USDC", "p": "18.70", "f": "1.70", "i": "19.70", "n": 1694687965941, "T": ...}
        """
        self._prices[symbol] = {
            "mark_price": data.get("p"),
            "index_price": data.get("i"),
            "funding_rate": data.get("f"),
            "next_funding_time": data.get("n"),
            "time": int(time.time() * 1000),
        }

        # Signal data ready
        if symbol in self._price_events:
            self._price_events[symbol].set()

    def _apply_depth_delta(self, symbol: str, data: Dict[str, Any]) -> None:
        """Apply incremental depth update to orderbook"""
        if symbol not in self._orderbooks:
            return

        orderbook = self._orderbooks[symbol]

        # Process asks
        for item in data.get("a", []):
            try:
                price = float(item[0])
                size = float(item[1])
                if size == 0:
                    # Remove level
                    orderbook["asks"] = [lvl for lvl in orderbook["asks"] if lvl[0] != price]
                else:
                    # Update or insert
                    updated = False
                    for i, lvl in enumerate(orderbook["asks"]):
                        if lvl[0] == price:
                            orderbook["asks"][i] = [price, size]
                            updated = True
                            break
                    if not updated:
                        orderbook["asks"].append([price, size])
            except (IndexError, ValueError, TypeError):
                continue

        # Process bids
        for item in data.get("b", []):
            try:
                price = float(item[0])
                size = float(item[1])
                if size == 0:
                    # Remove level
                    orderbook["bids"] = [lvl for lvl in orderbook["bids"] if lvl[0] != price]
                else:
                    # Update or insert
                    updated = False
                    for i, lvl in enumerate(orderbook["bids"]):
                        if lvl[0] == price:
                            orderbook["bids"][i] = [price, size]
                            updated = True
                            break
                    if not updated:
                        orderbook["bids"].append([price, size])
            except (IndexError, ValueError, TypeError):
                continue

        # Re-sort: asks ascending, bids descending
        orderbook["asks"].sort(key=lambda x: x[0])
        orderbook["bids"].sort(key=lambda x: x[0], reverse=True)

        # Limit to max levels
        orderbook["asks"] = orderbook["asks"][:ORDERBOOK_MAX_LEVELS]
        orderbook["bids"] = orderbook["bids"][:ORDERBOOK_MAX_LEVELS]
        orderbook["time"] = int(time.time() * 1000)

    async def _fetch_orderbook_snapshot(self, symbol: str) -> None:
        """Fetch orderbook snapshot from REST API"""
        try:
            if not self._http_session or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()

            url = f"{BACKPACK_REST_URL}/depth"
            params = {"symbol": symbol}

            async with self._http_session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[BackpackWS] failed to fetch orderbook snapshot: {resp.status}")
                    return

                data = await resp.json()

            # Parse snapshot
            # Format: {"lastUpdateId": "...", "asks": [["price", "size"], ...], "bids": [...]}
            asks = []
            for item in data.get("asks", []):
                try:
                    asks.append([float(item[0]), float(item[1])])
                except (IndexError, ValueError, TypeError):
                    continue

            bids = []
            for item in data.get("bids", []):
                try:
                    bids.append([float(item[0]), float(item[1])])
                except (IndexError, ValueError, TypeError):
                    continue

            # Sort: asks ascending, bids descending
            asks.sort(key=lambda x: x[0])
            bids.sort(key=lambda x: x[0], reverse=True)

            # Limit to max levels
            asks = asks[:ORDERBOOK_MAX_LEVELS]
            bids = bids[:ORDERBOOK_MAX_LEVELS]

            self._orderbooks[symbol] = {
                "asks": asks,
                "bids": bids,
                "time": int(time.time() * 1000),
            }

            # Update last update ID
            last_update_id = data.get("lastUpdateId")
            if last_update_id:
                try:
                    self._orderbook_last_u[symbol] = int(last_update_id)
                except (ValueError, TypeError):
                    self._orderbook_last_u[symbol] = 0

        except Exception as e:
            logger.error(f"[BackpackWS] failed to fetch orderbook snapshot: {e}")

    async def _resubscribe(self) -> None:
        """Resubscribe to all channels after reconnect"""
        # Clear cached data (stale data 방지)
        self._orderbooks.clear()
        self._orderbook_last_u.clear()
        self._prices.clear()

        # Clear events
        for ev in self._orderbook_events.values():
            ev.clear()
        for ev in self._price_events.values():
            ev.clear()

        # Resubscribe to orderbook channels
        for symbol in self._orderbook_subs:
            stream = f"depth.{symbol}"
            await self._ws.send(_json_dumps({"method": "SUBSCRIBE", "params": [stream]}))
            # Fetch snapshot after resubscribe
            await self._fetch_orderbook_snapshot(symbol)

        # Resubscribe to mark price channels
        for symbol in self._price_subs:
            stream = f"markPrice.{symbol}"
            await self._ws.send(_json_dumps({"method": "SUBSCRIBE", "params": [stream]}))

    def _build_ping_message(self) -> Optional[str]:
        """Backpack server sends ping, client responds with pong (handled by websockets lib)"""
        return None

    # ==================== Connection Management ====================

    async def connect(self) -> bool:
        """WS 연결 (base class 사용)"""
        return await super().connect()

    async def close(self) -> None:
        """연결 종료 및 상태 초기화"""
        await super().close()
        self._orderbook_subs.clear()
        self._price_subs.clear()

        # Close HTTP session
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    async def _handle_disconnect(self) -> None:
        """연결 끊김 처리 - reconnect event 관리 추가"""
        self._reconnect_event.clear()
        await super()._handle_disconnect()
        self._reconnect_event.set()

    # ==================== Subscription Methods ====================

    async def _send_msg(self, msg: Dict[str, Any]) -> None:
        """Send message to WebSocket (with reconnect wait)"""
        if self._reconnecting:
            try:
                await asyncio.wait_for(self._reconnect_event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                raise RuntimeError("[backpack_ws] reconnect timeout")

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

    async def subscribe_orderbook(self, symbol: str) -> None:
        """Subscribe to orderbook (depth) channel for symbol"""
        if symbol in self._orderbook_subs:
            return

        stream = f"depth.{symbol}"
        await self._send_msg({"method": "SUBSCRIBE", "params": [stream]})
        self._orderbook_subs.add(symbol)

        if symbol not in self._orderbook_events:
            self._orderbook_events[symbol] = asyncio.Event()

        # Fetch initial snapshot
        await self._fetch_orderbook_snapshot(symbol)

    async def unsubscribe_orderbook(self, symbol: str) -> None:
        """Unsubscribe from orderbook (depth) channel"""
        if symbol not in self._orderbook_subs:
            return

        stream = f"depth.{symbol}"
        await self._send_msg({"method": "UNSUBSCRIBE", "params": [stream]})
        self._orderbook_subs.discard(symbol)

        # Clean up cached data
        self._orderbooks.pop(symbol, None)
        self._orderbook_last_u.pop(symbol, None)

    async def subscribe_mark_price(self, symbol: str) -> None:
        """Subscribe to mark price channel for symbol"""
        if symbol in self._price_subs:
            return

        stream = f"markPrice.{symbol}"
        await self._send_msg({"method": "SUBSCRIBE", "params": [stream]})
        self._price_subs.add(symbol)

        if symbol not in self._price_events:
            self._price_events[symbol] = asyncio.Event()

    async def unsubscribe_mark_price(self, symbol: str) -> None:
        """Unsubscribe from mark price channel"""
        if symbol not in self._price_subs:
            return

        stream = f"markPrice.{symbol}"
        await self._send_msg({"method": "UNSUBSCRIBE", "params": [stream]})
        self._price_subs.discard(symbol)

        # Clean up cached data
        self._prices.pop(symbol, None)

    # ==================== Data Getters ====================

    def get_orderbook(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached orderbook for symbol"""
        return self._orderbooks.get(symbol)

    def get_mark_price(self, symbol: str) -> Optional[str]:
        """Get cached mark price for symbol"""
        price_data = self._prices.get(symbol)
        if price_data:
            return price_data.get("mark_price")
        return None

    def get_price_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get full cached price data for symbol (mark_price, index_price, funding_rate, etc)"""
        return self._prices.get(symbol)

    # ==================== Wait for data ====================

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

    async def wait_price_ready(self, symbol: str, timeout: float = 5.0) -> bool:
        """Wait until mark price data is available"""
        if symbol in self._prices:
            return True

        if symbol not in self._price_events:
            self._price_events[symbol] = asyncio.Event()

        try:
            await asyncio.wait_for(self._price_events[symbol].wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# ----------------------------
# WebSocket Pool (Singleton)
# ----------------------------
class BackpackWSPool:
    """
    Singleton pool for Backpack WebSocket connections.
    Shares connections across multiple exchange instances.
    """

    def __init__(self):
        self._client: Optional[BackpackWSClient] = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> BackpackWSClient:
        """
        Get or create a WebSocket client.
        Backpack WS doesn't require auth for public streams,
        so we can share a single connection.
        """
        async with self._lock:
            if self._client is not None:
                # Reconnect if needed
                if not self._client._running:
                    await self._client.connect()
                return self._client

            # Create new client
            self._client = BackpackWSClient()
            await self._client.connect()
            return self._client

    async def release(self) -> None:
        """Release client (does not close, just marks as available)"""
        pass  # Keep connection alive for reuse

    async def close_all(self) -> None:
        """Close all connections"""
        async with self._lock:
            if self._client:
                await self._client.close()
                self._client = None


# Global singleton
WS_POOL = BackpackWSPool()
