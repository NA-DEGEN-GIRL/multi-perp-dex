import base64
import time
import uuid
import nacl.signing
import aiohttp
from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin

class BackpackExchange(MultiPerpDexMixin, MultiPerpDex):
    def __init__(self,api_key,secret_key):
        self.API_KEY = api_key #API_KEY_TRADING
        self.PRIVATE_KEY = secret_key #SECRET_TRADING
        self.BASE_URL = "https://api.backpack.exchange/api/v1"
        self.COLLATERAL_SYMBOL = 'USDC'

    def _generate_signature(self, instruction):
        private_key_bytes = base64.b64decode(self.PRIVATE_KEY)
        signing_key = nacl.signing.SigningKey(private_key_bytes)
        signature = signing_key.sign(instruction.encode())
        return base64.b64encode(signature.signature).decode()

    def _format_number(self, n):
        if isinstance(n, float):
            if n.is_integer():
                return str(int(n))
            else:
                return str(n).rstrip('0').rstrip('.')
        return str(n)
    
    def parse_orders(self, orders):
        if not orders:
            return []

        # 단일 dict일 경우 → 리스트로 변환
        if isinstance(orders, dict):
            orders = [orders]

        return [
            {
                "symbol": o.get("symbol"),
                "id": o.get("id"),
                "quantity": o.get("quantity"),
                "price": o.get("price"),
                "side": o.get("side"),
                "order_type": o.get("orderType"),
            }
            for o in orders
        ]

    async def get_mark_price(self,symbol):
        async with aiohttp.ClientSession() as session:
            res = await self._get_mark_prices(session, symbol)
            price = res[0]['markPrice']
            return price

    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        if price != None:
            order_type = 'limit'
        
        client_id = uuid.uuid4().int % (2**32)
        
        order_type = 'Market' if order_type.lower() == 'market' else 'Limit'
        
        side = 'Bid' if side.lower() == 'buy' else 'Ask'

        async with aiohttp.ClientSession() as session:
            market_info = await self._get_market_info(session, symbol)
            tick_size = float(market_info['filters']['price']['tickSize'])
            step_size = float(market_info['filters']['quantity']['stepSize'])

            # ✔️ amount는 수량 자체이므로 그대로 사용 (단, stepSize에 맞춰 정리만)
            quantity = round(round(float(amount) / step_size) * step_size, len(str(step_size).split('.')[-1]))

            if order_type == "Limit":
                price = round(round(float(price) / tick_size) * tick_size, len(str(tick_size).split('.')[-1]))

            timestamp = str(int(time.time() * 1000))
            window = "5000"
            instruction_type = "orderExecute"

            order_data = {
                "clientId": client_id,
                "orderType": order_type,
                "quantity": self._format_number(quantity),
                "side": side,
                "symbol": symbol
            }
            if order_type == "Limit":
                order_data["price"] = self._format_number(price)

            sorted_data = "&".join(f"{k}={v}" for k, v in sorted(order_data.items()))
            signing_string = f"instruction={instruction_type}&{sorted_data}&timestamp={timestamp}&window={window}"
            signature = self._generate_signature(signing_string)

            headers = {
                "X-API-KEY": self.API_KEY,
                "X-SIGNATURE": signature,
                "X-TIMESTAMP": timestamp,
                "X-WINDOW": window,
                "Content-Type": "application/json; charset=utf-8"
            }

            async with session.post(f"{self.BASE_URL}/order", json=order_data, headers=headers) as resp:
                return self.parse_orders(await resp.json())

    async def get_position(self, symbol):
        timestamp = str(int(time.time() * 1000))
        window = "5000"
        instruction_type = "positionQuery"
        signing_string = f"instruction={instruction_type}&timestamp={timestamp}&window={window}"
        signature = self._generate_signature(signing_string)

        headers = {
            "X-API-KEY": self.API_KEY,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": timestamp,
            "X-WINDOW": window
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.BASE_URL}/position", headers=headers) as resp:
                positions = await resp.json()
                for pos in positions:
                    if pos["symbol"] == symbol:
                        return self.parse_position(pos)
                return None
            
    def parse_position(self,position):
        if not position:
            return None
        #print(position)
        size = position['netQuantity']
        side = 'short' if '-' in size else 'long'
        size = size.replace('-','')
        entry_price = position['entryPrice']
        # Not exactly. Our system has real timesettlement. 
        # # That quantity is the amount that's been extracted out of the position and settled into physical USDC.
        unrealized_pnl = position['pnlRealized'] # here is different from other exchanges
        
        return {
            "entry_price": entry_price,
            "unrealized_pnl": unrealized_pnl,
            "side": side,
            "size": size
        }
        
    async def get_collateral(self):
        timestamp = str(int(time.time() * 1000))
        window = "5000"
        instruction_type = "collateralQuery"
        
        signing_string = f"instruction={instruction_type}&timestamp={timestamp}&window={window}"
        
        signature = self._generate_signature(signing_string)

        headers = {
            "X-API-KEY": self.API_KEY,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": timestamp,
            "X-WINDOW": window
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.BASE_URL}/capital/collateral", headers=headers) as resp:
                return self.parse_collateral(await resp.json())
                
    def parse_collateral(self,collateral):
        coll_return = {
            'available_collateral':round(float(collateral['netEquityAvailable']),2),
            'total_collateral':round(float(collateral['assetsValue']),2),
        }
        return coll_return

    async def _get_mark_prices(self, session, symbol):
        """
        [{'fundingRate': '0.0000125', 'indexPrice': '95049.3749273', 'markPrice': '95075.00410592', 'nextFundingTimestamp': 1763362800000, 'symbol': 'BTC_USDC_PERP'}]
        """
        url = f"{self.BASE_URL}/markPrices"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        params = {"symbol": symbol}
        async with session.get(url, headers=headers, params=params) as resp:
            return await resp.json()
    
    async def _get_market_info(self, session, symbol):
        url = f"{self.BASE_URL}/market"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        params = {"symbol": symbol}
        async with session.get(url, headers=headers, params=params) as resp:
            return await resp.json()

    async def close_position(self, symbol, position):
        return await super().close_position(symbol, position)
    
    async def cancel_orders(self, symbol, positions=None):
        # do not use positions, just made it for pass the func
        async with aiohttp.ClientSession() as session:
            timestamp = str(int(time.time() * 1000))
            window = "5000"
            instruction_type = "orderCancelAll"
            order_data = {"symbol": symbol}
            sorted_data = "&".join(f"{k}={v}" for k, v in sorted(order_data.items()))
            signing_string = f"instruction={instruction_type}&{sorted_data}&timestamp={timestamp}&window={window}"
            signature = self._generate_signature(signing_string)
            headers = {
                "X-API-KEY": self.API_KEY,
                "X-SIGNATURE": signature,
                "X-TIMESTAMP": timestamp,
                "X-WINDOW": window,
                "Content-Type": "application/json; charset=utf-8"
            }
            async with session.delete(f"{self.BASE_URL}/orders", headers=headers, json=order_data) as response:
                return self.parse_orders(await response.json())
    
    async def get_open_orders(self, symbol):
        async with aiohttp.ClientSession() as session:
            timestamp = str(int(time.time() * 1000))
            window = "5000"
            instruction_type = "orderQueryAll"
            market_type = "PERP"  # 🔹 중요: PERP 마켓 지정

            params = {
                "marketType": market_type,
                "symbol": symbol
            }
            sorted_data = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            signing_string = f"instruction={instruction_type}&{sorted_data}&timestamp={timestamp}&window={window}"
            signature = self._generate_signature(signing_string)

            headers = {
                "X-API-KEY": self.API_KEY,
                "X-SIGNATURE": signature,
                "X-TIMESTAMP": timestamp,
                "X-WINDOW": window
            }

            url = f"{self.BASE_URL}/orders"

            async with session.get(url, headers=headers, params=params) as resp:
                return self.parse_orders(await resp.json())