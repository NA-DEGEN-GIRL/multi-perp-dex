import importlib  # [ADDED]

def _load(exchange_platform: str):  # [ADDED] 필요한 경우에만 모듈 로드
    mapping = {
        "paradex": ("wrappers.paradex", "ParadexExchange"),
        "edgex": ("wrappers.edgex", "EdgexExchange"),
        "lighter": ("wrappers.lighter", "LighterExchange"),
        "grvt": ("wrappers.grvt", "GrvtExchange"),
        "backpack": ("wrappers.backpack", "BackpackExchange"),
        "treadfi.hyperliquid": ("wrappers.treadfi_hl", "TreadfiHlExchange"),
        "treadfi.pacifica": ("wrappers.treadfi_pc", "TreadfiPcExchange"),
        "variational": ("wrappers.variational", "VariationalExchange"),
        "pacifica": ("wrappers.pacifica", "PacificaExchange"),
        "hyperliquid": ("wrappers.hyperliquid","HyperliquidExchange"),
        "superstack": ("wrappers.superstack","SuperstackExchange"),
        "standx": ("wrappers.standx", "StandXExchange"),
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
        return await Ex(
            key_params.wallet_address, 
            key_params.paradex_address, 
            key_params.paradex_private_key
            ).init()
    
    elif exchange_platform == "edgex":
        return await Ex(
            key_params.account_id, 
            key_params.private_key
            ).init()
    
    elif exchange_platform == "grvt":
        return await Ex(
            key_params.api_key, 
            key_params.account_id, 
            key_params.secret_key
            ).init()
    
    elif exchange_platform == "backpack":
        return await Ex(
            key_params.api_key, 
            key_params.secret_key
            ).init()
    
    elif exchange_platform == "lighter":
        return await Ex(
            key_params.account_id, 
            key_params.private_key, 
            key_params.api_key_id, 
            key_params.l1_address
            ).init()
    
    elif exchange_platform == "treadfi.hyperliquid":
        return await Ex(
            key_params.session_cookies,
            key_params.login_wallet_address,
            key_params.login_wallet_private_key,
            key_params.trading_wallet_address,
            key_params.account_name,
            key_params.fetch_by_ws,
            getattr(key_params,'trading_wallet_private_key',None),
            key_params.options if hasattr(key_params,"options") else None
            ).init()

    elif exchange_platform == "treadfi.pacifica":
        return await Ex(
            session_cookies=getattr(key_params, 'session_cookies', None),
            login_wallet_address=getattr(key_params, 'login_wallet_address', None),
            login_wallet_private_key=getattr(key_params, 'login_wallet_private_key', None),
            account_name=key_params.account_name,
            pacifica_public_key=getattr(key_params, 'pacifica_public_key', None),
            fetch_by_ws=getattr(key_params, 'fetch_by_ws', True),
            ).init()

    elif exchange_platform == "variational":
        return await Ex(
            key_params.evm_wallet_address, 
            key_params.session_cookies, 
            key_params.evm_private_key
            ).init()
    
    elif exchange_platform == "pacifica":
        return await Ex(
            key_params.public_key, 
            key_params.agent_public_key, 
            key_params.agent_private_key
            ).init()
    
    elif exchange_platform == "hyperliquid":
        return await Ex(
            wallet_address = key_params.wallet_address,
            wallet_private_key = key_params.wallet_private_key,
            agent_api_address = key_params.agent_api_address,
            agent_api_private_key = key_params.agent_api_private_key,
            by_agent = key_params.by_agent,
            vault_address = key_params.vault_address,
            builder_code = key_params.builder_code,
            builder_fee_pair = key_params.builder_fee_pair,
            fetch_by_ws = key_params.fetch_by_ws,
            FrontendMarket = key_params.FrontendMarket
        ).init()
    
    elif exchange_platform == "superstack":
        return await Ex(
            wallet_address = key_params.wallet_address,
            api_key = key_params.api_key,
            vault_address = key_params.vault_address,
            fetch_by_ws = key_params.fetch_by_ws,
            builder_fee_pair = key_params.builder_fee_pair,
            FrontendMarket = key_params.FrontendMarket
        ).init()

    elif exchange_platform == "standx":
        return await Ex(
            wallet_address = key_params.wallet_address,
            chain = getattr(key_params, 'chain', 'bsc'),
            evm_private_key = getattr(key_params, 'evm_private_key', None),
            session_token = getattr(key_params, 'session_token', None),
        ).init(
            login_port = getattr(key_params, 'login_port', 6969),
            open_browser = getattr(key_params, 'open_browser', False),
        )

    else:
        raise ValueError(f"Unsupported exchange: {exchange_platform}")

SYMBOL_FORMATS = {
    "paradex":  lambda c, q=None: f"{c}-USD-PERP",
    "edgex":    lambda c, q=None: f"{c}USD",
    "grvt":     lambda c, q=None: f"{c}_USDT_Perp",
    "backpack": lambda c, q=None: f"{c}_USDC_PERP",
    "lighter":  lambda c, q=None: c,
    "treadfi.hyperliquid": lambda coin, q=None: (
        f"{coin.split(':')[0].lower()}_{coin.split(':')[1].upper()}:PERP-{q or 'USDC'}" 
        if ":" in coin 
        else f"{coin.upper()}:PERP-{q or 'USDC'}"
    ),
    "treadfi.pacifica": lambda coin, q=None: f"{coin.upper()}:PERP-{q or 'USDC'}",
    "variational": lambda coin, q=None: coin.upper(), # same
    "pacifica": lambda coin, q=None: coin.upper(), # same
    "hyperliquid": lambda coin, q=None: coin.upper(), # use internal mapping
    "superstack": lambda coin, q=None: coin.upper(), # use internal mapping
    "standx": lambda coin, q=None: f"{coin.upper()}-USD",  # BTC-USD
}

SPOT_SYMBOL_FORMATS = {
    "backpack": lambda c: f"{c[0]}_{c[1]}", # BTC_USDC 형태
    "lighter": lambda c: f"{c[0]}/{c[1]}", # BTC/USDC 형태
    "hyperliquid": lambda c: f"{c[0]}/{c[1]}", # BTC/USDC 형태
    "superstack": lambda c: f"{c[0]}/{c[1]}", # BTC/USDC 형태
    "treadfi.hyperliquid": lambda c: f"{c[0]}-{c[1]}", # BTC-USDC 형태
    "edgex": lambda c: f"{c[0]}/{c[1]}", # BTC/USDC 형태
}

def symbol_create(exchange_platform: str, coin: str, *, is_spot=False, quote=None):
    """spot의 경우 BTC/USDC와 같은 형태, quote가 있음"""
    """perp의 경우 BTC의 형태, dex가 붙으면 xyz:XYZ100 형태, quote가 없음"""
    
    if is_spot:
        # 총 3케이스를 다룸 "/", "_", "-"
        splitters = ['/','_','-']
        for spliter in splitters:
            if spliter in coin:
                base_symbol = coin.split(spliter)[0].upper()
                quote = coin.split(spliter)[1].upper()
                #print(base_symbol,quote)
                break
        try:
            return SPOT_SYMBOL_FORMATS[exchange_platform]([base_symbol,quote])
        except KeyError:
            raise ValueError(f"Unsupported exchange: {exchange_platform}, coin: {coin}")
    else:
        # perp가 default
        coin = coin.upper()
        try:
            return SYMBOL_FORMATS[exchange_platform](coin, quote)
        except KeyError:
            raise ValueError(f"Unsupported exchange: {exchange_platform}, coin: {coin}")