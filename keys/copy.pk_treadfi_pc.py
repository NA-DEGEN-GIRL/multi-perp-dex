from dataclasses import dataclass
from typing import Optional

@dataclass
class TreadfiPcKey:
    session_cookies: Optional[dict]
    login_wallet_address: str
    login_wallet_private_key: Optional[str]
    account_name: str
    pacifica_public_key: Optional[str]
    fetch_by_ws: bool

TREADFI_PC_KEY = TreadfiPcKey(
    session_cookies=None,  # session cookies, can skip if using private key
    login_wallet_address='',  # EVM login wallet address, required
    login_wallet_private_key='',  # optional, for auto-signing
    account_name='',  # your TreadFi account name for Pacifica
    pacifica_public_key='',  # Solana pubkey for Pacifica data fetching (optional)
    fetch_by_ws=True,  # use Pacifica WS for data fetching
)
