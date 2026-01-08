"""
모든 거래소 create_exchange → close 테스트
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mpdex import create_exchange

# Import keys
from keys.pk_lighter import LIGHTER_KEY
from keys.pk_hyperliquid import HYPERLIQUID_KEY
from keys.pk_pacifica import PACIFICA_KEY
from keys.pk_standx import STANDX_KEY
from keys.pk_backpack import BACKPACK_KEY
from keys.pk_grvt import GRVT_KEY
from keys.pk_edgex import EDGEX_KEY
from keys.pk_treadfi_hl import TREADFI_HL_KEY
from keys.pk_treadfi_pc import TREADFI_PC_KEY
from keys.pk_variational import VARIATIONAL_KEY
from keys.pk_superstack import SUPERSTACK_KEY
from keys.pk_paradex import PARADEX_KEY

EXCHANGES = [
    ("lighter", LIGHTER_KEY),
    ("hyperliquid", HYPERLIQUID_KEY),
    ("pacifica", PACIFICA_KEY),
    ("standx", STANDX_KEY),
    ("backpack", BACKPACK_KEY),
    ("grvt", GRVT_KEY),
    ("edgex", EDGEX_KEY),
    ("paradex", PARADEX_KEY),
    ("treadfi.hyperliquid", TREADFI_HL_KEY),
    ("treadfi.pacifica", TREADFI_PC_KEY),
    ("variational", VARIATIONAL_KEY),
    ("superstack", SUPERSTACK_KEY),
]

async def test_exchange(name: str, key):
    """Test single exchange create + close"""
    try:
        print(f"[{name}] Creating...")
        ex = await create_exchange(name, key)
        print(f"[{name}] Created OK")

        await ex.close()
        print(f"[{name}] Closed OK")
        return True
    except Exception as e:
        print(f"[{name}] FAILED: {e}")
        return False

async def main():
    print("=== Exchange Close Test ===\n")

    results = {}
    for name, key in EXCHANGES:
        results[name] = await test_exchange(name, key)
        print()

    # Summary
    print("=== Summary ===")
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)

    for name, ok in results.items():
        status = "✓ OK" if ok else "✗ FAILED"
        print(f"  {name}: {status}")

    print(f"\nTotal: {passed} passed, {failed} failed")

if __name__ == "__main__":
    asyncio.run(main())
