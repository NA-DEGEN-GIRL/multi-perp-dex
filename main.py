import asyncio
import logging
import argparse
import random
from datetime import datetime
import json
from dataclasses import dataclass
from exchange_factory import create_exchange, symbol_create
from keys.pk_backpack import BACKPACK_KEY
from keys.pk_edgex import EDGEX_KEY
from keys.pk_grvt import GRVT_KEY
from keys.pk_lighter import LIGHTER_KEY
from keys.pk_paradex import PARADEX_KEY

logging.getLogger("asyncio").setLevel(logging.ERROR)
logging.getLogger().setLevel(logging.ERROR)

# argparse to override select_module
parser = argparse.ArgumentParser()
parser.add_argument("--module", type=str, default="", help="Select module name [close,order,check,auto]")
args = parser.parse_args()

@dataclass(frozen=True)
class Module:
    GET_COLLATERAL = 'get_collateral'
    CREATE_ORDER_LIMIT = 'create_order_limit'
    GET_OPEN_ORDERS = 'get_open_orders'
    CANCEL_ORDERS = 'cancel_orders'
    CREATE_ORDER_MARKET = 'create_order_market'
    GET_POSITION = 'get_position'
    CLOSE_POSITION = 'close_position'
    GET_UNREALIZED_PNL = 'pnl'
    REDUCE_POSITION = 'reduce'

ALL_MODULES = [
    Module.GET_COLLATERAL,
    Module.CREATE_ORDER_LIMIT,
    Module.GET_OPEN_ORDERS,
    Module.CANCEL_ORDERS,
    Module.CREATE_ORDER_MARKET,
    Module.GET_POSITION,
    Module.CLOSE_POSITION,
    Module.GET_UNREALIZED_PNL,
    Module.REDUCE_POSITION
]
SLEEP_BETWEEN_CALLS = 0.2
AUTO_RUN_TIMER = [60*5, 60*10] # between 30~60min
MAX_ORDER_SIZE = 0.13

# setting parameters
coin = 'BTC'
amount = 0.06
exchange_configs = {
    'backpack': {'create': False, 'side': 'short', 'need_close': False, 'key_params': BACKPACK_KEY,'multiply':2},
    
    'edgex': {'create': True, 'side': 'long', 'need_close': False, 'key_params': EDGEX_KEY,'multiply':1},
    
    'paradex': {'create': True, 'side': 'short', 'need_close': True, 'key_params': PARADEX_KEY,'multiply':1},
    
    'lighter': {'create': False, 'side': 'long', 'need_close': True, 'key_params': LIGHTER_KEY,'multiply':1},
    
    'grvt': {'create': False, 'side': 'NA', 'need_close': True, 'key_params': GRVT_KEY,'multiply':1},
}

select_module_to_keys = {
    'all': ALL_MODULES,
    # 1 collateral check
    'get_collateral': [Module.GET_COLLATERAL], 
    # 2 check open orders
    'check_open_orders': [Module.GET_OPEN_ORDERS], 
    # 3 [1]get_collateral -> [2]get position -> [3]get unrealized pnl
    'check': [Module.GET_COLLATERAL, Module.GET_POSITION, Module.GET_UNREALIZED_PNL], 
    # 4 [1] cancel orders -> [2] check position
    'cancel_open_order': [Module.CANCEL_ORDERS, Module.GET_OPEN_ORDERS],
    # 5 [1]market order -> [2]check position -> [3]get unrealized pnl
    'order': [Module.CREATE_ORDER_MARKET, Module.GET_POSITION, Module.GET_UNREALIZED_PNL], 
    # 6 [1]check position -> [2]close position -> [3]check position
    'close': [Module.GET_POSITION, Module.CLOSE_POSITION, Module.GET_POSITION],
    # 7 [1]check position -> [2]unrealized pnl
    'pnl': [Module.GET_POSITION, Module.GET_UNREALIZED_PNL],
    # 8 [1]reduce position -> [2]check position -> [3]get unrealized pnl
    'reduce': [Module.REDUCE_POSITION, Module.GET_POSITION, Module.GET_UNREALIZED_PNL],
    
    'check_auto': [Module.GET_COLLATERAL, Module.GET_POSITION], 
    'order_auto': [Module.CREATE_ORDER_MARKET], 
    'reduce_auto': [Module.REDUCE_POSITION], 
    
}
# end of setting

market_order_params_per_exchange = {}

for k, v in exchange_configs.items():
    mul = exchange_configs[k]['multiply']
    side = 'buy' if exchange_configs[k]['side']=='long' else 'sell'
    market_order_params_per_exchange[k] = {'side':side,'amount': round(amount*mul,3)}

