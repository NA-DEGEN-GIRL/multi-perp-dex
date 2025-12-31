from multi_perp_dex import MultiPerpDex, MultiPerpDexMixin  # [UNCHANGED]

# exchange_factory의 함수들을 "지연 임포트"로 재노출
# - 이렇게 해야 mpdex를 import할 때 wrappers의 무거운 의존성을 즉시 요구하지 않습니다.
async def create_exchange(exchange_name: str, key_params=None):
    # comment: 호출 시점에만 exchange_factory를 불러오므로, 선택적 의존성이 없을 경우에도 import mpdex는 안전합니다.
    from exchange_factory import create_exchange as _create_exchange
    return await _create_exchange(exchange_name, key_params)

def symbol_create(exchange_name: str, coin: str):
    from exchange_factory import symbol_create as _symbol_create
    return _symbol_create(exchange_name, coin)

# 개별 래퍼 클래스는 __getattr__로 지연 노출(필요할 때만 import)
# 사용 예: from mpdex import LighterExchange
import importlib

def __getattr__(name):
    mapping = {
        "LighterExchange": ("wrappers.lighter", "LighterExchange"),
        "BackpackExchange": ("wrappers.backpack", "BackpackExchange"),
        "EdgexExchange": ("wrappers.edgex", "EdgexExchange"),
        "GrvtExchange": ("wrappers.grvt", "GrvtExchange"),
        "ParadexExchange": ("wrappers.paradex", "ParadexExchange"),
        "TreadfiHlExchange": ("wrappers.treadfi_hl","TreadfiHlExchange"),
        "VariationalExchange": ("wrappers.variational","VariationalExchange"),
        "PacificaExchange": ("wrappers.pacifica","PacificaExchange"),
        "HyperliquidExchange": ("wrappers.hyperliquid","HyperliquidExchange"),
        "StandXExchange": ("wrappers.standx", "StandXExchange"),
    }
    if name in mapping:
        mod, attr = mapping[name]
        module = importlib.import_module(mod)
        return getattr(module, attr)
    raise AttributeError(f"module 'mpdex' has no attribute {name!r}")

__all__ = [  # 공개 심볼 명시
    "MultiPerpDex", "MultiPerpDexMixin",
    "create_exchange", "symbol_create",
    "LighterExchange", "BackpackExchange", "EdgexExchange", "GrvtExchange", "ParadexExchange", "TreadfiHlExchange",
    "VariationalExchange", "PacificaExchange", "HyperliquidExchange", "StandXExchange"
]