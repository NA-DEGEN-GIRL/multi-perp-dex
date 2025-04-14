from dataclasses import dataclass

@dataclass
class LighterKey:
    account_id: int
    private_key: str

LIGHTER_KEY = LighterKey(
    account_id = 1234, # go to website
    private_key = 'your_evm_private_key'
)