# Multi-Perp-DEX LLM Context Document

> This document is optimized for LLM consumption. It provides structured context for understanding and working with the mpdex codebase.

---

## SYSTEM OVERVIEW

**Project Name:** mpdex (Multi-Perp-DEX)
**Purpose:** Unified async Python interface for perpetual futures trading across multiple DEXs
**Language:** Python 3.8+ (Windows requires 3.10)
**Pattern:** Factory + Abstract Base Class + WebSocket Pooling

---

## CRITICAL RULES

### Rule 1: Symbol Format
ALWAYS use `symbol_create()` function. Each exchange has unique symbol format.

```python
# CORRECT
symbol = symbol_create("standx", "BTC")  # Returns "BTC-USD"
await exchange.get_mark_price(symbol)

# WRONG - Will fail
await exchange.get_mark_price("BTC")  # Exchange won't recognize
```

### Rule 2: Exchange Initialization
ALWAYS call async `init()` after construction (handled by factory).

```python
# CORRECT - Use factory
exchange = await create_exchange("standx", key_params)

# WRONG - Missing init
exchange = StandXExchange(...)  # Not initialized!
```

### Rule 3: Resource Cleanup
ALWAYS call `close()` when done.

```python
try:
    # trading logic
finally:
    await exchange.close()  # REQUIRED
```

### Rule 4: StandX WebSocket Ping
NEVER enable ping for StandX. Server disconnects if client sends ping.

```python
# In standx_ws_client.py
PING_INTERVAL = None  # MUST be None for StandX
RECV_TIMEOUT = None   # Order stream may be idle
```

### Rule 5: Hyperliquid USD Transfers
USD transfers MUST use wallet private key, not agent.

```python
# USD transfer - MUST use wallet
sign_user_signed_action(wallet_private_key, ...)  # CORRECT

# Regular trading - can use agent
sign_l1_action(agent_private_key, ...)  # OK
```

---

## FILE STRUCTURE MAP

```
multi-perp-dex/
├── multi_perp_dex.py         # BASE: Abstract classes
├── exchange_factory.py        # FACTORY: create_exchange(), symbol_create()
├── mpdex/__init__.py         # API: Public exports with lazy loading
├── wrappers/
│   ├── base_ws_client.py     # WS_BASE: Abstract WebSocket client
│   ├── lighter.py            # EXCHANGE: Lighter implementation
│   ├── standx.py             # EXCHANGE: StandX implementation
│   ├── standx_ws_client.py   # WS: StandX WebSocket client
│   ├── hyperliquid.py        # EXCHANGE: Hyperliquid implementation
│   └── ...                   # Other exchanges
└── keys/                     # CONFIG: Credential templates (gitignored)
```

---

## SYMBOL FORMAT TABLE

| Exchange | Format | Example | Function |
|----------|--------|---------|----------|
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

## INTERFACE SPECIFICATION

### MultiPerpDex (Abstract Base)

```python
class MultiPerpDex(ABC):
    has_spot: bool = False
    available_symbols: Dict[str, List[str]] = {}
    ws_supported: Dict[str, bool]  # Which operations support WebSocket

    # REQUIRED IMPLEMENTATIONS
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

### Return Value Formats

**get_position() -> Dict or None:**
```python
{
    "symbol": str,           # Trading pair
    "side": str,             # "long" | "short"
    "size": str,             # Position size (string for precision)
    "entry_price": str,      # Average entry price
    "mark_price": str,       # Current mark price
    "unrealized_pnl": str,   # Unrealized PnL
    "leverage": str,         # Current leverage
    "margin_mode": str,      # "cross" | "isolated"
    "liq_price": str,        # Liquidation price
}
```

**get_collateral() -> Dict:**
```python
{
    "available_collateral": float,  # Available for new positions
    "total_collateral": float,      # Total deposited
    "equity": float,                # Including unrealized PnL
    "upnl": float,                  # Unrealized PnL
}
```

**get_open_orders() -> List[Dict]:**
```python
[
    {
        "id": str,        # Order ID
        "symbol": str,    # Trading pair
        "side": str,      # "buy" | "sell"
        "size": float,    # Order size
        "price": float,   # Order price (None for market)
    },
]
```

---

## WEBSOCKET CONFIGURATION

### BaseWSClient Parameters

```python
class BaseWSClient(ABC):
    WS_URL: str                           # WebSocket endpoint
    WS_CONNECT_TIMEOUT: float = 10.0      # Connection timeout (seconds)
    PING_INTERVAL: Optional[float] = None # Ping interval (None = no ping)
    PING_FAIL_THRESHOLD: int = 2          # Failures before reconnect
    RECV_TIMEOUT: Optional[float] = None  # Receive timeout (None = no timeout)
    RECONNECT_MIN: float = 1.0            # Min backoff delay
    RECONNECT_MAX: float = 8.0            # Max backoff delay
    CONNECT_MAX_ATTEMPTS: int = 6         # Max connection retries
