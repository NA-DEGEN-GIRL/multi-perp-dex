import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from exchange_factory import create_exchange, symbol_create
import asyncio
import time
from keys.pk_hyperliquid import HYPERLIQUID_KEY, HYPERLIQUID_KEY2
from keys.pk_superstack import SUPERSTACK_KEY

# test done except spot order
# test done superstack perp

coin1 = 'xyz:COPPER'
amount1 = 0.0002
symbol = symbol_create('hyperliquid',coin1) # only perp atm

coin2 = 'xyz:XYZ100'
amount2 = 0.002
symbol2 = symbol_create('hyperliquid',coin2) # only perp atm

#is_spot = False

test_bool = [True, True, False]

async def main():
    
    #HYPERLIQUID_KEY.builder_fee_pair["base"] = (10, 10)
    HYPERLIQUID_KEY.proxy = None
    hyperliquid = await create_exchange('hyperliquid',HYPERLIQUID_KEY)
    await asyncio.sleep(0.5)

    res = await hyperliquid.get_position(symbol)
    print(res)

    #res = await hyperliquid.update_leverage(symbol, 40,'cross')
    #print(res)

    res = await hyperliquid.get_leverage_info(symbol)
    print(res)

    await hyperliquid.close()
    return

    #res = await hyperliquid.get_available_symbols()
    #for s in res:
    #    print(res[s])
    
    
    while False:
        res = await hyperliquid.get_orderbook('xyz:XYZ100')
        print(res.get('bids', [])[:1], res.get('asks', [])[:1])
        await asyncio.sleep(0.01)

    price1 = await hyperliquid.get_mark_price(symbol) #,is_spot=is_spot)
    
    l_price = price1*0.97
    res = await hyperliquid.create_order(symbol, 'buy', amount1, price=l_price)
    print(res)
    #await asyncio.sleep(0.5)
    while True:
        res = await hyperliquid.get_open_orders(symbol)
        print(res)
        await asyncio.sleep(0.01)
    return
    #print(len(res), [od.get('id') for od in res if len(res)>0])
    #for od in res:
    #    res = await hyperliquid.cancel_orders(symbol, od)
    #    print(res)

    #res2 = await hyperliquid.unsubscribe_orderbook('UBTC/USDC')
    #print(res2)
    #await asyncio.sleep(0.2)
    

    # superstack test
    #superstack = await create_exchange('superstack',SUPERSTACK_KEY)
    #await asyncio.sleep(0.2)

    res = await hyperliquid.get_collateral()
    print(res)
    
    #res = await hyperliquid.transfer_to_spot(10)
    #print(res)
    #await asyncio.sleep(0.5)


    #price1 = await hyperliquid.get_mark_price("UBTC/USDC") #,is_spot=is_spot)
    #print(price1)

    #l_price = price1*0.97
    #res = await hyperliquid.create_order("UBTC/USDC", 'buy', amount1, price=l_price)
    #print(res)
    return
    
    while False:
        res = await hyperliquid.update_leverage(symbol)
        print(res)
        print(hyperliquid._leverage_updated_to_max)
        res = await superstack.update_leverage(symbol2)
        print(res)
        print(superstack._leverage_updated_to_max)
        await asyncio.sleep(0.01)
        price1 = await hyperliquid.get_mark_price(symbol) #,is_spot=is_spot)
        print(price1)
        price2 = await superstack.get_mark_price(symbol2) #,is_spot=is_spot)
        print(price2)
        return
    #return
    
    HYPERLIQUID_KEY2.fetch_by_ws = True # for rest api test
    hyperliquid2 = await create_exchange('hyperliquid',HYPERLIQUID_KEY2)
    await asyncio.sleep(0.2)
    

    price1 = await hyperliquid.get_mark_price(symbol) #,is_spot=is_spot)
    print(price1)
    price2 = await hyperliquid2.get_mark_price(symbol2) #,is_spot=is_spot)
    print(price2)
    price2 = await superstack.get_mark_price(symbol2) #,is_spot=is_spot)
    print(price2)

    res = await hyperliquid.get_collateral()
    print(res)
    res = await hyperliquid2.get_collateral()
    print(res)
    res = await superstack.get_collateral()
    print(res)
    
    #print(hyperliquid.get_perp_quote(symbol))
    #print(hyperliquid2.get_perp_quote(symbol2))
    #print(superstack.get_perp_quote(symbol2))
    #return
    await asyncio.sleep(0.5)

    if test_bool[0]:
        # limit buy
        l_price = price1*0.97
        res = await hyperliquid.create_order(symbol, 'buy', amount1, price=l_price)
        print(res)
        await asyncio.sleep(0.5)
        
        # limit sell
        h_price = price1*1.03
        res = await hyperliquid.create_order(symbol, 'sell', amount1, price=h_price)
        print(res)
        await asyncio.sleep(0.5)
    
    if test_bool[1]:
        # limit buy
        l_price = price2*0.97
        res = await hyperliquid2.create_order(symbol2, 'buy', amount2, price=l_price)
        print(res)
        await asyncio.sleep(0.5)
        
        # limit sell
        h_price = price2*1.03
        res = await hyperliquid2.create_order(symbol2, 'sell', amount2, price=h_price)
        print(res)
        await asyncio.sleep(0.5)

    if test_bool[2]:
        # limit buy
        l_price = price2*0.97
        res = await superstack.create_order(symbol2, 'buy', amount2, price=l_price)
        print(res)
        await asyncio.sleep(0.5)
        
        # limit sell
        h_price = price2*1.03
        res = await superstack.create_order(symbol2, 'sell', amount2, price=h_price)
        print(res)
        await asyncio.sleep(0.5)
    
    if test_bool[0]:
        # market buy
        res = await hyperliquid.create_order(symbol, 'buy', amount1*1.5)
        print(res)
        await asyncio.sleep(0.5)
            
        # market sell
        res = await hyperliquid.create_order(symbol, 'sell', amount1)
        print(res)
        await asyncio.sleep(0.5)

    if test_bool[1]:
        # market buy
        res = await hyperliquid2.create_order(symbol2, 'buy', amount2*1.5)
        print(res)
        await asyncio.sleep(0.5)
            
        # market sell
        res = await hyperliquid2.create_order(symbol2, 'sell', amount2)
        print(res)
        await asyncio.sleep(0.5)

    if test_bool[2]:
        # market buy
        res = await superstack.create_order(symbol2, 'buy', amount2*1.5)
        print(res)
        await asyncio.sleep(0.5)
            
        # market sell
        res = await superstack.create_order(symbol2, 'sell', amount2)
        print(res)
        await asyncio.sleep(0.5)

    if test_bool[0]:
        open_orders = await hyperliquid.get_open_orders(symbol)
        if open_orders:
            print(len(open_orders), open_orders)
        else:
            print(open_orders)

    if test_bool[1]:
        open_orders2 = await hyperliquid2.get_open_orders(symbol2)
        if open_orders2:
            print(len(open_orders2), open_orders2)
        else:
            print(open_orders2)

    if test_bool[2]:
        open_orders3 = await superstack.get_open_orders(symbol2)
        if open_orders3:
            print(len(open_orders3), open_orders3)
        else:
            print(open_orders3)
        await asyncio.sleep(0.5)

    if test_bool[0]:
        # cancel all orders
        res = await hyperliquid.cancel_orders(symbol, open_orders)
        print(res)
        await asyncio.sleep(0.5)

    if test_bool[1]:
        res = await hyperliquid2.cancel_orders(symbol2, open_orders2)
        print(res)
        await asyncio.sleep(0.5)
    
    if test_bool[2]:
        res = await superstack.cancel_orders(symbol2, open_orders3)
        print(res)
        await asyncio.sleep(0.5)

    if test_bool[0]:
        position = await hyperliquid.get_position(symbol)
        print(position)
    if test_bool[1]:
        position2 = await hyperliquid2.get_position(symbol2)
        print(position2)
    if test_bool[2]:
        position3 = await superstack.get_position(symbol2)
        print(position3)
    await asyncio.sleep(0.5)
    
    if test_bool[0]:
        res = await hyperliquid.close_position(symbol, position)
        print(res)

    if test_bool[1]:
        res = await hyperliquid2.close_position(symbol2, position2)
        print(res)

    if test_bool[2]:
        res = await superstack.close_position(symbol2, position3)
        print(res)

    await hyperliquid.close()
    await hyperliquid2.close()
    await superstack.close()
    
if __name__ == "__main__":
    asyncio.run(main())