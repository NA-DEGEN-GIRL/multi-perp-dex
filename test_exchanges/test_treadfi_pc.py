import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_treadfi_pc import TREADFI_PC_KEY

# Test config
coin = 'BTC'
amount = 0.0002
symbol = symbol_create('treadfi.pacifica', coin)  # BTC:PERP-USDC

async def main():
    print(f"=== TreadFi.Pacifica Test ===")
    print(f"Symbol: {symbol}")
    print()

    # Initialize exchange (includes TreadFi login)
    ex = await create_exchange('treadfi.pacifica', TREADFI_PC_KEY)
    print(f"Logged in! Account ID: {ex.account_id}")
    print(f"Available symbols: {ex.available_symbols.get('perp', [])[:5]}...")
    print()

    #res = await ex.update_leverage(symbol)
    #print(f"Leverage update result: {res}")
    #return

    # Get collateral (via Pacifica WS/REST)
    coll = await ex.get_collateral()
    print(f"Collateral: {coll}")
    await asyncio.sleep(0.1)

    # Get mark price (via Pacifica WS/REST)
    price = await ex.get_mark_price(symbol)
    print(f"Mark price: {price}")
    await asyncio.sleep(0.1)

    print(f"\nFetching open orders...")
    open_orders = await ex.get_open_orders(symbol)
    print(f"Open orders: {open_orders}")
    await asyncio.sleep(0.5)

    # Cancel all orders (via TreadFi API)

    for o in open_orders:
        res = await ex.cancel_orders(symbol, o)
        print(f"Cancel result: {res}")
        return
        await asyncio.sleep(0.5)

    return

    # Get orderbook (via Pacifica WS)
    try:
        ob = await ex.get_orderbook(symbol)
        print(ob)
        #print(f"Orderbook: bids={len(ob.get('bids', []))}, asks={len(ob.get('asks', []))}")
    except Exception as e:
        print(f"Orderbook error: {e}")
    await asyncio.sleep(0.1)

    

    # Limit buy order (via TreadFi API)
    l_price = price * 0.97
    print(f"\nPlacing limit BUY at {l_price:.2f}...")
    res = await ex.create_order(symbol, 'buy', amount, price=l_price)
    print(f"Result: {res}")
    await asyncio.sleep(0.5)

    # Limit sell order (via TreadFi API)
    h_price = price * 1.03
    print(f"\nPlacing limit SELL at {h_price:.2f}...")
    res = await ex.create_order(symbol, 'sell', amount, price=h_price)
    print(f"Result: {res}")
    await asyncio.sleep(0.5)

    
    # Market buy order
    print(f"\nPlacing market BUY...")
    res = await ex.create_order(symbol, 'buy', amount*2)
    print(f"Result: {res}")
    await asyncio.sleep(0.5)

    # Market sell order
    print(f"\nPlacing market SELL...")
    res = await ex.create_order(symbol, 'sell', amount)
    print(f"Result: {res}")
    await asyncio.sleep(0.5)

    # Get open orders (via TreadFi API)
    print(f"\nFetching open orders...")
    open_orders = await ex.get_open_orders(symbol)
    print(f"Open orders: {open_orders}")
    await asyncio.sleep(0.5)

    # Cancel all orders (via TreadFi API)
    if open_orders:
        print(f"\nCancelling {len(open_orders)} orders...")
        res = await ex.cancel_orders(symbol, open_orders)
        print(f"Cancel result: {res}")
        await asyncio.sleep(0.5)

    # Get position (via Pacifica WS/REST)
    print(f"\nFetching position...")
    position = await ex.get_position(symbol)
    print(f"Position: {position}")
    await asyncio.sleep(0.5)

    # Close position if exists
    if position and float(position.get('size', 0)) > 0:
        print(f"\nClosing position...")
        res = await ex.close_position(symbol, position, is_reduce_only=True)
        print(f"Close result: {res}")

    await ex.close()
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(main())
