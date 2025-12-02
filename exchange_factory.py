import importlib  # [ADDED]

def _load(exchange_platform: str):  # [ADDED] 필요한 경우에만 모듈 로드
    mapping = {
        "paradex": ("wrappers.paradex", "ParadexExchange"),
        "edgex": ("wrappers.edgex", "EdgexExchange"),
        "lighter": ("wrappers.lighter", "LighterExchange"),
        "grvt": ("wrappers.grvt", "GrvtExchange"),
        "backpack": ("wrappers.backpack", "BackpackExchange"),
        "treadfi.hyperliquid": ("wrappers.treadfi_hl", "TreadfiHlExchange"),
        "variational": ("wrappers.variational", "VariationalExchange"),
        "pacifica": ("wrappers.pacifica", "PacificaExchange"),
        "hyperliquid": ("wrappers.hyperliquid","HyperliquidExchange")
    }
    try:
        mod, cls = mapping[exchange_platform]
    except KeyError:
        raise ValueError(f"Unsupported exchange: {exchange_platform}")
    module = importlib.import_module(mod)
    return getattr(module, cls)

async def create_exchange(exchange_platform: str, key_params=None):  # [MODIFIED] 지연 로드 사용
    if key_params is None:
        raise ValueError(f"[ERROR] key_params is required for exchange: {exchange_platform}")
    Ex = _load(exchange_platform)  # [ADDED]
    if exchange_platform == "paradex":
        return Ex(key_params.wallet_address, key_params.paradex_address, key_params.paradex_private_key)
    elif exchange_platform == "edgex":
        return await Ex(key_params.account_id, key_params.private_key).init()
    elif exchange_platform == "grvt":
        return await Ex(key_params.api_key, key_params.account_id, key_params.secret_key ).init()
    elif exchange_platform == "backpack":
        return Ex(key_params.api_key, key_params.secret_key)
    elif exchange_platform == "lighter":
        return await Ex(key_params.account_id, key_params.private_key, key_params.api_key_id, key_params.l1_address).initialize_market_info()
    elif exchange_platform == "treadfi.hyperliquid":
        return Ex(key_params.session_cookies, key_params.evm_private_key, key_params.main_wallet_address, key_params.sub_wallet_address, key_params.account_name)
    elif exchange_platform == "variational":
        return Ex(key_params.evm_wallet_address, key_params.session_cookies, key_params.evm_private_key)
    elif exchange_platform == "pacifica":
        return await Ex(key_params.public_key, key_params.agent_public_key, key_params.agent_private_key).init()
    elif exchange_platform == "hyperliquid":
        return Ex()
    else:
        raise ValueError(f"Unsupported exchange: {exchange_platform}")

SYMBOL_FORMATS = {
    "paradex":  lambda c: f"{c}-USD-PERP",
    "edgex":    lambda c: f"{c}USD",
    "grvt":     lambda c: f"{c}_USDT_Perp",
    "backpack": lambda c: f"{c}_USDC_PERP",
    "lighter":  lambda c: c,
    "treadfi.hyperliquid": lambda coin: f"{coin.split(':')[0].lower()}_{coin.split(':')[1].upper()}:PERP-USDC" if ":" in coin else f"{coin.upper()}:PERP-USDC",
    "variational": lambda coin: coin.upper(), # same
    "pacifica": lambda coin: coin.upper(), # same
    "hyperliquid": lambda coin: coin.upper(), # use internal mapping
}

def symbol_create(exchange_platform: str, coin: str):
    coin = coin.upper()
    try:
        return SYMBOL_FORMATS[exchange_platform](coin)
    except KeyError:
        raise ValueError(f"Unsupported exchange: {exchange_platform}, coin: {coin}")