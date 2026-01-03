from dataclasses import dataclass
from typing import Tuple, Optional
@dataclass
class HyperliquidKEY:
    wallet_address: str         # required
    wallet_private_key: str     # required only if no agent
    agent_api_address: str      # required only if agent
    agent_api_private_key: str  # required only if agent
    by_agent: bool              # required
    vault_address: str          # optional
    builder_code: str           # optional
    builder_fee_pair: dict[str, Tuple[int, int] | list[int] | int]      # optional
    fetch_by_ws: bool           # optional
    FrontendMarket: bool
    proxy: Optional[str] = None # optional, e.g. "http://user:pass@host:port"
    
HYPERLIQUID_KEY = HyperliquidKEY(
    wallet_address = None,
    wallet_private_key = None,
    agent_api_address = None,
    agent_api_private_key = None,
    by_agent = True,
    vault_address = None,
    builder_code = None,
    builder_fee_pair = None, # { 'spot':(20,20), 'base':(10,10), 'dex': (10,10) }, 을 의미 dex없으면 base로 함, dex를 상세하게 'xyz': (10,10) 이런형태로 나타내도됨, 기본은 'dex'를 따름
    # 표현 방식 예제, (1,2), [1,2], 1
    # (1,2): 1=limit fee, 2=market fee
    # [1,2]: 1=limit fee, 2=market fee
    # 1: 1 = limit fee = market fee
    fetch_by_ws = True,
    FrontendMarket = False
    )

HYPERLIQUID_KEY2 = HyperliquidKEY(
    wallet_address = None,
    wallet_private_key = None,
    agent_api_address = None,
    agent_api_private_key = None,
    by_agent = True,
    vault_address = None,
    builder_code = None,
    builder_fee_pair = None,
    fetch_by_ws = True,
    FrontendMarket = False
    )