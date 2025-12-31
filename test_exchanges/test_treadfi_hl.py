import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
from keys.pk_treadfi_hl import TREADFIHL_KEY

# note:
# tread.fi it self can't close a position of small size
# they will fix it, so it's not a bug in this code

coin = 'hyna:BTC'
amount = 0.002


async def main():
    treadfi_hl = await create_exchange('treadfi.hyperliquid',TREADFIHL_KEY)
    
    quote = treadfi_hl.get_perp_quote(coin)
    symbol = symbol_create('treadfi.hyperliquid', coin, quote=quote)
    print("account_name:", treadfi_hl.account_name, "\naccount_id:", treadfi_hl.account_id)
    
    price = await treadfi_hl.get_mark_price(symbol) #,is_spot=is_spot)
    print(price)

    res = await treadfi_hl.get_collateral()
    print(res)
    await asyncio.sleep(0.5)

    res = await treadfi_hl.create_order(symbol, 'sell', amount)
    print(res)

    return

    res = await treadfi_hl.transfer_to_spot(5)
    print(res)
    await asyncio.sleep(0.5)

    res = await treadfi_hl.get_collateral()
    print(res)
    await asyncio.sleep(1.5)

    res = await treadfi_hl.transfer_to_perp(5)
    print(res)
    await asyncio.sleep(0.5)

    res = await treadfi_hl.get_collateral()
    print(res)
    await asyncio.sleep(0.5)
    #return
    #quote = treadfi_hl.get_perp_quote(symbol, need_to_convert=True)
    #print(quote)
    #return

    return

    l_price = price*0.97
    res = await treadfi_hl.create_order(symbol, 'buy', amount, price=l_price)
    print(res)
    await asyncio.sleep(0.5)
    
    # limit sell
    h_price = price*1.03
    res = await treadfi_hl.create_order(symbol, 'sell', amount, price=h_price)
    print(res)
    await asyncio.sleep(0.5)

    # market buy
    res = await treadfi_hl.create_order(symbol, 'buy', amount*2)
    print(res)
    await asyncio.sleep(0.5)
        
    # market sell
    res = await treadfi_hl.create_order(symbol, 'sell', amount)
    print(res)
    await asyncio.sleep(10.0) # front api reflect가 느림
    
    position = await treadfi_hl.get_position(symbol)
    print(position)

    res = await treadfi_hl.close_position(symbol, position)
    print(res)

    open_orders = await treadfi_hl.get_open_orders(symbol)
    if open_orders:
        print(len(open_orders),open_orders)
    
    res = await treadfi_hl.cancel_orders(symbol, open_orders)
    print(res)
    await asyncio.sleep(0.2)

    await treadfi_hl.close()

if __name__ == "__main__":
    asyncio.run(main())