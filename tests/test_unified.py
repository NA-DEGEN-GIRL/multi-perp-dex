#!/usr/bin/env python3
"""
Unified Test Script for Multi-Perp-DEX (Simple Version)
========================================================
상단 설정만 변경해서 사용
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
from exchange_factory import create_exchange, symbol_create

# ==================== 여기서 설정 ====================

# 테스트할 거래소 선택 (하나만)
# EXCHANGE = "paradex"
# EXCHANGE = "lighter"
# EXCHANGE = "hyperliquid"
# EXCHANGE = "edgex"
# EXCHANGE = "backpack"
# EXCHANGE = "pacifica"
# EXCHANGE = "treadfi"
# EXCHANGE = "grvt"
# EXCHANGE = "paradex"
# EXCHANGE = "standx"
# EXCHANGE = "superstack"
EXCHANGE = "extended"

# 테스트 코인
COIN = "BTC"
AMOUNT = 0.0002

# Skip할 테스트들 (True = skip)
SKIP = {
    "available_symbols": True,
    "collateral": False,
    "mark_price": True,
    "orderbook": True,
    "position": True,
    "open_orders": True,
    "limit_order": True,     # 주문 생성 (주의!)
    "cancel_orders": True,   # 주문 취소
    "market_order": True,    # 시장가 주문 (주의!)
    "close_position": True,  # 포지션 종료 (주의!)
}

# ==================== 거래소별 키 설정 ====================

EXCHANGE_KEYS = {
    "lighter": ("keys.pk_lighter", "LIGHTER_KEY"),
    "hyperliquid": ("keys.pk_hyperliquid", "HYPERLIQUID_KEY"),
    "edgex": ("keys.pk_edgex", "EDGEX_KEY"),
    "backpack": ("keys.pk_backpack", "BACKPACK_KEY"),
    "pacifica": ("keys.pk_pacifica", "PACIFICA_KEY"),
    "treadfi": ("keys.pk_treadfi_pc", "TREADFI_KEY"),
    "variational": ("keys.pk_variational", "VARIATIONAL_KEY"),
    "grvt": ("keys.pk_grvt", "GRVT_KEY"),
    "paradex": ("keys.pk_paradex", "PARADEX_KEY"),
    "standx": ("keys.pk_standx", "STANDX_KEY"),
    "superstack": ("keys.pk_superstack", "SUPERSTACK_KEY"),
    "extended": ("keys.pk_extended", "EXTENDED_KEY"),
}

# ==================== Helper ====================

def load_key(exchange_name: str):
    module_name, key_name = EXCHANGE_KEYS.get(exchange_name, (None, None))
    if not module_name:
        raise ValueError(f"Unknown exchange: {exchange_name}")
    module = __import__(module_name, fromlist=[key_name])
    return getattr(module, key_name)

def ws_info(exchange, method_name: str) -> str:
    """WS 지원 여부 메시지"""
    ws_supported = getattr(exchange, 'ws_supported', {})
    if ws_supported.get(method_name) is True:
        return "[WS]"
    elif ws_supported.get(method_name) is False:
        return "[REST only]"
    elif ws_supported:
        return ""
    return "[REST]"

def not_implemented_check(exchange, method_name: str) -> bool:
    """메소드가 구현되어 있는지 확인"""
    method = getattr(exchange, method_name, None)
    if method is None:
        return True
    # NotImplementedError를 raise하는지 확인 (docstring 등으로는 확인 어려움)
    return False

# ==================== Test ====================

async def main():
    print(f"\n{'='*60}")
    print(f"  Testing: {EXCHANGE.upper()}")
    print(f"  Coin: {COIN}, Amount: {AMOUNT}")
    print(f"{'='*60}\n")

    # Load key & create exchange
    key = load_key(EXCHANGE)
    exchange = await create_exchange(EXCHANGE, key)
    symbol = symbol_create(EXCHANGE, COIN)
    print(f"Symbol: {symbol}\n")

    price = None

    try:
        # 1. Available Symbols
        if not SKIP.get("available_symbols"):
            print(f"[1] get_available_symbols() {ws_info(exchange, 'get_available_symbols')}")
            try:
                result = await exchange.get_available_symbols()
                perp = result.get("perp", [])
                spot = result.get("spot", [])
                print(f"    Perp ({len(perp)}): {perp[:5]}{'...' if len(perp) > 5 else ''}")
                if spot:
                    print(f"    Spot ({len(spot)}): {spot[:5]}{'...' if len(spot) > 5 else ''}")
                else:
                    print(f"    Spot: (none)")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print("[1] get_available_symbols() - SKIPPED")

        await asyncio.sleep(0.2)

        # 2. Collateral
        if not SKIP.get("collateral"):
            print(f"\n[2] get_collateral() {ws_info(exchange, 'get_collateral')}")
            try:
                result = await exchange.get_collateral()
                print(f"    {result}")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print("\n[2] get_collateral() - SKIPPED")

        await asyncio.sleep(0.2)

        # 3. Mark Price
        if not SKIP.get("mark_price"):
            print(f"\n[3] get_mark_price({symbol}) {ws_info(exchange, 'get_mark_price')}")
            try:
                price = await exchange.get_mark_price(symbol)
                print(f"    Price: {price}")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[3] get_mark_price() - SKIPPED")

        await asyncio.sleep(0.2)

        # 4. Orderbook
        if not SKIP.get("orderbook"):
            print(f"\n[4] get_orderbook({symbol}) {ws_info(exchange, 'get_orderbook')}")
            try:
                result = await exchange.get_orderbook(symbol)
                if result:
                    bids = result.get("bids", [])[:2]
                    asks = result.get("asks", [])[:2]
                    print(f"    Bids: {bids}")
                    print(f"    Asks: {asks}")
                    if result.get("msg"):
                        print(f"    Note: {result.get('msg')}")
                else:
                    print(f"    (empty)")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[4] get_orderbook() - SKIPPED")

        await asyncio.sleep(0.2)

        # 5. Position
        if not SKIP.get("position"):
            print(f"\n[5] get_position({symbol}) {ws_info(exchange, 'get_position')}")
            try:
                result = await exchange.get_position(symbol)
                print(f"    {result if result else '(no position)'}")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[5] get_position() - SKIPPED")

        await asyncio.sleep(0.2)

        # 6. Open Orders
        if not SKIP.get("open_orders"):
            print(f"\n[6] get_open_orders({symbol}) {ws_info(exchange, 'get_open_orders')}")
            try:
                result = await exchange.get_open_orders(symbol)
                if result:
                    print(f"    Orders ({len(result)}):")
                    for o in result[:3]:
                        print(f"      {o}")
                    if len(result) > 3:
                        print(f"      ... and {len(result)-3} more")
                else:
                    print(f"    (no open orders)")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[6] get_open_orders() - SKIPPED")

        await asyncio.sleep(0.2)

        # 7. Limit Order (optional)
        if not SKIP.get("limit_order"):
            if price:
                l_price = price * 0.95
                print(f"\n[7] create_order({symbol}, 'buy', {AMOUNT}, price={l_price:.2f}) {ws_info(exchange, 'create_order')}")
                try:
                    result = await exchange.create_order(symbol, 'buy', AMOUNT, price=l_price)
                    print(f"    Result: {result}")
                except NotImplementedError:
                    print(f"    -> Not implemented")
                except Exception as e:
                    print(f"    ERROR: {e}")
            else:
                print(f"\n[7] create_order() - SKIPPED (no price)")
        else:
            print(f"\n[7] create_order(limit) - SKIPPED")

        await asyncio.sleep(0.3)

        # 8. Cancel Orders (optional)
        if not SKIP.get("cancel_orders"):
            print(f"\n[8] cancel_orders({symbol}) {ws_info(exchange, 'cancel_orders')}")
            try:
                open_orders = await exchange.get_open_orders(symbol)
                if open_orders:
                    result = await exchange.cancel_orders(symbol, open_orders)
                    print(f"    Cancelled: {result}")
                else:
                    print(f"    (no orders to cancel)")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[8] cancel_orders() - SKIPPED")

        await asyncio.sleep(0.3)

        # 9. Market Order (optional)
        if not SKIP.get("market_order"):
            print(f"\n[9] create_order({symbol}, 'buy', {AMOUNT}) [MARKET] {ws_info(exchange, 'create_order')}")
            try:
                result = await exchange.create_order(symbol, 'buy', AMOUNT)
                print(f"    Result: {result}")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[9] create_order(market) - SKIPPED")

        await asyncio.sleep(0.3)

        # 10. Close Position (optional)
        if not SKIP.get("close_position"):
            print(f"\n[10] close_position({symbol}) {ws_info(exchange, 'close_position')}")
            try:
                position = await exchange.get_position(symbol)
                if position and float(position.get('size', 0)) > 0:
                    result = await exchange.close_position(symbol, position)
                    print(f"    Result: {result}")
                else:
                    print(f"    (no position to close)")
            except NotImplementedError:
                print(f"    -> Not implemented")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[10] close_position() - SKIPPED")

    finally:
        print(f"\n{'='*60}")
        print(f"Closing {EXCHANGE}...")
        try:
            await exchange.close()
        except:
            pass
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
