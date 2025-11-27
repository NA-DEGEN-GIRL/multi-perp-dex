import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_treadfi import TREADFIHL_KEY
# login / logout / create_order

coin = 'BTC'
symbol = symbol_create('treadfi.hyperliquid',coin) # only perp atm

async def main():
    treadfi_hl = await create_exchange('treadfi.hyperliquid',TREADFIHL_KEY)

    # login
    res = await treadfi_hl.login()
    print(res)
    
    position = {'size':0.0003,'side':'buy'}
    res = await treadfi_hl.close_position(symbol, position)
    print(res)

    # limit buy
    #res = await treadfi_hl.create_order(symbol, 'sell', 0.00015, price=85000)
    #print(res)
    
    # logout
    #res = await treadfi_hl.logout()
    #print(res)

    #await treadfi_hl.aclose()
    #print(treadfi_hl)
    #position = await treadfi_hl.get_position(symbol)
    #print(position)
    
    '''
    price = await treadfi_hl.get_mark_price(symbol)
    print(price)

    coll = await treadfi_hl.get_collateral()
    print(coll)
    await asyncio.sleep(0.2)
    
    # limit sell
    res = await treadfi_hl.create_order(symbol, 'sell', 0.002, price=86000)
    print(res)
    await asyncio.sleep(0.2)
    
    
    
    # get open orders
    res = await treadfi_hl.get_open_orders(symbol)
    print(res)
    
    # cancel
    res = await treadfi_hl.cancel_orders(symbol)
    print(res)
    await asyncio.sleep(0.2)
    
    # market buy
    res = await treadfi_hl.create_order(symbol, 'buy', 0.003)
    print(res)
    await asyncio.sleep(0.2)
        
    # market sell
    res = await treadfi_hl.create_order(symbol, 'sell', 0.002)
    print(res)
    await asyncio.sleep(0.2)
    
    # get position
    position = await treadfi_hl.get_position(symbol)
    print(position)
    await asyncio.sleep(0.2)
    
    # position close
    #res = await treadfi_hl.close_position(symbol, position)
    #print(res)
    '''

if __name__ == "__main__":
    asyncio.run(main())