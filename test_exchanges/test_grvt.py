import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
import logging
import time
logging.getLogger("asyncio").setLevel(logging.ERROR)
from keys.pk_grvt import GRVT_KEY

# test done
coin = 'BTC'
symbol = symbol_create('grvt',coin)

async def main():
    grvt = await create_exchange('grvt',GRVT_KEY)

    price = await grvt.get_mark_price(symbol)
    print(price)
    while False:
        position = await grvt.get_position(symbol)
        if position:
            print(position.get('size'),position.get('side'))
        o = await grvt.get_open_orders(symbol)
        if o:
            print(len(o))
            for x in o:
                print(x)
        print('waiting')
        await asyncio.sleep(0.2)

    while False:
        book = await grvt.get_orderbook(symbol)
        print(book)
        await asyncio.sleep(0.01)

    coll = await grvt.get_collateral()
    print(coll)

    # Get initial orders count
    initial_orders = await grvt.get_open_orders(symbol)
    initial_count = len(initial_orders) if initial_orders else 0
    print(f"Initial orders: {initial_count}")

    # Create order and measure time until cache updates
    
    res = await grvt.create_order(symbol, 'sell', 0.001, price=95000)
    print(f"Order created: {res}")
    start_time = time.time()
    # Poll until order appears in cache
    while True:
        orders = await grvt.get_open_orders(symbol)
        current_count = len(orders) if orders else 0
        elapsed = (time.time() - start_time) * 1000  # ms

        if current_count > initial_count:
            print(f"Order appeared in cache! Elapsed: {elapsed:.2f}ms")
            print(f"Orders: {orders}")
            break

        if elapsed > 5000:  # 5 second timeout
            print(f"Timeout! Order not appeared after {elapsed:.2f}ms")
            break

        await asyncio.sleep(0.001)  # 1ms poll

    # Cleanup: cancel orders
    orders = await grvt.get_open_orders(symbol)
    if orders:
        res = await grvt.cancel_orders(symbol, orders)
        print(f"Cancelled: {res}")

    res = await grvt.create_order(symbol, 'buy', 0.001)
    print(res)

    await asyncio.sleep(0.5)
    
    pos = await grvt.get_position(symbol)
    print(pos)
    
    res = await grvt.close_position(symbol,pos)
    print(res)

    

    await grvt.close()
    return


    
    '''
    # limit sell
    res = await grvt.create_order(symbol, 'sell', 0.001, price=110000)
    print(res)
    await asyncio.sleep(0.1)
    
    
    # limit buy
    res = await grvt.create_order(symbol, 'buy', 0.001, price=100000)
    print(res)
    await asyncio.sleep(0.1)
    
    # get_open_orders
    open_orders = await grvt.get_open_orders(symbol)
    print(open_orders)
    await asyncio.sleep(0.1)
    
    # cancel order
    res = await grvt.cancel_orders(symbol,open_orders)
    print(res)
    await asyncio.sleep(0.1)
    
    # market buy
    res = await grvt.create_order(symbol, 'buy', 0.002)
    print(res)
    await asyncio.sleep(0.1)
    
    # market sell
    res = await grvt.create_order(symbol, 'sell', 0.001)
    print(res)
    await asyncio.sleep(0.1)

    position = await grvt.get_position(symbol)
    print(position)
    await asyncio.sleep(0.1)
    
    # position close
    res = await grvt.close_position(symbol, position)
    print(res)
    '''    
    await grvt.close()

if __name__ == "__main__":
    asyncio.run(main())