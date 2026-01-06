# Multi-Perp-DEX 사용 가이드

> 여러 탈중앙화 거래소(DEX)에서 선물 거래를 할 수 있게 해주는 통합 라이브러리

---

## 이게 뭔가요?

**mpdex**는 여러 DEX에서 선물(perpetual) 거래를 하나의 코드로 할 수 있게 해주는 Python 라이브러리입니다.

### 지원하는 거래소

| 거래소 | 체인 | 특징 |
|--------|------|------|
| Lighter | Lighter Chain | 빠른 속도, 현물 지원 |
| Hyperliquid | Hyperliquid L1 | 가장 인기, 에이전트 지원 |
| Paradex | StarkNet | CCXT 통합 |
| Backpack | Solana | 현물 지원, 정밀 계산 |
| EdgeX | StarkNet | 공개/비공개 WS 분리 |
| Pacifica | Solana | 솔라나 기반 선물 |
| GRVT | GRVT Chain | API 키 기반 |
| Variational | EVM | 프론트엔드 API |
| TreadFi | 다양함 | 브라우저 서명 |
| Superstack | Hyperliquid | API 서명 |
| StandX | BSC | 듀얼 웹소켓 |

---

## 빠른 시작

### 1. 설치

```bash
pip install "mpdex @ git+https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git@master"
```

### 2. 기본 사용법

```python
import asyncio
from mpdex import create_exchange, symbol_create

async def main():
    # 거래소 연결
    exchange = await create_exchange("lighter", {
        "account_id": 0,
        "private_key": "your-private-key",
        "api_key_id": "your-api-key-id",
    })

    # 심볼 생성 (거래소마다 형식이 다름!)
    symbol = symbol_create("lighter", "BTC")

    # 현재 가격 조회
    price = await exchange.get_mark_price(symbol)
    print(f"BTC 가격: {price}")

    # 담보금 조회
    collateral = await exchange.get_collateral()
    print(f"사용 가능: ${collateral['available_collateral']}")

    # 포지션 조회
    position = await exchange.get_position(symbol)
    if position:
        print(f"포지션: {position['side']} {position['size']}")

    # 연결 종료 (중요!)
    await exchange.close()

asyncio.run(main())
```

---

## 주요 기능 설명

### 주문 넣기

```python
# 시장가 롱
await exchange.create_order(
    symbol=symbol,
    side="buy",
    amount=0.01,  # BTC 수량
    order_type="market"
)

# 지정가 숏
await exchange.create_order(
    symbol=symbol,
    side="sell",
    amount=0.01,
    price=100000,  # 지정가
    order_type="limit"
)
```

### 포지션 청산

```python
# 현재 포지션 전체 청산
await exchange.close_position(symbol)
```

### 미체결 주문 조회/취소

```python
# 미체결 주문 조회
open_orders = await exchange.get_open_orders(symbol)

# 모든 미체결 주문 취소
await exchange.cancel_orders(symbol)

# 특정 주문만 취소
await exchange.cancel_orders(symbol, open_orders=[specific_order])
```

### 레버리지 변경

```python
await exchange.update_leverage(symbol, 10)  # 10배 레버리지
```

---

## 심볼 형식 이해하기

**중요!** 거래소마다 심볼 형식이 다릅니다.

```python
from exchange_factory import symbol_create

# 같은 BTC인데 거래소마다 다른 형식
symbol_create("lighter", "BTC")      # → "BTC"
symbol_create("standx", "BTC")       # → "BTC-USD"
symbol_create("paradex", "BTC")      # → "BTC-USD-PERP"
symbol_create("grvt", "BTC")         # → "BTC_USDT_Perp"
symbol_create("backpack", "BTC")     # → "BTC_USDC_PERP"
symbol_create("edgex", "BTC")        # → "BTCUSD"
```

### 현물 거래 (지원하는 거래소만)

```python
# 현물 심볼
symbol_create("lighter", "ETH", is_spot=True, quote="USDC")  # → "ETH/USDC"
symbol_create("backpack", "BTC", is_spot=True, quote="USDC") # → "BTC_USDC"
```

---

## 거래소별 특이사항

### StandX

**웹소켓 ping 주의!**
- StandX는 클라이언트가 ping을 보내면 서버에서 연결을 끊어버립니다
- 그래서 `PING_INTERVAL = None`으로 설정되어 있습니다

**듀얼 웹소켓:**
- 시장 데이터용 (가격, 오더북)
- 주문 확인용 (별도 엔드포인트)

```python
# StandX 초기화
exchange = await create_exchange("standx", {
    "wallet_address": "0x...",
    "chain": "bsc",
    "evm_private_key": "0x...",
})
```

