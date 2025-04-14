import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange
import asyncio
from keys.pk_lighter import LIGHTER_KEY
# test done
coin = 'BTC'
symbol = f'{coin}'

async def main():
    lighter = await create_exchange('lighter',LIGHTER_KEY)

    coll = await lighter.get_collateral()
    print(coll)
    await asyncio.sleep(0.1)
    
    '''
    # limit sell
    res = await lighter.create_order(symbol, 'sell', 0.001, price=85000)
    print(res)
    await asyncio.sleep(0.1)
    
    # limit buy
    res = await lighter.create_order(symbol, 'buy', 0.001, price=80000)
    print(res)
    await asyncio.sleep(0.1)
    '''
    # get open orders
    open_orders = await lighter.get_open_orders(symbol)
    print(open_orders)
    await asyncio.sleep(0.1)
    ''' 
    # cancel orders
    res = await lighter.cancel_orders(symbol,open_orders)
    print(res)
    await asyncio.sleep(0.1)
    
    # market buy
    res = await lighter.create_order(symbol, 'buy', 0.002)
    print(res)
        
    # market sell
    res = await lighter.create_order(symbol, 'sell', 0.001)
    print(res)
    '''
    # get position
    position = await lighter.get_position(symbol)
    print(position)
    
    # open position close
    #res = await lighter.close_position(symbol, position)
    #print(res)
    
    await lighter.close()

if __name__ == "__main__":
    asyncio.run(main())