import importlib  # [ADDED]

def _load(exchange_name: str):  # [ADDED] 필요한 경우에만 모듈 로드
    mapping = {
        "paradex": ("wrappers.paradex", "ParadexExchange"),
        "edgex": ("wrappers.edgex", "EdgexExchange"),
        "lighter": ("wrappers.lighter", "LighterExchange"),
        "grvt": ("wrappers.grvt", "GrvtExchange"),
        "backpack": ("wrappers.backpack", "BackpackExchange"),
    }
    try:
        mod, cls = mapping[exchange_name]
    except KeyError:
        raise ValueError(f"Unsupported exchange: {exchange_name}")
    module = importlib.import_module(mod)
    return getattr(module, cls)

async def create_exchange(exchange_name: str, key_params=None):  # [MODIFIED] 지연 로드 사용
    if key_params is None:
        raise ValueError(f"[ERROR] key_params is required for exchange: {exchange_name}")
    Ex = _load(exchange_name)  # [ADDED]
    if exchange_name == "paradex":
        return Ex(key_params.wallet_address, key_params.paradex_address, key_params.paradex_private_key)
    elif exchange_name == "edgex":
        return await Ex(key_params.account_id, key_params.private_key).init()
    elif exchange_name == "grvt":
        return await Ex(key_params.api_key, key_params.account_id, key_params.secret_key ).init()
    elif exchange_name == "backpack":
        return Ex(key_params.api_key, key_params.secret_key)
    elif exchange_name == "lighter":
        return await Ex(key_params.account_id, key_params.private_key, key_params.api_key_id, key_params.l1_address).initialize_market_info()
    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")

SYMBOL_FORMATS = {
    "paradex":  lambda c: f"{c}-USD-PERP",
    "edgex":    lambda c: f"{c}USD",
    "grvt":     lambda c: f"{c}_USDT_Perp",
    "backpack": lambda c: f"{c}_USDC_PERP",
    "lighter":  lambda c: c,
    "treadfi_hl": lambda coin: f"{coin.split(':')[0]}_{coin.split(':')[1]}:PERP-USDC" if ":" in coin else f"{coin}:PERP-USDC"
}

def symbol_create(exchange_name: str, coin: str):
    coin = coin.upper()
    try:
        return SYMBOL_FORMATS[exchange_name](coin)
    except KeyError:
        raise ValueError(f"Unsupported exchange: {exchange_name}, coin: {coin}")