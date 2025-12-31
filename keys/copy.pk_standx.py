from dataclasses import dataclass
from typing import Optional

@dataclass
class StandXKey:
    wallet_address: str
    chain: str = "bsc"  # "bsc" or "solana"
    evm_private_key: Optional[str] = None  # Optional: for auto-signing
    session_token: Optional[str] = None  # Optional: cached JWT token
    login_port: Optional[int] = None  # Optional: for browser signing (e.g., 7081)
    open_browser: bool = True  # Auto open browser for signing

# Example usage:
# With private key (auto sign - no browser needed)
STANDX_KEY = StandXKey(
    wallet_address='0x...',
    chain='bsc',
    evm_private_key='0x...',  # Your wallet private key
)

# With browser signing (MetaMask/Rabby)
# STANDX_KEY = StandXKey(
#     wallet_address='0x...',
#     chain='bsc',
#     login_port=7081,  # Opens http://127.0.0.1:7081 for signing
# )
