from dataclasses import dataclass

@dataclass
class BackpackKey:
    api_key: str
    secret_key: str

# trading account
BACKPACK_KEY = BackpackKey(
    api_key = '',
    secret_key= ''
) 