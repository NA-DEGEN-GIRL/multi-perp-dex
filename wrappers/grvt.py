from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from pysdk.grvt_ccxt_pro import GrvtCcxtPro
from pysdk.grvt_ccxt_env import GrvtEnv
import logging
from pysdk.grvt_ccxt_utils import rand_uint32
import os
import asyncio

def create_logger(name: str, filename: str, level=logging.ERROR) -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    fh = logging.FileHandler(f"logs/{filename}")
    fh.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.propagate = False
    return logger

grvt_logger = create_logger("grvt_logger", "grvt_error.log")

class GrvtExchange(MultiPerpDexMixin, MultiPerpDex):
    def __init__(self, api_key, account_id, secret_key):
        super().__init__()
        logging.getLogger().setLevel(logging.ERROR)
        self.logger = grvt_logger
        self.exchange = GrvtCcxtPro(
            GrvtEnv("prod"),
            self.logger,
            parameters={
                "api_key": api_key,
                "trading_account_id": account_id,
                "private_key": secret_key,
            }
        )
    
    async def init(self):
        await self.exchange.load_markets()        
        return self
    
    def get_perp_quote(self, symbol, *, is_basic_coll=False):
        return 'USD'
    
    async def get_mark_price(self,symbol):
        res = await self.exchange.fetch_ticker(symbol)
        return float(res['mark_price'])
    
    def parse_order(self, order):
        try:
            return order['metadata']['client_order_id']
        except Exception as e:
            print(e)
            self.logger.error(e, exc_info=True)
            return None
        
    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        params={"client_order_id": rand_uint32()}
        if price != None:
            order_type = 'limit'
            
        if order_type == 'market':
            res = await self.exchange.create_order(symbol, 'market', side, amount, price, params=params)
            return self.parse_order(res)
        
        res = await self.exchange.create_order(symbol, 'limit', side, amount, price, params=params)
        
        return self.parse_order(res)
    
    def parse_position(self, pos):
        entry_price = pos['entry_price']
        unrealized_pnl = pos['unrealized_pnl']
        side = 'short' if '-' in pos['size'] else 'long'
        size = pos['size'].replace('-','')
        return {
            "entry_price": entry_price,
            "unrealized_pnl": unrealized_pnl,
            "side": side,
            "size": size
        }
    
    async def get_position(self, symbol):
        try:
            positions = await self.exchange.fetch_positions(symbols=[symbol])    
        except Exception as e:
            print(e)
            self.logger.error(e, exc_info=True)
            return None

        if len(positions) > 1:
            self.logger.error('can not have more than 1 position', exc_info=True)
            return None
        
        if len(positions) == 0:
            return None
        
        pos = positions[0]
        return self.parse_position(pos)
    
    async def get_collateral(self):
        try:
            res = await self.exchange.get_account_summary("sub-account")
            available_collateral = round(float(res['available_balance']),2)
            total_collateral = round(float(res['total_equity']),2)
        except Exception as e:
            print(e)
            self.logger.error(e, exc_info=True)
            available_collateral = None
            total_collateral = None
            
        return {
            "available_collateral": available_collateral,
            "total_collateral": total_collateral
        }
    
    async def close_position(self, symbol, position):
        return await super().close_position(symbol, position)
    
    async def close(self):
        await self.exchange._session.close()
    
    def parse_open_orders(self, orders):
        """id, symbol, type, side, size, price"""
        if len(orders) == 0:
            return None
        parsed = []
        for order in orders:
            #print(order)
            order_id = order['order_id']
            symbol = order['legs'][0]['instrument']
            size = order['legs'][0]['size']
            price = order['legs'][0]['limit_price']
            side = 'buy' if order['legs'][0]['is_buying_asset'] else 'sell'
            parsed.append({"id": order_id, "symbol": symbol, "size": size, "price": price, "side": side})
        return parsed
    
    async def get_open_orders(self, symbol):
        orders = await super().get_open_orders(symbol)
        return self.parse_open_orders(orders)
    
    async def cancel_orders(self, symbol, open_orders = None):
        if open_orders is None:
            open_orders = await self.get_open_orders(symbol)

        if not open_orders:
            return []

        if open_orders is not None and not isinstance(open_orders, list):
            open_orders = [open_orders]

        tasks = []
        for item in open_orders:
            order_id = item['id']
            # symbol is not required actually
            tasks.append(asyncio.create_task(self.exchange.cancel_order(id=order_id)))
        return await asyncio.gather(*tasks, return_exceptions=True)
        