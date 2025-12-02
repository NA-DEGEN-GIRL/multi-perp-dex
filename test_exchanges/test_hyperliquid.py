import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
#from keys.pk_hyperliquid import HYPERLIQUID_KEY

# test done
coin = 'BTC'
symbol = symbol_create('hyperliquid',coin) # only perp atm

async def main():
    hyperliquid = await create_exchange('hyperliquid',"")

    res = await hyperliquid.init() # login and initialize
    print(hyperliquid.spot_index_to_name)
    print(hyperliquid.spot_name_to_index)


    return
    
    coll = await hyperliquid.get_collateral()
    print(coll)
    await asyncio.sleep(0.5)
    
    price = await hyperliquid.get_mark_price(symbol) # 강제 250ms 단위 fetch가 이루어짐.
    print(price)
    await asyncio.sleep(0.5)

    # limit buy
    l_price = price*0.97
    res = await hyperliquid.create_order(symbol, 'buy', 0.0002, price=l_price)
    print(res)
    await asyncio.sleep(0.5)
    
    # limit sell
    h_price = price*1.03
    res = await hyperliquid.create_order(symbol, 'sell', 0.0002, price=h_price)
    print(res)
    await asyncio.sleep(0.5)

    # get open orders
    open_orders = await hyperliquid.get_open_orders(symbol)
    print(open_orders)
    await asyncio.sleep(0.5)

    # cancel all orders
    res = await hyperliquid.cancel_orders(symbol, open_orders)
    print(res)
    await asyncio.sleep(0.5)

    # market buy
    res = await hyperliquid.create_order(symbol, 'buy', 0.003)
    print(res)
    await asyncio.sleep(0.5)
        
    # market sell
    res = await hyperliquid.create_order(symbol, 'sell', 0.002)
    print(res)
    await asyncio.sleep(5.0)
    
    # get position
    position = await hyperliquid.get_position(symbol)
    print(position)
    await asyncio.sleep(0.5)
    
    # position close
    res = await hyperliquid.close_position(symbol, position)
    print(res)
    
    # logout = just clear local cache
    res = await hyperliquid.logout()
    print(res)
if __name__ == "__main__":
    asyncio.run(main())