from abc import ABC, abstractmethod

class MultiPerpDex(ABC):
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
    
class MultiPerpDexMixin:
    async def get_open_orders(self, symbol):
        return await self.exchange.fetch_open_orders(symbol)
    
    async def close_position(self, symbol, position):
        if not position:
            return None
        size = position.get('size')
        side = 'sell' if position.get('side') == 'long' else 'buy'
        return await self.create_order(symbol, side, size, price=None, order_type='market')