```

### Exchange-Specific WebSocket Settings

| Exchange | PING_INTERVAL | RECV_TIMEOUT | Reason |
|----------|---------------|--------------|--------|
| **StandX** | `None` | `None` | Server disconnects on ping; order stream idle |
| Lighter | `None` | `60.0` | Server sends heartbeat |
| Backpack | `None` | `90.0` | Server pings every 60s |
| EdgeX | `None` | `60.0` | Server pings, client pongs |
| Pacifica | `50.0` | `60.0` | Client must send ping |
| Hyperliquid | `None` | `60.0` | Recv timeout only |
| GRVT | varies | `60.0` | SDK handles internally |

### Reconnection Behavior

```
1. Connection lost
2. Print: "[Client] connection closed (code=X), reconnecting..."
3. Print: "[Client] reconnecting in {delay}s... (attempt N)"
4. Attempt reconnect with exponential backoff
5. On success: "[Client] ✓ reconnected successfully"
6. Call _resubscribe() to restore subscriptions
7. On failure: Retry with increased delay (up to RECONNECT_MAX)
```

---

## AUTHENTICATION METHODS

### Type 1: EVM Signing (StandX, Hyperliquid)

```python
# Credential structure
{
    "wallet_address": "0x...",
    "evm_private_key": "0x...",  # or "wallet_private_key"
}

# Signing pattern
from eth_account import Account
signed = Account.sign_message(encode_defunct(text=message), private_key)
signature = signed.signature.hex()
```

### Type 2: StarkNet Signing (EdgeX, Paradex)

```python
# Credential structure
{
    "account_id": str,
    "private_key": "0x...",  # StarkNet private key
}

# Signing pattern
from starkware.crypto.signature.signature import sign
r, s = sign(msg_hash=message_hash, priv_key=private_key)
```

### Type 3: NaCl Signing (Backpack)

```python
# Credential structure
{
    "api_key": str,
    "secret_key": str,  # Base64-encoded
}

# Signing pattern
from nacl.signing import SigningKey
signing_key = SigningKey(base64.b64decode(secret_key)[:32])
signature = signing_key.sign(message.encode())
```

### Type 4: Solana Signing (Pacifica)

```python
# Credential structure
{
    "public_key": str,
    "agent_public_key": str,
    "agent_private_key": str,  # Base58 string
}

# Signing pattern
from solders.keypair import Keypair
keypair = Keypair.from_base58_string(private_key)
signature = keypair.sign_message(message.encode())
```

### Type 5: Session Cookies (Variational, TreadFi)

```python
# Credential structure
{
    "session_cookies": {"vr-token": "..."},
}

# Request pattern
from curl_cffi.requests import AsyncSession
session.cookies.update(session_cookies)
```

---

## COMMON PATTERNS

### Pattern 1: Standard Usage

```python
from mpdex import create_exchange, symbol_create

async def trade():
    # Initialize
    exchange = await create_exchange("standx", {
        "wallet_address": "0x...",
        "chain": "bsc",
        "evm_private_key": "0x...",
    })

    try:
        symbol = symbol_create("standx", "BTC")

        # Read operations
        price = await exchange.get_mark_price(symbol)
        position = await exchange.get_position(symbol)
        collateral = await exchange.get_collateral()

        # Write operations
        await exchange.create_order(symbol, "buy", 0.01, order_type="market")
        await exchange.close_position(symbol)

    finally:
        await exchange.close()
