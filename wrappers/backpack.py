import base64
import time
import uuid
import nacl.signing
import aiohttp
from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Any

from wrappers.backpack_ws_client import WS_POOL, BackpackWSClient

class BackpackExchange(MultiPerpDexMixin, MultiPerpDex):
    def __init__(self,api_key,secret_key):
        super().__init__()
        self.has_spot = True
        self.API_KEY = api_key #API_KEY_TRADING
        self.PRIVATE_KEY = secret_key #SECRET_TRADING
        self.BASE_URL = "https://api.backpack.exchange/api/v1"
        self.COLLATERAL_SYMBOL = 'USDC'
        self._ws_client: Optional[BackpackWSClient] = None

    async def init(self):
        await self.update_avaiable_symbols()
        self._ws_client = await WS_POOL.acquire()
        return self

    async def update_avaiable_symbols(self):
        self.available_symbols['perp'] = []
        self.available_symbols['spot'] = []

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.BASE_URL}/markets") as resp:
                result = await resp.json()
                for v in result:
                    symbol = v.get("symbol")
                    base_symbol = v.get("baseSymbol")
                    quote = v.get("quoteSymbol")
                    market_type = v.get("marketType")
                    if market_type == 'PERP':
                        composite_symbol = f"{base_symbol}-{quote}"
                        self.available_symbols['perp'].append(composite_symbol)
                    else:
                        composite_symbol = f"{base_symbol}/{quote}"
                        self.available_symbols['spot'].append(composite_symbol)
                        #print(v)
                        #break
                    #print(market_type,base_symbol,quote,symbol)
        

    def _generate_signature(self, instruction):
        private_key_bytes = base64.b64decode(self.PRIVATE_KEY)
        signing_key = nacl.signing.SigningKey(private_key_bytes)
        signature = signing_key.sign(instruction.encode())
        return base64.b64encode(signature.signature).decode()

    @staticmethod
    def _to_decimal(v) -> Decimal:
        """
        float/int/str → Decimal 변환.
        - float일 경우 repr() 대신 format(v, 'f')로 고정소수점 문자열을 만든 뒤 Decimal로 변환
        - 이미 Decimal이면 그대로 반환
        """
        if isinstance(v, Decimal):
            return v
        if isinstance(v, float):
            # format(0.00002, 'f') → '0.000020' (지수 표기 없음)
            return Decimal(format(v, 'f'))
        # int, str 등
        return Decimal(str(v))

    def _format_number(self, n, step: str | None = None) -> str:
        """
        Decimal/float/int → 고정소수점 문자열 (지수 표기 없음).
        - step이 주어지면 해당 소수점 자릿수에 맞춰 quantize (ROUND_DOWN)
        - trailing zeros 제거
        """
        d = self._to_decimal(n)

        if step:
            step_d = self._to_decimal(step)
            d = d.quantize(step_d, rounding=ROUND_DOWN)

        s = format(d, 'f')  # 고정 소수점

        # trailing zeros 정리
        if '.' in s:
            s = s.rstrip('0').rstrip('.')

        return s
    
    def get_perp_quote(self, symbol, *, is_basic_coll=False):
        return 'USDC'
    
    async def get_spot_balance(self, coin: str = None) -> dict:
        """
        GET /api/v1/capital (instruction: balanceQuery)
        
        응답 예시:
        {
          "BTC": { "available": "0.1", "locked": "0.01", "staked": "0" },
          "USDC": { "available": "1000", "locked": "50", "staked": "0" },
          ...
        }
        
        반환:
        - coin이 None: { "BTC": { available, locked, staked, total }, "USDC": {...}, ... }
        - coin이 지정됨: { "BTC": { available, locked, staked, total } } (해당 코인만)
        - 코인이 없으면 빈 dict 반환
        """
        if coin:
            if "/" in coin: # symbol 형태로 들어온 경우
                coin = coin.split("/")[0]

        timestamp = str(int(time.time() * 1000))
        window = "5000"
        instruction_type = "balanceQuery"

        signing_string = f"instruction={instruction_type}&timestamp={timestamp}&window={window}"
        signature = self._generate_signature(signing_string)

        headers = {
            "X-API-KEY": self.API_KEY,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": timestamp,
            "X-WINDOW": window,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.BASE_URL}/capital", headers=headers) as resp:
                # 에러 응답 처리
                if resp.status >= 400:
                    ct = (resp.headers.get("content-type") or "").lower()
                    if "application/json" in ct:
                        body = await resp.json()
                    else:
                        body = await resp.text()
                    raise RuntimeError(f"get_spot_balance failed: {resp.status} {body}")

                data = await resp.json()

        # data: { "COIN": { "available": str, "locked": str, "staked": str }, ... }
        if not isinstance(data, dict):
            return {}

        def _parse_balance(bal: dict) -> dict:
            avail = self._to_decimal(bal.get("available") or "0")
            locked = self._to_decimal(bal.get("locked") or "0")
            staked = self._to_decimal(bal.get("staked") or "0")
            total = avail + locked + staked
            return {
                "available": float(avail),
                "locked": float(locked),
                "staked": float(staked),
                "total": float(total),
            }

        # 특정 코인만 요청
        if coin is not None:
            coin_upper = coin.upper()
            if coin_upper in data and isinstance(data[coin_upper], dict):
                return {coin_upper: _parse_balance(data[coin_upper])}
            return {coin_upper: {
                "available": 0,
                "locked": 0,
                "staked": 0,
                "total": 0,
            }}

        # 전체 반환
        result = {}
        for c, bal in data.items():
            if isinstance(bal, dict):
                result[c] = _parse_balance(bal)

        return result

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
                "size": o.get("quantity"),
                "price": o.get("price"),
                "side": o.get("side"),
                "order_type": o.get("orderType"),
            }
            for o in orders
        ]

    async def get_mark_price(self, symbol):
        """Get mark price via WS (preferred) or REST fallback"""
        # Try WS first
        if self._ws_client:
            price = self._ws_client.get_mark_price(symbol)
            if price is not None:
                return price

            # Subscribe and wait for data
            await self._ws_client.subscribe_mark_price(symbol)
            ready = await self._ws_client.wait_price_ready(symbol, timeout=3.0)
            if ready:
                price = self._ws_client.get_mark_price(symbol)
                if price is not None:
                    return price

        # Fallback to REST
        return await self.get_mark_price_rest(symbol)

    async def get_mark_price_rest(self, symbol):
        """Get mark price via REST API"""
        async with aiohttp.ClientSession() as session:
            res = await self._get_mark_prices(session, symbol)
            if isinstance(res, list):
                # perp
                price = res[0]['markPrice']
            else:
                # spot
                price = res['lastPrice']
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
                       
            step_d = self._to_decimal(step_size)
            amount_d = self._to_decimal(amount)
            quantity_d = (amount_d / step_d).to_integral_value(rounding=ROUND_DOWN) * step_d
            quantity_str = self._format_number(quantity_d, step_size)

            price_str = None
            if order_type == "Limit":
                tick_d = self._to_decimal(tick_size)
                price_d = self._to_decimal(price)
                price_d = (price_d / tick_d).to_integral_value(rounding=ROUND_DOWN) * tick_d
                price_str = self._format_number(price_d, tick_size)

            timestamp = str(int(time.time() * 1000))
            window = "5000"
            instruction_type = "orderExecute"
            #print(quantity_str,price_str)
            #return
            order_data = {
                "clientId": client_id,
                "orderType": order_type,
                "quantity": quantity_str,
                "side": side,
                "symbol": symbol
            }
            if order_type == "Limit":
                order_data["price"] = price_str #self._format_number(price)

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
        is_spot = "PERP" not in symbol
        if is_spot:
            url = f"{self.BASE_URL}/ticker"
        else:
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

    async def get_orderbook(self, symbol) -> Optional[Dict[str, Any]]:
        """Get orderbook via WS"""
        if not self._ws_client:
            self._ws_client = await WS_POOL.acquire()

        # Check if already have data
        orderbook = self._ws_client.get_orderbook(symbol)
        if orderbook is not None:
            return orderbook

        # Subscribe and wait for data
        await self._ws_client.subscribe_orderbook(symbol)
        ready = await self._ws_client.wait_orderbook_ready(symbol, timeout=3.0)
        if ready:
            return self._ws_client.get_orderbook(symbol)
        return None

    async def unsubscribe_orderbook(self, symbol) -> None:
        """Unsubscribe from orderbook WS"""
        if self._ws_client:
            await self._ws_client.unsubscribe_orderbook(symbol)

    async def close(self):
        """Close the exchange connection"""
        # WS pool manages lifecycle, we just release our reference
        self._ws_client = None
    
    async def cancel_orders(self, symbol, open_orders=None):
        if open_orders is not None and not isinstance(open_orders, list):
            open_orders = [open_orders]

        if open_orders is not None:
            # Cancel specific orders by ID
            async with aiohttp.ClientSession() as session:
                results = []
                for open_order in open_orders:
                    timestamp = str(int(time.time() * 1000))
                    window = "5000"
                    instruction_type = "orderCancel"
                    oid = open_order.get("id")
                    symbol = open_order.get("symbol")
                    order_data = {"orderId": oid, "symbol": symbol}
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
                    async with session.delete(f"{self.BASE_URL}/order", headers=headers, json=order_data) as response:
                        results.append(self.parse_orders(await response.json()))
                results = [d for sub in results for d in sub]
                return results
        
        # Cancel all orders for the given symbol
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