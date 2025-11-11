import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange
import asyncio
from keys.pk_lighter import LIGHTER_KEY

# test done

coin = 'BTC'
symbol = f'{coin}'

test_bool = {
    "limit_sell":False,
    "limit_buy":False,
    "get_open_orders":False,
    "cancel_orders":False,
    "market_buy":False,
    "market_sell":False,
    "get_position":True,
    "close_position":True,
}

async def main():
    lighter = await create_exchange('lighter',LIGHTER_KEY)

    coll = await lighter.get_collateral()
    print(coll)
    await asyncio.sleep(0.1)

    if test_bool["limit_sell"]:
        res = await lighter.create_order(symbol, 'sell', 0.001, price=110000)
        print(res)
        await asyncio.sleep(0.1)
    
    if test_bool["limit_buy"]:
        res = await lighter.create_order(symbol, 'buy', 0.001, price=100000)
        print(res)
        await asyncio.sleep(0.5)
    
    if test_bool["get_open_orders"]:
        open_orders = await lighter.get_open_orders(symbol)
        print(len(open_orders))
        print(open_orders)
        await asyncio.sleep(0.5)
    
    if test_bool["cancel_orders"]:
        res = await lighter.cancel_orders(symbol)
        print(res)
        await asyncio.sleep(0.1)

    if test_bool["market_buy"]:
        res = await lighter.create_order(symbol, 'buy', 0.001)
        print(res)
    
    if test_bool["market_sell"]:
        res = await lighter.create_order(symbol, 'sell', 0.001)
        print(res)
    
    if test_bool["get_position"]:
        position = await lighter.get_position(symbol)
        print(position)
    
    if test_bool["close_position"]:
        res = await lighter.close_position(symbol, position)
        print(res)
    
    await lighter.close()

if __name__ == "__main__":
    asyncio.run(main())