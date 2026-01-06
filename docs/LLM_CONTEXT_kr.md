# Multi-Perp-DEX LLM 컨텍스트 문서

> 이 문서는 LLM 소비에 최적화되어 있습니다. mpdex 코드베이스를 이해하고 작업하기 위한 구조화된 컨텍스트를 제공합니다.

---

## 시스템 개요

**프로젝트명:** mpdex (Multi-Perp-DEX)
**목적:** 여러 DEX에서 선물 거래를 위한 통합 비동기 Python 인터페이스
**언어:** Python 3.8+ (Windows는 3.10 필요)
**패턴:** 팩토리 + 추상 베이스 클래스 + 웹소켓 풀링

---

## 핵심 규칙

### 규칙 1: 심볼 포맷
항상 `symbol_create()` 함수를 사용하세요. 각 거래소마다 고유한 심볼 포맷이 있습니다.

```python
# 올바른 방법
symbol = symbol_create("standx", "BTC")  # "BTC-USD" 반환
await exchange.get_mark_price(symbol)

# 잘못된 방법 - 실패함
await exchange.get_mark_price("BTC")  # 거래소가 인식 못함
```

### 규칙 2: 거래소 초기화
생성 후 항상 비동기 `init()`을 호출하세요 (팩토리가 자동 처리).

```python
# 올바른 방법 - 팩토리 사용
exchange = await create_exchange("standx", key_params)

# 잘못된 방법 - init 누락
exchange = StandXExchange(...)  # 초기화 안 됨!
```

### 규칙 3: 리소스 정리
완료 시 항상 `close()`를 호출하세요.

```python
try:
    # 거래 로직
finally:
    await exchange.close()  # 필수
```

### 규칙 4: StandX 웹소켓 Ping
StandX에서 절대 ping을 활성화하지 마세요. 클라이언트가 ping을 보내면 서버가 연결을 끊습니다.

```python
# standx_ws_client.py에서
PING_INTERVAL = None  # StandX에서는 반드시 None
RECV_TIMEOUT = None   # 주문 스트림이 유휴 상태일 수 있음
```

### 규칙 5: Hyperliquid USD 전송
USD 전송은 반드시 지갑 프라이빗 키를 사용해야 합니다, 에이전트 불가.

```python
# USD 전송 - 반드시 지갑 사용
sign_user_signed_action(wallet_private_key, ...)  # 올바름

# 일반 거래 - 에이전트 사용 가능
sign_l1_action(agent_private_key, ...)  # OK
```

---

## 파일 구조 맵

```
multi-perp-dex/
├── multi_perp_dex.py         # BASE: 추상 클래스
├── exchange_factory.py        # FACTORY: create_exchange(), symbol_create()
├── mpdex/__init__.py         # API: 지연 로딩 공개 exports
├── wrappers/
│   ├── base_ws_client.py     # WS_BASE: 추상 웹소켓 클라이언트
│   ├── lighter.py            # EXCHANGE: Lighter 구현
│   ├── standx.py             # EXCHANGE: StandX 구현
│   ├── standx_ws_client.py   # WS: StandX 웹소켓 클라이언트
│   ├── hyperliquid.py        # EXCHANGE: Hyperliquid 구현
│   └── ...                   # 기타 거래소들
└── keys/                     # CONFIG: 인증 정보 템플릿 (gitignored)
```

---

## 심볼 포맷 테이블

