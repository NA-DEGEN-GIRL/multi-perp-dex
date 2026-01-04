import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_edgex import EDGEX_KEY

# test done

coin = 'SOL'
symbol = symbol_create('edgex',coin,is_spot=False)

async def main():
    edgex = await create_exchange('edgex', EDGEX_KEY)

    #available_symbols = await edgex.get_available_symbols()
    #print(available_symbols)
    #return

    coll = await edgex.get_collateral()
    print(coll)

    res = await edgex.create_order(symbol, 'buy', 0.5)
    print(res)
    return

    while True:
        price = await edgex.get_mark_price(symbol)
        print(price)

        pos = await edgex.get_position(symbol)
        if pos:
            print(pos.get('entry_price',0), pos.get('unrealized_pnl',0), pos.get('side',None), pos.get('size',0))

        o = await edgex.get_open_orders(symbol)
        if o:
            print(o)

        book = await edgex.get_orderbook(symbol,5)
        print(book)
        await asyncio.sleep(0.1)

    await edgex.close()
    return
    
    '''
    # limit sell
    res = await edgex.create_order(symbol, 'sell', 0.01, price=110000)
    print(res)
    
    # limit buy
    res = await edgex.create_order(symbol, 'buy', 0.01, price=100000)
    print(res)
    
    # get open orders
    open_orders = await edgex.get_open_orders(symbol)
    print(open_orders)

    # cancel open orders
    #res = await edgex.cancel_orders(symbol,open_orders)
    #print(res)

    # market buy
    
        
    # market sell
    res = await edgex.create_order(symbol, 'sell', 0.001)
    print(res)
    
    # get position
    position = await edgex.get_position(symbol)
    print(position)
        
    # position close
    res = await edgex.close_position(symbol, position)
    print(res)
    '''
    
if __name__ == "__main__":
    asyncio.run(main())