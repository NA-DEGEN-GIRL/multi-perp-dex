from dataclasses import dataclass

@dataclass
class ParadexKey:
    wallet_address: str
    paradex_address: str
    paradex_private_key: str

PARADEX_KEY = ParadexKey(
    paradex_address = '', # go to website
    wallet_address = 'your_evm_address',
    paradex_private_key = '', # go to website
    )
