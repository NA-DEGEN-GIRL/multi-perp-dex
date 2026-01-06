# Multi-Perp-DEX Developer Documentation

> **mpdex** - Unified async Python wrapper for trading across multiple perpetual DEXs

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Design Patterns](#core-design-patterns)
3. [Exchange Implementations](#exchange-implementations)
4. [WebSocket System](#websocket-system)
5. [Symbol Format Reference](#symbol-format-reference)
6. [Authentication Methods](#authentication-methods)
7. [Adding New Exchange](#adding-new-exchange)
8. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Project Structure

```
multi-perp-dex/
├── multi_perp_dex.py          # Abstract base classes
├── exchange_factory.py         # Factory pattern + symbol mappings
├── mpdex/                      # Public API package
│   ├── __init__.py            # Lazy-loading exports
│   └── utils/                 # Shared utilities
│       ├── hyperliquid_base.py
│       ├── common_hyperliquid.py
│       └── common_pacifica.py
├── wrappers/                   # Exchange implementations
│   ├── base_ws_client.py      # Abstract WebSocket base
│   ├── [exchange].py          # REST + business logic
│   ├── [exchange]_ws_client.py # WebSocket client
│   └── [exchange]_auth.py     # Auth helpers (some exchanges)
├── keys/                       # Credential templates (gitignored)
└── test_exchanges/             # Example scripts
```

### Dependency Flow

```
User Code
    │
    ▼
mpdex/__init__.py (lazy imports)
    │
    ▼
exchange_factory.py
    ├── create_exchange() ──▶ Exchange Wrapper
    └── symbol_create()   ──▶ Normalized Symbol
                                    │
                                    ▼
                            wrappers/[exchange].py
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            REST API (aiohttp)              WebSocket Client
                                        (wrappers/base_ws_client.py)
```

---

## Core Design Patterns

### 1. Abstract Base Class Pattern

**File:** `multi_perp_dex.py`

```python
class MultiPerpDex(ABC):
    """Abstract interface all exchanges must implement"""

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

**Mixin for Default Implementations:**

```python
class MultiPerpDexMixin:
    """Default implementations for common operations"""

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

### 2. Factory Pattern with Lazy Loading

**File:** `exchange_factory.py`

```python
def _load(exchange_name: str):
    """Lazy-load exchange class only when needed"""
    if exchange_name == "lighter":
        from wrappers.lighter import LighterExchange
        return LighterExchange
    elif exchange_name == "standx":
        from wrappers.standx import StandXExchange
        return StandXExchange
    # ... other exchanges

async def create_exchange(exchange_platform: str, key_params: dict):
    """Factory function to create exchange instances"""
    ExchangeClass = _load(exchange_platform)

    if exchange_platform == "lighter":
        ex = ExchangeClass(
            account_id=key_params["account_id"],
            private_key=key_params["private_key"],
            api_key_id=key_params["api_key_id"],
        )
    # ... handle other exchanges

    await ex.init()  # Async initialization
    return ex
```

**Benefits:**
- Heavy dependencies (cairo-lang, grvt-pysdk, etc.) only loaded when used
- Faster startup when using single exchange
- Memory efficiency

### 3. WebSocket Pool Pattern

```python
class StandXWSPool:
    """Singleton pool for shared WebSocket connections"""

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

# Global singleton
WS_POOL = StandXWSPool()
```

**Used by:** Lighter, Backpack, GRVT, Paradex, Pacifica, StandX

---

## Exchange Implementations

### Quick Reference Table

| Exchange | File | Auth Type | WS Support | Special Features |
|----------|------|-----------|------------|------------------|
| Lighter | `lighter.py` | SDK + API Key | Full | Delta orderbook, spot |
| GRVT | `grvt.py` | API Keys | Partial | Callback→cache WS |
| Paradex | `paradex.py` | StarkNet | Partial | CCXT integration |
| Hyperliquid | `hyperliquid.py` | EIP-712 | Full | Multi-DEX, agent signing |
| Backpack | `backpack.py` | NaCl | Partial | Spot, decimal precision |
| EdgeX | `edgex.py` | StarkNet | Partial | Dual WS (pub/priv) |
| Pacifica | `pacifica.py` | Solana | Full | JSON message signing |
| Variational | `variational.py` | Cookies | None | Frontend API |
| TreadFi HL | `treadfi_hl.py` | Browser | Partial | HTML UI signing |
| TreadFi PC | `treadfi_pc.py` | Browser | Partial | TreadFi + Pacifica |
| Superstack | `superstack.py` | API | Full | HyperliquidBase subclass |
| StandX | `standx.py` | EVM | Full | Dual WS streams |

### Exchange-Specific Notes

#### Lighter
```python
# Auth token caching (10-minute expiry)
self._token_cache = {
    'token': None,
    'expires_at': 0
}

# Spot trading support
self.has_spot = True
symbol = symbol_create("lighter", "ETH/USDC", is_spot=True)  # "ETH/USDC"
```

#### Hyperliquid
```python
# Dual signing modes
if self.by_agent:
    signature = sign_l1_action(agent_private_key, ...)
else:
    signature = sign_l1_action(wallet_private_key, ...)

# USD transfers MUST use wallet (not agent)
signature = sign_user_signed_action(wallet_private_key, ...)
```

#### StandX
```python
# Dual WebSocket streams
ws_client         # Market stream: price, orderbook, position, balance
order_ws_client   # Order stream: order confirmations (separate endpoint)

# IMPORTANT: No ping allowed!
PING_INTERVAL = None  # Server disconnects if ping is sent
RECV_TIMEOUT = None   # Order stream may be idle for long periods
```

#### Variational
```python
# Frontend API - may break with UI changes
# Uses curl_cffi for browser-like requests
from curl_cffi.requests import AsyncSession

# Session cookie required
session_cookies = {"vr-token": "..."}
```

---

## WebSocket System

### Base WebSocket Client

**File:** `wrappers/base_ws_client.py`

```python
class BaseWSClient(ABC):
    # Configuration (override in subclass)
    WS_URL: str = ""
    WS_CONNECT_TIMEOUT: float = 10.0
    PING_INTERVAL: Optional[float] = None   # None = no ping
    PING_FAIL_THRESHOLD: int = 2
    RECV_TIMEOUT: Optional[float] = None    # None = no timeout
    RECONNECT_MIN: float = 1.0
    RECONNECT_MAX: float = 8.0
    CONNECT_MAX_ATTEMPTS: int = 6

    # Abstract methods (must implement)
    @abstractmethod
    async def _handle_message(self, data: Dict) -> None: ...

    @abstractmethod
    async def _resubscribe(self) -> None: ...

    @abstractmethod
    def _build_ping_message(self) -> Optional[str]: ...
```

### Ping/Pong Configuration by Exchange

| Exchange | PING_INTERVAL | RECV_TIMEOUT | Notes |
|----------|---------------|--------------|-------|
| **StandX** | `None` | `None` | **Server disconnects if ping sent!** |
| Lighter | `None` | `60.0` | Server sends periodic pings |
| Backpack | `None` | `90.0` | Server pings every 60s |
| EdgeX | `None` | `60.0` | Must respond to server pings |
| Pacifica | `50.0` | `60.0` | Client sends `{"channel": "ping"}` |
| Hyperliquid | `None` | `60.0` | Recv timeout triggers reconnect |
| GRVT | varies | `60.0` | Handled by pysdk internals |

### Reconnection Strategy

```python
async def _reconnect_with_backoff(self) -> None:
    delay = self.RECONNECT_MIN  # Start at 0.2-1.0s
    attempt = 0

    while self._running:
        attempt += 1
        print(f"reconnecting in {delay:.1f}s... (attempt {attempt})")
        await asyncio.sleep(delay)

        if await self._do_reconnect():
            print("✓ reconnected successfully")
            return

        # Exponential backoff with jitter
        delay = min(self.RECONNECT_MAX, delay * 2.0) + random.uniform(0, 0.5)
```

### Proxy Support

```python
# HTTP CONNECT tunnel for WebSocket
client = BaseWSClient(proxy="http://user:pass@proxy.example.com:8080")

# Internally:
# 1. Connect to proxy
# 2. Send HTTP CONNECT request
# 3. Upgrade to WebSocket over tunnel
```

---

## Symbol Format Reference

### Perpetual Symbols

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

### Spot Symbols (where supported)

```python
SPOT_SYMBOL_FORMATS = {
    "backpack":    lambda coin, quote: f"{coin}_{quote}",    # "BTC_USDC"
    "lighter":     lambda coin, quote: f"{coin}/{quote}",    # "BTC/USDC"
    "hyperliquid": lambda coin, quote: f"{coin}/{quote}",    # "BTC/USDC"
    "edgex":       lambda coin, quote: f"{coin}/{quote}",    # "BTC/USDC"
}
```

### Usage

```python
from exchange_factory import symbol_create

# Perpetual
symbol = symbol_create("standx", "BTC")           # "BTC-USD"
symbol = symbol_create("paradex", "ETH")          # "ETH-USD-PERP"
symbol = symbol_create("grvt", "SOL")             # "SOL_USDT_Perp"

# Spot
symbol = symbol_create("lighter", "ETH", is_spot=True, quote="USDC")  # "ETH/USDC"
symbol = symbol_create("backpack", "BTC", is_spot=True, quote="USDC") # "BTC_USDC"
```

---

## Authentication Methods

### EVM-based Signing

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

# StandX - Simple EVM signing
def sign_request(self, body: str) -> dict:
    message = f"{timestamp}{body}"
    signed = Account.sign_message(encode_defunct(text=message), self.private_key)
    return {"x-request-signature": signed.signature.hex()}
```

### StarkNet Signing

```python
# EdgeX, Paradex
from starkware.crypto.signature.signature import sign

def stark_sign(private_key: int, message_hash: int) -> tuple:
    r, s = sign(msg_hash=message_hash, priv_key=private_key)
    return (r, s)
```

### NaCl Signing (Backpack)

```python
from nacl.signing import SigningKey
import base64

secret_bytes = base64.b64decode(secret_key)
signing_key = SigningKey(secret_bytes[:32])
signature = signing_key.sign(message.encode())
```

### Solana Signing (Pacifica)

```python
from solders.keypair import Keypair
import base58

keypair = Keypair.from_base58_string(private_key)
signature = keypair.sign_message(message.encode())
signature_b58 = base58.b58encode(bytes(signature)).decode()
```

### Session-based (Variational, TreadFi)

```python
# Variational
from curl_cffi.requests import AsyncSession

session = AsyncSession()
session.cookies.update(session_cookies)  # {"vr-token": "..."}
```

---

## Adding New Exchange

### Step 1: Create Wrapper

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
        """Async initialization"""
        await self._load_markets()
        return self

    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        # Implementation
        pass

    # ... implement all abstract methods

    async def close(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()
```

### Step 2: Add to Factory

```python
# exchange_factory.py

def _load(exchange_name):
    # ...
    elif exchange_name == "myexchange":
        from wrappers.myexchange import MyExchange
        return MyExchange

# Add symbol format
SYMBOL_FORMATS["myexchange"] = lambda coin, _: f"{coin}-PERP"

async def create_exchange(exchange_platform, key_params):
    # ...
    elif exchange_platform == "myexchange":
        ex = ExchangeClass(
            api_key=key_params["api_key"],
            secret=key_params["secret"],
        )
```

### Step 3: Create Credential Template

```python
# keys/copy.pk_myexchange.py
MYEXCHANGE_KEY = {
    "api_key": "your-api-key",
    "secret": "your-secret",
}
```

### Step 4: Add Lazy Import (Optional)

```python
# mpdex/__init__.py
def __getattr__(name):
    if name == "MyExchange":
        from wrappers.myexchange import MyExchange
        return MyExchange
    # ...
```

---

## Troubleshooting

### WebSocket Issues

**Problem: Connection keeps disconnecting**
```python
# Check if exchange requires specific ping behavior
# StandX: MUST NOT send ping (server disconnects)
PING_INTERVAL = None
RECV_TIMEOUT = None  # Order stream may be idle
```

**Problem: recv timeout on quiet markets**
```python
# Increase or disable timeout
RECV_TIMEOUT = 300.0  # 5 minutes
# or
RECV_TIMEOUT = None   # No timeout (rely on TCP keepalive)
```

**Problem: 429 Rate Limit**
```python
# Built-in exponential backoff handles this
# Check logs for "429 rate limit, retry in Xs"
```

### Authentication Issues

**Problem: StandX auth fails after reconnect**
```
[StandXWSClient] ✗ Auth failed after reconnect
```
- JWT token may have expired
- Check if session needs refresh

**Problem: Hyperliquid signing fails**
```
# Ensure correct signing method
if transferring_usd:
    # MUST use wallet private key, not agent
    sign_user_signed_action(wallet_private_key, ...)
```

### Symbol Issues

**Problem: Unknown symbol error**
```python
# Check symbol format for exchange
symbol = symbol_create("standx", "BTC")  # "BTC-USD"
symbol = symbol_create("paradex", "BTC") # "BTC-USD-PERP"

# Verify available symbols
symbols = await exchange.get_available_symbols()
print(symbols["perp"])
```

### Memory/Resource Issues

**Problem: Connection not closed properly**
```python
# Always call close()
try:
    # ... trading logic
finally:
    await exchange.close()
```

---

## Appendix

### Environment Requirements

- Python 3.8+ (Windows requires 3.10 for fastecdsa)
- `cairo-lang` takes significant install time
- Main branch: `master`

### Installation

```bash
# From Git
pip install "mpdex @ git+https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git@master"

# Development
git clone https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git
cd multi-perp-dex
pip install -e .
```

### Running Tests

```bash
# Individual exchange tests
python test_exchanges/test_lighter.py
python test_exchanges/test_standx.py

# Main application
python main.py --module check   # Check collateral, position
python main.py --module order   # Create order
python main.py --module close   # Close position
```
