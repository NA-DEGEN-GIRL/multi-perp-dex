from dataclasses import dataclass
from typing import Tuple
@dataclass
class SuperstackKEY:
    wallet_address: str         # optional, sub-account 안쓰면 필수
    api_key: str                # required
    vault_address: str          # optional, sub-account 쓰면 필수
    builder_fee_pair: dict      # {"base","dex"# optional,"xyz" # optional,"vntl" #optional,"flx" #optional}
    fetch_by_ws: bool
    FrontendMarket: bool
    
SUPERSTACK_KEY = SuperstackKEY(
    wallet_address = None,
    api_key = None,
    vault_address = None,
    builder_fee_pair = {"base":(4,11),"dex":(4,11)},
    fetch_by_ws = True,
    FrontendMarket = False
    )
