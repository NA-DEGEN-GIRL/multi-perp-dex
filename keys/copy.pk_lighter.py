from dataclasses import dataclass

@dataclass
class LighterKey:
    account_id: int
    private_key: str
    api_key_id: int
    l1_address: str


LIGHTER_KEY = LighterKey(
    account_id = 1234, # go to website, https://app.lighter.xyz/explorer/accounts/ 본인주소 넣고, 거래 내역보면 account index 볼수있음
    private_key = 'api_private_key',
    api_key_id = 'api_key_id',
    l1_address = 'your_evm_address',
)