# mpdex: Multi Perp DEX 비동기 통합 래퍼

여러 파생상품 거래소(Paradex, Edgex, Lighter, GRVT, Backpack)를 하나의 공통 인터페이스로 사용하기 위한 파이썬 비동기(Async) 래퍼입니다.  
핵심 인터페이스를 따르는 각 거래소별 구현을 제공하며, 문자열 한 줄로 인스턴스를 만드는 공장 함수(create_exchange)와 심볼 헬퍼(symbol_create)를 포함합니다.

---

## 지원 거래소

- Lighter (lighter-sdk)
- GRVT (grvt-pysdk)
- Paradex (ccxt.async_support.paradex)
- Edgex (직접 서명 구현)
- Backpack (공식 REST)
- TreadFi (프론트 api 사용) / login, logout, create_order 가능
- Variational (프론트 api 사용)
- Pacifica (공식 api)
- Hyperliquid (공식 api)
  - price / position 조회: 웹소켓사용, 여러 instance를 만들어도 WS_POOL 공통모듈로 통신
  - 주문: rest api
- Superstack
  - hyperliquid 이지만, 주문관련 endpoint는 superstack wallet api로 생성
  - price / position 조회: Hyperliquid WS_POOL 공통모듈 사용

---

## 요구 사항

- Python 3.8 이상 / **Windows 사용시 3.10 고정 (fastecdsa library때문에)**
- 리눅스/맥OS 권장(Windows에서도 동작 가능하나 일부 의존성 빌드 시간이 길 수 있음)
- pip 최신 버전 권장

---

## 설치

GitHub 원격에서 바로 설치합니다. 이 레포의 기본 브랜치는 `master`입니다.

```bash
# 가상환경(권장)
python -m venv .venv
source .venv/bin/activate

# 설치
pip install "mpdex @ git+https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git@master"

# 최신화(업그레이드)
pip install -U "mpdex @ git+https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git@master"
```

설치 시 포함되는 주요 런타임 의존성:
- aiohttp, pynacl, ccxt, eth-hash
- lighter-sdk(깃 리포에서 설치), grvt-pysdk
- cairo-lang(설치에 시간이 걸릴 수 있음)

> 팁: `pip --version`이 낮으면 VCS(깃) 의존성 설치가 실패할 수 있습니다. `pip install --upgrade pip`로 갱신하세요.

---

## 디렉터리 구조(요약)

```text
wrappers/               # 거래소별 래퍼 구현
  backpack.py
  edgex.py
  grvt.py
  lighter.py
  paradex.py
  treadfi_hl.py
  treadfi_login.html
  variational_auth.py
  variational.py
  pacifica.py
  hyperliquid_ws_client.py # 웹소켓
  hyperliquid.py
mpdex/__init__.py       # 공개 API(지연 임포트), create_exchange/symbol_create 노출
multi_perp_dex.py       # 공통 인터페이스(추상 클래스) 및 Mixin
exchange_factory.py     # 문자열→래퍼 매핑, 지연 임포트 및 심볼 생성
keys/                   # 키 템플릿(copy.pk_*.py)
test_exchanges/         # 예제 스크립트 수준의 테스트
pyproject.toml
```

---

## 키(자격증명) 준비

키 템플릿 파일을 복사해 값을 채워주세요. 실제 값은 각 거래소 웹사이트/콘솔에서 발급받아 입력합니다.

```bash
cp keys/copy.pk_lighter.py  keys/pk_lighter.py
cp keys/copy.pk_grvt.py     keys/pk_grvt.py
cp keys/copy.pk_paradex.py  keys/pk_paradex.py
cp keys/copy.pk_edgex.py    keys/pk_edgex.py
cp keys/copy.pk_backpack.py keys/pk_backpack.py
cp keys/copy.pk_treadfi_hl.py keys/pk_treadfi_hl.py
cp keys/copy.pk_variational.py keys/variational.py
cp keys/copy.pk_pacifica.py keys/pacifica.py
```

템플릿은 아래와 같이 Dataclass로 정의되어 있으며, `exchange_factory.create_exchange()`가 요구하는 필드명을 그대로 사용합니다.

