import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_backpack import BACKPACK_KEY
# test done

coin = 'BTC'
symbol = symbol_create('backpack',coin)

async def main():
    backpack = await create_exchange('backpack',BACKPACK_KEY)
    #print(backpack)
    #position = await backpack.get_position(symbol)
    #print(position)
    
    coll = await backpack.get_collateral()
    print(coll)
    await asyncio.sleep(0.2)
    
    # limit sell
    res = await backpack.create_order(symbol, 'sell', 0.002, price=86000)
    print(res)
    await asyncio.sleep(0.2)
    
    # limit buy
    res = await backpack.create_order(symbol, 'buy', 0.002, price=80000)
    print(res)
    await asyncio.sleep(0.2)
    
    # get open orders
    res = await backpack.get_open_orders(symbol)
    print(res)
    
    # cancel
    res = await backpack.cancel_orders(symbol)
    print(res)
    await asyncio.sleep(0.2)
    
    # market buy
    res = await backpack.create_order(symbol, 'buy', 0.003)
    print(res)
    await asyncio.sleep(0.2)
        
    # market sell
    res = await backpack.create_order(symbol, 'sell', 0.002)
    print(res)
    await asyncio.sleep(0.2)
    
    # get position
    position = await backpack.get_position(symbol)
    print(position)
    await asyncio.sleep(0.2)
    
    # position close
    #res = await backpack.close_position(symbol, position)
    #print(res)
    

if __name__ == "__main__":
    asyncio.run(main())