| 거래소 | 포맷 | 예시 | 함수 |
|--------|------|------|------|
| lighter | `{COIN}` | `BTC` | `symbol_create("lighter", "BTC")` |
| standx | `{COIN}-USD` | `BTC-USD` | `symbol_create("standx", "BTC")` |
| paradex | `{COIN}-USD-PERP` | `BTC-USD-PERP` | `symbol_create("paradex", "BTC")` |
| grvt | `{COIN}_USDT_Perp` | `BTC_USDT_Perp` | `symbol_create("grvt", "BTC")` |
| backpack | `{COIN}_USDC_PERP` | `BTC_USDC_PERP` | `symbol_create("backpack", "BTC")` |
| edgex | `{COIN}USD` | `BTCUSD` | `symbol_create("edgex", "BTC")` |
| hyperliquid | `{COIN}` | `BTC` | `symbol_create("hyperliquid", "BTC")` |
| pacifica | `{COIN}` | `BTC` | `symbol_create("pacifica", "BTC")` |
| variational | `{COIN}` | `BTC` | `symbol_create("variational", "BTC")` |
| superstack | `{COIN}` | `BTC` | `symbol_create("superstack", "BTC")` |
| treadfi.hyperliquid | `{COIN}:PERP-USDC` | `BTC:PERP-USDC` | `symbol_create("treadfi.hyperliquid", "BTC")` |

---

## 인터페이스 명세

### MultiPerpDex (추상 베이스)

```python
class MultiPerpDex(ABC):
    has_spot: bool = False
    available_symbols: Dict[str, List[str]] = {}
    ws_supported: Dict[str, bool]  # 웹소켓 지원 작업들

    # 필수 구현
    async def create_order(symbol, side, amount, price=None, order_type='market') -> Dict
    async def get_position(symbol) -> Optional[Dict]
    async def close_position(symbol, position=None) -> Optional[Dict]
    async def get_collateral() -> Dict
    async def get_open_orders(symbol) -> List[Dict]
    async def cancel_orders(symbol, open_orders=None) -> Any
    async def get_mark_price(symbol) -> str
    async def update_leverage(symbol, leverage) -> Any
    async def get_available_symbols() -> Dict[str, List[str]]
    async def close() -> None
```

### 반환값 형식

**get_position() -> Dict 또는 None:**
```python
{
    "symbol": str,           # 거래 쌍
    "side": str,             # "long" | "short"
    "size": str,             # 포지션 크기 (정밀도를 위한 문자열)
    "entry_price": str,      # 평균 진입가
    "mark_price": str,       # 현재 마크 가격
    "unrealized_pnl": str,   # 미실현 손익
    "leverage": str,         # 현재 레버리지
    "margin_mode": str,      # "cross" | "isolated"
    "liq_price": str,        # 청산가
}
```

**get_collateral() -> Dict:**
```python
{
    "available_collateral": float,  # 신규 포지션 가능 금액
    "total_collateral": float,      # 총 예치금
    "equity": float,                # 미실현 손익 포함
    "upnl": float,                  # 미실현 손익
}
```

**get_open_orders() -> List[Dict]:**
```python
[
    {
        "id": str,        # 주문 ID
        "symbol": str,    # 거래 쌍
        "side": str,      # "buy" | "sell"
        "size": float,    # 주문 수량
        "price": float,   # 주문 가격 (시장가는 None)
    },
]
```

---

## 웹소켓 설정

### BaseWSClient 파라미터

```python
class BaseWSClient(ABC):
    WS_URL: str                           # 웹소켓 엔드포인트
    WS_CONNECT_TIMEOUT: float = 10.0      # 연결 타임아웃 (초)
    PING_INTERVAL: Optional[float] = None # Ping 간격 (None = ping 없음)
    PING_FAIL_THRESHOLD: int = 2          # 재연결 전 실패 횟수
    RECV_TIMEOUT: Optional[float] = None  # 수신 타임아웃 (None = 타임아웃 없음)
    RECONNECT_MIN: float = 1.0            # 최소 백오프 지연
    RECONNECT_MAX: float = 8.0            # 최대 백오프 지연
    CONNECT_MAX_ATTEMPTS: int = 6         # 최대 연결 재시도
```

### 거래소별 웹소켓 설정

| 거래소 | PING_INTERVAL | RECV_TIMEOUT | 이유 |
|--------|---------------|--------------|------|
| **StandX** | `None` | `None` | ping 시 서버 연결 끊음; 주문 스트림 유휴 |
| Lighter | `None` | `60.0` | 서버가 heartbeat 전송 |
| Backpack | `None` | `90.0` | 서버가 60초마다 ping |
| EdgeX | `None` | `60.0` | 서버 ping, 클라이언트 pong |
| Pacifica | `50.0` | `60.0` | 클라이언트가 ping 전송 필요 |
| Hyperliquid | `None` | `60.0` | recv 타임아웃만 |
| GRVT | 가변 | `60.0` | SDK 내부에서 처리 |

