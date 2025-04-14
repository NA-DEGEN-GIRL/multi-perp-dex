import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange
import asyncio
import logging
from keys.pk_paradex import PARADEX_KEY
logging.getLogger().setLevel(logging.ERROR)
# test done

coin = 'BTC'
symbol = f'{coin}-USD-PERP'

async def main():
    paradex = await create_exchange('paradex',PARADEX_KEY)

    coll = await paradex.get_collateral()
    print(coll)
    await asyncio.sleep(0.1)
    
    '''
    # limit sell
    res = await paradex.create_order(symbol, 'sell', 0.005, price=85000)
    print(res)
    await asyncio.sleep(0.1)
    
    # limit buy
    res = await paradex.create_order(symbol, 'buy', 0.005, price=80000)
    print(res)
    await asyncio.sleep(0.1)
    
    # get open orders
    open_orders = await paradex.get_open_orders(symbol)
    print(open_orders)
    await asyncio.sleep(0.1)
    
    # cancel orders
    res = await paradex.cancel_orders(symbol,open_orders)
    print(res)
    await asyncio.sleep(0.1)
    
    # market buy
    res = await paradex.create_order(symbol, 'buy', 0.005)
    print(res)
    await asyncio.sleep(0.1)
        
    # market sell
    res = await paradex.create_order(symbol, 'sell', 0.004)
    print(res)
    await asyncio.sleep(0.1)
    
    # get position
    position = await paradex.get_position(symbol)
    print(position)
    await asyncio.sleep(0.1)
    
    # open position close
    #res = await paradex.close_position(symbol, position)
    #print(res)
    '''
    await paradex.close()
    
if __name__ == "__main__":
    asyncio.run(main())