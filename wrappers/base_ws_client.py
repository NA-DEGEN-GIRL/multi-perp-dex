"""
Base WebSocket Client
=====================
공통 연결/재연결/ping 로직을 제공하는 추상 베이스 클래스.

사용법:
    class MyWSClient(BaseWSClient):
        WS_URL = "wss://example.com/ws"
        PING_INTERVAL = 30.0

        async def _handle_message(self, data: Dict) -> None:
            ...

        async def _resubscribe(self) -> None:
            ...

        def _build_ping_message(self) -> Optional[str]:
            return json.dumps({"type": "ping"})
"""
import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed, InvalidStatusCode

logger = logging.getLogger(__name__)


def _json_dumps(obj: Any) -> str:
    """Compact JSON serialization (no spaces after separators)"""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


class BaseWSClient(ABC):
    """
    WebSocket 클라이언트 공통 베이스.

    서브클래스에서 구현해야 하는 메서드:
    - _handle_message(data): 메시지 처리
    - _resubscribe(): 재연결 후 구독 복구
    - _build_ping_message(): ping 메시지 생성 (None이면 ping 안 함)
    """

    # 서브클래스에서 override
    WS_URL: str = ""
    WS_CONNECT_TIMEOUT: float = 10.0
    PING_INTERVAL: Optional[float] = None  # None이면 ping 안 함
    PING_FAIL_THRESHOLD: int = 2  # ping 연속 실패 시 재연결
    RECV_TIMEOUT: Optional[float] = None  # 수신 타임아웃 (ping 없는 경우 사용)
    RECONNECT_MIN: float = 1.0
    RECONNECT_MAX: float = 8.0
    CLOSE_TIMEOUT: float = 2.0
    CONNECT_MAX_ATTEMPTS: int = 6  # 429 대응 최대 재시도

    def __init__(self):
        self._ws: Optional[WebSocketClientProtocol] = None
        self._running: bool = False
        self._recv_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._reconnecting: bool = False
        self._ping_fail_count: int = 0
        self._last_recv_time: float = 0.0

    @property
    def connected(self) -> bool:
        """연결 상태 확인"""
        return self._ws is not None and self._running

    async def connect(self) -> bool:
        """
        WebSocket 연결 (429 rate limit 대응 포함).
        서브클래스에서 추가 로직이 필요하면 super().connect() 호출 후 처리.
        """
        async with self._lock:
            if self._ws is not None and self._running:
                return True

        # 429 대응: exponential backoff with jitter
        base_delay = 0.5
        max_delay = 30.0

        for attempt in range(1, self.CONNECT_MAX_ATTEMPTS + 1):
            try:
                self._ws = await asyncio.wait_for(
                    websockets.connect(
                        self.WS_URL,
                        ping_interval=None,  # 자체 ping 사용
                        ping_timeout=None,
                        close_timeout=5,
                    ),
                    timeout=self.WS_CONNECT_TIMEOUT,
                )
                self._running = True
                self._recv_task = asyncio.create_task(self._recv_loop())
                if self.PING_INTERVAL is not None:
                    self._ping_task = asyncio.create_task(self._ping_loop())
                return True

            except InvalidStatusCode as e:
                status = getattr(e, "status_code", None) or getattr(e, "code", None)
                if status != 429:
                    msg = f"[{self.__class__.__name__}] connect failed (HTTP {status}): {e}"
                    print(msg)
                    logger.error(msg)
                    return False

                # 429: Retry-After 헤더 우선, 없으면 exponential backoff
                headers = getattr(e, "headers", None) or getattr(e, "response_headers", None) or {}
                retry_after = None
                try:
                    ra = headers.get("Retry-After") if hasattr(headers, "get") else None
                    retry_after = float(ra) if ra is not None else None
                except Exception:
                    pass

                if retry_after is None:
                    backoff = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    jitter = random.uniform(0, backoff * 0.2)
                    sleep_for = backoff + jitter
                else:
                    sleep_for = max(0.0, retry_after)

                msg = f"[{self.__class__.__name__}] 429 rate limit, retry in {sleep_for:.1f}s (attempt {attempt}/{self.CONNECT_MAX_ATTEMPTS})"
                print(msg)
                logger.warning(msg)
                await asyncio.sleep(sleep_for)

            except asyncio.TimeoutError:
                msg = f"[{self.__class__.__name__}] connect timeout (attempt {attempt}/{self.CONNECT_MAX_ATTEMPTS})"
                print(msg)
                logger.warning(msg)
                await asyncio.sleep(base_delay)

            except Exception as e:
                msg = f"[{self.__class__.__name__}] connect failed: {e}"
                print(msg)
                logger.error(msg)
                return False

        msg = f"[{self.__class__.__name__}] connect failed after {self.CONNECT_MAX_ATTEMPTS} attempts"
        print(msg)
        logger.error(msg)
        return False

    async def close(self) -> None:
        """연결 종료"""
        self._running = False

        # 태스크 취소
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None

        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None

        # 소켓 종료 (timeout으로 hang 방지)
        await self._safe_close(self._ws)
        self._ws = None

    async def _safe_close(self, ws: Optional[WebSocketClientProtocol]) -> None:
        """소켓 안전하게 종료 (timeout 적용)"""
        if ws is None:
            return
        try:
            await asyncio.wait_for(ws.close(), timeout=self.CLOSE_TIMEOUT)
        except Exception:
            pass

    async def _recv_loop(self) -> None:
        """메시지 수신 루프"""
        import time
        self._last_recv_time = time.time()

        while self._running:
            if not self._ws:
                await asyncio.sleep(0.1)
                continue
            try:
                # 수신 타임아웃 적용 (ping 없는 경우 연결 체크용)
                if self.RECV_TIMEOUT:
                    msg = await asyncio.wait_for(self._ws.recv(), timeout=self.RECV_TIMEOUT)
                else:
                    msg = await self._ws.recv()

                self._last_recv_time = time.time()
                self._ping_fail_count = 0  # 메시지 수신 시 ping 실패 카운트 리셋
                data = json.loads(msg)
                await self._handle_message(data)

            except asyncio.TimeoutError:
                # 수신 타임아웃 - 연결 죽은 것으로 간주
                log_msg = f"[{self.__class__.__name__}] recv timeout, reconnecting..."
                print(log_msg)
                logger.warning(log_msg)
                await self._handle_disconnect()
                break
            except ConnectionClosed as e:
                log_msg = f"[{self.__class__.__name__}] connection closed (code={e.code}), reconnecting..."
                print(log_msg)
                logger.warning(log_msg)
                await self._handle_disconnect()
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_msg = f"[{self.__class__.__name__}] recv error: {e}"
                print(log_msg)
                logger.error(log_msg)
                await asyncio.sleep(0.1)

    async def _ping_loop(self) -> None:
        """주기적 ping 전송 (연속 실패 시 재연결)"""
        if self.PING_INTERVAL is None:
            return

        try:
            while self._running:
                await asyncio.sleep(self.PING_INTERVAL)
                if self._ws and self._running:
                    ping_msg = self._build_ping_message()
                    if ping_msg:
                        try:
                            await self._ws.send(ping_msg)
                            # ping 성공 시 카운트 리셋 (pong 응답은 recv_loop에서 처리)
                        except Exception as e:
                            self._ping_fail_count += 1
                            log_msg = f"[{self.__class__.__name__}] ping failed ({self._ping_fail_count}/{self.PING_FAIL_THRESHOLD}): {e}"
                            print(log_msg)
                            logger.warning(log_msg)

                            if self._ping_fail_count >= self.PING_FAIL_THRESHOLD:
                                log_msg = f"[{self.__class__.__name__}] ping failed {self.PING_FAIL_THRESHOLD} times, reconnecting..."
                                print(log_msg)
                                logger.warning(log_msg)
                                self._ping_fail_count = 0
                                await self._handle_disconnect()
                                return  # 이 태스크는 종료, 재연결 시 새로 생성됨
        except asyncio.CancelledError:
            pass

    async def _handle_disconnect(self) -> None:
        """연결 끊김 처리"""
        print(f"[{self.__class__.__name__}] _handle_disconnect called, _running={self._running}, _reconnecting={self._reconnecting}")
        old_ws = self._ws
        self._ws = None
        await self._safe_close(old_ws)
        print(f"[{self.__class__.__name__}] calling _reconnect_with_backoff...")
        await self._reconnect_with_backoff()
        print(f"[{self.__class__.__name__}] _reconnect_with_backoff returned")

    async def _reconnect_with_backoff(self) -> None:
        """Exponential backoff으로 재연결"""
        print(f"[{self.__class__.__name__}] _reconnect_with_backoff: _reconnecting={self._reconnecting}, _running={self._running}")
        if self._reconnecting:
            print(f"[{self.__class__.__name__}] already reconnecting, returning")
            return
        self._reconnecting = True

        delay = self.RECONNECT_MIN
        try:
            while self._running:
                print(f"[{self.__class__.__name__}] reconnect loop: _running={self._running}")
                msg = f"[{self.__class__.__name__}] reconnecting in {delay:.1f}s..."
                print(msg)
                logger.info(msg)
                await asyncio.sleep(delay)
                print(f"[{self.__class__.__name__}] sleep done, attempting connect to {self.WS_URL}")

                # 기존 태스크 정리
                if self._ping_task and not self._ping_task.done():
                    self._ping_task.cancel()
                if self._recv_task and not self._recv_task.done():
                    self._recv_task.cancel()

                try:
                    print(f"[{self.__class__.__name__}] websockets.connect starting...")
                    self._ws = await asyncio.wait_for(
                        websockets.connect(
                            self.WS_URL,
                            ping_interval=None,
                            ping_timeout=None,
                            close_timeout=5,
                        ),
                        timeout=self.WS_CONNECT_TIMEOUT,
                    )
                    print(f"[{self.__class__.__name__}] websockets.connect done, starting tasks...")
                    self._recv_task = asyncio.create_task(self._recv_loop())
                    if self.PING_INTERVAL is not None:
                        self._ping_task = asyncio.create_task(self._ping_loop())

                    # 재구독
                    print(f"[{self.__class__.__name__}] calling _resubscribe...")
                    await self._resubscribe()
                    msg = f"[{self.__class__.__name__}] reconnected"
                    print(msg)
                    logger.info(msg)
                    return
                except Exception as e:
                    msg = f"[{self.__class__.__name__}] reconnect failed: {e}"
                    print(msg)
                    logger.error(msg)
                    import traceback
                    traceback.print_exc()
                    delay = min(self.RECONNECT_MAX, delay * 2.0) + random.uniform(0, 0.5)
        finally:
            self._reconnecting = False

    async def _send(self, msg: Dict[str, Any]) -> None:
        """메시지 전송 (연결 안 되어 있으면 연결 시도)"""
        if not self._ws or not self._running:
            await self.connect()
        if self._ws:
            await self._ws.send(json.dumps(msg))

    # ==================== Abstract Methods ====================

    @abstractmethod
    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """
        수신한 메시지 처리.
        서브클래스에서 채널별 dispatch 구현.
        """
        pass

    @abstractmethod
    async def _resubscribe(self) -> None:
        """
        재연결 후 구독 복구.
        이전에 구독했던 채널들을 다시 구독.
        """
        pass

    @abstractmethod
    def _build_ping_message(self) -> Optional[str]:
        """
        Ping 메시지 생성.
        None을 반환하면 ping 전송 안 함.
        예: return json.dumps({"method": "ping"})
        """
        pass
