import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_backpack import BACKPACK_KEY
# test done

coin = 'BTC'
symbol = symbol_create('backpack',coin,is_spot=False)
symbol_spot = 'BTC_USDC'
async def main():
    backpack = await create_exchange('backpack',BACKPACK_KEY)
    #print(backpack)


    price = await backpack.get_mark_price(symbol)
    print(price)
    #price = await backpack.get_mark_price(symbol_spot)
    #print(price)

    res = await backpack.get_orderbook(symbol)
    print(len(res.get('bids', [])), res.get('bids', [])[:10])
    print(len(res.get('asks', [])), res.get('asks', [])[:10])

    
    coll = await backpack.get_collateral()
    print(coll)

    position = await backpack.get_position(symbol)
    print(position)
    
    ods = await backpack.get_open_orders(symbol)
    print(ods)
    return

    oid = []
    for od in ods:
        oid.append(od)
    res = await backpack.cancel_orders(symbol, oid)
    print(res)
    return 
    

    
    #print(symbol)
    #available_symbols = await backpack.get_available_symbols()
    #print(available_symbols)
    #symbol = 
    

    spot_amount = await backpack.get_spot_balance("BTC")
    print(spot_amount)
    #print(symbol)

    #res = await backpack.create_order(symbol, 'buy', 0.015) #, price=86000)
    #print(res)
    await asyncio.sleep(0.2)
    return
    
    price = await backpack.get_mark_price(symbol)
    print(price)

    coll = await backpack.get_collateral()
    print(coll)
    await asyncio.sleep(0.2)
    '''
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
    '''

if __name__ == "__main__":
    asyncio.run(main())