from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from lighter.signer_client import SignerClient
from lighter.api.account_api import AccountApi
from lighter.api.order_api import OrderApi
import aiohttp
import time
import json
import logging

class LighterExchange(MultiPerpDexMixin, MultiPerpDex):
    def __init__(self, account_id, private_key, api_key_id, l1_address):
        logging.getLogger().setLevel(logging.WARNING)
        self.url = "https://mainnet.zklighter.elliot.ai"
        # self.chain_id = 304 # no need anymore
        self.client = SignerClient(url=self.url, private_key=private_key, account_index=account_id, api_key_index=api_key_id)
        #self.apiAccount = AccountApi(self.client.api_client)
        self.apiOrder = OrderApi(self.client.api_client)
        self.market_info = {}
        self._cached_auth_token = None
        self._auth_expiry_ts = 0
        self.l1_address = l1_address

    def get_auth(self, expiry_sec=600):
        now = int(time.time())
        if self._cached_auth_token is None or now >= self._auth_expiry_ts:
            self._auth_expiry_ts = int(expiry_sec/60)
            self._cached_auth_token, _ = self.client.create_auth_token_with_expiry(self._auth_expiry_ts)
        return self._cached_auth_token
    
    # use initialize when using main account
    async def initialize(self):
        await self.client.set_account_index()

    async def initialize_market_info(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.url}/api/v1/orderBooks") as resp:
                data = await resp.json()
                for m in data["order_books"]:
                    self.market_info[m["symbol"].upper()] = {
                        "market_id": m["market_id"],
                        "size_decimals": m["supported_size_decimals"],
                        "price_decimals": m["supported_price_decimals"]
                    }
        return self
    
    async def close(self):
        await self.client.close()
    
    async def get_mark_price(self, symbol):
        m_info = self.market_info[symbol]
        market_id = m_info["market_id"]
        res = await self.apiOrder.order_book_details(market_id=market_id)
        price = res.to_dict()["order_book_details"][0]["last_trade_price"]
        return price

    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        if price is not None:
            order_type = 'limit'
        m_info = self.market_info[symbol]
        market_index = m_info["market_id"]
        size_decimals = m_info["size_decimals"]
        price_decimals = m_info["price_decimals"]

        is_ask = 0 if side.lower() == 'buy' else 1
        order_type_code = SignerClient.ORDER_TYPE_MARKET if order_type == 'market' else SignerClient.ORDER_TYPE_LIMIT
        
        if order_type == 'market':
            time_in_force = SignerClient.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL
        else:
            time_in_force = SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME
        
        client_order_index = 0

        amount = int(round(float(amount) * (10 ** size_decimals)))

        if order_type_code == 0:
            if price is None:
                raise ValueError("Limit order requires a price.")
            price = int(round(float(price) * (10 ** price_decimals)))
        else:
            if side == 'buy':
                price = 2**63 - 1
            else:
                price = 10 ** price_decimals
            
        #print(price, amount)
        if order_type == 'market':
            order_expiry = 0
        else:
            order_expiry = int((time.time() + 60 * 60 * 24) * 1000)
            
        resp = await self.client.create_order(
            market_index=market_index,
            client_order_index=client_order_index,
            base_amount=amount,
            price=price,
            is_ask=is_ask,
            order_type= order_type_code,
            time_in_force=time_in_force,
            order_expiry=order_expiry,
        )
        # been changed to tuple
        resp = resp[1]

        try:
            parsed = json.loads(resp.message)
            return {
                "code": resp.code,
                "message": parsed,
                "tx_hash": resp.tx_hash
            }
        except Exception:
            return {
                "code": resp.code,
                "message": resp.message,
                "tx_hash": resp.tx_hash
            }
    
    def parse_position(self, pos):
        entry_price = pos['avg_entry_price']
        unrealized_pnl = pos['unrealized_pnl']
        side = 'short' if pos['sign'] == -1 else 'long'
        size = pos['position']
        if float(size) == 0:
            return None
        return {
            "entry_price": entry_price,
            "unrealized_pnl": unrealized_pnl,
            "side": side,
            "size": size
        }
        
    async def get_position(self, symbol):
        l1_address = self.l1_address
        url = f"{self.url}/api/v1/account?by=l1_address&value={l1_address}"
        headers = {"accept": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                accounts = data['accounts']
                for account in accounts:
                    
                    if account['index'] == self.client.account_index:
                        positions = account['positions']
                        for pos in positions:
                            if pos['symbol'] in symbol:
                                return self.parse_position(pos)
                return None
    
    async def close_position(self, symbol, position):
        return await super().close_position(symbol, position)

    async def get_collateral(self):
        
        l1_address = self.l1_address
        url = f"{self.url}/api/v1/account?by=l1_address&value={l1_address}"
        headers = {"accept": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                accounts = data['accounts']
                for account in accounts:
                    
                    if account['index'] == self.client.account_index:
                        total_collateral = account['total_asset_value']
                        margin_used = 0
                        for pos in account['positions']:
                            position_value = float(pos['position_value'])
                            initial_margin_fraction = float(pos['initial_margin_fraction'])/100.0
                            margin_used += position_value*initial_margin_fraction
                            
                        available_collateral = float(total_collateral)-margin_used
                        
                return {
            "available_collateral": round(float(available_collateral), 2),
            "total_collateral": round(float(total_collateral), 2)
        }
    
    async def get_open_orders(self, symbol):
        market_id = self.market_info[symbol]["market_id"]
        account_index = self.client.account_index
        auth = self.get_auth()

        try:
            response = await self.apiOrder.account_active_orders(
                account_index=account_index,
                market_id=market_id,
                auth=auth
            )
        except Exception as e:
            print(f"[get_open_orders] Error: {e}")
            return []

        return self.parse_open_orders(response.orders)

    def parse_open_orders(self, orders):
        if not orders:
            return []

        parsed = []
        for o in orders:
            # side 처리: Lighter에선 'is_ask' → True = sell, False = buy
            side = "sell" if o.is_ask else "buy"

            parsed.append({
                "id": o.order_index,  # for cancellation
                "client_order_id": o.client_order_index,
                "symbol": self._get_symbol_from_market_index(o.market_index),  # 필요 시
                "quantity": str(o.initial_base_amount),  # Decimal or string
                "price": str(o.price),
                "side": side,
                "order_type": o.type,
                "status": o.status,
                "reduce_only": o.reduce_only,
                "time_in_force": o.time_in_force
            })

        return parsed

    def _get_symbol_from_market_index(self, market_index):
        for symbol, info in self.market_info.items():
            if info.get("market_id") == market_index:
                return symbol
        return f"MARKET_{market_index}"

    async def cancel_orders(self, symbol, open_orders = None):
        if open_orders is None:
            open_orders = await self.get_open_orders(symbol)
            
        if not open_orders:
            #print(f"[cancel_orders] No open orders for {symbol}")
            return []

        market_id = self.market_info[symbol]["market_id"]

        results = []
        for order in open_orders:
            order_index = order["id"]
            try:
                resp = await self.client.cancel_order(
                    market_index=market_id,
                    order_index=order_index
                )
                resp = resp[1]
                results.append({
                    "id": order_index,
                    "status": resp.code,
                    "message": resp.message,
                    "tx_hash": resp.tx_hash
                })
            except Exception as e:
                results.append({
                    "id": order_index,
                    "status": "FAILED",
                    "message": str(e)
                })

        return results
