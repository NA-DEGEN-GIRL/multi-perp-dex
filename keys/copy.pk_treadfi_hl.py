from dataclasses import dataclass

@dataclass
class TreadfiHlKey:
    session_cookies: dict
    login_wallet_address: str
    login_wallet_private_key: str
    trading_wallet_address: str
    account_name: str
    fetch_by_ws: bool
    trading_wallet_private_key: str

TREADFIHL_KEY = TreadfiHlKey(
    session_cookies = {"csrftoken":"",
                       "sessionid":""}, # session cookies, can skip
    login_wallet_address = '',          # login wallet address, required
    login_wallet_private_key = '',      # optional
    trading_wallet_address = '',        # optional, your trading wallet address. same if not specified
    account_name= '', # your account name of hyperliquid @ traedfi
    fetch_by_ws=True, # use WS_POOL common,
    trading_wallet_private_key='' # optional, need when want 'transfer' between perp/spot
    )
