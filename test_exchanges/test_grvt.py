import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
import logging
logging.getLogger("asyncio").setLevel(logging.ERROR)
from keys.pk_grvt import GRVT_KEY

# test done
coin = 'BTC'
symbol = symbol_create('grvt',coin)

async def main():
    grvt = await create_exchange('grvt',GRVT_KEY)
    
    position = await grvt.get_position(symbol)
    print(position)
    
    coll = await grvt.get_collateral()
    print(coll)
    
    ''' temporary SL for my own use
    while True:
        mark_price = await grvt.get_mark_price(symbol)
        print(mark_price)
        
        if mark_price > 0.1702:
            print('SL execute!')
            res = await grvt.create_order(symbol, 'buy', 44900, price=0.1705)
            print(res)
            break
        await asyncio.sleep(0.25)
    '''
    '''
    # limit sell
    res = await grvt.create_order(symbol, 'sell', 0.001, price=86000)
    print(res)
    await asyncio.sleep(0.1)
    
    # limit buy
    res = await grvt.create_order(symbol, 'buy', 0.001, price=80000)
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
    '''
    position = await grvt.get_position(symbol)
    print(position)
    await asyncio.sleep(0.1)
    
    # position close
    #res = await grvt.close_position(symbol, position)
    #print(res)
    
    await grvt.close()

if __name__ == "__main__":
    asyncio.run(main())