### 재연결 동작

```
1. 연결 끊김
2. 출력: "[Client] connection closed (code=X), reconnecting..."
3. 출력: "[Client] reconnecting in {delay}s... (attempt N)"
4. 지수 백오프로 재연결 시도
5. 성공 시: "[Client] ✓ reconnected successfully"
6. _resubscribe() 호출로 구독 복구
7. 실패 시: 지연 증가 후 재시도 (RECONNECT_MAX까지)
```

---

## 인증 방식

### 타입 1: EVM 서명 (StandX, Hyperliquid)

```python
# 인증 정보 구조
{
    "wallet_address": "0x...",
    "evm_private_key": "0x...",  # 또는 "wallet_private_key"
}

# 서명 패턴
from eth_account import Account
signed = Account.sign_message(encode_defunct(text=message), private_key)
signature = signed.signature.hex()
```

### 타입 2: StarkNet 서명 (EdgeX, Paradex)

```python
# 인증 정보 구조
{
    "account_id": str,
    "private_key": "0x...",  # StarkNet 프라이빗 키
}

# 서명 패턴
from starkware.crypto.signature.signature import sign
r, s = sign(msg_hash=message_hash, priv_key=private_key)
```

### 타입 3: NaCl 서명 (Backpack)

```python
# 인증 정보 구조
{
    "api_key": str,
    "secret_key": str,  # Base64 인코딩
}

# 서명 패턴
from nacl.signing import SigningKey
signing_key = SigningKey(base64.b64decode(secret_key)[:32])
signature = signing_key.sign(message.encode())
```

### 타입 4: Solana 서명 (Pacifica)

```python
# 인증 정보 구조
{
    "public_key": str,
    "agent_public_key": str,
    "agent_private_key": str,  # Base58 문자열
}

# 서명 패턴
from solders.keypair import Keypair
keypair = Keypair.from_base58_string(private_key)
signature = keypair.sign_message(message.encode())
```

### 타입 5: 세션 쿠키 (Variational, TreadFi)

```python
# 인증 정보 구조
{
    "session_cookies": {"vr-token": "..."},
}

# 요청 패턴
from curl_cffi.requests import AsyncSession
session.cookies.update(session_cookies)
```

---

## 공통 패턴

### 패턴 1: 표준 사용법

```python
from mpdex import create_exchange, symbol_create

async def trade():
    # 초기화
    exchange = await create_exchange("standx", {
        "wallet_address": "0x...",
        "chain": "bsc",
        "evm_private_key": "0x...",
    })

    try:
        symbol = symbol_create("standx", "BTC")

        # 읽기 작업
        price = await exchange.get_mark_price(symbol)
        position = await exchange.get_position(symbol)
        collateral = await exchange.get_collateral()

        # 쓰기 작업
        await exchange.create_order(symbol, "buy", 0.01, order_type="market")
        await exchange.close_position(symbol)

    finally:
        await exchange.close()
```

### 패턴 2: 웹소켓 데이터 접근

```python
# 초기화 후, WS 클라이언트가 데이터 캐싱
if exchange.ws_client:
    # 데이터 대기
    await exchange.ws_client.wait_price_ready(symbol, timeout=5.0)

    # 캐시된 데이터 가져오기 (await 없음 - 동기 접근)
    price = exchange.ws_client.get_mark_price(symbol)
    orderbook = exchange.ws_client.get_orderbook(symbol)
```

### 패턴 3: 에러 처리

```python
try:
    result = await exchange.create_order(...)
except ValueError as e:
    # 잘못된 파라미터 (심볼, 수량 등)
    print(f"잘못된 주문: {e}")
except RuntimeError as e:
    # API/연결 에러
    print(f"API 에러: {e}")
except asyncio.TimeoutError:
    # 작업 타임아웃
    print("요청 시간 초과")
```

