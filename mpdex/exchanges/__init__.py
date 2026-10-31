# mpdex.exchanges - Exchange wrapper implementations
# All exchange classes can be imported from here
#
# 지연 임포트: 거래소 하나(mpdex.exchanges.xxx)만 써도 이 패키지 __init__이 먼저 실행되므로,
# 여기서 전부 import하면 모든 거래소 SDK(lighter, cairo 등)를 로드해 수십 초가 걸림.
# → 클래스 접근 시점에만 해당 모듈 로드 (from mpdex.exchanges import LighterExchange 그대로 동작)
import importlib

_LAZY = {
    "LighterExchange": ".lighter",
    "BackpackExchange": ".backpack",
    "EdgexExchange": ".edgex",
    "GrvtExchange": ".grvt",
    "ParadexExchange": ".paradex",
    "PacificaExchange": ".pacifica",
    "HyperliquidExchange": ".hyperliquid",
    "SuperstackExchange": ".superstack",
    "StandXExchange": ".standx",
    "VariationalExchange": ".variational",
    "TreadfiHlExchange": ".treadfi_hl",
    "TreadfiPcExchange": ".treadfi_pc",
}


def __getattr__(name):
    if name in _LAZY:
        return getattr(importlib.import_module(_LAZY[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "LighterExchange",
    "BackpackExchange",
    "EdgexExchange",
    "GrvtExchange",
    "ParadexExchange",
    "PacificaExchange",
    "HyperliquidExchange",
    "SuperstackExchange",
    "StandXExchange",
    "VariationalExchange",
    "TreadfiHlExchange",
    "TreadfiPcExchange",
]
