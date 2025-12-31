"""
StandX Perps Authentication
- Ed25519 key pair generation for body signing
- Browser wallet signing flow (like TreadFi/Variational)
- Private key signing flow
- Session caching
"""
import asyncio
import base64
import json
import os
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from aiohttp import web
import aiohttp

# Ed25519 signing
try:
    from nacl.signing import SigningKey
    from nacl.encoding import RawEncoder
except ImportError:
    SigningKey = None
    RawEncoder = None

# Base58 encoding
try:
    import base58
except ImportError:
    base58 = None

# EVM signing
try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except ImportError:
    Account = None
    encode_defunct = None

# Checksum address
try:
    from eth_utils import to_checksum_address
except ImportError:
    def to_checksum_address(addr: str) -> str:
        return addr


STANDX_API_BASE = "https://api.standx.com"
STANDX_PERPS_BASE = "https://perps.standx.com"


class StandXAuth:
    """
    StandX authentication wrapper

    Usage:
        # With private key (auto sign)
        auth = StandXAuth(wallet_address="0x...", evm_private_key="0x...")
        await auth.login()

        # With browser wallet signing
        auth = StandXAuth(wallet_address="0x...")
        await auth.login(port=7081)  # Opens browser for signing
    """

    def __init__(
        self,
        wallet_address: str,
        chain: str = "bsc",
        evm_private_key: Optional[str] = None,
        session_token: Optional[str] = None,
        http_timeout: float = 30.0,
    ):
        if not wallet_address:
            raise ValueError("wallet_address is required")

        if SigningKey is None:
            raise RuntimeError("pynacl not installed: pip install pynacl")
        if base58 is None:
            raise RuntimeError("base58 not installed: pip install base58")

        self.wallet_address = to_checksum_address(wallet_address)
        self.chain = chain
        self._pk = evm_private_key
        self._http_timeout = http_timeout

        # Ed25519 key pair for body signing
        self._ed25519_private_key: Optional[SigningKey] = None
        self._ed25519_public_key: Optional[bytes] = None
        self._request_id: Optional[str] = None

        # JWT token
        self._token: Optional[str] = session_token
        self._logged_in: bool = False

        # Cache path
        self._session_store_path = self._cache_path()

    # ----------------------------
    # Public API
    # ----------------------------
    async def login(self, port: Optional[int] = None, open_browser: bool = True, expires_seconds: int = 604800) -> Dict[str, Any]:
        """
        Login to StandX

        1) Check cached session
        2) If private key provided -> auto sign
        3) Otherwise -> browser wallet signing via local server

        Args:
            port: Port for local web server (browser signing)
            open_browser: Auto open browser
            expires_seconds: Token expiration (default 7 days)
        """
        self._load_session_cache()

        # Check cached token
        if self._token and self._is_token_valid(self._token):
            self._logged_in = True
            return {
                "ok": True,
                "cached": True,
                "token": self._token,
                "message": "cached token valid",
            }

        # Generate Ed25519 key pair for body signing
        self._generate_ed25519_keypair()

        # Private key flow
        if self._pk:
            if Account is None or encode_defunct is None:
                raise RuntimeError("eth-account not installed: pip install eth-account")

            # 1. Get signed data
            signed_data = await self._prepare_signin()

            # 2. Parse and extract message
            payload = self._parse_jwt_payload(signed_data)
            message = payload.get("message", "")
            if not message:
                raise RuntimeError("No message in signedData")

            # 3. Sign message with wallet
            signature = self._personal_sign_local(message, self._pk)

            # 4. Login
            resp = await self._login_request(signature, signed_data, expires_seconds)
            self._token = resp.get("token")
            self._logged_in = bool(self._token)
            self._save_session_cache()

            return {"ok": True, "method": "private_key", **resp}

        # Browser wallet flow
        if not port:
            raise ValueError("Browser signing requires port. Example: port=7081")

        result = await self._browser_login_flow(port, open_browser, expires_seconds)
        return result

    def sign_request(self, payload: str) -> Dict[str, str]:
        """
        Sign request body for StandX API

        Returns headers:
            x-request-sign-version: v1
            x-request-id: uuid
            x-request-timestamp: timestamp_ms
            x-request-signature: base64_signature
        """
        if self._ed25519_private_key is None:
            raise RuntimeError("Ed25519 key not initialized. Call login() first.")

        version = "v1"
        request_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)

        # Build message: "{version},{id},{timestamp},{payload}"
        sign_msg = f"{version},{request_id},{timestamp},{payload}"

        # Sign with Ed25519
        signed = self._ed25519_private_key.sign(sign_msg.encode("utf-8"), encoder=RawEncoder)
        signature_bytes = signed.signature
        signature_b64 = base64.b64encode(signature_bytes).decode("utf-8")

        return {
            "x-request-sign-version": version,
            "x-request-id": request_id,
            "x-request-timestamp": str(timestamp),
            "x-request-signature": signature_b64,
        }

    def get_auth_headers(self) -> Dict[str, str]:
        """Get Authorization header"""
        if not self._token:
            raise RuntimeError("Not logged in. Call login() first.")
        return {"Authorization": f"Bearer {self._token}"}

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in and self._token is not None

    @property
    def request_id(self) -> Optional[str]:
        """Base58 encoded Ed25519 public key"""
        return self._request_id

    # ----------------------------
    # Ed25519 Key Management
    # ----------------------------
    def _generate_ed25519_keypair(self) -> None:
        """Generate Ed25519 key pair for body signing"""
        self._ed25519_private_key = SigningKey.generate()
        self._ed25519_public_key = self._ed25519_private_key.verify_key.encode()
        self._request_id = base58.b58encode(self._ed25519_public_key).decode("utf-8")

    # ----------------------------
    # HTTP Helpers
    # ----------------------------
    async def _prepare_signin(self) -> str:
        """
        POST /v1/offchain/prepare-signin
        Returns signedData (JWT)
        """
        url = f"{STANDX_API_BASE}/v1/offchain/prepare-signin?chain={self.chain}"
        payload = {
            "address": self.wallet_address,
            "requestId": self._request_id,
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"prepare-signin failed: {resp.status} {text}")
                data = await resp.json()
                if not data.get("success"):
                    raise RuntimeError(f"prepare-signin failed: {data}")
                return data.get("signedData", "")

    async def _login_request(self, signature: str, signed_data: str, expires_seconds: int = 604800) -> Dict[str, Any]:
        """
        POST /v1/offchain/login
        Returns JWT token
        """
        url = f"{STANDX_API_BASE}/v1/offchain/login?chain={self.chain}"
        payload = {
            "signature": signature,
            "signedData": signed_data,
            "expiresSeconds": expires_seconds,
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._http_timeout)) as session:
            async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"login failed: {resp.status} {text}")
                return await resp.json()

    def _personal_sign_local(self, message: str, private_key: str) -> str:
        """Sign message with EVM wallet (personal_sign)"""
        signed = Account.sign_message(encode_defunct(text=message), private_key=private_key)
        return signed.signature.hex()

    def _parse_jwt_payload(self, jwt_token: str) -> Dict[str, Any]:
        """Parse JWT payload without verification"""
        try:
            parts = jwt_token.split(".")
            if len(parts) < 2:
                return {}
            payload_b64 = parts[1]
            # Add padding
            rem = len(payload_b64) % 4
            if rem:
                payload_b64 += "=" * (4 - rem)
            payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
            return json.loads(payload_bytes)
        except Exception:
            return {}

    def _is_token_valid(self, jwt_token: str, leeway_sec: int = 30) -> bool:
        """Check if JWT token is expired"""
        try:
            payload = self._parse_jwt_payload(jwt_token)
            exp = int(payload.get("exp", 0))
            now = int(time.time())
            return exp > (now + leeway_sec)
        except Exception:
            return False

    # ----------------------------
    # Browser Login Flow
    # ----------------------------
    async def _browser_login_flow(self, port: int, open_browser: bool, expires_seconds: int) -> Dict[str, Any]:
        """Local web server for browser wallet signing"""
        login_event = asyncio.Event()
        last_response: Dict[str, Any] = {}

        async def handle_index(_req: web.Request):
            return web.Response(text=self._login_html(), content_type="text/html")

        async def handle_prepare(_req: web.Request):
            """Get signing data"""
            try:
                signed_data = await self._prepare_signin()
                payload = self._parse_jwt_payload(signed_data)
                message = payload.get("message", "")
                return web.json_response({
                    "ok": True,
                    "signedData": signed_data,
                    "message": message,
                    "address": self.wallet_address,
                })
            except Exception as e:
                return web.json_response({"ok": False, "error": str(e)}, status=500)

        async def handle_submit(req: web.Request):
            nonlocal last_response
            try:
                body = await req.json()
                signature = body.get("signature")
                signed_data = body.get("signedData")

                if not signature or not signed_data:
                    return web.json_response({"ok": False, "error": "missing signature/signedData"}, status=400)

                resp = await self._login_request(signature, signed_data, expires_seconds)
                self._token = resp.get("token")
                self._logged_in = bool(self._token)
                self._save_session_cache()

                last_response = {"ok": True, **resp}
                login_event.set()
                return web.json_response(last_response)
            except Exception as e:
                last_response = {"ok": False, "error": str(e)}
                return web.json_response(last_response, status=500)

        app = web.Application()
        app.router.add_get("/", handle_index)
        app.router.add_get("/prepare", handle_prepare)
        app.router.add_post("/submit", handle_submit)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()

        url = f"http://127.0.0.1:{port}"
        print(f"[standx] Open {url} in your browser to sign the login message")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        await login_event.wait()
        await runner.cleanup()
        return last_response

    def _login_html(self) -> str:
        """Login UI HTML"""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>StandX Login</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 24px; max-width: 600px; margin: 0 auto; }}