- Lighter: account_id(int), private_key(str), api_key_id(int), l1_address(str)
- GRVT: api_key(str), account_id(str), secret_key(str)
- Paradex: wallet_address(str), paradex_address(str), paradex_private_key(str)
- Edgex: account_id(str), private_key(str)
- Backpack: api_key(str), secret_key(str)
- Tread.fi: session_cookies(dick, optional), evm_private_key(str, optional), main_wallet_address(str, required), sub_wallet_address(str, required), account_name(str, required)
  - Tread.fi의 sub_wallet_address는 sub-account의 주소이며, 쓰지 않는 경우 main_wallet_address와 동일하게 작성하면 됩니다. session cookies를 알고 있다면, 별도의 로그인 절차가 필요 없습니다.
- Variational: evm_wallet_address(str, required), session_cookies(dict, optional), evm_private_key(str, optional)
  - Variational: vr-token을 알고 있다면 별도의 로그인 절차가 필요 없습니다.
- Pacifica: public_key(str), agent_public_key(str), agent_private_key(str)

---

## 심볼 규칙

거래소마다 심볼(종목) 표기가 다릅니다. 아래 규칙을 따르거나, `symbol_create(exchange, coin)`를 사용하세요.

- Paradex: `f"{COIN}-USD-PERP"` (예: BTC-USD-PERP)
- Edgex: `f"{COIN}USDT"` (예: BTCUSDT)
- GRVT: `f"{COIN}_USDT_Perp"` (예: BTC_USDT_Perp)
- Backpack: `f"{COIN}_USDC_PERP"` (예: BTC_USDC_PERP)
- Lighter: 코인 심볼 그대로(예: BTC)
- TreadFi: `f"{COIN}:PERP-USDC"` 덱스 사용시, `f"{DEX}_{COIN}:PERP-USDC"`, 스팟 현재 미지원
- Variational: `f"{COIN}"`

```python
from mpdex import symbol_create
symbol = symbol_create("grvt", "BTC")  # "BTC_USDT_Perp"
```

---

## 빠른 시작: 공장 함수로 간단 사용

`create_exchange(exchange_name, key_params)`로 바로 인스턴스를 생성합니다. 모든 API는 비동기입니다.

```python
# example_lighter.py
import asyncio
from mpdex import create_exchange, symbol_create
from keys.pk_lighter import LIGHTER_KEY  # 위에서 복사/작성한 파일

async def main():
    # Lighter 예시(설치 시 기본 의존성에 lighter-sdk가 포함되어 있음)
    ex = await create_exchange("lighter", LIGHTER_KEY)  # 내부에서 시장 메타데이터 초기화 수행
    symbol = symbol_create("lighter", "BTC")

    # 담보 조회
    print(await ex.get_collateral())

    # 포지션 조회
    print(await ex.get_position(symbol))

    # 마켓 주문 예시
    # print(await ex.create_order(symbol, side="buy", amount=0.001))

    # 지정가 주문 예시
    # print(await ex.create_order(symbol, side="sell", amount=0.001, price=85000))

    # 열려있는 주문
    # print(await ex.get_open_orders(symbol))

    # 주문 취소
    # print(await ex.cancel_orders(symbol))

    await ex.close()

if __name__ == "__main__":
    asyncio.run(main())
```

실행:
```bash
python example_lighter.py
```

---

## 직접 사용: 특정 래퍼 클래스를 import

원하면 개별 거래소 래퍼를 직접 가져와 세부 제어를 할 수 있습니다.

