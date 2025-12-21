from abc import ABC, abstractmethod

class MultiPerpDex(ABC):
    def __init__(self):
        self.has_spot = False

    @abstractmethod
    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        pass

    @abstractmethod
    async def get_position(self, symbol):
        pass
    
    @abstractmethod
    async def close_position(self, symbol, position):
        pass
    
    @abstractmethod
    async def get_collateral(self):
        pass
    
    @abstractmethod
    async def get_open_orders(self, symbol):
        pass
    
    @abstractmethod
    async def cancel_orders(self, symbol):
        pass

    @abstractmethod
    async def get_mark_price(self,symbol):
        pass

class MultiPerpDexMixin:
    async def get_open_orders(self, symbol):
        return await self.exchange.fetch_open_orders(symbol)
    
    async def close_position(self, symbol, position, *, is_reduce_only=False):
        if not position:
            return None
        size = position.get('size')
        side = 'sell' if position.get('side').lower() in ['long','buy'] else 'buy'
        if is_reduce_only:
            return await self.create_order(symbol, side, size, price=None, order_type='market', is_reduce_only=True)
        else:
            return await self.create_order(symbol, side, size, price=None, order_type='market')