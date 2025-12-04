import argparse
import asyncio
import json
import os
import random
import re
import signal
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError
import json
import websockets  # type: ignore
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK  # type: ignore
import logging
from logging.handlers import RotatingFileHandler

ws_logger = logging.getLogger("ws")
def _ensure_ws_logger():
    """
    WebSocket 전용 파일 핸들러를 한 번만 부착.
    - 기본 파일: ./ws.log
    - 기본 레벨: INFO
    - 기본 전파: False (루트 로그와 중복 방지)
    환경변수:
      PDEX_WS_LOG_FILE=/path/to/ws.log
      PDEX_WS_LOG_LEVEL=DEBUG|INFO|...
      PDEX_WS_LOG_CONSOLE=0|1
      PDEX_WS_PROPAGATE=0|1
    """
    if getattr(ws_logger, "_ws_logger_attached", False):
        return

    lvl_name = os.getenv("PDEX_WS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, lvl_name, logging.INFO)
    log_file = os.path.abspath(os.getenv("PDEX_WS_LOG_FILE", "ws.log"))
    to_console = os.getenv("PDEX_WS_LOG_CONSOLE", "0") == "1"
    propagate = os.getenv("PDEX_WS_PROPAGATE", "0") == "1"

    # 포맷 + 중복 핸들러 제거
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    for h in list(ws_logger.handlers):
        ws_logger.removeHandler(h)

    # 파일 핸들러(회전)
    fh = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.NOTSET)  # 핸들러는 로거 레벨만 따름
    ws_logger.addHandler(fh)

    # 콘솔(옵션)
    if to_console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.setLevel(logging.NOTSET)
        ws_logger.addHandler(sh)

    ws_logger.setLevel(level)
    ws_logger.propagate = propagate
    ws_logger._ws_logger_attached = True
    ws_logger.info("[WS-LOG] attached file=%s level=%s console=%s propagate=%s",
                   log_file, lvl_name, to_console, propagate)

# 모듈 import 시 한 번 설정
_ensure_ws_logger()

DEFAULT_HTTP_BASE = "https://api.hyperliquid.xyz"  # 메인넷
DEFAULT_WS_PATH = "/ws"                            # WS 엔드포인트
WS_CONNECT_TIMEOUT = 15
WS_READ_TIMEOUT = 60
PING_INTERVAL = 20
RECONNECT_MIN = 1.0
RECONNECT_MAX = 8.0

def json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

def _sample_items(d: Dict, n: int = 5):
    try:
        return list(d.items())[:n]
    except Exception:
        return []

def _clean_coin_key_for_perp(key: str) -> Optional[str]:
    """
    Perp/일반 심볼 정규화:
    - '@...' 내부키 제외
    - 'AAA/USDC'처럼 슬래시 포함은 Spot 처리로 넘김
    - 그 외 upper()
    """
    if not key:
        return None
    k = str(key).strip()
    if k.startswith("@"):
        return None
    if "/" in k:
        return None
    return k.upper() or None

def _clean_spot_key_from_pair(key: str) -> Optional[str]:
    """
    'AAA/USDC' → 'AAA' (베이스 심볼만 사용)
    """
    if not key:
        return None
    if "/" not in key:
        return None
    base, _quote = key.split("/", 1)
    base = base.strip().upper()
    return base or None

def http_to_wss(url: str) -> str:
    """
    'https://api.hyperliquid.xyz' → 'wss://api.hyperliquid.xyz/ws'
    이미 wss면 그대로, /ws 미포함 시 자동 부가.
    """
    if url.startswith("wss://"):
        return url if re.search(r"/ws($|[\?/#])", url) else (url.rstrip("/") + DEFAULT_WS_PATH)
    if url.startswith("https://"):
        base = re.sub(r"^https://", "wss://", url.rstrip("/"))
        return base + DEFAULT_WS_PATH if not base.endswith("/ws") else base
    return "wss://api.hyperliquid.xyz/ws"

def _sub_key(sub: dict) -> str:
    """구독 payload를 정규화하여 키 문자열로 변환."""
    # type + 주요 파라미터만 안정적으로 정렬
    t = str(sub.get("type"))
    u = (sub.get("user") or "").lower()
    d = (sub.get("dex") or "").lower()
    c = (sub.get("coin") or "").upper()
    return f"{t}|u={u}|d={d}|c={c}"

