import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_lighter import LIGHTER_KEY

# test done

coin = 'ETH/USDC'
symbol = f'{coin}'

test_bool = {
    "limit_sell":True,
    "limit_buy":True,
    "get_open_orders":True,
    "cancel_orders":True,
    "market_buy":True,
    "market_sell":True,
    "get_position":True,
    "close_position":True,
}

async def main():
    lighter = await create_exchange('lighter',LIGHTER_KEY)

    available_symbols = await lighter.get_available_symbols()
    print(available_symbols)
    
    price = await lighter.get_mark_price(symbol)
    print(price)

    #res = await lighter.create_order(symbol, 'buy', 0.01, price=2500)
    #print(res)
    #await asyncio.sleep(0.5)
    
    coll = await lighter.get_collateral()
    print(coll)
    
    res = await lighter.get_spot_balance('ETH')
    print(res)
    return
    await asyncio.sleep(0.1)
    
    if test_bool["limit_sell"]:
        res = await lighter.create_order(symbol, 'sell', 0.001, price=89000)
        print(res)
        await asyncio.sleep(0.5)
    
    if test_bool["limit_buy"]:
        res = await lighter.create_order(symbol, 'buy', 0.001, price=85000)
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
        await asyncio.sleep(0.5)

    if test_bool["market_buy"]:
        res = await lighter.create_order(symbol, 'buy', 0.0003)
        print(res)
        await asyncio.sleep(0.5)
    
    if test_bool["market_sell"]:
        res = await lighter.create_order(symbol, 'sell', 0.0002)
        print(res)
        await asyncio.sleep(0.5)
    
    if test_bool["get_position"]:
        position = await lighter.get_position(symbol)
        print(position)
        await asyncio.sleep(0.5)
    
    if test_bool["close_position"]:
        res = await lighter.close_position(symbol, position)
        print(res)
        await asyncio.sleep(0.5)
    
    await lighter.close()


if __name__ == "__main__":
    asyncio.run(main())