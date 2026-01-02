"""
Lighter WebSocket Client
========================
WS URL: wss://mainnet.zklighter.elliot.ai/stream

주요 채널:
- market_stats/all: 전체 마켓 가격 정보 (mark_price, index_price)
- user_stats/{ACCOUNT_ID}: 계정 담보/잔고 통계
- account_all/{ACCOUNT_ID}: 포지션, 자산, 오더 전체 정보
- account_all_positions/{ACCOUNT_ID}: 포지션만

사용 방법:
    client = LighterWSClient(account_id=123)
    await client.connect()
    await client.subscribe()
    # 이후 get_mark_price(), get_position(), get_collateral() 등 사용
"""
import asyncio
import json
import random
import logging
import time
from typing import Any, Dict, List, Optional
import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK, InvalidStatusCode

logger = logging.getLogger(__name__)

# 상수
WS_URL_MAINNET = "wss://mainnet.zklighter.elliot.ai/stream"
WS_URL_TESTNET = "wss://testnet.zklighter.elliot.ai/stream"
WS_CONNECT_TIMEOUT = 15
WS_READ_TIMEOUT = 60
PING_INTERVAL = 30
RECONNECT_MIN = 1.0
RECONNECT_MAX = 16.0


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


class LighterWSClient:
    """
    Lighter WebSocket 클라이언트.
    - market_stats/all 로 전체 마켓 가격 스트리밍
    - user_stats/{account_id} 로 계정 담보 정보
    - account_all/{account_id} 로 포지션/자산 정보
    """

    def __init__(
        self,
        account_id: int,
        auth_token: Optional[str] = None,
        ws_url: str = WS_URL_MAINNET,
    ):
        self.account_id = account_id
        self.auth_token = auth_token  # 일부 채널에 필요 (account_all_orders 등)
        self.ws_url = ws_url

        self.conn: Optional[websockets.WebSocketClientProtocol] = None
        self._stop = asyncio.Event()
        self._tasks: List[asyncio.Task] = []
        self._active_subs: set[str] = set()
        self._send_lock = asyncio.Lock()

        # ========== 캐시 데이터 ==========
        # 마켓 가격 (market_id -> {mark_price, index_price, last_trade_price, ...})
        self._market_stats: Dict[int, Dict[str, Any]] = {}
        # 스팟 마켓 가격 (market_id -> {mid_price, last_trade_price, ...})
        self._spot_market_stats: Dict[int, Dict[str, Any]] = {}
        # 계정 통계 (collateral, available_balance 등)
        self._user_stats: Dict[str, Any] = {}
        # 계정 포지션 (market_id -> Position dict)
        self._positions: Dict[int, Dict[str, Any]] = {}
        # 계정 자산 (asset_id -> {symbol, balance, locked_balance})
        self._assets: Dict[int, Dict[str, Any]] = {}
        # [ADDED] 오픈 오더 (market_id -> [Order])
        self._orders: Dict[int, List[Dict[str, Any]]] = {}
        # symbol -> market_id 매핑 (외부에서 주입)
        self._symbol_to_market_id: Dict[str, int] = {}
        self._market_id_to_symbol: Dict[int, str] = {}

        # ========== Orderbook (delta-based) ==========
        # market_id -> {"asks": [[px, sz], ...], "bids": [...], "time": ms}
        self._orderbooks: Dict[int, Dict[str, Any]] = {}
        self._orderbook_nonces: Dict[int, int] = {}  # market_id -> last nonce
        self._orderbook_subs: set[int] = set()  # subscribed market_ids
        self._orderbook_events: Dict[int, asyncio.Event] = {}

        # ========== 이벤트 (첫 데이터 수신 대기용) ==========
        self._market_stats_ready = asyncio.Event()
        self._user_stats_ready = asyncio.Event()
        self._account_all_ready = asyncio.Event()
        self._orders_ready = asyncio.Event()  # [ADDED]

    # ==================== 연결 관리 ====================

    @property
    def connected(self) -> bool:
        return self.conn is not None and self.conn.open

    async def connect(self) -> None:
        """WS 연결 (429 대응 백오프 포함)"""
        max_attempts = 6
        base = 0.5
        cap = 30.0

        for attempt in range(1, max_attempts + 1):
            try:
                self.conn = await websockets.connect(
                    self.ws_url,
                    ping_interval=None,  # 수동 ping 사용
                    open_timeout=WS_CONNECT_TIMEOUT,
                )
                # 백그라운드 태스크 시작
                self._tasks.append(asyncio.create_task(self._ping_loop(), name="ping"))
                self._tasks.append(asyncio.create_task(self._listen_loop(), name="listen"))
                logger.info(f"[LighterWS] Connected to {self.ws_url}")
                return
            except InvalidStatusCode as e:
                status = getattr(e, "status_code", None) or getattr(e, "code", None)
                if status != 429:
                    raise
                # 429 → 백오프
                backoff = min(cap, base * (2 ** (attempt - 1)))
                jitter = random.uniform(0, backoff * 0.2)
                await asyncio.sleep(backoff + jitter)
            except Exception:
                raise

        raise RuntimeError("WS connect failed after retries")

    async def close(self) -> None:
        """연결 종료"""
        self._stop.set()
        for t in self._tasks:
            if not t.done():
                t.cancel()
        self._tasks.clear()
        if self.conn:
            try:
                await self.conn.close()
            except Exception:
                pass
        self.conn = None
        logger.info("[LighterWS] Closed")

    # ==================== 구독 ====================

    async def subscribe(self) -> None:
        """기본 구독: market_stats/all, user_stats, account_all, account_all_orders"""
        if not self.conn:
            raise RuntimeError("WebSocket not connected")

        # 1) 마켓 가격 (perp)
        await self._send_subscribe("market_stats/all")
        # 2) 마켓 가격 (spot)
        await self._send_subscribe("spot_market_stats/all")
        # 3) 계정 통계 (담보 등)
        await self._send_subscribe(f"user_stats/{self.account_id}")
        # 4) 계정 전체 (포지션, 자산)
        await self._send_subscribe(f"account_all/{self.account_id}")
        # 5) [ADDED] 오픈 오더 전체 (auth 필요)
        if self.auth_token:
            await self._send_subscribe(f"account_all_orders/{self.account_id}")

    async def _send_subscribe(self, channel: str) -> None:
        """단일 채널 구독 (중복 방지)"""
        if channel in self._active_subs:
            return
        async with self._send_lock:
            if channel in self._active_subs:
                return
            # conn이 None이거나 닫혀있으면 스킵 (재연결 후 _resubscribe에서 재구독됨)
            if not self.conn or not self.conn.open:
                logger.warning(f"[LighterWS] _send_subscribe skipped (conn not ready): {channel}")
                return
            msg = {"type": "subscribe", "channel": channel}
            # auth 필요한 채널이면 추가
            if self.auth_token and ("orders" in channel or "tx" in channel):
                msg["auth"] = self.auth_token
            await self.conn.send(_json_dumps(msg))
            self._active_subs.add(channel)
            logger.debug(f"[LighterWS] Subscribed: {channel}")

    async def _resubscribe(self) -> None:
        """재연결 시 구독 복원"""
        old_subs = list(self._active_subs)
        self._active_subs.clear()
        for ch in old_subs:
            await self._send_subscribe(ch)

    # ==================== Orderbook 구독 ====================

    async def subscribe_orderbook(self, symbol: str) -> bool:
        """
        Orderbook 채널 구독 (delta-based).
        첫 메시지는 스냅샷, 이후는 변경분만 전달됨.
        """
        mid = self._symbol_to_market_id.get(symbol.upper())
        if mid is None:
            logger.warning(f"[LighterWS] Unknown symbol for orderbook: {symbol}")
            return False

        if mid in self._orderbook_subs:
            return True  # 이미 구독 중

        channel = f"order_book/{mid}"
        await self._send_subscribe(channel)
        self._orderbook_subs.add(mid)

        if mid not in self._orderbook_events:
            self._orderbook_events[mid] = asyncio.Event()

        return True

    async def unsubscribe_orderbook(self, symbol: str) -> bool:
        """Orderbook 채널 구독 해제"""
        mid = self._symbol_to_market_id.get(symbol.upper())
        if mid is None:
            return False

        if mid not in self._orderbook_subs:
            return True  # 이미 구독 안함

        channel = f"order_book/{mid}"
        if channel not in self._active_subs:
            self._orderbook_subs.discard(mid)
            return True

        # Unsubscribe 메시지 전송
        async with self._send_lock:
            msg = {"type": "unsubscribe", "channel": channel}
            if self.conn and self.conn.open:
                await self.conn.send(_json_dumps(msg))
            self._active_subs.discard(channel)
            self._orderbook_subs.discard(mid)

        # 캐시 정리
        self._orderbooks.pop(mid, None)
        self._orderbook_nonces.pop(mid, None)
        if mid in self._orderbook_events:
            self._orderbook_events[mid].clear()

        logger.debug(f"[LighterWS] Unsubscribed orderbook: {symbol} (market_id={mid})")
        return True

    # ==================== 내부 루프 ====================

    async def _ping_loop(self) -> None:
        """주기적 ping (Lighter는 JSON ping 지원)"""
        try:
            while not self._stop.is_set():
                await asyncio.sleep(PING_INTERVAL)
                if self.conn and self.conn.open:
                    try:
                        await self.conn.send(_json_dumps({"type": "ping"}))
                    except Exception as e:
                        logger.warning(f"[LighterWS] Ping error: {e}")
        except asyncio.CancelledError:
            pass

    async def _listen_loop(self) -> None:
        """메시지 수신 루프"""
        assert self.conn is not None
        while not self._stop.is_set():
            try:
                raw = await asyncio.wait_for(self.conn.recv(), timeout=WS_READ_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("[LighterWS] Recv timeout, reconnecting...")
                await self._handle_disconnect()
                break
            except (ConnectionClosed, ConnectionClosedOK):
                logger.warning("[LighterWS] Connection closed, reconnecting...")
                await self._handle_disconnect()
                break
            except Exception as e:
                logger.error(f"[LighterWS] Recv error: {e}")
                await self._handle_disconnect()
                break

            # 초기 핸드셰이크 문자열 무시
            if isinstance(raw, str) and "established" in raw.lower():
                continue

            try:
                msg = json.loads(raw)
            except Exception:
                continue

            try:
                self._dispatch(msg)
            except Exception as e:
                logger.exception(f"[LighterWS] Dispatch error: {e}")

    def _dispatch(self, msg: Dict[str, Any]) -> None:
        """메시지 타입별 처리"""
        ch = str(msg.get("channel") or "")
        msg_type = str(msg.get("type") or "")

        # pong
        if msg_type == "pong" or ch == "pong":
            return

        # error
        if msg_type == "error":
            logger.error(f"[LighterWS] Error: {msg}")
            return

        # market_stats (perp)
        if ch.startswith("market_stats:"):
            self._handle_market_stats(msg)
            return

        # spot_market_stats
        if ch.startswith("spot_market_stats:"):
            self._handle_spot_market_stats(msg)
            return

        # user_stats
        if ch.startswith("user_stats:"):
            self._handle_user_stats(msg)
            return

        # account_all (포지션, 자산)
        if ch.startswith("account_all:"):
            self._handle_account_all(msg)
            return

        # account_all_positions
        if ch.startswith("account_all_positions:"):
            self._handle_positions(msg)
            return

        # [ADDED] account_all_orders (오픈 오더)
        if ch.startswith("account_all_orders:"):
            self._handle_orders(msg)
            return

        # orderbook (delta-based)
        if ch.startswith("order_book:"):
            self._handle_orderbook(msg)
            return

    def _handle_market_stats(self, msg: Dict[str, Any]) -> None:
        """
        market_stats/all 또는 market_stats/{market_id} 처리
        - channel: "market_stats:all" 또는 "market_stats:{id}"
        """
        ch = msg.get("channel", "")
        data = msg.get("market_stats")
        if not data:
            return

        # "market_stats:all" → data가 dict {market_id: stats} 형태일 수 있음
        # "market_stats:{id}" → data가 단일 stats
        if ch == "market_stats:all":
            # 문서상 all은 개별 stats 형태로 오는 듯, 실제 테스트 필요
            # 단일 객체로 올 경우
            if isinstance(data, dict) and "market_id" in data:
                mid = int(data["market_id"])
                self._market_stats[mid] = data
            elif isinstance(data, dict):
                # {market_id: stats, ...} 형태
                for k, v in data.items():
                    try:
                        mid = int(k)
                        self._market_stats[mid] = v
                    except Exception:
                        pass
        else:
            # 단일 마켓
            if isinstance(data, dict) and "market_id" in data:
                mid = int(data["market_id"])
                self._market_stats[mid] = data

        if not self._market_stats_ready.is_set():
            self._market_stats_ready.set()

    def _handle_spot_market_stats(self, msg: Dict[str, Any]) -> None:
        """spot_market_stats 처리"""
        ch = msg.get("channel", "")
        data = msg.get("spot_market_stats")
        if not data:
            return

        if ch == "spot_market_stats:all":
            if isinstance(data, dict):
                for k, v in data.items():
                    try:
                        mid = int(k)
                        self._spot_market_stats[mid] = v
                    except Exception:
                        pass
        else:
            if isinstance(data, dict) and "market_id" in data:
                mid = int(data["market_id"])
                self._spot_market_stats[mid] = data

    def _handle_user_stats(self, msg: Dict[str, Any]) -> None:
        """user_stats/{account_id} 처리"""
        stats = msg.get("stats")
        if stats:
            self._user_stats = stats
            if not self._user_stats_ready.is_set():
                self._user_stats_ready.set()

    def _handle_account_all(self, msg: Dict[str, Any]) -> None:
        """account_all/{account_id} 처리 (포지션, 자산)"""
        # positions: {market_id: Position}
        positions = msg.get("positions")
        if positions and isinstance(positions, dict):
            for k, v in positions.items():
                try:
                    mid = int(k)
                    self._positions[mid] = v
                except Exception:
                    pass

        # assets: {asset_id: Asset} 또는 list
        assets = msg.get("assets")
        if assets:
            if isinstance(assets, dict):
                for k, v in assets.items():
                    try:
                        aid = int(k)
                        self._assets[aid] = v
                    except Exception:
                        pass
            elif isinstance(assets, list):
                for a in assets:
                    if isinstance(a, dict) and "asset_id" in a:
                        self._assets[int(a["asset_id"])] = a

        if not self._account_all_ready.is_set():
            self._account_all_ready.set()

    def _handle_positions(self, msg: Dict[str, Any]) -> None:
        """account_all_positions 처리"""
        positions = msg.get("positions")
        if positions and isinstance(positions, dict):
            for k, v in positions.items():
                try:
                    mid = int(k)
                    self._positions[mid] = v
                except Exception:
                    pass

    def _handle_orders(self, msg: Dict[str, Any]) -> None:
        """
        [ADDED] account_all_orders/{account_id} 처리
        응답 형태: { "orders": { "{MARKET_INDEX}": [Order, ...] }, ... }
        """
        orders = msg.get("orders")
        if orders and isinstance(orders, dict):
            for k, v in orders.items():
                try:
                    mid = int(k)
                    # v는 Order 리스트
                    if isinstance(v, list):
                        self._orders[mid] = v
                    else:
                        self._orders[mid] = [v] if v else []
                except Exception:
                    pass
        
        if not self._orders_ready.is_set():
            self._orders_ready.set()

    def _handle_orderbook(self, msg: Dict[str, Any]) -> None:
        """
        order_book/{market_id} 처리 (delta-based).

        첫 메시지: 스냅샷 (전체 orderbook)
        이후 메시지: 변경분만 (size가 0이면 해당 가격 레벨 삭제)

        nonce 연속성:
        - 현재 메시지의 begin_nonce == 이전 메시지의 nonce 여야 함
        - 불연속 시 로그 경고 (스냅샷 재요청 고려 가능)
        """
        ch = msg.get("channel", "")
        # channel: "order_book:{market_id}"
        try:
            mid = int(ch.split(":")[1])
        except (IndexError, ValueError):
            return

        ob_data = msg.get("order_book")
        if not ob_data:
            return

        new_nonce = ob_data.get("nonce")
        begin_nonce = ob_data.get("begin_nonce")
        asks_update = ob_data.get("asks", [])
        bids_update = ob_data.get("bids", [])

        # 첫 스냅샷 여부 확인
        is_first = mid not in self._orderbooks

        if is_first:
            # 스냅샷: 전체 교체
            asks = []
            bids = []
            for item in asks_update:
                try:
                    px = float(item.get("price", 0))
                    sz = float(item.get("size", 0))
                    if sz > 0:
                        asks.append([px, sz])
                except (ValueError, TypeError):
                    continue
            for item in bids_update:
                try:
                    px = float(item.get("price", 0))
                    sz = float(item.get("size", 0))
                    if sz > 0:
                        bids.append([px, sz])
                except (ValueError, TypeError):
                    continue

            # 정렬: asks 오름차순, bids 내림차순
            asks.sort(key=lambda x: x[0])
            bids.sort(key=lambda x: x[0], reverse=True)

            self._orderbooks[mid] = {
                "asks": asks,
                "bids": bids,
                "time": int(time.time() * 1000),
            }
        else:
            # Delta 업데이트
            # nonce 연속성 체크
            last_nonce = self._orderbook_nonces.get(mid)
            if last_nonce is not None and begin_nonce is not None:
                if begin_nonce != last_nonce:
                    logger.warning(
                        f"[LighterWS] Orderbook nonce discontinuity for market {mid}: "
                        f"expected begin_nonce={last_nonce}, got {begin_nonce}"
                    )

            # 현재 orderbook 가져오기
            current = self._orderbooks[mid]
            asks_dict = {lvl[0]: lvl[1] for lvl in current["asks"]}
            bids_dict = {lvl[0]: lvl[1] for lvl in current["bids"]}

            # asks 업데이트 적용
            for item in asks_update:
                try:
                    px = float(item.get("price", 0))
                    sz = float(item.get("size", 0))
                    if sz <= 0:
                        asks_dict.pop(px, None)  # 삭제
                    else:
                        asks_dict[px] = sz  # 추가/업데이트
                except (ValueError, TypeError):
                    continue

            # bids 업데이트 적용
            for item in bids_update:
                try:
                    px = float(item.get("price", 0))
                    sz = float(item.get("size", 0))
                    if sz <= 0:
                        bids_dict.pop(px, None)  # 삭제
                    else:
                        bids_dict[px] = sz  # 추가/업데이트
                except (ValueError, TypeError):
                    continue

            # dict -> list로 변환 후 정렬, 50개만 유지
            asks = [[px, sz] for px, sz in asks_dict.items()]
            bids = [[px, sz] for px, sz in bids_dict.items()]
            asks.sort(key=lambda x: x[0])
            bids.sort(key=lambda x: x[0], reverse=True)

            self._orderbooks[mid] = {
                "asks": asks,
                "bids": bids,
                "time": int(time.time() * 1000),
            }

        # nonce 저장
        if new_nonce is not None:
            self._orderbook_nonces[mid] = new_nonce

        # 이벤트 시그널
        if mid in self._orderbook_events:
            self._orderbook_events[mid].set()

    async def _handle_disconnect(self) -> None:
        """연결 끊김 처리 → 재연결"""
        if self.conn:
            try:
                await self.conn.close()
            except Exception:
                pass
        self.conn = None
        await self._reconnect_with_backoff()

    async def _reconnect_with_backoff(self) -> None:
        """지수 백오프로 재연결"""
        delay = RECONNECT_MIN
        while not self._stop.is_set():
            try:
                await asyncio.sleep(delay)
                # 기존 태스크 정리
                for t in self._tasks:
                    if not t.done():
                        t.cancel()
                self._tasks.clear()

                await self.connect()
                await self._resubscribe()
                logger.info("[LighterWS] Reconnected")
                return
            except Exception as e:
                logger.warning(f"[LighterWS] Reconnect failed: {e}")
                delay = min(RECONNECT_MAX, delay * 2.0) + random.uniform(0, 0.5)

    # ==================== 외부 인터페이스 ====================

    def set_market_mapping(self, symbol_to_market_id: Dict[str, int]) -> None:
        """symbol -> market_id 매핑 설정 (LighterExchange.init()에서 호출)"""
        self._symbol_to_market_id = {k.upper(): v for k, v in symbol_to_market_id.items()}
        self._market_id_to_symbol = {v: k for k, v in self._symbol_to_market_id.items()}

    async def wait_ready(self, timeout: float = 5.0) -> bool:
        """첫 데이터 수신 대기"""
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    self._market_stats_ready.wait(),
                    self._user_stats_ready.wait(),
                    self._account_all_ready.wait(),
                ),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            return False

    def get_mark_price(self, symbol: str) -> Optional[float]:
        """마크 가격 조회 (캐시)"""
        mid = self._symbol_to_market_id.get(symbol.upper())
        if mid is None:
            return None
        stats = self._market_stats.get(mid)
        if stats:
            # mark_price > last_trade_price 순으로 시도
            for key in ("mark_price", "last_trade_price", "index_price"):
                val = stats.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except Exception:
                        pass
        return None

    def get_spot_price(self, symbol: str) -> Optional[float]:
        """스팟 마켓 가격 조회"""
        mid = self._symbol_to_market_id.get(symbol.upper())
        if mid is None:
            return None
        stats = self._spot_market_stats.get(mid)
        if stats:
            for key in ("mid_price", "last_trade_price"):
                val = stats.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except Exception:
                        pass
        return None

    def get_all_prices(self) -> Dict[str, float]:
        """모든 마켓 가격 반환 {symbol: mark_price}"""
        result = {}
        for mid, stats in self._market_stats.items():
            symbol = self._market_id_to_symbol.get(mid)
            if symbol:
                for key in ("mark_price", "last_trade_price"):
                    val = stats.get(key)
                    if val is not None:
                        try:
                            result[symbol] = float(val)
                            break
                        except Exception:
                            pass
        return result

    # ==================== Orderbook 조회 ====================

    def get_orderbook(self, symbol: str, depth: int = 50) -> Optional[Dict[str, Any]]:
        """
        Orderbook 조회 (캐시).

        Args:
            symbol: 심볼
            depth: 반환할 레벨 수 (기본 50)

        반환: {
            "asks": [[price, size], ...],  # 오름차순, 상위 depth개
            "bids": [[price, size], ...],  # 내림차순, 상위 depth개
            "time": int (ms timestamp),
        }
        """
        mid = self._symbol_to_market_id.get(symbol.upper())
        if mid is None:
            return None
        ob = self._orderbooks.get(mid)
        if ob is None:
            return None
        # depth개만 반환
        return {
            "asks": ob["asks"][:depth],
            "bids": ob["bids"][:depth],
            "time": ob["time"],
        }

    async def wait_orderbook_ready(self, symbol: str, timeout: float = 5.0) -> bool:
        """Orderbook 데이터 수신 대기"""
        mid = self._symbol_to_market_id.get(symbol.upper())
        if mid is None:
            return False

        if mid in self._orderbooks:
            return True

        if mid not in self._orderbook_events:
            self._orderbook_events[mid] = asyncio.Event()

        try:
            await asyncio.wait_for(self._orderbook_events[mid].wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def get_collateral(self) -> Dict[str, Any]:
        """
        담보 정보 조회 (캐시).
        반환: {
            'total_collateral': float,
            'available_collateral': float,
            'portfolio_value': float,
            'leverage': float,
            'margin_usage': float,
        }
        """
        stats = self._user_stats
        if not stats:
            return {}

        def _f(key: str, default=0.0) -> float:
            try:
                return float(stats.get(key, default))
            except Exception:
                return default

        return {
            "total_collateral": _f("collateral"),
            "available_collateral": _f("available_balance"),
            "portfolio_value": _f("portfolio_value"),
            "leverage": _f("leverage"),
            "margin_usage": _f("margin_usage"),
            "buying_power": _f("buying_power"),
        }

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        특정 심볼 포지션 조회 (캐시).
        반환: {
            'size': float,
            'side': 'long' | 'short',
            'entry_price': float,
            'unrealized_pnl': float,
            'liquidation_price': float,
            ...
        }
        """
        mid = self._symbol_to_market_id.get(symbol.upper())
        if mid is None:
            return None

        pos = self._positions.get(mid)
        if not pos:
            return None

        return self._normalize_position(pos)

    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """모든 포지션 반환 {symbol: normalized_position}"""
        result = {}
        for mid, pos in self._positions.items():
            symbol = self._market_id_to_symbol.get(mid)
            if symbol:
                norm = self._normalize_position(pos)
                if norm and norm.get("size", 0) != 0:
                    result[symbol] = norm
        return result

    def _normalize_position(self, pos: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """WS 포지션 데이터 정규화"""
        if not pos:
            return None

        def _f(key: str, default=None):
            val = pos.get(key)
            if val is None:
                return default
            try:
                return float(val)
            except Exception:
                return default

        size_val = _f("position", 0)
        sign = pos.get("sign", 1)
        # sign: 1 = long, -1 = short
        if sign == -1:
            side = "short"
        else:
            side = "long"

        if size_val == 0:
            return None

        return {
            "symbol": pos.get("symbol", ""),
            "size": abs(size_val),
            "side": side,
            "entry_price": _f("avg_entry_price"),
            "position_value": _f("position_value"),
            "unrealized_pnl": _f("unrealized_pnl"),
            "realized_pnl": _f("realized_pnl"),
            "liquidation_price": _f("liquidation_price"),
            "margin_mode": pos.get("margin_mode"),
            "allocated_margin": _f("allocated_margin"),
            "initial_margin_fraction": _f("initial_margin_fraction"),
        }

    def get_assets(self) -> Dict[str, Dict[str, float]]:
        """
        자산(스팟 잔고) 조회.
        반환: { 'USDC': {'total': x, 'available': y, 'locked': z}, ... }
        """
        result = {}
        for aid, asset in self._assets.items():
            if not isinstance(asset, dict):
                continue
            symbol = asset.get("symbol", f"ASSET_{aid}")
            try:
                total = float(asset.get("balance", 0))
                locked = float(asset.get("locked_balance", 0))
                available = total - locked
                result[symbol] = {
                    "total": total,
                    "available": available,
                    "locked": locked,
                }
            except Exception:
                pass
        return result

    # ==================== [ADDED] Open Orders ====================

    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """
        특정 심볼의 오픈 오더 조회 (캐시).
        반환: [
            {
                'id': int,
                'client_order_id': int,
                'symbol': str,
                'quantity': str,
                'price': str,
                'side': 'buy' | 'sell',
                'order_type': str,
                'status': str,
                'reduce_only': bool,
                'time_in_force': str,
            },
            ...
        ]
        """
        mid = self._symbol_to_market_id.get(symbol.upper())
        if mid is None:
            return []

        orders = self._orders.get(mid, [])
        return [self._normalize_order(o, symbol) for o in orders if o]

    def get_all_open_orders(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        모든 심볼의 오픈 오더 반환.
        반환: { 'ETH-USD': [...], 'BTC-USD': [...], ... }
        """
        result = {}
        for mid, orders in self._orders.items():
            symbol = self._market_id_to_symbol.get(mid)
            if symbol and orders:
                normalized = [self._normalize_order(o, symbol) for o in orders if o]
                if normalized:
                    result[symbol] = normalized
        return result

    def _normalize_order(self, order: Dict[str, Any], symbol: str = "") -> Dict[str, Any]:
        """WS 오더 데이터 정규화 (lighter.py의 parse_open_orders와 호환)"""
        if not order:
            return {}

        # side: is_ask=True → sell, False → buy
        is_ask = order.get("is_ask", False)
        side = "sell" if is_ask else "buy"

        return {
            "id": order.get("order_index"),
            "client_order_id": order.get("client_order_index"),
            "symbol": symbol or self._market_id_to_symbol.get(order.get("market_index", 0), ""),
            "size": str(order.get("initial_base_amount", "")),
            "remaining_size": str(order.get("remaining_base_amount", "")),
            "filled_size": str(order.get("filled_base_amount", "")),
            "price": str(order.get("price", "")),
            "side": side,
            "order_type": order.get("type", ""),
            "status": order.get("status", ""),
            "reduce_only": order.get("reduce_only", False),
            "time_in_force": order.get("time_in_force", ""),
            "created_at": order.get("created_at"),
            "updated_at": order.get("updated_at"),
        }


# ==================== 공유 풀 (싱글턴) ====================

class LighterWSPool:
    """
    계정별 WS 클라이언트 풀.
    동일 account_id는 같은 클라이언트 공유.
    """

    def __init__(self):
        self._clients: Dict[int, LighterWSClient] = {}
        self._refcnt: Dict[int, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        account_id: int,
        auth_token: Optional[str] = None,
        ws_url: str = WS_URL_MAINNET,
        symbol_to_market_id: Optional[Dict[str, int]] = None,
    ) -> LighterWSClient:
        """클라이언트 획득 (없으면 생성)"""
        async with self._lock:
            if account_id in self._clients:
                self._refcnt[account_id] = self._refcnt.get(account_id, 0) + 1
                client = self._clients[account_id]
                # 매핑 업데이트
                if symbol_to_market_id:
                    client.set_market_mapping(symbol_to_market_id)
                return client

            # 새 클라이언트 생성
            client = LighterWSClient(
                account_id=account_id,
                auth_token=auth_token,
                ws_url=ws_url,
            )
            if symbol_to_market_id:
                client.set_market_mapping(symbol_to_market_id)

            await client.connect()
            await client.subscribe()

            self._clients[account_id] = client
            self._refcnt[account_id] = 1
            return client

    async def release(self, account_id: int) -> None:
        """클라이언트 해제 (참조 카운트 0이면 종료)"""
        async with self._lock:
            if account_id not in self._clients:
                return

            self._refcnt[account_id] = max(0, self._refcnt.get(account_id, 1) - 1)
            if self._refcnt[account_id] == 0:
                client = self._clients.pop(account_id, None)
                self._refcnt.pop(account_id, None)
                if client:
                    await client.close()


# 글로벌 풀 인스턴스
LIGHTER_WS_POOL = LighterWSPool()
