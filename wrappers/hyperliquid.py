from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from .hyperliquid_ws_client import HLWSClientRaw

class HyperliquidExchange(MultiPerpDexMixin,MultiPerpDex):
	def __init__(self, 
			  wallet_address, 
			  wallet_private_key, 
			  agent_api_address,
			  agent_api_private_key,
			  *,
			  ws_client = None,
			  fetch_by_ws = False, # fetch pos, balance, and price by ws client
			  signing_method = None, # special case: superstack, tread.fi
			  ):
		pass
	
	async def create_order(self, symbol, side, amount, price=None, order_type='market'):
		pass

	async def get_position(self, symbol):
		pass
	
	async def close_position(self, symbol, position):
		pass
	
	async def get_collateral(self):
		pass
	
	async def get_open_orders(self, symbol):
		pass
	
	async def cancel_orders(self, symbol):
		pass

	async def get_mark_price(self,symbol):
		pass

	async def get_open_orders(self, symbol):
		pass
	
	async def close_position(self, symbol, position, *, is_reduce_only=False):
		pass