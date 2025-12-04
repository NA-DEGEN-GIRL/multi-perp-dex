from dataclasses import dataclass

@dataclass
class HyperliquidKEY:
    wallet_address: str         # required
    wallet_private_key: str     # required only if no agent
    agent_api_address: str      # required only if agent
    agent_api_private_key: str  # required only if agent
    by_agent: bool              # required
    vault_address: str          # optional
    builder_code: str           # optional
    builder_fee_pair: dict      # optional
    fetch_by_ws: bool           # optional
    
HYPERLIQUID_KEY = HyperliquidKEY(
    wallet_address = None,
    wallet_private_key = None,
    agent_api_address = None,
    agent_api_private_key = None,
    by_agent = True,
    vault_address = None,
    builder_code = None,
    builder_fee_pair = None, # {'base':10,'dex':10}, dex없으면 base로 함, dex를 상세하게 'xyz':10 이런형태로 나타내도됨, 기본은 'dex'를 따름
    fetch_by_ws = True
    )

HYPERLIQUID_KEY2 = HyperliquidKEY(
    wallet_address = None,
    wallet_private_key = None,
    agent_api_address = None,
    agent_api_private_key = None,
    by_agent = True,
    vault_address = None,
    builder_code = None,
    builder_fee_pair = None, # {'base':10,'dex':10}, dex없으면 base로 함, dex를 상세하게 'xyz':10 이런형태로 나타내도됨, 기본은 'dex'를 따름
    fetch_by_ws = True
    )