import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
import time
from keys.pk_hyperliquid import HYPERLIQUID_KEY, HYPERLIQUID_KEY2

# test done
coin = 'BTC'
symbol = symbol_create('hyperliquid',coin) # only perp atm
coin = 'xyz:XYZ100'
symbol2 = symbol_create('hyperliquid',coin) # only perp atm
is_spot = False

async def main():
    
    HYPERLIQUID_KEY.fetch_by_ws = True
    HYPERLIQUID_KEY.builder_fee_pair["base"] = 10
    HYPERLIQUID_KEY.builder_fee_pair["dex"] = 10 # example
    HYPERLIQUID_KEY.builder_fee_pair["xyz"] = 10 # example
    HYPERLIQUID_KEY.builder_fee_pair["vntl"] = 10 # example
    HYPERLIQUID_KEY.builder_fee_pair["flx"] = 10 # example
    hyperliquid = await create_exchange('hyperliquid',HYPERLIQUID_KEY)

    HYPERLIQUID_KEY2.fetch_by_ws = False # for rest api test
    hyperliquid2 = await create_exchange('hyperliquid',HYPERLIQUID_KEY2)

    price1 = await hyperliquid.get_mark_price(symbol,is_spot=is_spot)
    print(price1)
    price2 = await hyperliquid2.get_mark_price(symbol2,is_spot=is_spot)
    print(price2)

    await asyncio.sleep(0.5)
    res = await hyperliquid.get_collateral()
    print(res)
    res = await hyperliquid2.get_collateral()
    print(res)

    await asyncio.sleep(0.5)

    # get position
    position = await hyperliquid.get_position(symbol)
    print(position)
    position = await hyperliquid2.get_position(symbol2)
    print(position)
    await asyncio.sleep(0.5)

    open_orders = await hyperliquid.get_open_orders(symbol)
    if open_orders:
        print(len(open_orders), open_orders)
    else:
        print(open_orders)
    open_orders = await hyperliquid2.get_open_orders(symbol2)
    if open_orders:
        print(len(open_orders), open_orders)
    else:
        print(open_orders)
    await asyncio.sleep(0.5)
    
    # limit buy
    l_price = price1*0.97
    res = await hyperliquid.create_order(symbol, 'buy', 0.0002, price=l_price)
    print(res)
    await asyncio.sleep(0.5)
    
    # limit sell
    h_price = price1*1.03
    res = await hyperliquid.create_order(symbol, 'sell', 0.0002, price=h_price)
    print(res)
    await asyncio.sleep(0.5)
    
    # limit buy
    l_price = price2*0.97
    res = await hyperliquid2.create_order(symbol2, 'buy', 0.002, price=l_price)
    print(res)
    await asyncio.sleep(0.5)
    
    # limit sell
    h_price = price2*1.03
    res = await hyperliquid2.create_order(symbol2, 'sell', 0.002, price=h_price)
    print(res)
    await asyncio.sleep(0.5)

    # market buy
    res = await hyperliquid.create_order(symbol, 'buy', 0.0002)
    print(res)
    await asyncio.sleep(0.5)
        
    # market sell
    res = await hyperliquid.create_order(symbol, 'sell', 0.0002)
    print(res)
    await asyncio.sleep(0.5)

    # market buy
    res = await hyperliquid2.create_order(symbol2, 'buy', 0.002)
    print(res)
    await asyncio.sleep(0.5)
        
    # market sell
    res = await hyperliquid2.create_order(symbol2, 'sell', 0.002)
    print(res)
    await asyncio.sleep(0.5)

    await hyperliquid.close()
    await hyperliquid2.close()
    return
    # cancel all orders
    res = await hyperliquid.cancel_orders(symbol, open_orders)
    print(res)
    await asyncio.sleep(0.5)

    
    
    # position close
    res = await hyperliquid.close_position(symbol, position)
    print(res)
    
    
if __name__ == "__main__":
    asyncio.run(main())