limit_order_params = [
    {'price': 80000, 'side': 'buy', 'amount': 0.01},
    {'price': 86000, 'side': 'sell', 'amount': 0.01},
]
limit_order_params_per_exchange = {
    name: limit_order_params
    for name in exchange_configs
}

def log_volume(exchange: str, coin: str, amount: float, is_coll_volume: bool = False, entry_price: float = 0, unrealized_pnl: float = 0):
    write_log_line(exchange, coin, amount)
    if is_coll_volume:
        update_volume_summary(exchange, coin, amount, is_coll_volume, entry_price, unrealized_pnl)

def write_log_line(exchange: str, coin: str, amount: float):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    logline = f"{now} | {exchange} | {coin} | {amount}"
    with open("volume_log.txt", "a") as f:
        f.write(logline + "\n")
        
def update_volume_summary(exchange: str, coin: str, amount: float, is_coll_volume: bool = False, entry_price: float = 0, unrealized_pnl: float = 0):
    try:
        with open("volume_summary.json", "r") as f:
            summary = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        summary = {}

    if exchange not in summary:
        summary[exchange] = {}
    if coin not in summary[exchange]:
        summary[exchange][coin] = 0.0
    if 'coll_volume' not in summary[exchange]:
        summary[exchange]['coll_volume'] = 0.0
        summary[exchange]['pnl'] = 0.0

    summary[exchange][coin] += amount * 2
    if is_coll_volume:
        summary[exchange]['coll_volume'] += round(entry_price * amount * 2 + unrealized_pnl, 2)
        summary[exchange]['pnl'] += round(unrealized_pnl, 2)
        
    with open("volume_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

def reverse_side(side:str):
    if side not in ['buy','sell']:
        raise ValueError('side must be in buy or sell')
    
    return 'buy' if side == 'sell' else 'sell'

async def run_batch(title, exchanges, handler_fn):
    print(f"\n[V] {title}")
    tasks, names = [], []
    for name, ex in exchanges.items():
        try:
            tasks.append(asyncio.create_task(handler_fn(name, ex)))
            names.append(name)
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

    results = await asyncio.gather(*tasks, return_exceptions=True)
    if title == 'Check Collaterals':
        usdc = 0
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            print(f"[ERROR] {name}: {result}")
        else:
            if title == 'Check Positions':
                try:
                    usdc_size = round(float(result['entry_price'])*float(result['size']),2)
                    usdc_size *= -1 if result['side'] == 'short' else 1
                except Exception as e:
                    usdc_size = 0
                print(f"{name}: {result} \n usdc_size: {usdc_size}")
            else:
                print(f"{name}: {len(result) if result else 0} {result}")
                if title == 'Check Collaterals':
                    try:
                        usdc += float(result['total_collateral'])
                    except Exception as e:
                        pass
                    print(f"sum: {usdc}")
                
    return dict(zip(names, results))

def select_next_module(positions):
    module_list = ['order_auto','reduce_auto']
    next_module = random.choice(module_list)
    #module_id = module_list.index(next_module)
    
    for name, v in positions.items():
        if v == None:
            return next_module
        
        eparam = market_order_params_per_exchange[name]
        
        order_side = eparam['side'] # order일때의 주문방향, rever일때는 반대
        order_amount = eparam['amount']
        
        curr_side = v['side']
        curr_size = v['size']
        
        next_amount = float(curr_size) if curr_side == 'long' else -float(curr_size)
        if next_module == 'order_auto':
            # +- real value
            next_amount += float(order_amount) if order_side == 'buy' else -float(order_amount)
        elif next_module == 'reduce_auto':
            next_amount += -float(order_amount) if order_side == 'buy' else +float(order_amount)
        
        next_amount = round(next_amount,3)
        #print("#####")
        #print(next_module,name,'order_side:',order_side,order_amount,'currside:',curr_side,curr_size,next_amount,MAX_ORDER_SIZE)
        #print("#####")
        if abs(next_amount) >= MAX_ORDER_SIZE:
            next_module = 'order_auto' if next_module == 'reduce_auto' else 'reduce_auto'
            print(f'amount will exceed maximum order amount {MAX_ORDER_SIZE}, in next order {abs(next_amount)}')
            print(f'so change to {next_module}')
            return next_module
            
    return next_module
    

async def main():
    positions = None
    run_forever = False
    if args.module == 'auto':
        print(args.module)
        run_forever = True
    
    run_cnt = 0
    while True:
        run_cnt += 1
        
        if run_forever:
            module_select = ['check_auto','random'][run_cnt%2-1]
            
            if positions is not None and module_select == 'random':
                module_select = select_next_module(positions)
                #print('')
                #print(run_cnt,next_module)
                #print('')
                if run_cnt >= 3:
                    random_sleep_time = round(random.uniform(AUTO_RUN_TIMER[0], AUTO_RUN_TIMER[1]),1)
                    print('will sleep',random_sleep_time)
                    await asyncio.sleep(random_sleep_time)
                    
            #print('autorun',module_select)
            selected_keys = select_module_to_keys.get(module_select, select_module_to_keys["get_collateral"])
            
        else:
            selected_keys = select_module_to_keys.get(args.module, select_module_to_keys["get_collateral"])
        
        print(f"[RUNNING MODULES] {', '.join(selected_keys)}")
        #if module_select == 'order' or module_select == 'reduce':
        #    continue
        
        exchanges = {
            name: await create_exchange(name, key_params=cfg['key_params'])
            for name, cfg in exchange_configs.items() if cfg['create']
        }

        open_orders = {}
        positions = {}

        for key in selected_keys:
            if key == Module.GET_COLLATERAL:
                await run_batch("Check Collaterals", exchanges, lambda n, e: e.get_collateral())

            elif key == Module.CREATE_ORDER_LIMIT:
                print('\n[V] Create Limit Orders (per exchange)')
                async def limit_order_handler(name, ex):
                    symbol = symbol_create(name, coin)
                    results = []
                    for param in limit_order_params_per_exchange.get(name, []):
                        print(' *limit order', name, param["side"], param["amount"], param['price'])
                        res = await ex.create_order(symbol, param["side"], param["amount"], param["price"], "limit")
                        results.append(res)
                    return results
                await run_batch("Create Limit Orders", exchanges, limit_order_handler)

            elif key == Module.GET_OPEN_ORDERS:
                async def get_orders(n, e):
                    symbol = symbol_create(n, coin)
                    return await e.get_open_orders(symbol)
                open_orders = await run_batch("Check Open Orders", exchanges, get_orders)

            elif key == Module.CANCEL_ORDERS:
                async def cancel(n, e):
                    symbol = symbol_create(n, coin)
                    orders = open_orders.get(n)
                    return await e.cancel_orders(symbol, orders)
                await run_batch("Cancel Orders", exchanges, cancel)

            elif key == Module.CREATE_ORDER_MARKET or key == Module.REDUCE_POSITION:
                print('\n[V] Create Market Orders (per exchange)')
                async def market_order_handler(name, ex):
                    symbol = symbol_create(name, coin)
                    results = []
                    
                    param = market_order_params_per_exchange.get(name, {})
                    order_side = reverse_side(param['side']) if key == Module.REDUCE_POSITION else param['side']
                    print(' *market order', name, order_side, param["amount"])
                    res = await ex.create_order(symbol, order_side, param["amount"], None, "market")
                    log_volume(name, coin, float(param["amount"]))
                    results.append(res)
                    return results
                await run_batch("Create Market Orders", exchanges, market_order_handler)

            elif key == Module.GET_POSITION:
                async def get_pos(n, e):
                    symbol = symbol_create(n, coin)
                    return await e.get_position(symbol)
                positions = await run_batch("Check Positions", exchanges, get_pos)
                

            elif key == Module.CLOSE_POSITION:
                async def close_pos(n, e):
                    symbol = symbol_create(n, coin)
                    pos = positions.get(n)
                    res = await e.close_position(symbol, pos)
                    if pos and res:  # 또는 res가 성공 조건일 경우 판단
                        log_volume(n,coin,float(pos.get("size",0)),True,float(pos.get("entry_price",0)),float(pos.get("unrealized_pnl",0)))
                    return res
                await run_batch("Close Positions", exchanges, close_pos)
            
            elif key == Module.GET_UNREALIZED_PNL:
                unrealized_pnl = 0
                for n in positions:
                    pos = positions[n]
                    if pos is not None:
                        unrealized_pnl += float(pos.get("unrealized_pnl",0))

                print('Unrealized PNL = ', round(unrealized_pnl,2))
            
            await asyncio.sleep(SLEEP_BETWEEN_CALLS)

        for name, ex in exchanges.items():
            if exchange_configs[name]['need_close']:
                await ex.close()
        
        if run_forever == False:
            break
        print('run complete', run_cnt)
        print('')
        await asyncio.sleep(2)

if __name__ == "__main__":
        if args.module:  # 🔸 명령이 있을 때만 실행
            asyncio.run(main())
        else:
            print('--module {명령어} 를 입력하세요')