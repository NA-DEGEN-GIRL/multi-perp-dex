#!/usr/bin/env python3
"""
Extended Exchange Test Script
==============================
테스트 전 SDK 설치 필요: pip install x10-python-trading-starknet
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
from exchange_factory import create_exchange, symbol_create


# ==================== 설정 ====================

COIN = "BTC"
AMOUNT = 0.0002

# Skip할 테스트들 (True = skip)
SKIP = {
    "available_symbols": False,
    "collateral": False,
    "mark_price": False,
    "orderbook": False,
    "position": False,
    "open_orders": False,
    "limit_order": False,     # 주문 생성 (주의!)
    "cancel_orders": False,   # 주문 취소
    "market_order": False,    # 시장가 주문 (주의!)
    "close_position": False,  # 포지션 종료 (주의!)
}


def ws_info(exchange, method_name: str) -> str:
    """WS 지원 여부 메시지"""
    ws_supported = getattr(exchange, 'ws_supported', {})
    if ws_supported.get(method_name) is True:
        return "[WS]"
    elif ws_supported.get(method_name) is False:
        return "[REST only]"
    return "[REST]"


async def main():
    print(f"\n{'='*60}")
    print(f"  Testing: EXTENDED")
    print(f"  Coin: {COIN}, Amount: {AMOUNT}")
    print(f"{'='*60}\n")

    # Load key
    try:
        from keys.pk_extended import EXTENDED_KEY as key
    except ImportError as e:
        print(f"ERROR: Could not load keys. Create keys/pk_extended.py from template.")
        print(f"  {e}")
        return

    # Create exchange
    try:
        exchange = await create_exchange("extended", key)
    except Exception as e:
        print(f"ERROR: Failed to create exchange: {e}")
        return
    
    symbol = symbol_create("extended", COIN)
    print(f"Symbol: {symbol}\n")

    res = await exchange.update_leverage(symbol, 50, "isolated")
    print(f"Update Leverage: {res}\n")

    res = await exchange.get_leverage_info(symbol)
    print(f"Leverage Info: {res}\n")
    await exchnage.close()
    return

    price = None

    try:
        # 1. Available Symbols
        if not SKIP.get("available_symbols"):
            print(f"[1] get_available_symbols() {ws_info(exchange, 'get_available_symbols')}")
            try:
                result = await exchange.get_available_symbols()
                perp = result.get("perp", [])
                print(f"    Perp ({len(perp)}): {perp[:5]}{'...' if len(perp) > 5 else ''}")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print("[1] get_available_symbols() - SKIPPED")

        await asyncio.sleep(0.2)
        while True:
            # 2. Collateral
            if not SKIP.get("collateral"):
                print(f"\n[2] get_collateral() {ws_info(exchange, 'get_collateral')}")
                try:
                    result = await exchange.get_collateral()
                    print(f"    {result}")
                except Exception as e:
                    print(f"    ERROR: {e}")
            else:
                print("\n[2] get_collateral() - SKIPPED")

            await asyncio.sleep(0.2)
            break

        # 3. Mark Price
        if not SKIP.get("mark_price"):
            print(f"\n[3] get_mark_price({symbol}) {ws_info(exchange, 'get_mark_price')}")
            try:
                price = await exchange.get_mark_price(symbol)
                print(f"    Price: {price}")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[3] get_mark_price() - SKIPPED")

        await asyncio.sleep(0.2)

        while True:
            # 4. Orderbook
            if not SKIP.get("orderbook"):
                print(f"\n[4] get_orderbook({symbol}) {ws_info(exchange, 'get_orderbook')}")
                try:
                    result = await exchange.get_orderbook(symbol)
                    if result:
                        bids = result.get("bids", [])[:3]
                        asks = result.get("asks", [])[:3]
                        print(f"    Bids: {bids}")
                        print(f"    Asks: {asks}")
                    else:
                        print(f"    (empty)")
                except Exception as e:
                    print(f"    ERROR: {e}")
            else:
                print(f"\n[4] get_orderbook() - SKIPPED")

            await asyncio.sleep(0.2)
            break

        while True:
            # 5. Position
            if not SKIP.get("position"):
                print(f"\n[5] get_position({symbol}) {ws_info(exchange, 'get_position')}")
                try:
                    result = await exchange.get_position(symbol)
                    print(f"    {result if result else '(no position)'}")
                except Exception as e:
                    print(f"    ERROR: {e}")
            else:
                print(f"\n[5] get_position() - SKIPPED")

            await asyncio.sleep(0.2)
            break
        
        while True:
            # 6. Open Orders
            if not SKIP.get("open_orders"):
                print(f"\n[6] get_open_orders({symbol}) {ws_info(exchange, 'get_open_orders')}")
                try:
                    result = await exchange.get_open_orders(symbol)
                    if result:
                        print(f"    Orders ({len(result)}):")
                        for o in result[:3]:
                            print(f"      {o}")
                    else:
                        print(f"    (no open orders)")
                except Exception as e:
                    print(f"    ERROR: {e}")
            else:
                print(f"\n[6] get_open_orders() - SKIPPED")

            await asyncio.sleep(0.2)
            break

        # 6. Limit Order
        if not SKIP.get("limit_order"):
            if price:
                l_price = price * 0.95
                print(f"\n[6] create_order({symbol}, 'buy', {AMOUNT}, price={l_price:.2f}) {ws_info(exchange, 'create_order')}")
                try:
                    result = await exchange.create_order(symbol, 'buy', AMOUNT, price=l_price)
                    print(f"    Result: {result}")
                except Exception as e:
                    print(f"    ERROR: {e}")
            else:
                print(f"\n[6] create_order() - SKIPPED (no price)")
            
            if price:
                l_price = price * 1.05
                print(f"\n[6] create_order({symbol}, 'sell', {AMOUNT}, price={l_price:.2f}) {ws_info(exchange, 'create_order')}")
                try:
                    result = await exchange.create_order(symbol, 'sell', AMOUNT, price=l_price)
                    print(f"    Result: {result}")
                except Exception as e:
                    print(f"    ERROR: {e}")
            else:
                print(f"\n[6] create_order() - SKIPPED (no price)")
        else:
            print(f"\n[6] create_order(limit) - SKIPPED")

        await asyncio.sleep(1.5)

        # 7. Cancel Orders
        if not SKIP.get("cancel_orders"):
            print(f"\n[7] cancel_orders({symbol}) {ws_info(exchange, 'cancel_orders')}")
            try:
                open_orders = await exchange.get_open_orders(symbol)
                if open_orders:
                    result = await exchange.cancel_orders(symbol, open_orders)
                    print(f"    Cancelled: {result}")
                else:
                    print(f"    (no orders to cancel)")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[7] cancel_orders() - SKIPPED")

        await asyncio.sleep(0.3)

        # 8. Market Order
        if not SKIP.get("market_order"):
            print(f"\n[8] create_order({symbol}, 'buy', {AMOUNT}) [MARKET] {ws_info(exchange, 'create_order')}")
            try:
                result = await exchange.create_order(symbol, 'buy', AMOUNT)
                print(f"    Result: {result}")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[8] create_order(market) - SKIPPED")

        await asyncio.sleep(0.3)

        # 9. Close Position
        if not SKIP.get("close_position"):
            print(f"\n[9] close_position({symbol}) {ws_info(exchange, 'close_position')}")
            try:
                position = await exchange.get_position(symbol)
                if position and float(position.get('size', 0)) > 0:
                    result = await exchange.close_position(symbol, position)
                    print(f"    Result: {result}")
                else:
                    print(f"    (no position to close)")
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"\n[9] close_position() - SKIPPED")

    finally:
        print(f"\n{'='*60}")
        print(f"Closing Extended...")
        try:
            await exchange.close()
        except:
            pass
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
