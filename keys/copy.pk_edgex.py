from dataclasses import dataclass

@dataclass
class EdgexKey:
    account_id: str
    private_key: str

EDGEX_KEY = EdgexKey(
    account_id="", # go to website
    private_key="" # go to website
)