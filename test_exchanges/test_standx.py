"""
StandX Exchange Test Script
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mpdex import create_exchange, symbol_create


async def main():
    # Import key (copy keys/copy.pk_standx.py to keys/pk_standx.py and fill in values)
    try:
        from keys.pk_standx import STANDX_KEY
    except ImportError:
        print("Please copy keys/copy.pk_standx.py to keys/pk_standx.py and fill in your credentials")
        return

    print("=== StandX Exchange Test ===\n")

    # Create exchange instance
    print("1. Creating exchange instance...")
    ex = await create_exchange("standx", STANDX_KEY)
    print(f"   Logged in: {ex._auth.is_logged_in}")
    print(f"   Available symbols: {ex.available_symbols.get('perp', [])[:5]}...")

    # Symbol
    symbol = symbol_create("standx", "BTC")
    print(f"\n2. Symbol: {symbol}")

    # Get open orders
    print(f"\n6. Getting open orders for {symbol}...")
    try:
        orders = await ex.get_open_orders(symbol)
        print(f"   Open orders: {len(orders)}")
        for o in orders[:3]:
            print(f"   - {o.get('side')} {o.get('qty')} @ {o.get('price')}")
    except Exception as e:
        print(f"   Error: {e}")

    for o in orders:
        res = await ex.cancel_orders(symbol, o)
        print(f"   Cancel orders result: {res}")
        return

    # Get mark price
    print("\n3. Getting mark price...")
    try:
        price = await ex.get_mark_price(symbol)
        print(f"   Mark price: {price}")
    except Exception as e:
        print(f"   Error: {e}")

    while True:
        # Get collateral
        print("\n4. Getting collateral...")
        try:
            coll = await ex.get_collateral()
            print(f"   Available: {coll.get('available_collateral')}")
            print(f"   Total: {coll.get('total_collateral')}")
            print(f"   Equity: {coll.get('equity')}")
            print(f"   UPNL: {coll.get('upnl')}")
        except Exception as e:
            print(f"   Error: {e}")
        return
        # Get position
        print(f"\n5. Getting position for {symbol}...")
        try:
            pos = await ex.get_position(symbol)
            if pos:
                print(f"   Side: {pos.get('side')}")
                print(f"   Size: {pos.get('size')}")
                print(f"   Entry: {pos.get('entry_price')}")
                print(f"   UPNL: {pos.get('unrealized_pnl')}")
            else:
                print("   No position")
        except Exception as e:
            print(f"   Error: {e}")

    
        print("\n3. Getting mark price...")
        try:
            price = await ex.get_mark_price(symbol)
            print(f"   Mark price: {price}")
        except Exception as e:
            print(f"   Error: {e}")
        # Get orderbook
        print(f"\n7. Getting orderbook for {symbol}...")
        try:
            book = await ex.get_orderbook(symbol)
            asks = book.get("asks", [])[:3]
            bids = book.get("bids", [])[:3]
            print(f"   Top asks: {asks}")
            print(f"   Top bids: {bids}")
        except Exception as e:
            print(f"   Error: {e}")
        
        await asyncio.sleep(0.5)
        await ex.unsubscribe_orderbook(symbol)
    # Example order (commented out for safety)
    '''
    print("\n8. Creating test order...")
    try:
        order = await ex.create_order(
            symbol=symbol,
            side="buy",
            amount=0.00025,
            price=80000,  # Limit price far from market
            order_type="limit"
        )
        print(f"   Order result: {order}")
    except Exception as e:
        print(f"   Error: {e}")
    try:
        order = await ex.create_order(
            symbol=symbol,
            side="sell",
            amount=0.0002,
            price=90000,  # Limit price far from market
            order_type="limit"
        )
        print(f"   Order result: {order}")
    except Exception as e:
        print(f"   Error: {e}")

    await asyncio.sleep(0.1)
    print("\n=== Cancel Orders ===")
    res = await ex.cancel_orders(symbol)
    print(f"\n   Cancel all orders result: {res}")

    print("\n=== Market order ===")

    try:
        order = await ex.create_order(
            symbol=symbol,
            side="buy",
            amount=0.0002,
            )
        print(f"   Order result: {order}")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n=== close position ===")
    try:
        order = await ex.close_position(
            symbol=symbol,
            )
        print(f"   Order result: {order}")
    except Exception as e:
        print(f"   Error: {e}")
    '''

    await ex.close()
if __name__ == "__main__":
    asyncio.run(main())
