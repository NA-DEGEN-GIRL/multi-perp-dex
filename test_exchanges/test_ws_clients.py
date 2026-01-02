"""
WebSocket Clients Test Script

Tests non-order related functionality for all WS-based exchanges:
- Lighter
- Hyperliquid
- Pacifica
- StandX

Runs in infinite loop to verify real-time data updates.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpdex import create_exchange, symbol_create


# Test configuration
EXCHANGES = {
    "lighter": {
        "key_module": "keys.pk_lighter",
        "key_name": "LIGHTER_KEY",
        "coin": "BTC",
        "skip": [],
    },
    "hyperliquid": {
        "key_module": "keys.pk_hyperliquid",
        "key_name": "HYPERLIQUID_KEY",
        "coin": "BTC",
        "skip": [],
    },
    "pacifica": {
        "key_module": "keys.pk_pacifica",
        "key_name": "PACIFICA_KEY",
        "coin": "BTC",
        "skip": [],
    },
    "standx": {
        "key_module": "keys.pk_standx",
        "key_name": "STANDX_KEY",
        "coin": "BTC",
        "skip": ["collateral", "position"],  # REST API only
    },
}

INTERVAL = 0.05  # seconds between updates


def load_key(key_module: str, key_name: str):
    """Dynamically load exchange key"""
    try:
        import importlib
        mod = importlib.import_module(key_module)
        return getattr(mod, key_name)
    except (ImportError, AttributeError):
        return None


async def run_exchange_loop(name: str, config: dict):
    """Run infinite loop for a single exchange"""
    key = load_key(config["key_module"], config["key_name"])
    if not key:
        print(f"[{name.upper()}] Key not found: {config['key_module']}")
        return

    coin = config["coin"]
    symbol = symbol_create(name, coin)
    skip = config.get("skip", [])
    tag = name.upper()[:4]

    try:
        print(f"[{tag}] Connecting... (symbol: {symbol})")
        ex = await create_exchange(name, key)
        print(f"[{tag}] Connected!")

        loop_count = 0
        while True:
            loop_count += 1
            lines = []

            # Mark Price
            try:
                price = await ex.get_mark_price(symbol)
                lines.append(f"price={price}")
            except Exception as e:
                lines.append(f"price=ERR({e})")

            # Orderbook
            try:
                book = await ex.get_orderbook(symbol)
                if book:
                    bids = book.get("bids", [])
                    asks = book.get("asks", [])
                    best_bid = bids[0][0] if bids else "-"
                    best_ask = asks[0][0] if asks else "-"
                    lines.append(f"book={best_bid}/{best_ask}")
                else:
                    lines.append("book=empty")
            except Exception as e:
                lines.append(f"book=ERR({e})")

            # Collateral
            if "collateral" not in skip:
                try:
                    coll = await ex.get_collateral()
                    avail = coll.get("available_collateral") or coll.get("cross_available") or coll.get("available_to_spend") or coll.get("balance")
                    lines.append(f"coll={avail}")
                except Exception as e:
                    lines.append(f"coll=ERR({e})")

            # Position
            if "position" not in skip:
                try:
                    pos = await ex.get_position(symbol)
                    if pos and pos.get("size"):
                        lines.append(f"pos={pos.get('side')}/{pos.get('size')}")
                    else:
                        lines.append("pos=None")
                except Exception as e:
                    lines.append(f"pos=ERR({e})")

            print(f"[{tag}] #{loop_count:04d} | " + " | ".join(lines))
            await asyncio.sleep(INTERVAL)

    except asyncio.CancelledError:
        print(f"[{tag}] Cancelled")
    except Exception as e:
        print(f"[{tag}] Error: {e}")
    finally:
        try:
            await ex.close()
        except Exception:
            pass
        print(f"[{tag}] Closed")


async def main():
    print("=" * 70)
    print("  WebSocket Clients Test (Ctrl+C to stop)")
    print("=" * 70)

    # Parse command line args for specific exchanges
    target_exchanges = sys.argv[1:] if len(sys.argv) > 1 else list(EXCHANGES.keys())
    target_exchanges = [e for e in target_exchanges if e in EXCHANGES]

    if not target_exchanges:
        print(f"Usage: python {sys.argv[0]} [exchange1] [exchange2] ...")
        print(f"Available: {', '.join(EXCHANGES.keys())}")
        return

    print(f"Testing: {', '.join(target_exchanges)}\n")

    # Create tasks for all exchanges
    tasks = []
    for name in target_exchanges:
        config = EXCHANGES[name]
        task = asyncio.create_task(run_exchange_loop(name, config))
        tasks.append(task)

    # Wait for all tasks (or until cancelled)
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        # Cancel all tasks on exit
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
