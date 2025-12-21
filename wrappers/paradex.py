from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
import ccxt.async_support as ccxt  # 비동기 CCXT 지원
from starkware.crypto.signature.signature import ec_mult, ALPHA, FIELD_PRIME, EC_GEN
import asyncio

class ParadexExchange(MultiPerpDexMixin, MultiPerpDex):
    def __init__(self, wallet_address, paradex_address, paradex_private_key):
        self.exchange = ccxt.paradex({
            'walletAddress': wallet_address,
            'privateKey': int(paradex_private_key.replace('0x', ''), 16),
        })

        self.exchange.options.update({
            "paradexAccount": {
                "address": paradex_address,
                "publicKey": self.public_key_from_private_key(paradex_private_key),
                "privateKey": int(paradex_private_key.replace('0x', ''), 16),
            }
        })
        
    def public_key_from_private_key(self,private_key):
        private_key_int = int(private_key,16)
        x, _ =  ec_mult(private_key_int, EC_GEN, ALPHA, FIELD_PRIME)
        return hex(x)
        
    def parse_position(self, positions, symbol):
        if not positions:
            return None
        
        for position in positions:
            market = position.get('market')
            if market == symbol:
                break
        
        if position.get("size") == '0' or position.get("size") == 0:
            return None
        
        return {
            "entry_price": float(position.get("average_entry_price", 0)),
            "unrealized_pnl": float(position.get("unrealized_pnl", 0)),
            "side": position.get("side", "").lower(),
            "size": position.get("size").replace('-','')
        }
    
    async def get_mark_price(self, symbol):
        res = await self.exchange.fetch_ticker(symbol)
        price = res['last']
        return price
        
    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        if price != None:
            order_type = 'limit'
        
        if order_type == 'market':
            return self.parse_orders(await self.exchange.create_order(symbol, 'market', side, amount, price))
        return self.parse_orders(await self.exchange.create_order(symbol, 'limit', side, amount, price))

    def parse_orders(self, orders):
        if not orders:
            return []

        # 단일 dict일 경우 리스트로 감싸기
        if isinstance(orders, dict):
            orders = [orders]

        parsed = []
        for order in orders:
            parsed.append({
                "id": order.get("id"),
                "symbol": order.get("symbol"),
                "type": order.get("type"),
                "side": order.get("side"),
                "amount": order.get("amount"),
                "price": order.get("price")
            })

        return parsed

    
    async def get_position(self, symbol):
        await self.exchange.authenticate_rest()
        try:
            positions = await self.exchange.private_get_positions()
            return self.parse_position(positions['results'], symbol)
        except Exception as e:
            print(f"[get_position] error: {e}")
            return None
        
    
    async def close_position(self, symbol, position):
        return await super().close_position(symbol, position)
    
    async def get_collateral(self):
        await self.exchange.authenticate_rest()
        return self.parse_collateral(await self.exchange.private_get_account())
    
    def parse_collateral(self,collateral):
        available_collateral = round(float(collateral['free_collateral']),2)
        total_collateral = round(float(collateral['total_collateral']),2)
        return {
            'available_collateral':available_collateral,
            'total_collateral':total_collateral
        }
    
    async def close(self):
        return self.parse_orders(await self.exchange.close())
    
    async def get_open_orders(self, symbol):
        orders = await super().get_open_orders(symbol)
        return self.parse_orders(orders)
    
    async def cancel_orders(self, symbol, open_orders = None):
        if open_orders is None:
            open_orders = await self.get_open_orders(symbol)
            
        if not open_orders:
            #print(f"[cancel_orders] No open orders for {symbol}")
            return []

        tasks = []
        for order in open_orders:
            order_id = order["id"]
            tasks.append(asyncio.create_task(self.exchange.cancel_order(order_id)))

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            parsed_results = []
            for i, res in enumerate(results):
                order_id = open_orders[i]["id"]
                if isinstance(res, Exception):
                    print(f"[cancel_order] order_id={order_id} failed: {res}")
                    parsed_results.append({
                        "id": order_id,
                        "status": "FAILED",
                        "error": str(res)
                    })
                else:
                    parsed_results.append({
                        "id": res.get("id"),
                        "symbol": res.get("market"),
                        "type": res.get("type"),
                        "side": res.get("side"),
                        "price": res.get("price"),
                        "status": res.get("status")
                    })
            return parsed_results
        except Exception as e:
            print(f"[cancel_orders] Unexpected error: {e}")
            return []