from wrappers.paradex import ParadexExchange
from wrappers.edgex import EdgexExchange
from wrappers.lighter import LighterExchange
from wrappers.grvt import GrvtExchange
from wrappers.backpack import BackpackExchange

async def create_exchange(exchange_name: str, key_params=None):
    if key_params is None:
        raise ValueError(f"[ERROR] key_params is required for exchange: {exchange_name}")
    
    if exchange_name == "paradex":
        return ParadexExchange(key_params.wallet_address, key_params.paradex_address, key_params.paradex_private_key)
    elif exchange_name == "edgex":
        return await EdgexExchange(key_params.account_id, key_params.private_key).init()
    elif exchange_name == "grvt":
        return await GrvtExchange(key_params.api_key, key_params.account_id, key_params.secret_key ).init()
    elif exchange_name == "backpack":
        return BackpackExchange(key_params.api_key, key_params.secret_key)
    elif exchange_name == "lighter":
        return await LighterExchange(key_params.account_id, key_params.private_key).initialize_market_info()
    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")

SYMBOL_FORMATS = {
    "paradex":  lambda c: f"{c}-USD-PERP",
    "edgex":    lambda c: f"{c}USDT",
    "grvt":     lambda c: f"{c}_USDT_Perp",
    "backpack": lambda c: f"{c}_USDC_PERP",
    "lighter":  lambda c: c,
}

def symbol_create(exchange_name: str, coin: str):
    coin = coin.upper()
    try:
        return SYMBOL_FORMATS[exchange_name](coin)
    except KeyError:
        raise ValueError(f"Unsupported exchange: {exchange_name}, coin: {coin}")