```

### Pattern 2: WebSocket Data Access

```python
# After initialization, WS client caches data
if exchange.ws_client:
    # Wait for data
    await exchange.ws_client.wait_price_ready(symbol, timeout=5.0)

    # Get cached data (no await - sync access)
    price = exchange.ws_client.get_mark_price(symbol)
    orderbook = exchange.ws_client.get_orderbook(symbol)
```

### Pattern 3: Error Handling

```python
try:
    result = await exchange.create_order(...)
except ValueError as e:
    # Invalid parameters (symbol, amount, etc.)
    print(f"Invalid order: {e}")
except RuntimeError as e:
    # API/connection error
    print(f"API error: {e}")
except asyncio.TimeoutError:
    # Operation timeout
    print("Request timed out")
```

### Pattern 4: Multiple Exchanges

```python
async def arbitrage():
    ex1 = await create_exchange("lighter", LIGHTER_KEY)
    ex2 = await create_exchange("standx", STANDX_KEY)

    try:
        # Parallel price fetch
        prices = await asyncio.gather(
            ex1.get_mark_price(symbol_create("lighter", "BTC")),
            ex2.get_mark_price(symbol_create("standx", "BTC")),
        )
    finally:
        await asyncio.gather(ex1.close(), ex2.close())
```

---

## EXCHANGE-SPECIFIC NOTES

### StandX
- **Chain:** BSC (Binance Smart Chain)
- **Quote Currency:** DUSD (not USDC)
- **WebSocket:** Dual streams (market + order)
- **Ping:** DISABLED - Server disconnects on ping
- **Order Response:** Separate WS endpoint (ws-api/v1)
- **Auth:** JWT token with body signature

### Hyperliquid
- **Signing:** EIP-712 typed data
- **Agent Support:** Can delegate signing to agent address
- **USD Transfers:** MUST use wallet key (not agent)
- **Builder Fees:** Complex fee structure support
- **Proxy:** Supports HTTP proxy

### Lighter
- **Orderbook:** Delta-based updates
- **Auth Token:** Cached with 10-minute expiry
- **Spot:** Supported (has_spot=True)
- **Reconnect:** Force reconnect every 60s

### Paradex
- **Integration:** Uses CCXT library
- **Chain:** StarkNet
- **Auth:** JWT from REST auth endpoint
- **Stability:** May break with API changes

### Variational
- **WebSocket:** NOT SUPPORTED (REST only)
- **API:** Frontend API (may break with UI changes)
- **Auth:** Session cookies via curl_cffi
- **Requests:** Browser-like with Impersonate

---

## DEBUGGING CHECKLIST

### Connection Issues

1. Check PING_INTERVAL setting for exchange
2. Check RECV_TIMEOUT (too short = false disconnects)
3. Check JWT/token expiry
4. Check network/firewall

### Order Issues

1. Verify symbol format: `symbol_create(exchange, coin)`
2. Check minimum order size
3. Verify collateral is sufficient
4. Check if market is active

### Authentication Issues

1. Verify credential fields match exchange requirements
2. Check key format (hex prefix, base64, base58)
3. For StandX: Check JWT token refresh
4. For agents: Verify agent is authorized

---

## CODE LOCATION REFERENCE

| Functionality | Primary File | Secondary |
|---------------|--------------|-----------|
| Factory function | `exchange_factory.py:create_exchange()` | |
| Symbol creation | `exchange_factory.py:symbol_create()` | |
| Base interface | `multi_perp_dex.py:MultiPerpDex` | |
| Default impls | `multi_perp_dex.py:MultiPerpDexMixin` | |
| WS base | `wrappers/base_ws_client.py` | |
| StandX exchange | `wrappers/standx.py` | `standx_ws_client.py` |
| StandX auth | `wrappers/standx_auth.py` | |
| Hyperliquid | `wrappers/hyperliquid.py` | `mpdex/utils/hyperliquid_base.py` |
| Lighter | `wrappers/lighter.py` | `lighter_ws_client.py` |

---

## VERSION INFORMATION

- **Python:** 3.8+ (Windows: 3.10+)
- **Main Branch:** master
- **Installation:** `pip install "mpdex @ git+https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git@master"`
