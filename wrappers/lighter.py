from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin
from lighter.signer_client import SignerClient
from lighter.api.account_api import AccountApi
from lighter.api.order_api import OrderApi
import aiohttp
import time
import json
import logging
from typing import Optional, Dict, Any

# [ADDED] WebSocket 클라이언트 풀 import
from wrappers.lighter_ws_client import LIGHTER_WS_POOL, LighterWSClient

STABLES = ['USDC']

class LighterExchange(MultiPerpDexMixin, MultiPerpDex):
    def __init__(
        self, 
        account_id, 
        private_key, 
        api_key_id, 
        l1_address, 
        l1_private_key=None,
        *,
        fetch_by_ws: bool = True,  # [ADDED] WS 모드 플래그
    ):
        super().__init__()
        logging.getLogger().setLevel(logging.WARNING)
        self.url = "https://mainnet.zklighter.elliot.ai"
        self.client = SignerClient(
            url=self.url, 
            api_private_keys={api_key_id: private_key}, 
            account_index=account_id
        )
        self.apiOrder = OrderApi(self.client.api_client)
        self.market_info = {}
        self._cached_auth_token = None
        self._auth_expiry_ts = 0
        self.l1_address = l1_address
        self.dummy_pk = "0x0000000000000000000000000000000000000000000000000000000000000001"
        self.has_spot = True
        self.spot_balance = {}
        self._collateral_cache: dict | None = None
        self._collateral_last_fetch_ts: float = 0.0
        self._collateral_cooldown_sec: float = 0.5

        # [ADDED] WebSocket 관련
        self._fetch_by_ws = fetch_by_ws
        self._ws_client: Optional[LighterWSClient] = None
        self._account_id = account_id 

    def get_auth(self, expiry_sec=600):
        now = int(time.time())
        if self._cached_auth_token is None or now >= self._auth_expiry_ts:
            self._auth_expiry_ts = int(expiry_sec/60)
            self._cached_auth_token, _ = self.client.create_auth_token_with_expiry(self._auth_expiry_ts)
        return self._cached_auth_token
    
    def get_perp_quote(self, symbol):
        return 'USDC'
    
    # use initialize when using main account
    #async def initialize(self):
    #    await self.client.set_account_index()

    async def init(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.url}/api/v1/orderBooks") as resp:
                data = await resp.json()
                for m in data["order_books"]:
                    self.market_info[m["symbol"].upper()] = {
                        "market_id": m["market_id"],
                        "size_decimals": m["supported_size_decimals"],
                        "price_decimals": m["supported_price_decimals"],
                        "market_type":m["market_type"], # perp or spot
                    }
        
        self.update_available_symbols()
        
        # [ADDED] WebSocket 모드면 WS 클라이언트 초기화
        if self._fetch_by_ws:
            await self._init_ws()
        
        return self

    # [ADDED] ========== WebSocket 관련 메서드 ==========
    
    async def _init_ws(self) -> None:
        """WebSocket 클라이언트 초기화"""
        # symbol -> market_id 매핑 생성
        symbol_to_market_id = {
            symbol: info["market_id"] 
            for symbol, info in self.market_info.items()
        }
        
        # 풀에서 클라이언트 획득
        self._ws_client = await LIGHTER_WS_POOL.acquire(
            account_id=self._account_id,
            auth_token=self.get_auth(),
            symbol_to_market_id=symbol_to_market_id,
        )
        
        # 첫 데이터 수신 대기 (최대 5초)
        await self._ws_client.wait_ready(timeout=5.0)

    @property
    def ws_client(self) -> Optional[LighterWSClient]:
        """WS 클라이언트 접근자"""
        return self._ws_client

    async def ensure_ws_ready(self) -> bool:
        """WS 연결 보장 (필요시 재연결)"""
        if not self._fetch_by_ws:
            return False
        if self._ws_client and self._ws_client.connected:
            return True
        # 재초기화
        await self._init_ws()
        return self._ws_client is not None and self._ws_client.connected

    async def get_all_prices(self) -> Dict[str, float]:
        """
        [WS 전용] 모든 마켓의 가격을 한 번에 반환.
        WS 모드가 아니면 빈 dict 반환.
        반환 형식: {"ETH": 3500.0, "BTC": 95000.0, ...}
        """
        if not self._fetch_by_ws or not self._ws_client:
            return {}
        return self._ws_client.get_all_prices()

    async def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        [WS 전용] 모든 포지션을 한 번에 반환.
        WS 모드가 아니면 빈 dict 반환.
        반환 형식: {"ETH": {"size": 0.5, "side": "long", ...}, ...}
        """
        if not self._fetch_by_ws or not self._ws_client:
            return {}
        return self._ws_client.get_all_positions()
    
    async def get_spot_balance(self, coin: str = None) -> dict:
        """
        spot 잔고 조회.
        - 내부적으로 get_collateral()을 호출해 self.spot_balance를 갱신
        - 쿨다운 내 재호출 시 캐시 사용
        - coin이 주어지면 해당 코인만, None이면 전체 반환

        반환 형식:
          { "USDC": { "total": float, "available": float, "locked": float }, ... }
        """
        # get_collateral 내부에서 spot_balance도 갱신됨
        await self.get_collateral()

        if coin is not None:
            coin_upper = coin.upper()
            if coin_upper in self.spot_balance:
                return {coin_upper: self.spot_balance[coin_upper]}
            return {}

        return dict(self.spot_balance)
    
    def update_available_symbols(self):
        self.available_symbols['perp'] = []
        self.available_symbols['spot'] = []
        for k, v in self.market_info.items():
            #print(k,v)
            market_type = v.get('market_type','perp')
            if market_type == 'perp':
                coin = k
                quote = self.get_perp_quote(k)
                composite_symbol = f"{coin}-{quote}"
                self.available_symbols['perp'].append(composite_symbol)
                #self.available_symbols['perp'].append(coin)

            else:
                self.available_symbols['spot'].append(k)
    
    async def close(self):
        # [ADDED] WS 클라이언트 해제
        if self._ws_client:
            await LIGHTER_WS_POOL.release(self._account_id)
            self._ws_client = None
        await self.client.close()
    

    def _ensure_l1_private_key(self):
        """transfer에 필요한 L1 private key 확인"""
        if not self.l1_private_key:
            raise RuntimeError(
                "l1_private_key가 필요합니다: "
                "Lighter transfer는 L1 wallet 서명이 필요합니다."
            )
        # 0x 접두어 제거 (SDK가 알아서 처리하지만 일관성을 위해)
        priv = self.l1_private_key
        if priv.startswith("0x"):
            priv = priv[2:]
        return priv

    async def transfer_to_spot(self, amount):
        """
        Perp 지갑 → Spot 지갑으로 USDC 전송.
        - route_from: ROUTE_PERP
        - route_to: ROUTE_SPOT
        """
        coll_coin = "USDC"
        amount = float(amount)

        # 잔고 확인
        res = await self.get_collateral()
        available = res.get("available_collateral") or 0
        if amount > available:
            return {
                "status": "error",
                "message": f"insufficient perp balance: available={available} {coll_coin}, requested={amount}"
            }

        try:
            transfer_tx, response, err = await self.client.transfer(
                self.dummy_pk,
                to_account_index=self.client.account_index,
                asset_id=self.client.ASSET_ID_USDC,
                amount=amount,  # SDK가 decimals 처리
                route_from=self.client.ROUTE_PERP,
                route_to=self.client.ROUTE_SPOT,
                fee=0,
                memo="0x" + "00" * 32,
            )

            if err is not None:
                return {"status": "error", "message": str(err)}

            return {
                "status": "ok",
                #"tx_hash": transfer_tx,
                "tx_hash": response.tx_hash,
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def transfer_to_perp(self, amount):
        """
        Spot 지갑 → Perp 지갑으로 USDC 전송.
        - route_from: ROUTE_SPOT
        - route_to: ROUTE_PERP
        """
        coll_coin = "USDC"
        amount = float(amount)

        # 잔고 확인
        res = await self.get_spot_balance(coll_coin)
        balance_info = res.get(coll_coin) or res.get(coll_coin.upper()) or {}
        available = balance_info.get("available", 0)
        if amount > available:
            return {
                "status": "error",
                "message": f"insufficient spot balance: available={available} {coll_coin}, requested={amount}"
            }

        try:
            transfer_tx, response, err = await self.client.transfer(
                self.dummy_pk,
                to_account_index=self.client.account_index,
                asset_id=self.client.ASSET_ID_USDC,
                amount=amount,  # SDK가 decimals 처리
                route_from=self.client.ROUTE_SPOT,
                route_to=self.client.ROUTE_PERP,
                fee=0,
                memo="0x" + "00" * 32,
            )

            if err is not None:
                return {"status": "error", "message": str(err)}

            return {
                "status": "ok",
                #"tx_hash": transfer_tx,
                "tx_hash": response.tx_hash,
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def get_mark_price(self, symbol):
        # [MODIFIED] WS 모드면 캐시에서 조회
        if self._fetch_by_ws and self._ws_client:
            m_info = self.market_info.get(symbol)
            is_spot = m_info and m_info.get('market_type', 'perp') == 'spot'
            if is_spot:
                price = self._ws_client.get_spot_price(symbol)
            else:
                price = self._ws_client.get_mark_price(symbol)
            if price is not None:
                return price
            # WS에 아직 데이터가 없으면 REST fallback
        print("LighterExchange.get_mark_price: using REST fallback")
        # [ORIGINAL] REST API 호출
        m_info = self.market_info[symbol]
        market_id = m_info["market_id"]
        is_spot = m_info.get('market_type','perp') == 'spot'
        
        res = await self.apiOrder.order_book_details(market_id=market_id)
        if is_spot:
            price = res.to_dict()["spot_order_book_details"][0]["last_trade_price"]
        else:
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
        # [MODIFIED] WS 모드면 캐시에서 조회
        if self._fetch_by_ws and self._ws_client:
            # account_all 데이터가 수신되었는지 확인
            if self._ws_client._account_all_ready.is_set():
                pos = self._ws_client.get_position(symbol)
                if pos is not None:
                    # WS 포맷 → 기존 포맷으로 변환
                    return {
                        "entry_price": pos.get("entry_price"),
                        "unrealized_pnl": pos.get("unrealized_pnl"),
                        "side": pos.get("side"),
                        "size": pos.get("size"),
                    }
                # WS에 해당 심볼 포지션 없음 = 포지션 없음
                return None
            # WS 데이터 미수신 상태면 REST fallback
        print("LighterExchange.get_position: using REST fallback")
        # [ORIGINAL] REST API 호출
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

    async def get_collateral(self, *, force_refresh: bool = False) -> dict:
        """
        담보/잔고 조회.
        - WS 모드: 캐시에서 조회 (실시간)
        - REST 모드: 쿨다운 내 재호출 시 캐시 반환
        - force_refresh=True면 강제로 REST API 호출
        """
        # [MODIFIED] WS 모드면 WS 캐시에서 조회
        if self._fetch_by_ws and self._ws_client and not force_refresh:
            ws_coll = self._ws_client.get_collateral()
            ws_assets = self._ws_client.get_assets()
            
            # WS에 데이터가 있으면 사용
            if ws_coll:
                # spot_balance 갱신
                for symbol, asset_info in ws_assets.items():
                    self.spot_balance[symbol] = asset_info
                
                spot = {}
                for symbol in STABLES:
                    if symbol in ws_assets:
                        spot[symbol] = ws_assets[symbol].get("total", 0)
                
                return {
                    "available_collateral": round(ws_coll.get("available_collateral", 0), 2),
                    "total_collateral": round(ws_coll.get("total_collateral", 0), 2),
                    "spot": spot,
                }
            # WS에 아직 데이터가 없으면 REST fallback
        print("LighterExchange.get_collateral: using REST fallback")
        now = time.time()

        # 캐시 유효 → 바로 반환
        if (
            not force_refresh
            and self._collateral_cache is not None
            and (now - self._collateral_last_fetch_ts) < self._collateral_cooldown_sec
        ):
            return self._collateral_cache

        # [ORIGINAL] REST API 호출
        l1_address = self.l1_address
        url = f"{self.url}/api/v1/account?by=l1_address&value={l1_address}"
        headers = {"accept": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                accounts = data['accounts']
                for account in accounts:
                    
                    if account['index'] == self.client.account_index:
                        total_collateral = float(account['total_asset_value'])
                        margin_used = 0
                        for pos in account['positions']:
                            position_value = float(pos['position_value'])
                            initial_margin_fraction = float(pos['initial_margin_fraction'])/100.0
                            margin_used += position_value*initial_margin_fraction
                            
                        available_collateral = float(total_collateral)-margin_used

                        # spot data
                        assets = account.get('assets',{})
                        spot = {}
                        for asset in assets:
                            symbol = asset.get('symbol',"")
                            total = float(asset.get('balance',0))
                            locked = float(asset.get('locked_balance',0))
                            available = total - locked
                            
                            self.spot_balance[symbol] = {'total':total, 
                                                         'available':available,
                                                         'locked':locked
                                                         }
                            
                            # spot stable data
                            if symbol in STABLES:
                                spot[symbol] = total

                    result = {
                            "available_collateral": round(available_collateral, 2),
                            "total_collateral": round(total_collateral, 2),
                            "spot": spot,
                        }

                    # 캐시 갱신
                    self._collateral_cache = result
                    self._collateral_last_fetch_ts = now

                    return result
                
        # 해당 계정 못 찾음 → 빈 결과(캐시 안 함)
        return {
            "available_collateral": 0.0,
            "total_collateral": 0.0,
            "spot": {},
        }
    
    async def get_open_orders(self, symbol):
        # [MODIFIED] WS 모드면 캐시에서 조회
        if self._fetch_by_ws and self._ws_client:
            if self._ws_client._orders_ready.is_set():
                orders = self._ws_client.get_open_orders(symbol)
                # WS에서 반환된 오더가 있거나, orders_ready가 set된 상태면 WS 결과 신뢰
                return orders
            # WS 데이터 미수신 상태면 REST fallback
        
        print("LighterExchange.get_open_orders: using REST fallback")
        # [ORIGINAL] REST API 호출
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
    
    async def get_all_open_orders(self) -> dict:
        """
        [ADDED] 모든 마켓의 오픈 오더를 한 번에 조회.
        WS 모드: 캐시에서 즉시 반환
        REST 모드: 각 마켓별로 순차 조회 (비효율적이므로 WS 권장)
        
        반환: { 'ETH-USD': [...], 'BTC-USD': [...], ... }
        """
        if self._fetch_by_ws and self._ws_client:
            if self._ws_client._orders_ready.is_set():
                return self._ws_client.get_all_open_orders()
        
        # REST fallback: 모든 perp 마켓 순회
        result = {}
        for symbol, info in self.market_info.items():
            if info.get('market_type', 'perp') == 'perp':
                orders = await self.get_open_orders(symbol)
                if orders:
                    result[symbol] = orders
        return result

    def parse_open_orders(self, orders):
        """id, symbol, type, side, size, price"""
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
                "size": str(o.initial_base_amount),  # Decimal or string
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
