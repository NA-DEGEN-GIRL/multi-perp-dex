import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_variational import VARIATIONAL_KEY

# test done
coin = 'BTC'
symbol = symbol_create('variational',coin) # only perp atm

async def main():
    variational = await create_exchange('variational',VARIATIONAL_KEY)

    #res = await variational.initialize() # login and initialize
    #print(res.get('ok'))
    #await asyncio.sleep(0.5)
    
    
    coll = await variational.get_collateral()
    print(coll)
    await asyncio.sleep(0.5)

    position = await variational.get_position(symbol)
    print(position)
    await asyncio.sleep(0.5)
    
    
    open_orders = await variational.get_open_orders(symbol)
    print(open_orders)
    await asyncio.sleep(0.5)

    for o in open_orders:
        res = await variational.cancel_orders(symbol, o)
        print(res)
        return 
    await asyncio.sleep(0.5)

    return
    
    price = await variational.get_mark_price(symbol) # 강제 250ms 단위 fetch가 이루어짐.
    print(price)
    await asyncio.sleep(0.5)

    # limit buy
    l_price = price*0.97
    res = await variational.create_order(symbol, 'buy', 0.0002, price=l_price)
    print(res)
    await asyncio.sleep(0.5)
    
    # limit sell
    h_price = price*1.03
    res = await variational.create_order(symbol, 'sell', 0.0002, price=h_price)
    print(res)
    await asyncio.sleep(0.5)

    # get open orders
    open_orders = await variational.get_open_orders(symbol)
    print(open_orders)
    await asyncio.sleep(0.5)

    # cancel all orders
    res = await variational.cancel_orders(symbol, open_orders)
    print(res)
    await asyncio.sleep(0.5)

    # market buy
    res = await variational.create_order(symbol, 'buy', 0.003)
    print(res)
    await asyncio.sleep(0.5)
        
    # market sell
    res = await variational.create_order(symbol, 'sell', 0.002)
    print(res)
    await asyncio.sleep(5.0)
    
    # get position
    position = await variational.get_position(symbol)
    print(position)
    await asyncio.sleep(0.5)
    
    # position close
    res = await variational.close_position(symbol, position)
    print(res)
    
    # logout = just clear local cache
    res = await variational.logout()
    print(res)
if __name__ == "__main__":
    asyncio.run(main())