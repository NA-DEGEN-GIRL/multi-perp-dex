#!/usr/bin/env python3
"""
Unified Test Script for Multi-Perp-DEX
======================================

Usage:
    python test_unified.py                      # Interactive mode (select exchange)
    python test_unified.py lighter              # Test specific exchange
    python test_unified.py lighter --full       # Full test (including orders)
    python test_unified.py lighter --read-only  # Read-only test (default)
    python test_unified.py all --read-only      # Test all exchanges (read-only)

Test Modes:
    --read-only : Only test read operations (get_collateral, get_position, etc.)
    --full      : Full test including order creation/cancellation (USE WITH CAUTION!)

Supported Exchanges:
    lighter, hyperliquid, edgex, backpack, pacifica, treadfi, variational,
    grvt, paradex, standx, superstack
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
import argparse
from typing import Optional, Dict, Any
from exchange_factory import create_exchange, symbol_create

# ==================== Exchange Configurations ====================

EXCHANGE_CONFIGS = {
    "lighter": {
        "key_module": "keys.pk_lighter",
        "key_name": "LIGHTER_KEY",
        "coin": "BTC",
        "amount": 0.0003,
        "is_spot": False,
    },
    "hyperliquid": {
        "key_module": "keys.pk_hyperliquid",
        "key_name": "HYPERLIQUID_KEY",
        "coin": "BTC",
        "amount": 0.0002,
        "is_spot": False,
    },
    "superstack": {
        "key_module": "keys.pk_superstack",
        "key_name": "SUPERSTACK_KEY",
        "coin": "xyz:XYZ100",
        "amount": 0.002,
        "is_spot": False,
    },
    "edgex": {
        "key_module": "keys.pk_edgex",
        "key_name": "EDGEX_KEY",
        "coin": "BTC",
        "amount": 0.001,
        "is_spot": False,
    },
    "backpack": {
        "key_module": "keys.pk_backpack",
        "key_name": "BACKPACK_KEY",
        "coin": "BTC",
        "amount": 0.0001,
        "is_spot": False,
    },
    "pacifica": {
        "key_module": "keys.pk_pacifica",
        "key_name": "PACIFICA_KEY",
        "coin": "BTC",
        "amount": 0.0002,
        "is_spot": False,
    },
    "treadfi": {
        "key_module": "keys.pk_treadfi_pc",
        "key_name": "TREADFI_KEY",
        "coin": "BTC",
        "amount": 0.0002,
        "is_spot": False,
    },
    "variational": {
        "key_module": "keys.pk_variational",
        "key_name": "VARIATIONAL_KEY",
        "coin": "BTC",
        "amount": 0.0002,
        "is_spot": False,
    },
    "grvt": {
        "key_module": "keys.pk_grvt",
        "key_name": "GRVT_KEY",
        "coin": "BTC",
        "amount": 0.0001,
        "is_spot": False,
    },
    "paradex": {
        "key_module": "keys.pk_paradex",
        "key_name": "PARADEX_KEY",
        "coin": "BTC",
        "amount": 0.0001,
        "is_spot": False,
    },
    "standx": {
        "key_module": "keys.pk_standx",
        "key_name": "STANDX_KEY",
        "coin": "BTC",
        "amount": 0.0001,
        "is_spot": False,
    },
}

# ==================== Helper Functions ====================

def load_key(exchange_name: str):
    """Dynamically load API key for exchange"""
    config = EXCHANGE_CONFIGS.get(exchange_name)
    if not config:
        raise ValueError(f"Unknown exchange: {exchange_name}")

    try:
        module = __import__(config["key_module"], fromlist=[config["key_name"]])
        return getattr(module, config["key_name"])
    except (ImportError, AttributeError) as e:
        print(f"[ERROR] Failed to load key for {exchange_name}: {e}")
        print(f"        Make sure {config['key_module']}.py exists with {config['key_name']}")
        return None

def print_result(label: str, result: Any, indent: int = 2):
    """Pretty print test result"""
    prefix = " " * indent
    if result is None:
        print(f"{prefix}{label}: None")
    elif isinstance(result, dict):
        print(f"{prefix}{label}:")
        for k, v in result.items():
            if k.startswith("_"):  # Skip private/raw fields
                continue
            print(f"{prefix}  {k}: {v}")
    elif isinstance(result, list):
        print(f"{prefix}{label}: [{len(result)} items]")
        for i, item in enumerate(result[:3]):  # Show first 3
            print(f"{prefix}  [{i}] {item}")
        if len(result) > 3:
            print(f"{prefix}  ... and {len(result) - 3} more")
    else:
        print(f"{prefix}{label}: {result}")

# ==================== Test Functions ====================

async def test_read_only(exchange, symbol: str, exchange_name: str):
    """Read-only tests (safe to run anytime)"""
    print(f"\n{'='*60}")
    print(f"[READ-ONLY TEST] {exchange_name.upper()}")
    print(f"{'='*60}")

    results = {}

    # 1. Get Collateral
    print("\n[1] get_collateral()")
    try:
        result = await exchange.get_collateral()
        print_result("Collateral", result)
        results["collateral"] = "PASS" if result else "EMPTY"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["collateral"] = f"FAIL: {e}"

    await asyncio.sleep(0.2)

    # 2. Get Mark Price
    print(f"\n[2] get_mark_price({symbol})")
    try:
        result = await exchange.get_mark_price(symbol)
        print_result("Mark Price", result)
        results["mark_price"] = "PASS" if result else "EMPTY"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["mark_price"] = f"FAIL: {e}"

    await asyncio.sleep(0.2)

    # 3. Get Position
    print(f"\n[3] get_position({symbol})")
    try:
        result = await exchange.get_position(symbol)
        print_result("Position", result)
        results["position"] = "PASS" if result else "NO_POSITION"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["position"] = f"FAIL: {e}"

    await asyncio.sleep(0.2)

    # 4. Get Open Orders
    print(f"\n[4] get_open_orders({symbol})")
    try:
        result = await exchange.get_open_orders(symbol)
        print_result("Open Orders", result)
        results["open_orders"] = "PASS" if result is not None else "EMPTY"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["open_orders"] = f"FAIL: {e}"

    await asyncio.sleep(0.2)

    # 5. Get Orderbook
    print(f"\n[5] get_orderbook({symbol})")
    try:
        result = await exchange.get_orderbook(symbol)
        if result:
            bids = result.get("bids", [])[:2]
            asks = result.get("asks", [])[:2]
            print(f"  Bids (top 2): {bids}")
            print(f"  Asks (top 2): {asks}")
            if result.get("msg"):
                print(f"  Note: {result.get('msg')}")
        results["orderbook"] = "PASS" if result else "EMPTY"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["orderbook"] = f"FAIL: {e}"

    return results

async def test_full(exchange, symbol: str, amount: float, exchange_name: str):
    """Full tests including order operations (USE WITH CAUTION!)"""
    print(f"\n{'='*60}")
    print(f"[FULL TEST] {exchange_name.upper()} - INCLUDING ORDERS!")
    print(f"{'='*60}")

    # First run read-only tests
    results = await test_read_only(exchange, symbol, exchange_name)

    # Get current price for limit orders
    print("\n[6] Getting price for limit orders...")
    try:
        price = await exchange.get_mark_price(symbol)
        if not price:
            print("  ERROR: Could not get price, skipping order tests")
            return results
    except Exception as e:
        print(f"  ERROR: {e}")
        return results

    await asyncio.sleep(0.3)

    # 7. Limit Buy Order
    print(f"\n[7] create_order({symbol}, 'buy', {amount}, price={price*0.95:.2f})")
    try:
        l_price = price * 0.95
        result = await exchange.create_order(symbol, 'buy', amount, price=l_price)
        print_result("Limit Buy", result)
        results["limit_buy"] = "PASS" if result else "FAIL"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["limit_buy"] = f"FAIL: {e}"

    await asyncio.sleep(0.5)

    # 8. Limit Sell Order
    print(f"\n[8] create_order({symbol}, 'sell', {amount}, price={price*1.05:.2f})")
    try:
        h_price = price * 1.05
        result = await exchange.create_order(symbol, 'sell', amount, price=h_price)
        print_result("Limit Sell", result)
        results["limit_sell"] = "PASS" if result else "FAIL"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["limit_sell"] = f"FAIL: {e}"

    await asyncio.sleep(0.5)

    # 9. Get Open Orders (should have 2)
    print(f"\n[9] get_open_orders({symbol}) - expecting 2 orders")
    try:
        open_orders = await exchange.get_open_orders(symbol)
        print_result("Open Orders", open_orders)
        results["open_orders_after"] = f"PASS ({len(open_orders) if open_orders else 0} orders)"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["open_orders_after"] = f"FAIL: {e}"
        open_orders = []

    await asyncio.sleep(0.3)

    # 10. Cancel Orders
    print(f"\n[10] cancel_orders({symbol})")
    try:
        result = await exchange.cancel_orders(symbol, open_orders)
        print_result("Cancel Result", result)
        results["cancel_orders"] = "PASS" if result is not None else "FAIL"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["cancel_orders"] = f"FAIL: {e}"

    await asyncio.sleep(0.5)

    # 11. Market Buy
    print(f"\n[11] create_order({symbol}, 'buy', {amount}) - MARKET")
    try:
        result = await exchange.create_order(symbol, 'buy', amount)
        print_result("Market Buy", result)
        results["market_buy"] = "PASS" if result else "FAIL"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["market_buy"] = f"FAIL: {e}"

    await asyncio.sleep(0.5)

    # 12. Get Position (should have position now)
    print(f"\n[12] get_position({symbol}) - expecting position")
    try:
        position = await exchange.get_position(symbol)
        print_result("Position", position)
        results["position_after"] = "PASS" if position else "NO_POSITION"
    except Exception as e:
        print(f"  ERROR: {e}")
        results["position_after"] = f"FAIL: {e}"
        position = None

    await asyncio.sleep(0.3)

    # 13. Close Position
    if position:
        print(f"\n[13] close_position({symbol})")
        try:
            result = await exchange.close_position(symbol, position)
            print_result("Close Position", result)
            results["close_position"] = "PASS" if result else "FAIL"
        except Exception as e:
            print(f"  ERROR: {e}")
            results["close_position"] = f"FAIL: {e}"

    return results

# ==================== Main ====================

async def run_test(exchange_name: str, mode: str = "read-only"):
    """Run test for a single exchange"""
    config = EXCHANGE_CONFIGS.get(exchange_name)
    if not config:
        print(f"[ERROR] Unknown exchange: {exchange_name}")
        print(f"        Available: {', '.join(EXCHANGE_CONFIGS.keys())}")
        return None

    # Load API key
    key = load_key(exchange_name)
    if not key:
        return None

    # Create exchange instance
    print(f"\n[INIT] Creating {exchange_name} exchange...")
    try:
        exchange = await create_exchange(exchange_name, key)
    except Exception as e:
        print(f"[ERROR] Failed to create exchange: {e}")
        return None

    # Create symbol
    symbol = symbol_create(exchange_name, config["coin"], is_spot=config.get("is_spot", False))
    print(f"[INIT] Symbol: {symbol}")

    # Run tests
    try:
        if mode == "full":
            results = await test_full(exchange, symbol, config["amount"], exchange_name)
        else:
            results = await test_read_only(exchange, symbol, exchange_name)
    finally:
        # Always close
        print(f"\n[CLEANUP] Closing {exchange_name}...")
        try:
            await exchange.close()
        except Exception:
            pass

    return results

async def run_all_tests(mode: str = "read-only"):
    """Run tests for all exchanges"""
    all_results = {}

    for exchange_name in EXCHANGE_CONFIGS.keys():
        print(f"\n{'#'*70}")
        print(f"# Testing: {exchange_name.upper()}")
        print(f"{'#'*70}")

        try:
            results = await run_test(exchange_name, mode)
            all_results[exchange_name] = results if results else {"status": "SKIPPED"}
        except Exception as e:
            print(f"[ERROR] {exchange_name}: {e}")
            all_results[exchange_name] = {"status": f"ERROR: {e}"}

        await asyncio.sleep(1)  # Delay between exchanges

    # Print summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for name, results in all_results.items():
        status = "OK" if results and "FAIL" not in str(results) else "ISSUES"
        print(f"  {name:15} : {status}")

    return all_results

def interactive_mode():
    """Interactive exchange selection"""
    print("\n" + "="*50)
    print("Available Exchanges:")
    print("="*50)
    for i, name in enumerate(EXCHANGE_CONFIGS.keys(), 1):
        print(f"  {i:2}. {name}")
    print(f"  {len(EXCHANGE_CONFIGS)+1:2}. all (test all exchanges)")
    print("="*50)

    try:
        choice = input("\nSelect exchange (number or name): ").strip().lower()

        # Check if number
        if choice.isdigit():
            idx = int(choice) - 1
            names = list(EXCHANGE_CONFIGS.keys())
            if idx == len(names):
                return "all"
            elif 0 <= idx < len(names):
                return names[idx]
        elif choice in EXCHANGE_CONFIGS or choice == "all":
            return choice

        print(f"Invalid choice: {choice}")
        return None
    except (KeyboardInterrupt, EOFError):
        return None

def main():
    parser = argparse.ArgumentParser(
        description="Unified test script for Multi-Perp-DEX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("exchange", nargs="?", help="Exchange name (or 'all')")
    parser.add_argument("--full", action="store_true", help="Full test including orders")
    parser.add_argument("--read-only", action="store_true", help="Read-only test (default)")

    args = parser.parse_args()

    # Determine mode
    mode = "full" if args.full else "read-only"

    # Determine exchange
    exchange = args.exchange
    if not exchange:
        exchange = interactive_mode()
        if not exchange:
            print("No exchange selected. Exiting.")
            return

    # Confirm full mode
    if mode == "full":
        print("\n" + "!"*60)
        print("! WARNING: FULL MODE WILL CREATE AND CANCEL REAL ORDERS!")
        print("!"*60)
        confirm = input("Type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            return

    # Run tests
    if exchange == "all":
        asyncio.run(run_all_tests(mode))
    else:
        asyncio.run(run_test(exchange, mode))

if __name__ == "__main__":
    main()
