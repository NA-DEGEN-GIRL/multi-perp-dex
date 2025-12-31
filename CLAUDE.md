# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**mpdex** is an async Python wrapper library providing a unified interface for trading across multiple perpetual DEXs (Lighter, GRVT, Paradex, Edgex, Backpack, TreadFi, Variational, Pacifica, Hyperliquid, Superstack).

## Commands

```bash
# Installation (from Git)
pip install "mpdex @ git+https://github.com/NA-DEGEN-GIRL/multi-perp-dex.git@master"

# Run individual exchange tests
python test_exchanges/test_lighter.py
python test_exchanges/test_hyperliquid.py
# etc.

# Main application
python main.py --module check   # Check collateral, position, PnL
python main.py --module order   # Create market order
python main.py --module close   # Close position
python main.py --module all     # Run all modules
```

No pytest/lint commands - testing is done through example scripts in `test_exchanges/`.

## Architecture

### Core Design Patterns

1. **Abstract Base Class** (`multi_perp_dex.py`):
   - `MultiPerpDex`: Abstract interface all exchanges implement
   - `MultiPerpDexMixin`: Default implementations for `get_open_orders()` and `close_position()`
   - All methods are async

2. **Factory Pattern with Lazy Loading** (`exchange_factory.py`, `mpdex/__init__.py`):
   - `create_exchange(exchange_name, key_params)`: Async factory that only loads exchange SDKs when needed
   - `symbol_create(exchange_name, coin, is_spot=False, quote=None)`: Normalizes symbol formats across exchanges
   - Heavy dependencies (CCXT, lighter-sdk, grvt-pysdk, cairo-lang) only load when that exchange is used

3. **WebSocket Pooling** (`wrappers/lighter_ws_client.py`, `wrappers/hyperliquid_ws_client.py`):
   - Singleton pools (`LIGHTER_WS_POOL`, `HYPERLIQUID_WS_POOL`) share connections across multiple exchange instances

### Core Interface Methods

```python
async create_order(symbol, side, amount, price=None, order_type='market')
async get_position(symbol)
async close_position(symbol, position)
async get_collateral()
async get_open_orders(symbol)
async cancel_orders(symbol)
async get_mark_price(symbol)
async close()  # Session cleanup
```

### Key Files

- `multi_perp_dex.py`: Abstract base class and Mixin
- `exchange_factory.py`: Factory function and symbol format mappings
- `mpdex/__init__.py`: Public API with lazy imports
- `wrappers/*.py`: Exchange-specific implementations
- `keys/copy.pk_*.py`: Credential templates (copy and fill with real values)

## Symbol Formats

Each exchange uses different formats. Always use `symbol_create()`:

```python
symbol_create("paradex", "BTC")           # "BTC-USD-PERP"
symbol_create("edgex", "BTC")             # "BTCUSD"
symbol_create("grvt", "BTC")              # "BTC_USDT_Perp"
symbol_create("backpack", "BTC")          # "BTC_USDC_PERP"
symbol_create("lighter", "BTC")           # "BTC"
symbol_create("hyperliquid", "BTC")       # "BTC"
symbol_create("treadfi.hyperliquid", "BTC")  # "BTC:PERP-USDC"

# Spot (where supported)
symbol_create("lighter", "ETH/USDC", is_spot=True)  # "ETH/USDC"
symbol_create("backpack", "BTC/USDC", is_spot=True) # "BTC_USDC"
```

## Usage Patterns

```python
import asyncio
from mpdex import create_exchange, symbol_create

async def main():
    # Factory pattern (recommended)
    from keys.pk_lighter import LIGHTER_KEY
    ex = await create_exchange("lighter", LIGHTER_KEY)
    symbol = symbol_create("lighter", "BTC")

    collateral = await ex.get_collateral()
    position = await ex.get_position(symbol)

    await ex.close()

asyncio.run(main())
```

## Adding New Exchange Wrappers

1. Create `wrappers/<exchange>.py` implementing `MultiPerpDex` and `MultiPerpDexMixin`
2. Add mapping to `_load()` in `exchange_factory.py`
3. Add symbol format to `SYMBOL_FORMATS` (and `SPOT_SYMBOL_FORMATS` if applicable)
4. Add factory creation logic in `create_exchange()`
5. Create credential template in `keys/copy.pk_<exchange>.py`
6. Add lazy import in `mpdex/__init__.py`

## Important Notes

- **Python 3.8+** required; **Windows requires 3.10** (fastecdsa dependency)
- `cairo-lang` takes significant time to install
- Main branch is `master` (not main)
- Credentials in `keys/pk_*.py` are gitignored - only templates are committed
- Some exchanges (TreadFi, Variational) use frontend APIs - may break with website changes
- Always call `await ex.close()` for proper session cleanup
