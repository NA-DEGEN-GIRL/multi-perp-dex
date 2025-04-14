from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
import time
import aiohttp
import uuid
import hashlib
from eth_hash.auto import keccak  # 꼭 이걸 써야 함
from starkware.crypto.signature.fast_pedersen_hash import pedersen_hash
from starkware.crypto.signature.signature import sign, ec_mult, verify, ALPHA, FIELD_PRIME, EC_GEN
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
import asyncio

class EdgexExchange(MultiPerpDexMixin, MultiPerpDex):
    def __init__(self,account_id,private_key):
        self.base_url = 'https://pro.edgex.exchange'
        self.account_id = account_id
        self.private_key_hex = private_key.replace("0x", "")
                
        self.K_MODULUS = int("0800000000000010ffffffffffffffffb781126dcae7b2321e66a241adc64d2f", 16)
        self.market_info = {}  # symbol → metadata
        self.usdt_coin_id = '1000'
    
    async def init(self):
        await self.get_meta_data()
        return self

    def round_step_size(self, value: Decimal, step_size: str) -> Decimal:
        step = Decimal(step_size)
        precision = abs(step.as_tuple().exponent)
        return value.quantize(step, rounding=ROUND_DOWN)
    
    async def get_meta_data(self):
        url = f"{self.base_url}/api/v1/public/meta/getMetaData"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    #print(f"[get_meta_data] HTTP {resp.status}")
                    return None
                res = await resp.json()
                data = res.get("data", {})
                meta = data
                contract_list = data.get("contractList", [])

                for contract in contract_list:
                    name = contract["contractName"]
                    self.market_info[name] = {
                        "contract": contract,
                        "meta": meta,
                        "contractId": contract["contractId"],
                        "tickSize": contract["tickSize"],
                        "stepSize": contract["stepSize"],
                        "minOrderSize": contract["minOrderSize"],
                        "maxOrderSize": contract["maxOrderSize"],
                        "defaultTakerFeeRate": contract["defaultTakerFeeRate"],
                    }

                return contract_list
    
    def generate_signature(self, method, path, params, timestamp=None):
        if not timestamp:
            timestamp = str(int(time.time() * 1000))
        
        sorted_items = sorted(params.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
        
        message = timestamp+method+path+param_str
        msg_bytes = message.encode("utf-8")
        
        msg_hash = int.from_bytes(keccak(msg_bytes), "big")
        msg_hash = msg_hash % self.K_MODULUS # FIELD_PRIME
        
        private_key_int = int(self.private_key_hex, 16)
        
        r, s = sign(msg_hash, private_key_int)
        _, y =  ec_mult(private_key_int, EC_GEN, ALPHA, FIELD_PRIME)
        
        y_hex = y.to_bytes(32, "big").hex()
        
        stark_signature = r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex() + y_hex
        
        return stark_signature, timestamp

    async def create_order(self, symbol, side, amount, price=None, order_type='market'):
        LIMIT_ORDER_WITH_FEES = 3
        if price != None:
            order_type = 'limit'
            
        contract_info = self.market_info[symbol]
        contract_id = contract_info['contractId']
        tick_size = Decimal(contract_info['tickSize'])
        step_size = contract_info['stepSize']
        resolution = Decimal(int(contract_info['contract']['starkExResolution'], 16))
        fee_rate = Decimal(contract_info['defaultTakerFeeRate'])

        # Oracle price fetch
        oracle_url = f"{self.base_url}/api/v1/public/quote/getTicker"
        async with aiohttp.ClientSession() as session:
            async with session.get(oracle_url, params={"contractId": contract_id}) as resp:
                ticker_data = await resp.json()
                oracle_price = Decimal(ticker_data["data"][0]["oraclePrice"])

        # Price calculation
        if order_type.upper() == 'MARKET':
            if side.upper() == 'BUY':
                price = oracle_price * Decimal("1.1")
                price = price.quantize(tick_size, rounding=ROUND_HALF_UP)
            else:
                price = tick_size
        else:
            price = Decimal(price).quantize(tick_size, rounding=ROUND_HALF_UP)

        value = price * Decimal(amount)
        value = self.round_step_size(value, '0.0001')
        size = Decimal(amount)
        size = self.round_step_size(size, step_size)
        
        time_in_force = 'IMMEDIATE_OR_CANCEL' if order_type.upper() == 'MARKET' else 'GOOD_TIL_CANCEL'
        is_buy = side.upper() == 'BUY'

        client_order_id = str(uuid.uuid4())
        l2_nonce = int(hashlib.sha256(client_order_id.encode()).hexdigest()[:8], 16)
        l2_expire_time = str(int(time.time() * 1000) + 14 * 24 * 60 * 60 * 1000)
        expire_time = str(int(l2_expire_time) - 10 * 24 * 60 * 60 * 1000)

        amt_synth = int((size * resolution).to_integral_value())
        amt_coll = int((value * Decimal("1e6")).to_integral_value())
        amt_fee = int((value * fee_rate * Decimal("1e6")).to_integral_value())
        expire_ts = int(int(l2_expire_time) / (1000 * 60 * 60))

        asset_id_synth = int(contract_info['contract']['starkExSyntheticAssetId'], 16)
        asset_id_coll = int(contract_info['meta']['global']['starkExCollateralCoin']['starkExAssetId'], 16)

        # L2 order hash
        h = pedersen_hash(asset_id_coll if is_buy else asset_id_synth,
                          asset_id_synth if is_buy else asset_id_coll)
        h = pedersen_hash(h, asset_id_coll)
        packed_0 = (amt_coll if is_buy else amt_synth)
        packed_0 = (packed_0 << 64) + (amt_synth if is_buy else amt_coll)
        packed_0 = (packed_0 << 64) + amt_fee
        packed_0 = (packed_0 << 32) + l2_nonce
        h = pedersen_hash(h, packed_0)
        packed_1 = LIMIT_ORDER_WITH_FEES
        pid = int(self.account_id)
        packed_1 = (packed_1 << 64) + pid
        packed_1 = (packed_1 << 64) + pid
        packed_1 = (packed_1 << 64) + pid
        packed_1 = (packed_1 << 32) + expire_ts
        packed_1 = (packed_1 << 17)
        h = pedersen_hash(h, packed_1)

        private_key_int = int(self.private_key_hex, 16)
        r, s = sign(h, private_key_int)
        l2_signature = r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex()

        body = {
            "accountId": self.account_id,
            "contractId": contract_id,
            "price": str(price if order_type.upper() != 'MARKET' else 0),
            "size": str(size),
            "type": order_type.upper(),
            "timeInForce": time_in_force,
            "side": side.upper(),
            "reduceOnly": 'false',
            "clientOrderId": client_order_id,
            "expireTime": expire_time,
            "l2Nonce": str(l2_nonce),
            "l2Value": str(value),
            "l2Size": str(size),
            "l2LimitFee": str((value * fee_rate).quantize(Decimal("1.000000"))),
            "l2ExpireTime": l2_expire_time,
            "l2Signature": l2_signature
        }

        method = "POST"
        path = "/api/v1/private/order/createOrder"
        signature, ts = self.generate_signature(method, path, body)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"{self.base_url}{path}",
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-edgeX-Api-Timestamp": ts,
                    "X-edgeX-Api-Signature": signature
                }
            ) as resp:
                return await resp.json()

    def parse_position(self, position_list,position_asset_list, symbol):
        contract_id = self.market_info[symbol]['contractId']
        
        size = 0
        
        for position in position_list:
            if position['contractId'] == contract_id:
                #print(position)
                size = position['openSize']
                side = 'short' if '-' in size else 'long'
                size = size.replace('-','')
                
        for position in position_asset_list:
            if position['contractId'] == contract_id:
                entry_price = position['avgEntryPrice']
                unrealized_pnl = position['unrealizePnl']
        
        if size == 0:
            return None        
        
        return {
            "entry_price": float(entry_price),
            "unrealized_pnl": round(float(unrealized_pnl),2),
            "side": side,
            "size": size
        }
        
    
    async def get_position(self, symbol):
        method = "GET"
        path = "/api/v1/private/account/getAccountAsset"
        params = {
            "accountId": self.account_id,
        }

        signature, timestamp = self.generate_signature(method, path, params)

        headers = {
            "X-edgeX-Api-Timestamp": timestamp,
            "X-edgeX-Api-Signature": signature
        }

        query_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if query_str:
            url = f"{self.base_url}{path}?{query_str}"
        else:
            url = f"{self.base_url}{path}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    print(f"[get_position] HTTP {resp.status}")
                    print(await resp.text())
                    return None
                data = await resp.json()
                position_list = data['data']['positionList']
                position_asset_list = data['data']['positionAssetList']
                return self.parse_position(position_list,position_asset_list,symbol)
    
    async def close_position(self, symbol, position):
        return await super().close_position(symbol, position)
    
    async def get_collateral(self):
        method = "GET"
        path = "/api/v1/private/account/getAccountAsset"
        params = {
            "accountId": self.account_id,
        }

        signature, timestamp = self.generate_signature(method, path, params)

        headers = {
            "X-edgeX-Api-Timestamp": timestamp,
            "X-edgeX-Api-Signature": signature
        }

        query_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if query_str:
            url = f"{self.base_url}{path}?{query_str}"
        else:
            url = f"{self.base_url}{path}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    print(f"[get_position] HTTP {resp.status}")
                    print(await resp.text())
                    return None
                data = await resp.json()
                collateral = data['data']['collateralAssetModelList']
                return self.parse_collateral(collateral)
            
    def parse_collateral(self,collateral):
        for col in collateral:
            if col['coinId'] == self.usdt_coin_id:
                available_collateral = round(float(col['availableAmount']),2)
                total_collateral = round(float(col['totalEquity']),2)
                return {'available_collateral': available_collateral, 'total_collateral': total_collateral}
            
    async def get_open_orders(self, symbol):
        contract_id = self.market_info[symbol]['contractId']
        method = "GET"
        path = "/api/v1/private/order/getActiveOrderPage"
        params = {
            "accountId": self.account_id,
            "size": "200",
            "filterContractIdList": contract_id,  # ✅ 특정 심볼의 주문만
        }

        signature, timestamp = self.generate_signature(method, path, params)

        headers = {
            "X-edgeX-Api-Timestamp": timestamp,
            "X-edgeX-Api-Signature": signature
        }

        query_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        url = f"{self.base_url}{path}?{query_str}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    #print(f"[get_open_orders] HTTP {resp.status}")
                    #print(await resp.text())
                    return []

                res = await resp.json()
                orders = res.get("data", {}).get("dataList", [])
                return self.parse_open_orders(orders)
            
    def parse_open_orders(self, orders):
        if not orders:
            return []

        return [
            {
                "symbol": self._get_symbol_from_contract_id(o["contractId"]),
                "id": o["id"],
                "quantity": o["size"],
                "price": o["price"],
                "side": o["side"],
                "order_type": o["type"],
                "status": o["status"]
            }
            for o in orders if o.get("status") == "OPEN"
        ]
        
    def _get_symbol_from_contract_id(self, contract_id):
        for symbol, info in self.market_info.items():
            if info.get("contractId") == contract_id:
                return symbol
        return None  # 없을 경우 None 반환 (혹은 raise 예외)

    async def cancel_orders(self, symbol, open_orders = None):
        if open_orders is None:
            open_orders = await self.get_open_orders(symbol)
        if not open_orders:
            #print(f"[cancel_orders] No open orders for {symbol}")
            return []

        order_ids = [o["id"] for o in open_orders]

        method = "POST"
        path = "/api/v1/private/order/cancelOrderById"

        # ✅ 서명용 문자열에서 orderIdList=id1&id2 포맷 필요
        order_id_str = "&".join(order_ids)
        params = {
            "accountId": self.account_id,
            "orderIdList": order_id_str  # ⚠️ 문자열이어야 함
        }

        signature, timestamp = self.generate_signature(method, path, params)

        headers = {
            "X-edgeX-Api-Timestamp": timestamp,
            "X-edgeX-Api-Signature": signature,
            "Content-Type": "application/json"
        }

        # ✅ 요청 본문은 리스트 형태
        body = {
            "accountId": self.account_id,
            "orderIdList": order_ids
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}{path}", json=body, headers=headers) as resp:
                if resp.status != 200:
                    print(f"[cancel_orders] HTTP {resp.status}")
                    print(await resp.text())
                    return []

                res = await resp.json()
                cancel_map = res.get("data", {}).get("cancelResultMap", {})
                return [{"id": k, "status": v} for k, v in cancel_map.items()]