class HLWSClientRaw:
    """
    최소 WS 클라이언트:
    - 단건 구독 메시지: {"method":"subscribe","subscription": {...}}
    - ping: {"method":"ping"}
    - 자동 재연결/재구독
    - Spot 토큰 인덱스 맵을 REST로 1회 로드하여 '@{index}' 키를 Spot 심볼로 변환
    """

    def __init__(self, ws_url: str, dex: Optional[str], address: Optional[str], coins: List[str], http_base: str):
        self.ws_url = ws_url
        self.http_base = (http_base.rstrip("/") or DEFAULT_HTTP_BASE)
        self.address = address.lower() if address else None
        self.dex = dex.lower() if dex else None
        self.coins = [c.upper() for c in (coins or [])]

        self.conn: Optional[websockets.WebSocketClientProtocol] = None
        self._stop = asyncio.Event()
        self._tasks: List[asyncio.Task] = []

        # 최신 스냅샷 캐시
        self.prices: Dict[str, float] = {}        # Perp 등 일반 심볼: 'BTC' -> 104000.0
        self.spot_prices: Dict[str, float] = {}         # BASE → px (QUOTE=USDC일 때만)
        self.spot_pair_prices: Dict[str, float] = {}    # 'BASE/QUOTE' → px
        self.positions: Dict[str, Dict[str, Any]] = {}

        # 재연결 시 재구독용
        self._subscriptions: List[Dict[str, Any]] = []

        # Spot 토큰 인덱스 ↔ 이름 맵
        self.spot_index_to_name: Dict[int, str] = {}
        self.spot_name_to_index: Dict[str, int] = {}

        # [추가] Spot '페어 인덱스(spotInfo.index)' → 'BASE/QUOTE' & (BASE, QUOTE)
        self.spot_asset_index_to_pair: Dict[int, str] = {}
        self.spot_asset_index_to_bq: Dict[int, tuple[str, str]] = {}

        # [추가] 보류(펜딩) 큐를 '토큰 인덱스'와 '페어 인덱스'로 분리
        self._pending_spot_token_mids: Dict[int, float] = {}  # '@{tokenIdx}' 대기분
        self._pending_spot_pair_mids: Dict[int, float] = {}   # '@{pairIdx}'를 쓴 환경 대비(옵션)

        # 매핑 준비 전 수신된 '@{index}' 가격을 보류
        self._pending_spot_mids: Dict[int, float] = {}

        # webData3 기반 캐시
        self.margin: Dict[str, float] = {}                       # {'accountValue': float, 'withdrawable': float, ...}
        self.perp_meta: Dict[str, Dict[str, Any]] = {}           # coin -> {'szDecimals': int, 'maxLeverage': int|None, 'onlyIsolated': bool}
        self.asset_ctxs: Dict[str, Dict[str, Any]] = {}          # coin -> assetCtx(dict)
        self.positions: Dict[str, Dict[str, Any]] = {}           # coin -> position(dict)
        self.open_orders: List[Dict[str, Any]] = []              # raw list
        self.balances: Dict[str, float] = {}                          # token -> total
        #self.spot_pair_ctxs: Dict[str, Dict[str, Any]] = {}      # 'BASE/QUOTE' -> ctx(dict)
        #self.spot_base_px: Dict[str, float] = {}                 # BASE -> px (QUOTE=USDC일 때)
        self.collateral_quote: Optional[str] = None              # 예: 'USDC'
        self.server_time: Optional[int] = None                   # ms
        self.agent: Dict[str, Any] = {}                          # {'address': .., 'validUntil': ..}
        self.positions_norm: Dict[str, Dict[str, Any]] = {}  # coin -> normalized position
        
        # [추가] webData3 DEX별 캐시/순서
        self.dex_keys: List[str] = ["hl", "xyz", "flx", "vntl", "hyna"]  # 인덱스→DEX 키 매핑 우선순위
        self.margin_by_dex: Dict[str, Dict[str, float]] = {}     # dex -> {'accountValue', 'withdrawable', ...}
        self.positions_by_dex_norm: Dict[str, Dict[str, Dict[str, Any]]] = {}  # dex -> {coin -> norm pos}
        self.positions_by_dex_raw: Dict[str, List[Dict[str, Any]]] = {}         # dex -> raw assetPositions[*].position 목록
        self.asset_ctxs_by_dex: Dict[str, List[Dict[str, Any]]] = {}            # dex -> assetCtxs(raw list)
        self.total_account_value: float = 0.0

        self._send_lock = asyncio.Lock()
        self._active_subs: set[str] = set()  # 이미 보낸 구독의 키 집합

        # 이벤트 키 충돌 방지: kind 네임스페이스를 포함한 문자열 키 사용
        #   예) "perp|BTC", "spot_base|PURR", "spot_pair|PURR/USDC"
        self._price_events: Dict[str, asyncio.Event] = {}  # comment: {'perp|BTC': Event(), ...}

    # 외부(풀)에서 DEX 순서를 주입
    def set_dex_order(self, order: List[str]) -> None:
        try:
            ks = []
            seen = set()
            for k in order:
                key = str(k).lower().strip()
                if not key or key in seen:
                    continue
                ks.append(key)
                seen.add(key)
            if ks:
                self.dex_keys = ks
        except Exception:
            pass
    
    # 외부(풀)에서 Spot 메타를 주입
    def set_spot_meta(
        self,
        idx2name: Dict[int, str],
        name2idx: Dict[str, int],
        pair_by_index: Dict[int, str],
        bq_by_index: Dict[int, tuple[str, str]],
    ) -> None:
        # 내부에서 그대로 참조해도 되지만, 방어적으로 복사
        self.spot_index_to_name = dict(idx2name or {})
        self.spot_name_to_index = {str(k).upper(): int(v) for k, v in (name2idx or {}).items()}
        self.spot_asset_index_to_pair = dict(pair_by_index or {})
        self.spot_asset_index_to_bq = dict(bq_by_index or {})

    def _event_key(self, kind: str, key: str) -> str:
        return f"{kind}|{str(key).upper().strip()}"
    
    def _notify_perp(self, coin: str) -> None:
        try:
            ev = self._price_events.get(self._event_key("perp", coin))
            if ev and not ev.is_set():
                ev.set()
        except Exception:
            pass

    def _notify_spot_base(self, base: str) -> None:
        try:
            ev = self._price_events.get(self._event_key("spot_base", base))
            if ev and not ev.is_set():
                ev.set()
        except Exception:
            pass

    def _notify_spot_pair(self, pair: str) -> None:
        try:
            ev = self._price_events.get(self._event_key("spot_pair", pair))
            if ev and not ev.is_set():
                ev.set()
        except Exception:
            pass
    
    # 외부 API: 첫 틱(또는 이미 캐시 보유)까지 대기
    async def wait_price_ready(
        self,
        symbol: str,
        timeout: float = 5.0,
        *,
        kind: Optional[str] = None,    # 'perp' | 'spot_base' | 'spot_pair' (None이면 자동 판단)
    ) -> bool:
        """
        - kind가 명시되면 해당 타입의 캐시를 점검하고 그 이벤트만 대기.
        - kind가 None이면: '/' 포함 → spot_pair, 그 외 → perp 로 간주.
          (PURR 같은 모호한 베이스 토큰은 반드시 kind를 지정하세요: kind='spot_base')
        """
        s = str(symbol).strip().upper()
        k = (kind or ("spot_pair" if "/" in s else "perp")).lower()

        # 1) 즉시 보유 체크
        has_val = False
        if k == "perp":
            has_val = (self.get_price(s) is not None)
        elif k == "spot_pair":
            has_val = (self.get_spot_pair_px(s) is not None)
        elif k == "spot_base":
            has_val = (self.get_spot_price(s) is not None)
        else:
            raise ValueError(f"wait_price_ready: invalid kind={kind!r}")

        if has_val:
            return True

        # 2) 이벤트 생성 후 대기
        ek = self._event_key(k, s)
        ev = self._price_events.get(ek)
        if ev is None:
            ev = asyncio.Event()
            self._price_events[ek] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def connected(self) -> bool:
        return self.conn is not None
    
    async def ensure_connected_and_subscribed(self) -> None:
        if not self.connected:
            await self.connect()
            await self.subscribe()
        else:
            # 이미 연결되어 있으면 누락 구독 재보장
            await self.ensure_core_subs()

    async def ensure_allmids_for(self, dex: Optional[str]) -> None:
        """
        하나의 WS 커넥션에서 여러 DEX allMids를 구독할 수 있게 한다.
        - dex=None 또는 'hl' → {"type":"allMids"}
        - 그 외 → {"type":"allMids","dex": "<dex>"}
        중복 구독은 내부 dedup으로 자동 방지.
        """
        key = None
        if dex is None or str(dex).lower() == "hl":
            sub = {"type": "allMids"}
            key = _sub_key(sub)
            if key not in self._active_subs:
                await self._send_subscribe(sub)
        else:
            d = str(dex).lower().strip()
            sub = {"type": "allMids", "dex": d}
            key = _sub_key(sub)
            if key not in self._active_subs:
                await self._send_subscribe(sub)

    async def _send_subscribe(self, sub: dict) -> None:
        """subscribe 메시지 전송(중복 방지)."""
        key = _sub_key(sub)
        if key in self._active_subs:
            return
        async with self._send_lock:
            if key in self._active_subs:
                return
            payload = {"method": "subscribe", "subscription": sub}
            await self.conn.send(json.dumps(payload, separators=(",", ":")))
            self._active_subs.add(key)

    async def ensure_core_subs(self) -> None:
        """
        스코프별 필수 구독을 보장:
        - allMids: 가격(이 스코프 문맥)
        - webData3/spotState: 주소가 있을 때만
        """
        # 1) 가격(스코프별)
        if self.dex:
            await self._send_subscribe({"type": "allMids", "dex": self.dex})
        else:
            await self._send_subscribe({"type": "allMids"})
        # 2) 주소 구독(webData3/spotState)
        if self.address:
            await self._send_subscribe({"type": "webData3", "user": self.address})
            await self._send_subscribe({"type": "spotState", "user": self.address})

    async def ensure_subscribe_active_asset(self, coin: str) -> None:
        """
        필요 시 코인 단위 포지션 스트림까지 구독(선택).
        보통 webData3로 충분하므로 기본은 호출 필요 없음.
        """
        sub = {"type": "activeAssetData", "coin": coin}
        if self.address:
            sub["user"] = self.address
        await self._send_subscribe(sub)

    @staticmethod
    def discover_perp_dexs_http(http_base: str, timeout: float = 8.0) -> list[str]:
        """
        POST {http_base}/info {"type":"perpDexs"} → [{'name':'xyz'}, {'name':'flx'}, ...]
        반환: ['xyz','flx','vntl', ...] (소문자)
        """
        url = f"{http_base.rstrip('/')}/info"
        payload = {"type":"perpDexs"}
        headers = {"Content-Type": "application/json"}
        def _post():
            data = json_dumps(payload).encode("utf-8")
            req = urllib_request.Request(url, data=data, headers=headers, method="POST")
            with urllib_request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        try:
            resp = _post()
            out = []
            if isinstance(resp, list):
                for e in resp:
                    n = (e or {}).get("name")
                    if n:
                        out.append(str(n).lower())
            # 중복 제거/정렬
            return sorted(set(out))
        except (HTTPError, URLError):
            return []
        except Exception:
            return []
        
    def _dex_key_by_index(self, i: int) -> str:
        """perpDexStates 배열 인덱스를 DEX 키로 매핑. 부족하면 'dex{i}' 사용."""
        return self.dex_keys[i] if 0 <= i < len(self.dex_keys) else f"dex{i}"

    def set_dex_order(self, order: List[str]) -> None:
        """DEX 표시 순서를 사용자 정의로 교체. 예: ['hl','xyz','flx','vntl']"""
        try:
            ks = [str(k).lower().strip() for k in order if str(k).strip()]
            if ks:
                self.dex_keys = ks
        except Exception:
            pass

    def get_dex_keys(self) -> List[str]:
        """현재 스냅샷에 존재하는 DEX 키(순서 보장)를 반환."""
        present = [k for k in self.dex_keys if k in self.margin_by_dex]
        # dex_keys 외의 임시 dex{i}가 있을 수 있으므로 뒤에 덧붙임
        extras = [k for k in self.margin_by_dex.keys() if k not in present]
        return present + sorted(extras)

    def get_total_account_value_web3(self) -> float:
        """webData3 기준 전체 AV 합계."""
        try:
            return float(sum(float((v or {}).get("accountValue", 0.0)) for v in self.margin_by_dex.values()))
        except Exception:
            return 0.0

    def get_account_value_by_dex(self, dex: Optional[str] = None) -> Optional[float]:
        d = self.margin_by_dex.get((dex or "hl").lower())
        if not d: return None
        try: return float(d.get("accountValue"))
        except Exception: return None

    def get_withdrawable_by_dex(self, dex: Optional[str] = None) -> Optional[float]:
        d = self.margin_by_dex.get((dex or "hl").lower())
        if not d: return None
        try: return float(d.get("withdrawable"))
        except Exception: return None

    def get_margin_summary_by_dex(self, dex: Optional[str] = None) -> Dict[str, float]:
        return dict(self.margin_by_dex.get((dex or "hl").lower(), {}))

    def get_positions_by_dex(self, dex: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        return dict(self.positions_by_dex_norm.get((dex or "hl").lower(), {}))

    def get_asset_ctxs_by_dex(self, dex: Optional[str] = None) -> List[Dict[str, Any]]:
        return list(self.asset_ctxs_by_dex.get((dex or "hl").lower(), []))

    def _update_from_webData3(self, data: Dict[str, Any]) -> None:
        """
        webData3 포맷을 DEX별로 분리 파싱해 내부 캐시에 반영.
        data 구조:
        - userState: {...}
        - perpDexStates: [ { clearinghouseState, assetCtxs, ...}, ... ]  # HL, xyz, flx, vntl 순
        """
        try:
            # userState(참고/보조)
            user_state = data.get("userState") or {}
            
            self.server_time = user_state.get("serverTime") or self.server_time
            if user_state.get("user"):
                self.agent["user"] = user_state.get("user")
            if user_state.get("agentAddress"):
                self.agent["agentAddress"] = user_state["agentAddress"]
            if user_state.get("agentValidUntil"):
                self.agent["agentValidUntil"] = user_state["agentValidUntil"]
            
            dex_states = data.get("perpDexStates") or []
            
            # 누적 합계 재계산
            self.total_account_value = 0.0


            for i, st in enumerate(dex_states):
                dex_key = self._dex_key_by_index(i)
                ch = (st or {}).get("clearinghouseState") or {}
                ms = ch.get("marginSummary") or {}

                # 숫자 변환
                def fnum(x, default=0.0):
                    try: return float(x)
                    except Exception: return default

                margin = {
                    "accountValue": fnum(ms.get("accountValue")),
                    "totalNtlPos":  fnum(ms.get("totalNtlPos")),
                    "totalRawUsd":  fnum(ms.get("totalRawUsd")),
                    "totalMarginUsed": fnum(ms.get("totalMarginUsed")),
                    "crossMaintenanceMarginUsed": fnum(ch.get("crossMaintenanceMarginUsed")),
                    "withdrawable": fnum(ch.get("withdrawable")),
                    "time": ch.get("time"),
                }
                self.margin_by_dex[dex_key] = margin
                self.total_account_value += float(margin["accountValue"])

                # 포지션(정규화/원본)
                norm_map: Dict[str, Dict[str, Any]] = {}
                raw_list: List[Dict[str, Any]] = []
                for ap in ch.get("assetPositions") or []:
                    pos = (ap or {}).get("position") or {}
                    if not pos:
                        continue
                    raw_list.append(pos)
                    coin_raw = str(pos.get("coin") or "")
                    coin_upper = coin_raw.upper()
                    if coin_upper:
                        try:
                            norm = self._normalize_position(pos)
                            # [ADD] 기존 대문자 키
                            norm_map[coin_upper] = norm  # comment: 기존 동작 유지
                            # [ADD] HIP-3 호환: 원문 키도 함께 저장해 조회 경로 다양성 보장
                            if ":" in coin_raw:
                                norm_map[coin_raw] = norm  # comment: 'xyz:XYZ100' 같은 원문 키 추가
                        except Exception:
                            continue
                self.positions_by_dex_raw[dex_key] = raw_list
                self.positions_by_dex_norm[dex_key] = norm_map

                # 자산 컨텍스트(raw 리스트 그대로 저장)
                asset_ctxs = st.get("assetCtxs") or []
                if isinstance(asset_ctxs, list):
                    self.asset_ctxs_by_dex[dex_key] = asset_ctxs

        except Exception as e:
            ws_logger.debug(f"[webData3] update error: {e}", exc_info=True)

    def _normalize_position(self, pos: Dict[str, Any]) -> Dict[str, Any]:
        """
        webData3.clearinghouseState.assetPositions[*].position → 표준화 dict
        반환 키:
        - coin: str
        - size: float(절대값), side: 'long'|'short'
        - entry_px, position_value, upnl, roe, liq_px, margin_used: float|None
        - lev_type: 'cross'|'isolated'|..., lev_value: int|None, max_leverage: int|None
        """
        def f(x, default=None):
            try:
                return float(x)
            except Exception:
                return default
        coin = str(pos.get("coin") or "").upper()
        szi = f(pos.get("szi"), 0.0) or 0.0
        side = "long" if szi > 0 else ("short" if szi < 0 else "flat")
        lev = pos.get("leverage") or {}
        lev_type = str(lev.get("type") or "").lower() or None
        try:
            lev_value = int(float(lev.get("value"))) if lev.get("value") is not None else None
        except Exception:
            lev_value = None
        return {
            "coin": coin,
            "size": abs(float(szi)),
            "side": side,
            "entry_px": f(pos.get("entryPx"), None),
            "position_value": f(pos.get("positionValue"), None),
            "upnl": f(pos.get("unrealizedPnl"), None),
            "roe": f(pos.get("returnOnEquity"), None),
            "liq_px": f(pos.get("liquidationPx"), None),
            "margin_used": f(pos.get("marginUsed"), None),
            "lev_type": lev_type,
            "lev_value": lev_value,
            "max_leverage": (int(float(pos.get("maxLeverage"))) if pos.get("maxLeverage") is not None else None),
            "raw": pos,  # 원본도 보관(디버깅/확장용)
        }

    # [추가] 정규화 포지션 전체 반환(사본)
    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.positions_norm)

    # [추가] 단일 코인의 핵심 요약 반환(사이즈=0 이면 None)
    def get_position_simple(self, coin: str) -> Optional[tuple]:
        """
        반환: (side, size, entry_px, upnl, roe, lev_type, lev_value)
        없거나 size=0이면 None
        """
        p = self.positions_norm.get(coin.upper())
        if not p or not p.get("size"):
            return None
        return (
            p.get("side"),
            float(p.get("size") or 0.0),
            p.get("entry_px"),
            p.get("upnl"),
            p.get("roe"),
            p.get("lev_type"),
            p.get("lev_value"),
        )
    
    def get_account_value(self) -> Optional[float]:
        return self.margin.get("accountValue")

    def get_withdrawable(self) -> Optional[float]:
        return self.margin.get("withdrawable")

    def get_collateral_quote(self) -> Optional[str]:
        return self.collateral_quote

    def get_perp_ctx(self, coin: str) -> Optional[Dict[str, Any]]:
        return self.asset_ctxs.get(coin.upper())

    def get_perp_sz_decimals(self, coin: str) -> Optional[int]:
        meta = self.perp_meta.get(coin.upper())
        return meta.get("szDecimals") if meta else None

    def get_perp_max_leverage(self, coin: str) -> Optional[int]:
        meta = self.perp_meta.get(coin.upper())
        return meta.get("maxLeverage") if meta else None

    def get_position(self, coin: str) -> Optional[Dict[str, Any]]:
        return self.positions.get(coin.upper())

    def get_spot_balance(self, token: str) -> float:
        return float(self.balances.get(token.upper(), 0.0))

    def get_spot_pair_px(self, pair: str) -> Optional[float]:
        """
        스팟 페어 가격 조회(내부 캐시 기반, 우선순위):
        1) spot_pair_ctxs['BASE/QUOTE']의 midPx → markPx → prevDayPx
        2) spot_pair_prices['BASE/QUOTE'] (allMids로부터 받은 숫자)
        3) 페어가 BASE/USDC이면 spot_prices['BASE'] (allMids에서 받은 BASE 단가)
        """
        if not pair:
            return None
        p = str(pair).strip().upper()

        """
        # 1) webData2/3에서 온 페어 컨텍스트가 있으면 거기서 mid/mark/prev 순으로 사용
        ctx = self.spot_pair_ctxs.get(p)
        if isinstance(ctx, dict):
            for k in ("midPx", "markPx", "prevDayPx"):
                v = ctx.get(k)
                if v is not None:
                    try:
                        return float(v)
                    except Exception:
                        continue
        """

        # 2) allMids에서 유지하는 페어 가격 맵(숫자) 사용
        v = self.spot_pair_prices.get(p)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass

        # 3) BASE/USDC인 경우 BASE 단가(spot_prices['BASE'])를 사용
        if p.endswith("/USDC") and "/" in p:
            base = p.split("/", 1)[0].strip().upper()
            v2 = self.spot_prices.get(base)
            if v2 is not None:
                try:
                    return float(v2)
                except Exception:
                    pass

        return None

    #def get_spot_px_base(self, base: str) -> Optional[float]:
    #    return self.spot_base_px.get(base.upper())

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return list(self.open_orders)

    async def connect(self) -> None:
        ws_logger.info(f"WS connect: {self.ws_url}")
        self.conn = await websockets.connect(self.ws_url, ping_interval=None, open_timeout=WS_CONNECT_TIMEOUT)
        # keepalive task (JSON ping)
        self._tasks.append(asyncio.create_task(self._ping_loop(), name="ping"))
        # listen task
        self._tasks.append(asyncio.create_task(self._listen_loop(), name="listen"))

    async def close(self) -> None:
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

    def build_subscriptions(self) -> List[Dict[str, Any]]:
        subs: list[dict] = []
        # 1) scope별 allMids
        if self.dex:
            subs.append({"type":"allMids","dex": self.dex})
        else:
            subs.append({"type":"allMids"})  # HL(메인)
        # 2) 주소가 있으면 user 스트림(webData3/spotState)도 구독
        if self.address:
            subs.append({"type":"webData3","user": self.address})
            subs.append({"type":"spotState","user": self.address})
        return subs
    
    def _update_spot_balances(self, balances_list: Optional[List[Dict[str, Any]]]) -> None:
        """
        balances_list: [{'coin':'USDC','token':0,'total':'88.2969',...}, ...]
        - balances[token_name] 갱신
        """
        if not isinstance(balances_list, list):
            return
        updated = 0
        for b in balances_list:
            try:
                token_name = str(b.get("coin") or b.get("tokenName") or b.get("token")).upper()
                if not token_name:
                    continue
                total = float(b.get("total") or 0.0)
                self.balances[token_name] = total
                updated += 1
            except Exception:
                continue

    async def subscribe(self) -> None:
        """
        단건 구독 전송(중복 방지): build_subscriptions() 결과를 _send_subscribe로 보냅니다.
        """
        if not self.conn:
            raise RuntimeError("WebSocket is not connected")

        subs = self.build_subscriptions()
        self._subscriptions = subs  # 재연결 시 재사용

        for sub in subs:
            await self._send_subscribe(sub)
            ws_logger.info(f"SUB -> {json_dumps({'method':'subscribe','subscription':sub})}")

    async def resubscribe(self) -> None:
        if not self.conn or not self._subscriptions:
            return
        # 재연결 시 서버는 이전 구독 상태를 잊었으므로 클라이언트 dedup도 비웁니다.
        self._active_subs.clear()
        for sub in self._subscriptions:
            await self._send_subscribe(sub)
            ws_logger.info(f"RESUB -> {json_dumps({'method':'subscribe','subscription':sub})}")

    # ---------------------- 루프/콜백 ----------------------

    async def _ping_loop(self) -> None:
        """
        WebSocket 프레임 ping이 아니라, 서버 스펙에 맞춘 JSON ping 전송.
        """
        try:
            while not self._stop.is_set():
                await asyncio.sleep(PING_INTERVAL)
                if not self.conn:
                    continue
                try:
                    await self.conn.send(json_dumps({"method": "ping"}))
                    ws_logger.debug("ping sent (json)")
                except Exception as e:
                    ws_logger.warning(f"ping error: {e}")
        except asyncio.CancelledError:
            return

    async def _listen_loop(self) -> None:
        assert self.conn is not None
        ws = self.conn
        while not self._stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=WS_READ_TIMEOUT)
            except asyncio.TimeoutError:
                ws_logger.warning("recv timeout; forcing reconnect")
                await self._handle_disconnect()
                break
            except (ConnectionClosed, ConnectionClosedOK):
                ws_logger.warning("ws closed; reconnecting")
                await self._handle_disconnect()
                break
            except Exception as e:
                ws_logger.error(f"recv error: {e}", exc_info=True)
                await self._handle_disconnect()
                break

            # 서버 초기 문자열 핸드셰이크 처리
            if isinstance(raw, str) and raw == "Websocket connection established.":
                ws_logger.debug(raw)
                continue

            try:
                msg = json.loads(raw)
            except Exception:
                ws_logger.debug(f"non-json message: {str(raw)[:200]}")
                continue

            try:
                self._dispatch(msg)
            except Exception:
                ws_logger.exception("dispatch error")

    def _dispatch(self, msg: Dict[str, Any]) -> None:
        """
        서버 메시지 처리:
        - allMids: data = {'mids': { '<symbol or @pairIdx>': '<px_str>', ... } }
        - '@{pairIdx}'는 spotMeta.universe의 spotInfo.index로 매핑
        """
        ch = str(msg.get("channel") or msg.get("type") or "")
        if not ch:
            ws_logger.debug(f"no channel key in message: {msg}")
            return

        if ch == "error":
            data_str = str(msg.get("data") or "")
            if "Already subscribed" in data_str:
                ws_logger.debug(f"[WS info] {data_str}")
            else:
                ws_logger.error(f"[WS error] {data_str}")
            return
        if ch == "pong":
            ws_logger.debug("received pong")
            return

        if ch == "allMids":
            data = msg.get("data") or {}
            
            if isinstance(data, dict) and isinstance(data.get("mids"), dict):
                mids: Dict[str, Any] = data["mids"]
                n_pair = n_pair_text = n_perp = 0

                for raw_key, raw_mid in mids.items():
                    # 1) '@{pairIdx}' → spotInfo.index
                    if isinstance(raw_key, str) and raw_key.startswith("@"):
                        try:
                            pair_idx = int(raw_key[1:])
                            px = float(raw_mid)
                        except Exception:
                            continue

                        pair_name = self.spot_asset_index_to_pair.get(pair_idx)   # 'BASE/QUOTE'
                        bq_tuple  = self.spot_asset_index_to_bq.get(pair_idx)     # (BASE, QUOTE)

                        if not pair_name or not bq_tuple:
                            # 페어 맵 미준비 → 보류
                            continue

                        base, quote = bq_tuple

                        # 1-1) 페어 가격 캐시
                        self.spot_pair_prices[pair_name] = px
                        self._notify_spot_pair(pair_name)
                        
                        # 1-2) 쿼트가 USDC인 경우 base 단일 가격도 채움
                        if quote == "USDC":
                            self.spot_prices[base] = px
                            self._notify_spot_base(base)
                        
                        n_pair += 1
                        continue

                    # 2) 텍스트 페어 'AAA/USDC' → pair 캐시, USDC 쿼트면 base 캐시
                    maybe_spot_base = _clean_spot_key_from_pair(raw_key)
                    if maybe_spot_base:
                        try:
                            px = float(raw_mid)
                        except Exception:
                            px = None
                        if px is not None:
                            pair_name = raw_key.strip().upper()
                            self.spot_pair_prices[pair_name] = px
                            self._notify_spot_pair(pair_name)

                            if pair_name.endswith("/USDC"):
                                self.spot_prices[maybe_spot_base] = px
                                self._notify_spot_base(maybe_spot_base)
                                
                        n_pair_text += 1
                        continue

                    # 3) Perp/기타 심볼
                    perp_key = _clean_coin_key_for_perp(raw_key)
                    if not perp_key:
                        continue
                    try:
                        px = float(raw_mid)
                    except Exception:
                        continue
                    self.prices[perp_key] = px
                    self._notify_perp(perp_key)
                    n_perp += 1

            return

        # 포지션(코인별)
        elif ch == "spotState":
            # 예시 구조: {'channel':'spotState','data':{'user': '0x...','spotState': {'balances': [...]}}}
            data_body = msg.get("data") or {}
            spot = data_body.get("spotState") or {}
            balances_list = spot.get("balances") or []
            self._update_spot_balances(balances_list)

            return
            
        # 유저 스냅샷(잔고 등)
        elif ch == "webData3":
            data_body = msg.get("data") or {}
            self._update_from_webData3(data_body)

    async def _handle_disconnect(self) -> None:
        await self._safe_close_only()
        await self._reconnect_with_backoff()

    async def _safe_close_only(self) -> None:
        if self.conn:
            try:
                await self.conn.close()
            except Exception:
                pass
        self.conn = None

    async def _reconnect_with_backoff(self) -> None:
        delay = RECONNECT_MIN
        while not self._stop.is_set():
            try:
                await asyncio.sleep(delay)
                await self.connect()
                await self.resubscribe()
                return
            except Exception as e:
                delay = min(RECONNECT_MAX, delay * 2.0) + random.uniform(0.0, 0.5)

    def get_price(self, symbol: str) -> Optional[float]:
        """Perp/일반 심볼 가격 조회(캐시)."""
        return self.prices.get(symbol.upper())

    def get_spot_price(self, symbol: str) -> Optional[float]:
        """Spot 심볼 가격 조회(캐시)."""
        return self.spot_prices.get(symbol.upper())

    def get_all_spot_balances(self) -> Dict[str, float]:
        return dict(self.balances)

    def get_spot_portfolio_value_usdc(self) -> float:
        """
        USDC 기준 추정 총가치:
        - USDC = 1.0
        - 기타 토큰은 BASE/USDC 단가(self.spot_prices 또는 spot_pair_ctxs의 mid/mark/prev) 사용
        - 가격을 알 수 없는 토큰은 0으로 계산
        """
        total = 0.0
        for token, amt in self.balances.items():
            try:
                if token == "USDC":
                    px = 1.0
                else:
                    # 우선 캐시된 BASE/USDC mid/mark/prev 기반
                    px = self.spot_prices.get(token)
                    if px is None:
                        # spot_pair_ctxs에 'TOKEN/USDC'가 있으면 그 값을 사용
                        pair = f"{token}/USDC"
                        ctx = self.spot_pair_ctxs.get(pair)
                        if isinstance(ctx, dict):
                            for k in ("midPx","markPx","prevDayPx"):
                                v = ctx.get(k)
                                if v is not None:
                                    try:
                                        px = float(v); break
                                    except Exception:
                                        continue
                if px is None:
                    continue
                total += float(amt) * float(px)
            except Exception:
                continue
        return float(total)


