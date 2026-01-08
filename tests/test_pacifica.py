import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_pacifica import PACIFICA_KEY

# test done
coin = 'BTC'
amount = 0.0002
symbol = symbol_create('pacifica',coin) # only perp atm

async def main():
    pacifica = await create_exchange('pacifica',PACIFICA_KEY)

    #res = await pacifica.init()
    #print(res.get("ok"))

    coll = await pacifica.get_collateral()
    print(coll)
    await asyncio.sleep(0.1)

    position = await pacifica.get_position(symbol)
    print(position)
    return

    #available_symbols = pacifica.available_symbols.get('perp',[])
    #print(available_symbols)

    price = await pacifica.get_mark_price(symbol) # 강제 250ms 단위 fetch가 이루어짐.
    print(price)
    await asyncio.sleep(0.1)
    
    while True:
        position = await pacifica.get_position(symbol)
        print(position)
        #await asyncio.sleep(0.5)
        
        open_orders = await pacifica.get_open_orders(symbol)
        print(open_orders)
        await asyncio.sleep(0.01)
    return
    for order in open_orders:
        # cancel all orders
        res = await pacifica.cancel_orders(symbol, order)
        print(res)
        return
    await asyncio.sleep(0.5)

    return

    #res = await pacifica.update_leverage(symbol)
    #print(res)
    #return
    
    res = await pacifica.get_orderbook(symbol)
    print(res)
    res = await pacifica.unsubscribe_orderbook(symbol)
    print(res)
    await asyncio.sleep(0.01)   

    # limit buy
    l_price = price*0.97
    res = await pacifica.create_order(symbol, 'buy', amount, price=l_price)
    print(res)
    await asyncio.sleep(0.1)
    
    # limit sell
    h_price = price*1.03
    res = await pacifica.create_order(symbol, 'sell', amount, price=h_price)
    print(res)
    await asyncio.sleep(0.5)
    
    # market buy
    res = await pacifica.create_order(symbol, 'buy', amount+0.0001)
    print(res)
    await asyncio.sleep(0.1)
        
    # market sell
    res = await pacifica.create_order(symbol, 'sell', amount)
    print(res)
    await asyncio.sleep(0.1)
    
    # get open orders
    open_orders = await pacifica.get_open_orders(symbol)
    print(open_orders)
    await asyncio.sleep(0.5)
    
    # cancel all orders
    res = await pacifica.cancel_orders(symbol, open_orders)
    print(res)
    await asyncio.sleep(0.5)
    
    # get position
    position = await pacifica.get_position(symbol)
    print(position)
    await asyncio.sleep(0.5)
    
    # close position
    res = await pacifica.close_position(symbol, position, is_reduce_only=True)
    print(res)

    await pacifica.close()
    return
    
if __name__ == "__main__":
    asyncio.run(main())