### Hyperliquid

**에이전트 vs 직접 서명:**
```python
# 에이전트 사용 (권장)
exchange = await create_exchange("hyperliquid", {
    "wallet_address": "0x...",
    "agent_api_address": "0x...",
    "agent_api_private_key": "0x...",
    "by_agent": True,
})

# 직접 서명
exchange = await create_exchange("hyperliquid", {
    "wallet_address": "0x...",
    "wallet_private_key": "0x...",
    "by_agent": False,
})
```

**주의:** USD 송금은 반드시 지갑으로 직접 서명해야 합니다 (에이전트 불가)

### Variational

- REST API만 지원 (웹소켓 없음)
- 프론트엔드 API 사용 (UI 변경 시 깨질 수 있음)
- 세션 쿠키 필요

### TreadFi

- 브라우저를 통한 서명 필요
- 로그인 시 HTML UI가 열림

---

## 웹소켓 연결 관리

### 연결 상태 확인

```python
if exchange.ws_client and exchange.ws_client.connected:
    print("웹소켓 연결됨")
```

### 수동 재연결

```python
await exchange.ws_client.connect()
```

### 연결 끊김 시 동작

1. 자동 재연결 시도 (exponential backoff)
2. 기존 구독 자동 복구
3. 인증 자동 재시도

**로그 메시지 예시:**
```
[StandXWSClient] connection closed (code=1006), reconnecting...
[StandXWSClient] reconnecting in 0.2s... (attempt 1)
[StandXWSClient] attempting reconnect...
[StandXWSClient] ✓ reconnected successfully
[StandXWSClient] ✓ Reconnected, resubscribing...
[StandXWSClient] ✓ Re-authenticated
[StandXWSClient] ✓ Resubscribed: 1 price, 1 orderbook
```

---

## 자주 묻는 질문

### Q: 연결이 자꾸 끊겨요

**A: 거래소마다 다릅니다**

1. **StandX**: ping을 보내면 안 됩니다 → `PING_INTERVAL = None`
2. **조용한 마켓**: 데이터가 안 와서 타임아웃 → `RECV_TIMEOUT` 늘리기
3. **네트워크 문제**: 자동 재연결됩니다

### Q: 심볼을 못 찾아요

**A: `symbol_create()` 사용하세요**

```python
# 잘못된 방법
await exchange.get_mark_price("BTC")  # ❌ 거래소마다 다름

# 올바른 방법
symbol = symbol_create("standx", "BTC")  # "BTC-USD"
await exchange.get_mark_price(symbol)    # ✅
```

### Q: 메모리 누수가 있는 것 같아요

**A: `close()` 호출하세요**

```python
try:
    # 거래 로직
    pass
finally:
    await exchange.close()  # 반드시 호출!
```

### Q: 주문이 안 들어가요

**A: 확인사항**
1. 담보금 충분한지
2. 심볼 형식 맞는지
3. 최소 주문 수량 이상인지
4. 레버리지 설정됐는지

---

## 반환값 형식

### get_position()

```python
{
    "symbol": "BTC-USD",
    "side": "long",  # "long" 또는 "short"
    "size": "0.01",
    "entry_price": "95000",
    "mark_price": "96000",
    "unrealized_pnl": "10.5",
    "leverage": "10",
}
```

### get_collateral()

```python
{
    "available_collateral": 1000.0,  # 사용 가능 금액
    "total_collateral": 1500.0,      # 총 담보금
    "equity": 1520.5,                # 자산 (미실현 포함)
    "upnl": 20.5,                    # 미실현 손익
}
```

### get_open_orders()

```python
[
    {
        "id": "123456",
        "symbol": "BTC-USD",
        "side": "buy",
        "size": 0.01,
        "price": 90000,
    },
    # ...
]
```

---

## 팁

### 1. 비동기 컨텍스트 관리

```python
async with exchange:  # close() 자동 호출
    await exchange.create_order(...)
```
*주의: 모든 거래소가 지원하지는 않음*

### 2. 여러 거래소 동시 사용

```python
async def main():
    lighter = await create_exchange("lighter", LIGHTER_KEY)
    standx = await create_exchange("standx", STANDX_KEY)

    # 동시에 가격 조회
    prices = await asyncio.gather(
        lighter.get_mark_price(symbol_create("lighter", "BTC")),
        standx.get_mark_price(symbol_create("standx", "BTC")),
    )

    await lighter.close()
    await standx.close()
```

### 3. 에러 핸들링

```python
try:
    await exchange.create_order(symbol, "buy", 0.01)
except Exception as e:
    print(f"주문 실패: {e}")
    # 에러 유형별 처리
```