.row {{ margin: 12px 0; }}
input, textarea {{ width: 100%; padding: 8px; font-size: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
textarea {{ height: 120px; resize: vertical; }}
button {{ padding: 12px 24px; cursor: pointer; font-size: 14px; margin-right: 8px; }}
button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
.status {{ padding: 12px; border-radius: 6px; margin-top: 12px; }}
.status.success {{ background: #d4edda; color: #155724; }}
.status.error {{ background: #f8d7da; color: #721c24; }}
.status.info {{ background: #cce5ff; color: #004085; }}
h2 {{ margin-bottom: 24px; }}
label {{ font-weight: 500; display: block; margin-bottom: 4px; }}
</style>
</head>
<body>
<h2>StandX Perps Login</h2>

<div class="row">
    <label>Wallet Address</label>
    <input id="address" type="text" value="{self.wallet_address}" readonly />
</div>

<div class="row">
    <button id="connectBtn">1. Connect Wallet</button>
    <button id="prepareBtn" disabled>2. Get Message</button>
    <button id="signBtn" disabled>3. Sign & Login</button>
</div>

<div class="row">
    <label>Message to Sign</label>
    <textarea id="message" readonly placeholder="Click 'Get Message' to fetch the signing message..."></textarea>
</div>

<div id="statusBox" class="status info" style="display:none;"></div>

<script>
const $ = s => document.querySelector(s);
let signedData = null;
let connectedAddress = null;

function showStatus(msg, type) {{
    const box = $('#statusBox');
    box.textContent = msg;
    box.className = 'status ' + type;
    box.style.display = 'block';
}}

// 1. Connect Wallet
$('#connectBtn').onclick = async () => {{
    try {{
        if (!window.ethereum) throw new Error('No wallet detected. Please install MetaMask or Rabby.');
        const accounts = await window.ethereum.request({{ method: 'eth_requestAccounts' }});
        connectedAddress = accounts[0];
        $('#address').value = connectedAddress;
        $('#prepareBtn').disabled = false;
        showStatus('Wallet connected: ' + connectedAddress, 'success');
    }} catch (e) {{
        showStatus('Connect failed: ' + e.message, 'error');
    }}
}};

// 2. Get Message
$('#prepareBtn').onclick = async () => {{
    try {{
        showStatus('Fetching signing message...', 'info');
        const r = await fetch('/prepare');
        const j = await r.json();
        if (!j.ok) throw new Error(j.error || 'Failed to get message');
        signedData = j.signedData;
        $('#message').value = j.message;
        $('#signBtn').disabled = false;
        showStatus('Message ready. Click "Sign & Login" to proceed.', 'success');
    }} catch (e) {{
        showStatus('Prepare failed: ' + e.message, 'error');
    }}
}};

// 3. Sign & Login
$('#signBtn').onclick = async () => {{
    try {{
        if (!connectedAddress) throw new Error('Please connect wallet first');
        if (!signedData) throw new Error('Please get message first');

        const message = $('#message').value;
        showStatus('Please sign the message in your wallet...', 'info');

        const signature = await window.ethereum.request({{
            method: 'personal_sign',
            params: [message, connectedAddress]
        }});

        showStatus('Submitting login...', 'info');
        const r = await fetch('/submit', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ signature, signedData }})
        }});
        const j = await r.json();
        if (!j.ok) throw new Error(j.error || 'Login failed');

        showStatus('Login successful! You can close this tab.', 'success');
        $('#signBtn').disabled = true;
    }} catch (e) {{
        showStatus('Sign/Login failed: ' + e.message, 'error');
    }}
}};

// Auto-connect if wallet available
window.addEventListener('load', async () => {{
    if (window.ethereum) {{
        try {{
            const accounts = await window.ethereum.request({{ method: 'eth_accounts' }});
            if (accounts.length > 0) {{
                connectedAddress = accounts[0];
                $('#address').value = connectedAddress;
                $('#prepareBtn').disabled = false;
                showStatus('Wallet already connected: ' + connectedAddress, 'info');
            }}
        }} catch (e) {{}}
    }}
}});
</script>
</body>
</html>
"""

    # ----------------------------
    # Cache Management
    # ----------------------------
    def _find_project_root_from_cwd(self) -> Path:
        """Find project root from CWD"""
        markers = {"pyproject.toml", "setup.cfg", "setup.py", ".git"}
        p = Path.cwd().resolve()
        try:
            for parent in [p] + list(p.parents):
                for name in markers:
                    if (parent / name).exists():
                        return parent
        except Exception:
            pass
        return Path.cwd().resolve()

    def _cache_dir(self) -> str:
        """Get cache directory"""
        base = self._find_project_root_from_cwd()
        target = base / ".cache"
        try:
            target.mkdir(parents=True, exist_ok=True)
            return str(target)
        except Exception:
            home_fallback = Path.home() / ".cache" / "mpdex"
            home_fallback.mkdir(parents=True, exist_ok=True)
            return str(home_fallback)

    def _cache_path(self) -> str:
        """Get cache file path for this wallet"""
        addr = (self.wallet_address or "default").lower()
        safe = addr.replace(":", "_")
        return os.path.join(self._cache_dir(), f"standx_session_{safe}.json")

    def _save_session_cache(self) -> None:
        """Save session to cache"""
        os.makedirs(os.path.dirname(self._session_store_path), exist_ok=True)

        data = {
            "address": self.wallet_address,
            "chain": self.chain,
            "token": self._token,
            "ed25519_private_key": base64.b64encode(bytes(self._ed25519_private_key)).decode("utf-8") if self._ed25519_private_key else None,
            "request_id": self._request_id,
            "saved_at": int(time.time()),
        }
        try:
            with open(self._session_store_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[standx] cache save failed: {e}")

    def _load_session_cache(self) -> None:
        """Load session from cache"""
        try:
            if not os.path.exists(self._session_store_path):
                return
            with open(self._session_store_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data.get("address", "").lower() != self.wallet_address.lower():
                return

            # Restore token
            tok = data.get("token")
            if tok and self._is_token_valid(tok):
                self._token = tok

            # Restore Ed25519 key
            ed_key_b64 = data.get("ed25519_private_key")
            if ed_key_b64:
                ed_key_bytes = base64.b64decode(ed_key_b64)
                self._ed25519_private_key = SigningKey(ed_key_bytes)
                self._ed25519_public_key = self._ed25519_private_key.verify_key.encode()
                self._request_id = data.get("request_id") or base58.b58encode(self._ed25519_public_key).decode("utf-8")
        except Exception as e:
            print(f"[standx] cache load failed: {e}")

    def clear_cache(self) -> bool:
        """Clear cached session"""
        try:
            if os.path.exists(self._session_store_path):
                os.remove(self._session_store_path)
                return True
        except Exception:
            pass
        return False

    def cache_path(self) -> str:
        """Get cache file path (public)"""
        return self._session_store_path


# ----------------------------
# CLI Support
# ----------------------------
async def _amain():
    import argparse
    p = argparse.ArgumentParser(description="StandX Login")
    p.add_argument("--address", required=True, help="EVM wallet address (0x...)")
    p.add_argument("--chain", default="bsc", help="Chain: bsc or solana")
    p.add_argument("--pk", default=None, help="Optional: EVM private key for auto-sign")
    p.add_argument("--port", type=int, default=7081, help="Local server port for browser signing")
    p.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    p.add_argument("--expires", type=int, default=604800, help="Token expiration in seconds (default: 7 days)")
    args = p.parse_args()

    auth = StandXAuth(
        wallet_address=args.address,
        chain=args.chain,
        evm_private_key=args.pk,
    )

    if args.pk:
        result = await auth.login()
    else:
        result = await auth.login(port=args.port, open_browser=not args.no_browser, expires_seconds=args.expires)

    print(json.dumps({
        "ok": result.get("ok"),
        "has_token": bool(auth.token),
        "cache_path": auth.cache_path(),
    }, ensure_ascii=False, indent=2))


def main():
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