### 패턴 4: 다중 거래소

```python
async def arbitrage():
    ex1 = await create_exchange("lighter", LIGHTER_KEY)
    ex2 = await create_exchange("standx", STANDX_KEY)

    try:
        # 병렬 가격 조회
        prices = await asyncio.gather(
            ex1.get_mark_price(symbol_create("lighter", "BTC")),
            ex2.get_mark_price(symbol_create("standx", "BTC")),
        )
    finally:
        await asyncio.gather(ex1.close(), ex2.close())
```

---

## 거래소별 특이사항

### StandX
- **체인:** BSC (바이낸스 스마트 체인)
- **견적 통화:** DUSD (USDC 아님)
- **웹소켓:** 이중 스트림 (마켓 + 주문)
- **Ping:** 비활성화 - 서버가 ping 받으면 연결 끊음
- **주문 응답:** 별도 WS 엔드포인트 (ws-api/v1)
- **인증:** 본문 서명 포함 JWT 토큰

### Hyperliquid
- **서명:** EIP-712 typed data
- **에이전트 지원:** 에이전트 주소에 서명 위임 가능
- **USD 전송:** 반드시 지갑 키 사용 (에이전트 불가)
- **빌더 수수료:** 복잡한 수수료 구조 지원
- **프록시:** HTTP 프록시 지원

### Lighter
- **오더북:** 델타 기반 업데이트
- **인증 토큰:** 10분 만료로 캐싱
- **현물:** 지원 (has_spot=True)
- **재연결:** 60초마다 강제 재연결

### Paradex
- **통합:** CCXT 라이브러리 사용
- **체인:** StarkNet
- **인증:** REST 인증 엔드포인트에서 JWT
- **안정성:** API 변경 시 깨질 수 있음

### Variational
- **웹소켓:** 지원 안 함 (REST만)
- **API:** 프론트엔드 API (UI 변경 시 깨질 수 있음)
- **인증:** curl_cffi로 세션 쿠키
- **요청:** Impersonate로 브라우저 유사 요청

---

## 디버깅 체크리스트

### 연결 문제

1. 거래소별 PING_INTERVAL 설정 확인
2. RECV_TIMEOUT 확인 (너무 짧으면 거짓 연결 끊김)
3. JWT/토큰 만료 확인
4. 네트워크/방화벽 확인

### 주문 문제

1. 심볼 포맷 확인: `symbol_create(exchange, coin)`
2. 최소 주문 수량 확인
3. 담보금 충분한지 확인
4. 마켓 활성화 여부 확인

### 인증 문제

1. 인증 필드가 거래소 요구사항과 일치하는지 확인
2. 키 포맷 확인 (hex 접두사, base64, base58)
3. StandX: JWT 토큰 갱신 확인
4. 에이전트: 에이전트 승인 여부 확인

---

## 코드 위치 참조

| 기능 | 주 파일 | 보조 |
|------|---------|------|
| 팩토리 함수 | `exchange_factory.py:create_exchange()` | |
| 심볼 생성 | `exchange_factory.py:symbol_create()` | |
| 베이스 인터페이스 | `multi_perp_dex.py:MultiPerpDex` | |
| 기본 구현 | `multi_perp_dex.py:MultiPerpDexMixin` | |
| WS 베이스 | `wrappers/base_ws_client.py` | |
| StandX 거래소 | `wrappers/standx.py` | `standx_ws_client.py` |
| StandX 인증 | `wrappers/standx_auth.py` | |
| Hyperliquid | `wrappers/hyperliquid.py` | `mpdex/utils/hyperliquid_base.py` |
| Lighter | `wrappers/lighter.py` | `lighter_ws_client.py` |

---

## 버전 정보

- **Python:** 3.8+ (Windows: 3.10+)
- **메인 브랜치:** master
- **설치:** `pip install "mpdex @ git+https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git@master"`
