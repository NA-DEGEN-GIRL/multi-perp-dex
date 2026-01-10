"""
Extended Exchange Credentials Template

Copy this file to pk_extended.py and fill in your credentials.

To get credentials:
1. Go to Extended exchange and create account
2. Generate API key from API Management page
3. Get Stark keys (vault_id, stark_public_key, stark_private_key)
   - Can be derived using SDK's UserClient.onboard() method

SDK Installation:
    pip install x10-python-trading-starknet

Requires Python 3.10+
"""

from dataclasses import dataclass


@dataclass
class ExtendedKey:
    api_key: str
    stark_public_key: str
    stark_private_key: str
    vault_id: int
    network: str = "mainnet"  # "mainnet" or "testnet"
    prefer_ws: bool = True


# Replace with your actual credentials
EXTENDED_KEY = ExtendedKey(
    api_key="your_api_key_here",
    stark_public_key="0x...",
    stark_private_key="0x...",
    vault_id=12345,
    network="mainnet",
)