class HLWSClientPool:
    """
    (ws_url, address) 단위로 HLWSClientRaw를 1개만 생성/공유하는 풀.
    - 동일 주소에서 다중 DEX allMids는 하나의 커넥션에서 추가 구독한다.
    - address가 None/""이면 '가격 전용' 공유 커넥션으로 취급(유저 스트림 없음).
    """
    def __init__(self) -> None:
        self._clients: dict[str, HLWSClientRaw] = {}
        self._refcnt: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # 공용 메타 저장소(+ 보호용 락)
        self._shared_lock = asyncio.Lock()
        self._shared_primed: bool = False
        self._shared_dex_order: List[str] = ["hl"]
        self._shared_spot_idx2name: Dict[int, str] = {}
        self._shared_spot_name2idx: Dict[str, int] = {}
        self._shared_spot_pair_by_index: Dict[int, str] = {}
        self._shared_spot_bq_by_index: Dict[int, tuple[str, str]] = {}

                
    # 초기 1회만 공유 메타를 주입(이미 primed면 무시)
    async def prime_shared_meta(
        self,
        *,
        dex_order: Optional[List[str]] = None,
        idx2name: Optional[Dict[int, str]] = None,
        name2idx: Optional[Dict[str, int]] = None,
        pair_by_index: Optional[Dict[int, str]] = None,
        bq_by_index: Optional[Dict[int, Tuple[str, str]]] = None,
    ) -> None:
        async with self._shared_lock:
            if self._shared_primed:
                return
            # 정규화
            ks, seen = [], set()
            for k in (dex_order or ["hl"]):
                kk = str(k).lower().strip()
                if kk and kk not in seen:
                    ks.append(kk); seen.add(kk)
            self._shared_dex_order = ks or ["hl"]
            self._shared_spot_idx2name = dict(idx2name or {})
            self._shared_spot_name2idx = {str(k).upper(): int(v) for k, v in (name2idx or {}).items()}
            self._shared_spot_pair_by_index = dict(pair_by_index or {})
            self._shared_spot_bq_by_index = dict(bq_by_index or {})
            self._shared_primed = True  # comment: 이후 호출은 무시

    def _apply_shared_to_client_unlocked(self, c: HLWSClientRaw) -> None:
        # [INTERNAL] _shared_lock 보유 상태에서만 호출
        c.set_dex_order(self._shared_dex_order or ["hl"])
        c.set_spot_meta(
            self._shared_spot_idx2name,
            self._shared_spot_name2idx,
            self._shared_spot_pair_by_index,
            self._shared_spot_bq_by_index,
        )

    def _key(self, ws_url: str, address: Optional[str]) -> str:
        addr = (address or "").lower().strip()
        url = http_to_wss(ws_url) if ws_url.startswith("http") else ws_url
        return f"{url}|{addr}"

    def _get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def acquire(
        self,
        *,
        ws_url: str,
        http_base: str,
        address: Optional[str],
        dex: Optional[str] = None,
        # 최초 1회 주입용(선택)
        dex_order: Optional[List[str]] = None,
        idx2name: Optional[Dict[int, str]] = None,
        name2idx: Optional[Dict[str, int]] = None,
        pair_by_index: Optional[Dict[int, str]] = None,
        bq_by_index: Optional[Dict[int, Tuple[str, str]]] = None,
    ) -> HLWSClientRaw:
        """
        풀에서 (ws_url,address) 키로 클라이언트를 획득(없으면 생성).
        생성 시:
          - spotMeta 선행 로드
          - connect + 기본 subscribe(webData3/spotState는 address가 있을 때만)
        이후 요청된 dex의 allMids를 추가 구독.
        """
        # per-key 락 전에 공유 스냅샷을 1회 주입 시도(데드락 회피)
        await self.prime_shared_meta(
            dex_order=dex_order,
            idx2name=idx2name,
            name2idx=name2idx,
            pair_by_index=pair_by_index,
            bq_by_index=bq_by_index,
        )

        key = self._key(ws_url, address)
        lock = self._get_lock(key)
        async with lock:
            client = self._clients.get(key)
            if client is None:
                # [ADDED] 최초 생성: dex=None로 만들어 HL 메인 allMids만 기본 구독
                client = HLWSClientRaw(
                    ws_url=http_to_wss(ws_url),
                    dex=None,                      # comment: allMids(기본, HL)만 우선
                    address=address,
                    coins=[],
                    http_base=http_base,
                )
                async with self._shared_lock:
                    self._apply_shared_to_client_unlocked(client)
                await client.ensure_connected_and_subscribed()
                self._clients[key] = client
                self._refcnt[key] = 0

            # 참조 카운트 증가
            self._refcnt[key] += 1

        # 락 밖에서 dex allMids 추가 구독(중복 방지 로직 보유)
        await client.ensure_allmids_for(dex)
        return client

    async def release(self, *, ws_url: str, address: Optional[str]) -> None:
        key = self._key(ws_url, address)
        lock = self._get_lock(key)
        async with lock:
            if key not in self._clients:
                return
            self._refcnt[key] = max(0, self._refcnt.get(key, 1) - 1)
            if self._refcnt[key] == 0:
                client = self._clients.pop(key)
                self._refcnt.pop(key, None)
                try:
                    await client.close()
                except Exception:
                    pass
                # 락은 재사용 가능하므로 남겨둠

WS_POOL = HLWSClientPool()