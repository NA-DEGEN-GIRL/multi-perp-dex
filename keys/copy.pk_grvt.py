from dataclasses import dataclass

@dataclass
class GrvtKey:
    api_key: str
    account_id: str
    secret_key: str

# trading account
GRVT_KEY = GrvtKey(
    api_key='', # go to website
    account_id='',  # go to website
    secret_key=''  # go to website
)