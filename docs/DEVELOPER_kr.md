# Multi-Perp-DEX 개발자 문서

> **mpdex** - 여러 탈중앙화 선물 거래소(DEX)를 위한 통합 비동기 Python 래퍼

## 목차

1. [아키텍처 개요](#아키텍처-개요)
2. [핵심 디자인 패턴](#핵심-디자인-패턴)
3. [거래소별 구현](#거래소별-구현)
4. [웹소켓 시스템](#웹소켓-시스템)
5. [심볼 포맷 참조](#심볼-포맷-참조)
6. [인증 방식](#인증-방식)
7. [새 거래소 추가하기](#새-거래소-추가하기)
8. [문제 해결](#문제-해결)

---

## 아키텍처 개요

### 프로젝트 구조

```
multi-perp-dex/
├── multi_perp_dex.py          # 추상 베이스 클래스
├── exchange_factory.py         # 팩토리 패턴 + 심볼 매핑
├── mpdex/                      # 공개 API 패키지
│   ├── __init__.py            # 지연 로딩 exports
│   └── utils/                 # 공유 유틸리티
│       ├── hyperliquid_base.py
│       ├── common_hyperliquid.py
│       └── common_pacifica.py
├── wrappers/                   # 거래소별 구현
│   ├── base_ws_client.py      # 추상 웹소켓 베이스
│   ├── [거래소].py            # REST + 비즈니스 로직
│   ├── [거래소]_ws_client.py  # 웹소켓 클라이언트
│   └── [거래소]_auth.py       # 인증 헬퍼 (일부 거래소)
├── keys/                       # 인증 정보 템플릿 (gitignored)
└── test_exchanges/             # 예제 스크립트
```

### 의존성 흐름

```
사용자 코드
    │
    ▼
mpdex/__init__.py (지연 로딩)
    │
    ▼
exchange_factory.py
    ├── create_exchange() ──▶ 거래소 래퍼
    └── symbol_create()   ──▶ 정규화된 심볼
                                    │
                                    ▼
                            wrappers/[거래소].py
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            REST API (aiohttp)              웹소켓 클라이언트
                                        (wrappers/base_ws_client.py)
```

---

## 핵심 디자인 패턴

### 1. 추상 베이스 클래스 패턴

**파일:** `multi_perp_dex.py`

```python
class MultiPerpDex(ABC):
    """모든 거래소가 구현해야 하는 추상 인터페이스"""

    def __init__(self):
        self.has_spot = False
        self.available_symbols = {}
        self.ws_supported = {
            "get_mark_price": False,
            "get_position": False,
            "get_open_orders": False,
            "get_collateral": False,
            "get_orderbook": False,
            "create_order": False,
            "cancel_orders": False,
            "update_leverage": False,
        }

    @abstractmethod
    async def create_order(self, symbol, side, amount, price=None, order_type='market'): ...

    @abstractmethod
    async def get_position(self, symbol): ...

    @abstractmethod
    async def close_position(self, symbol, position): ...

    @abstractmethod
    async def get_collateral(self): ...

    @abstractmethod
    async def get_open_orders(self, symbol): ...

    @abstractmethod
    async def cancel_orders(self, symbol, open_orders=None): ...

    @abstractmethod
    async def get_mark_price(self, symbol): ...

    @abstractmethod
    async def update_leverage(self, symbol, leverage): ...

    @abstractmethod
    async def get_available_symbols(self): ...

    @abstractmethod
    async def close(self): ...
```

**공통 구현을 위한 Mixin:**

```python
class MultiPerpDexMixin:
    """공통 작업의 기본 구현"""

    async def close_position(self, symbol, position=None):
        if position is None:
            position = await self.get_position(symbol)
        if not position:
            return None
        size = position.get('size')
        side = 'sell' if position.get('side').lower() in ['long','buy'] else 'buy'
        return await self.create_order(symbol, side, size, price=None,
                                       order_type='market', is_reduce_only=True)
```

### 2. 지연 로딩 팩토리 패턴

**파일:** `exchange_factory.py`

```python
def _load(exchange_name: str):
    """필요할 때만 거래소 클래스를 지연 로딩"""
    if exchange_name == "lighter":
        from wrappers.lighter import LighterExchange
        return LighterExchange
    elif exchange_name == "standx":
        from wrappers.standx import StandXExchange
        return StandXExchange
    # ... 다른 거래소들

async def create_exchange(exchange_platform: str, key_params: dict):
    """거래소 인스턴스 생성 팩토리 함수"""
    ExchangeClass = _load(exchange_platform)

    if exchange_platform == "lighter":
        ex = ExchangeClass(
            account_id=key_params["account_id"],
            private_key=key_params["private_key"],
            api_key_id=key_params["api_key_id"],
        )
    # ... 다른 거래소 처리

    await ex.init()  # 비동기 초기화
    return ex
```

**장점:**
- 무거운 의존성(cairo-lang, grvt-pysdk 등)은 사용할 때만 로딩
- 단일 거래소 사용 시 빠른 시작
- 메모리 효율성

### 3. 웹소켓 풀 패턴

```python
class StandXWSPool:
    """공유 웹소켓 연결을 위한 싱글톤 풀"""

    def __init__(self):
        self._clients: Dict[str, StandXWSClient] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, wallet_address: str, jwt_token: str = None) -> StandXWSClient:
        key = wallet_address.lower()
        async with self._lock:
            if key in self._clients:
                client = self._clients[key]
                if not client._running:
                    await client.connect()
                return client

            client = StandXWSClient(jwt_token=jwt_token)
            await client.connect()
            self._clients[key] = client
            return client

# 전역 싱글톤
WS_POOL = StandXWSPool()
```

**사용 거래소:** Lighter, Backpack, GRVT, Paradex, Pacifica, StandX

---

## 거래소별 구현

### 빠른 참조 테이블

| 거래소 | 파일 | 인증 방식 | WS 지원 | 특수 기능 |
|--------|------|-----------|---------|-----------|
| Lighter | `lighter.py` | SDK + API 키 | 전체 | 델타 오더북, 현물 |
| GRVT | `grvt.py` | API 키 | 일부 | 콜백→캐시 WS |
| Paradex | `paradex.py` | StarkNet | 일부 | CCXT 통합 |
| Hyperliquid | `hyperliquid.py` | EIP-712 | 전체 | 멀티 DEX, 에이전트 서명 |
| Backpack | `backpack.py` | NaCl | 일부 | 현물, 소수점 정밀도 |
| EdgeX | `edgex.py` | StarkNet | 일부 | 이중 WS (공개/비공개) |
| Pacifica | `pacifica.py` | Solana | 전체 | JSON 메시지 서명 |
| Variational | `variational.py` | 쿠키 | 없음 | 프론트엔드 API |
| TreadFi HL | `treadfi_hl.py` | 브라우저 | 일부 | HTML UI 서명 |
| TreadFi PC | `treadfi_pc.py` | 브라우저 | 일부 | TreadFi + Pacifica |
| Superstack | `superstack.py` | API | 전체 | HyperliquidBase 서브클래스 |
| StandX | `standx.py` | EVM | 전체 | 이중 WS 스트림 |

### 거래소별 특이사항

#### Lighter
```python
# 인증 토큰 캐싱 (10분 만료)
self._token_cache = {
    'token': None,
    'expires_at': 0
}

# 현물 거래 지원
self.has_spot = True
symbol = symbol_create("lighter", "ETH/USDC", is_spot=True)  # "ETH/USDC"
```

#### Hyperliquid
```python
# 이중 서명 모드
if self.by_agent:
    signature = sign_l1_action(agent_private_key, ...)
else:
    signature = sign_l1_action(wallet_private_key, ...)

# USD 전송은 반드시 지갑 키 사용 (에이전트 불가)
signature = sign_user_signed_action(wallet_private_key, ...)
```

#### StandX
```python
# 이중 웹소켓 스트림
ws_client         # 마켓 스트림: 가격, 오더북, 포지션, 잔고
order_ws_client   # 주문 스트림: 주문 확인 (별도 엔드포인트)

# 중요: ping 비활성화 필수!
PING_INTERVAL = None  # 서버가 ping 받으면 연결 끊음
RECV_TIMEOUT = None   # 주문 스트림이 오래 유휴 상태일 수 있음
```

#### Variational
```python
# 프론트엔드 API - UI 변경 시 깨질 수 있음
# 브라우저 유사 요청을 위해 curl_cffi 사용
from curl_cffi.requests import AsyncSession

# 세션 쿠키 필요
session_cookies = {"vr-token": "..."}
```

---

## 웹소켓 시스템

### 베이스 웹소켓 클라이언트

**파일:** `wrappers/base_ws_client.py`

```python
class BaseWSClient(ABC):
    # 설정 (서브클래스에서 오버라이드)
    WS_URL: str = ""
    WS_CONNECT_TIMEOUT: float = 10.0
    PING_INTERVAL: Optional[float] = None   # None = ping 비활성화
    PING_FAIL_THRESHOLD: int = 2
    RECV_TIMEOUT: Optional[float] = None    # None = 타임아웃 없음
    RECONNECT_MIN: float = 1.0
    RECONNECT_MAX: float = 8.0
    CONNECT_MAX_ATTEMPTS: int = 6

    # 추상 메서드 (반드시 구현)
    @abstractmethod
    async def _handle_message(self, data: Dict) -> None: ...

    @abstractmethod
    async def _resubscribe(self) -> None: ...

    @abstractmethod
    def _build_ping_message(self) -> Optional[str]: ...
```

### 거래소별 Ping/Pong 설정

| 거래소 | PING_INTERVAL | RECV_TIMEOUT | 비고 |
|--------|---------------|--------------|------|
| **StandX** | `None` | `None` | **서버가 ping 받으면 연결 끊음!** |
| Lighter | `None` | `60.0` | 서버가 주기적으로 ping 전송 |
| Backpack | `None` | `90.0` | 서버가 60초마다 ping |
| EdgeX | `None` | `60.0` | 서버 ping에 응답 필요 |
| Pacifica | `50.0` | `60.0` | 클라이언트가 `{"channel": "ping"}` 전송 |
| Hyperliquid | `None` | `60.0` | recv 타임아웃 시 재연결 |
| GRVT | 가변 | `60.0` | pysdk 내부에서 처리 |

### 재연결 전략

```python
async def _reconnect_with_backoff(self) -> None:
    delay = self.RECONNECT_MIN  # 0.2~1.0초로 시작
    attempt = 0

    while self._running:
        attempt += 1
        print(f"reconnecting in {delay:.1f}s... (attempt {attempt})")
        await asyncio.sleep(delay)

        if await self._do_reconnect():
            print("✓ reconnected successfully")
            return

        # 지터 포함 지수 백오프
        delay = min(self.RECONNECT_MAX, delay * 2.0) + random.uniform(0, 0.5)
```

### 프록시 지원

```python
# 웹소켓용 HTTP CONNECT 터널
client = BaseWSClient(proxy="http://user:pass@proxy.example.com:8080")

# 내부 동작:
# 1. 프록시에 연결
# 2. HTTP CONNECT 요청 전송
# 3. 터널 위에서 웹소켓으로 업그레이드
```

---

## 심볼 포맷 참조

### 선물 심볼

```python
SYMBOL_FORMATS = {
    "lighter":            lambda coin, _: coin,                    # "BTC"
    "grvt":               lambda coin, _: f"{coin}_USDT_Perp",     # "BTC_USDT_Perp"
    "paradex":            lambda coin, _: f"{coin}-USD-PERP",      # "BTC-USD-PERP"
    "edgex":              lambda coin, _: f"{coin}USD",            # "BTCUSD"
    "backpack":           lambda coin, _: f"{coin}_USDC_PERP",     # "BTC_USDC_PERP"
    "treadfi.hyperliquid": lambda coin, _: f"{coin}:PERP-USDC",    # "BTC:PERP-USDC"
    "variational":        lambda coin, _: coin,                    # "BTC"
    "pacifica":           lambda coin, _: coin,                    # "BTC"
    "hyperliquid":        lambda coin, _: coin,                    # "BTC"
    "superstack":         lambda coin, _: coin,                    # "BTC"
    "standx":             lambda coin, _: f"{coin}-USD",           # "BTC-USD"
}
```

### 현물 심볼 (지원 거래소만)

```python
SPOT_SYMBOL_FORMATS = {
    "backpack":    lambda coin, quote: f"{coin}_{quote}",    # "BTC_USDC"
    "lighter":     lambda coin, quote: f"{coin}/{quote}",    # "BTC/USDC"
    "hyperliquid": lambda coin, quote: f"{coin}/{quote}",    # "BTC/USDC"
    "edgex":       lambda coin, quote: f"{coin}/{quote}",    # "BTC/USDC"
}
```

### 사용법

```python
from exchange_factory import symbol_create

# 선물
symbol = symbol_create("standx", "BTC")           # "BTC-USD"
symbol = symbol_create("paradex", "ETH")          # "ETH-USD-PERP"
symbol = symbol_create("grvt", "SOL")             # "SOL_USDT_Perp"

# 현물
symbol = symbol_create("lighter", "ETH", is_spot=True, quote="USDC")  # "ETH/USDC"
symbol = symbol_create("backpack", "BTC", is_spot=True, quote="USDC") # "BTC_USDC"
```

---

## 인증 방식

### EVM 기반 서명

```python
# Hyperliquid - EIP-712
from eth_account import Account
from eth_account.messages import encode_typed_data

def sign_l1_action(private_key, action, nonce, vault_address=None):
    typed_data = {
        "domain": {"name": "Exchange", ...},
        "message": {"action": action, "nonce": nonce, ...},
        ...
    }
    signed = Account.sign_typed_data(private_key, typed_data)
    return signed.signature.hex()

# StandX - 단순 EVM 서명
def sign_request(self, body: str) -> dict:
    message = f"{timestamp}{body}"
    signed = Account.sign_message(encode_defunct(text=message), self.private_key)
    return {"x-request-signature": signed.signature.hex()}
```

### StarkNet 서명

```python
# EdgeX, Paradex
from starkware.crypto.signature.signature import sign

def stark_sign(private_key: int, message_hash: int) -> tuple:
    r, s = sign(msg_hash=message_hash, priv_key=private_key)
    return (r, s)
```

### NaCl 서명 (Backpack)

```python
from nacl.signing import SigningKey
import base64

secret_bytes = base64.b64decode(secret_key)
signing_key = SigningKey(secret_bytes[:32])
signature = signing_key.sign(message.encode())
```

### Solana 서명 (Pacifica)

```python
from solders.keypair import Keypair
import base58

keypair = Keypair.from_base58_string(private_key)
signature = keypair.sign_message(message.encode())
signature_b58 = base58.b58encode(bytes(signature)).decode()
```

### 세션 기반 (Variational, TreadFi)

```python
# Variational
from curl_cffi.requests import AsyncSession

session = AsyncSession()
session.cookies.update(session_cookies)  # {"vr-token": "..."}
```

---

## 새 거래소 추가하기

### 1단계: 래퍼 생성

```python
# wrappers/myexchange.py
from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin

class MyExchange(MultiPerpDexMixin, MultiPerpDex):
    def __init__(self, api_key: str, secret: str):
        super().__init__()
        self.api_key = api_key
        self.secret = secret
        self.has_spot = False

    async def init(self):
        """비동기 초기화"""
        await self._load_markets()
        return self

    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        # 구현
        pass

    # ... 모든 추상 메서드 구현

    async def close(self):
        """리소스 정리"""
        if self.session:
            await self.session.close()
```

### 2단계: 팩토리에 추가

```python
# exchange_factory.py

def _load(exchange_name):
    # ...
    elif exchange_name == "myexchange":
        from wrappers.myexchange import MyExchange
        return MyExchange

# 심볼 포맷 추가
SYMBOL_FORMATS["myexchange"] = lambda coin, _: f"{coin}-PERP"

async def create_exchange(exchange_platform, key_params):
    # ...
    elif exchange_platform == "myexchange":
        ex = ExchangeClass(
            api_key=key_params["api_key"],
            secret=key_params["secret"],
        )
```

### 3단계: 인증 정보 템플릿 생성

```python
# keys/copy.pk_myexchange.py
MYEXCHANGE_KEY = {
    "api_key": "your-api-key",
    "secret": "your-secret",
}
```

### 4단계: 지연 로딩 추가 (선택)

```python
# mpdex/__init__.py
def __getattr__(name):
    if name == "MyExchange":
        from wrappers.myexchange import MyExchange
        return MyExchange
    # ...
```

---

## 문제 해결

### 웹소켓 문제

**문제: 연결이 계속 끊김**
```python
# 거래소별 ping 동작 확인
# StandX: ping 보내면 안 됨 (서버가 연결 끊음)
PING_INTERVAL = None
RECV_TIMEOUT = None  # 주문 스트림이 유휴 상태일 수 있음
```

**문제: 조용한 마켓에서 recv 타임아웃**
```python
# 타임아웃 늘리거나 비활성화
RECV_TIMEOUT = 300.0  # 5분
# 또는
RECV_TIMEOUT = None   # 타임아웃 없음 (TCP keepalive 의존)
```

**문제: 429 속도 제한**
```python
# 내장된 지수 백오프가 자동 처리
# 로그에서 "429 rate limit, retry in Xs" 확인
```

### 인증 문제

**문제: 재연결 후 StandX 인증 실패**
```
[StandXWSClient] ✗ Auth failed after reconnect
```
- JWT 토큰이 만료됐을 수 있음
- 세션 갱신 필요 여부 확인

**문제: Hyperliquid 서명 실패**
```
# 올바른 서명 방법 사용 확인
if transferring_usd:
    # 반드시 지갑 프라이빗 키 사용, 에이전트 불가
    sign_user_signed_action(wallet_private_key, ...)
```

### 심볼 문제

**문제: 알 수 없는 심볼 오류**
```python
# 거래소별 심볼 포맷 확인
symbol = symbol_create("standx", "BTC")  # "BTC-USD"
symbol = symbol_create("paradex", "BTC") # "BTC-USD-PERP"

# 사용 가능한 심볼 확인
symbols = await exchange.get_available_symbols()
print(symbols["perp"])
```

### 메모리/리소스 문제

**문제: 연결이 제대로 종료되지 않음**
```python
# 항상 close() 호출
try:
    # ... 거래 로직
finally:
    await exchange.close()
```

---

## 부록

### 환경 요구사항

- Python 3.8+ (Windows는 fastecdsa 때문에 3.10 필요)
- `cairo-lang` 설치에 상당한 시간 소요
- 메인 브랜치: `master`

### 설치

```bash
# Git에서 설치
pip install "mpdex @ git+https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git@master"

# 개발용
git clone https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git
cd multi-perp-dex
pip install -e .
```

### 테스트 실행

```bash
# 개별 거래소 테스트
python test_exchanges/test_lighter.py
python test_exchanges/test_standx.py

# 메인 애플리케이션
python main.py --module check   # 담보금, 포지션 확인
python main.py --module order   # 주문 생성
python main.py --module close   # 포지션 종료
```
