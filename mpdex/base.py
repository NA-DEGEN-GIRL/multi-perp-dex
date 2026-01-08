from abc import ABC, abstractmethod

class MultiPerpDex(ABC):
    def __init__(self):
        self.has_spot = False
        self.available_symbols = {}
        # WebSocket support flags for each function
        # Override in subclass if WS is implemented for that function
        self.ws_supported = {
            "get_mark_price": False,
            "get_position": False,
            "get_open_orders": False,
            "get_collateral": False,
            "get_orderbook": False,
            "create_order": False,
            "cancel_orders": False,
            "update_leverage": False,
        }

    @abstractmethod
    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        """
        If price is None, it is a market order.
        """
        pass

    @abstractmethod
    async def get_position(self, symbol):
        """
        side: long / short
        size:
        entry_price:
        unrealized_pnl:
        """
        pass
    
    @abstractmethod
    async def close_position(self, symbol, position, *, is_reduce_only=True):
        pass
    
    @abstractmethod
    async def get_collateral(self):
        pass
    
    @abstractmethod
    async def get_open_orders(self, symbol):
        """
        Output: List of open orders for the given symbol.
        Each order is a dict with at least the following keys:
            - id: Order ID
            - symbol: Trading pair symbol
            - side: 'buy' or 'sell'
            - size: Order size/amount
            - price: Order price (None for market orders)
        """
        pass
    
    @abstractmethod
    async def cancel_orders(self, symbol, open_orders = None):
        """
        Docstring for cancel_orders
        If open_orders is None, cancel all open orders for the given symbol.
        open_orders: List of orders to cancel. If provided, only these orders will be canceled.
        Each open order is a dict with at least the following keys:
            - id: Order ID
            - symbol: Trading pair symbol
            - side: 'buy' or 'sell'
            - size: Order size/amount
            - price: Order price (None for market orders)
        """
        pass

    @abstractmethod
    async def get_mark_price(self,symbol):
        pass

    @abstractmethod
    async def update_leverage(self, symbol, leverage):
        """
        Update the leverage for the given symbol.
        Returns the result of the leverage update operation.
        If leverage is none, make it MAX leverage.
        """
        pass

    @abstractmethod
    async def get_available_symbols(self):
        pass

    @abstractmethod
    async def close(self):
        """
        Close exchange connections (HTTP sessions, WebSocket clients, etc.)
        Must be called when done using the exchange to properly release resources.
        """
        pass

class MultiPerpDexMixin:
    async def update_leverage(self, symbol, leverage):
        """Default implementation: does nothing and returns None."""
        raise NotImplementedError("update_leverage method not implemented.")

    async def get_available_symbols(self):
        """
        Returns a dictionary of available trading symbols categorized by market type.
        Example output:
        {
            "perp": ["BTC-USDT", "ETH-USDT", ...],
            "spot": ["BTC/USDT", "ETH/USDT", ...]
        }
        For hyperliquid, it returns:
        {
            "perp": {dex: [symbols...] for dex in self.supported_dexes},
            "spot": [symbols...]
        }
        
        """
        if self.available_symbols == {}:
            raise NotImplementedError("get_available_symbols method not implemented.")
        
        return self.available_symbols

    async def get_open_orders(self, symbol):
        return await self.exchange.fetch_open_orders(symbol)
    
    async def close_position(self, symbol, position=None, *, is_reduce_only=True):
        if position is None:
            position = await self.get_position(symbol)
        if not position:
            return None
        size = position.get('size')
        side = 'sell' if position.get('side').lower() in ['long','buy'] else 'buy'
        return await self.create_order(symbol, side, size, price=None, order_type='market', is_reduce_only=is_reduce_only)