```python
# example_direct_lighter.py
import asyncio
from mpdex import LighterExchange
from keys.pk_lighter import LIGHTER_KEY

async def main():
    ex = LighterExchange(
        account_id=LIGHTER_KEY.account_id,
        private_key=LIGHTER_KEY.private_key,
        api_key_id=LIGHTER_KEY.api_key_id,
        l1_address=LIGHTER_KEY.l1_address,
    )
    await ex.initialize()
    await ex.initialize_market_info()

    print(await ex.get_collateral())
    print(await ex.get_position("BTC"))
    await ex.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 공통 인터페이스(API)

모든 거래소 래퍼는 동일한 추상 인터페이스를 구현합니다.  
`multi_perp_dex.MultiPerpDex`:

- `create_order(symbol, side, amount, price=None, order_type='market')`
- `get_position(symbol)`
- `close_position(symbol, position)` — 포지션 객체를 받아 반대 주문으로 닫음
- `get_collateral()` — 사용 가능/총 담보
- `get_open_orders(symbol)`
- `cancel_orders(symbol, open_orders=None)`
- `close()` — 필요 시 세션 정리

Mixin(`MultiPerpDexMixin`)은 `close_position`과 `get_open_orders`의 기본 구현을 제공합니다.

---

## 거래소별 최소 예제

Lighter:
```python
from mpdex import create_exchange, symbol_create
from keys.pk_lighter import LIGHTER_KEY
import asyncio

async def main():
    ex = await create_exchange("lighter", LIGHTER_KEY)
    symbol = symbol_create("lighter", "BTC")
    print(await ex.get_collateral())
    await ex.close()

asyncio.run(main())
```

GRVT:
```python
from mpdex import create_exchange, symbol_create
from keys.pk_grvt import GRVT_KEY
import asyncio

async def main():
    ex = await create_exchange("grvt", GRVT_KEY)
    symbol = symbol_create("grvt", "BTC")  # "BTC_USDT_Perp"
    print(await ex.get_position(symbol))
    await ex.close()

asyncio.run(main())
```

Paradex:
```python
from mpdex import create_exchange, symbol_create
from keys.pk_paradex import PARADEX_KEY
import asyncio

async def main():
    ex = await create_exchange("paradex", PARADEX_KEY)
    symbol = symbol_create("paradex", "BTC")  # "BTC-USD-PERP"
    print(await ex.get_open_orders(symbol))
    await ex.close()

asyncio.run(main())
```

Edgex:
```python
from mpdex import create_exchange, symbol_create
from keys.pk_edgex import EDGEX_KEY
import asyncio

async def main():
    ex = await create_exchange("edgex", EDGEX_KEY)
    symbol = symbol_create("edgex", "BTC")  # "BTCUSDT"
    print(await ex.get_collateral())
    await ex.close()

asyncio.run(main())
```

Backpack:
```python
from mpdex import create_exchange, symbol_create
from keys.pk_backpack import BACKPACK_KEY
import asyncio

async def main():
    ex = await create_exchange("backpack", BACKPACK_KEY)
    symbol = symbol_create("backpack", "BTC")  # "BTC_USDC_PERP"
    print(await ex.get_open_orders(symbol))
    await ex.close()

asyncio.run(main())
```

---

## 예제/테스트 스크립트 실행

레포에 포함된 간단한 테스트(예제) 스크립트를 그대로 실행할 수 있습니다.  
실행 전, `keys/pk_*.py` 파일을 올바르게 작성했는지 확인하세요.

```bash
python test_exchanges/test_lighter.py
python test_exchanges/test_grvt.py
python test_exchanges/test_paradex.py
python test_exchanges/test_edgex.py
python test_exchanges/test_backpack.py
python test_exchanges/test_treadfi_hl.py
python test_exchanges/test_variational.py
```

---

## 문제 해결(Troubleshooting)

- Git 브랜치 에러(예: main이 없음)
  - 이 레포는 `master` 브랜치를 사용합니다. 설치 시 `@master`를 지정하세요.
- 의존성 설치 오래 걸림/실패
  - 네트워크 환경(프록시, 방화벽) 또는 VCS(깃) 접근 권한 문제일 수 있습니다. `pip install --upgrade pip` 후 재시도하세요.
- Lighter/GRVT 호출 시 오류
  - 키 값이 정확한지 확인하고, 해당 거래소의 API 콘솔에서 발급받은 값인지 점검하세요.
- 이벤트 루프/비동기 오류
  - 모든 호출은 비동기입니다. `asyncio.run(...)`으로 실행하세요.

---

## 보안 주의

- `keys/pk_*.py` 파일에는 민감 정보가 들어갑니다. 절대 공개 저장소에 커밋하지 마세요.
- 운영 환경에서는 환경변수나 비밀 관리자를 사용해 키를 주입하는 것을 권장합니다.

---

## 라이선스

MIT