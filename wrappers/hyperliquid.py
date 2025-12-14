from mpdex.utils.hyperliquid_base import HyperliquidBase
from eth_account import Account
from .hl_sign import sign_l1_action as hl_sign_l1_action
import time

class HyperliquidExchange(HyperliquidBase):
    def __init__(
        self,
        wallet_address=None,
        wallet_private_key=None,
        agent_api_address=None,
        agent_api_private_key=None,
        by_agent=True,
        vault_address=None,
        builder_code=None,
        builder_fee_pair=None,
        *,
        fetch_by_ws=False,
        FrontendMarket=False,
    ):
        super().__init__(
            wallet_address=wallet_address,
            vault_address=vault_address,
            builder_code=builder_code,
            builder_fee_pair=builder_fee_pair,
            fetch_by_ws=fetch_by_ws,
            FrontendMarket=FrontendMarket,
        )
        self.by_agent = by_agent
        self.wallet_private_key = wallet_private_key if not by_agent else None
        self.agent_api_address = agent_api_address if by_agent else None
        self.agent_api_private_key = agent_api_private_key if by_agent else None

    async def _make_signed_payload(self, action: dict) -> dict:
        nonce = int(time.time() * 1000)
        priv = (self.agent_api_private_key if self.by_agent else self.wallet_private_key) or ""

        if not priv:
            if self.by_agent:
                raise RuntimeError("agent_api_private_key가 필요합니다")
            else:
                raise RuntimeError("wallet_private_key가 필요합니다")

        priv = priv[2:] if priv.startswith("0x") else priv
        wallet = Account.from_key(bytes.fromhex(priv))
        sig = hl_sign_l1_action(wallet, action, self.vault_address, nonce, None, True)
        payload = {"action": action, "nonce": nonce, "signature": sig}
        if self.vault_address:
            payload["vaultAddress"] = self.vault_address
        return payload