from typing import Optional
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP, ROUND_DOWN

def _strip_decimal_trailing_zeros(s: str) -> str:
    """
    문자열 s가 '123.4500'이면 '123.45'로,
    '123.000'이면 '123'으로 변환한다.
    소수점이 없으면(예: '26350') 정수부의 0는 절대 제거하지 않는다.
    """
    if "." in s:
        return s.rstrip("0").rstrip(".")  # comment: 정수부는 건드리지 않음
    return s

def parse_hip3_symbol(sym: str) -> tuple[Optional[str], str]:
    s = str(sym).strip()
    if ":" in s:
        dex, coin = s.split(":", 1)
        return dex.lower().strip(), f"{dex.lower().strip()}:{coin.upper().strip()}"
    return None, s.upper().strip()

def round_to_tick(value: float, decimals: int, up: bool) -> Decimal:
    q = Decimal(f"1e-{decimals}") if decimals > 0 else Decimal("1")
    d = Decimal(str(value))
    return d.quantize(q, rounding=(ROUND_UP if up else ROUND_DOWN))

def format_price(px: float, tick_decimals: int) -> str:
    d = Decimal(str(px))
    # 1) tick에 맞게 반올림
    q = Decimal(f"1e-{max(0,int(tick_decimals))}") if int(tick_decimals) > 0 else Decimal("1")
    d = d.quantize(q, rounding=ROUND_HALF_UP)
    s = format(d, "f")
    if "." not in s:
        return s  # 정수 그대로

    int_part, frac_part = s.split(".", 1)
    int_digits = 0 if int_part in ("", "0") else len(int_part.lstrip("0"))
    sig_digits = (0 if int_part in ("", "0") else int_digits) + len(frac_part)

    # 유효숫자 5 이하면 그대로(소수부 0 제거만)
    if sig_digits <= 5:
        return _strip_decimal_trailing_zeros(s)

    # 2) 유효숫자 5로 축소(소수 자리만 줄임). 여기서도 tick보다 '더 굵은' 자리로만 줄여서 tick 배수 성질은 유지됨.
    allow_frac = max(0, 5 - int_digits)
    allow_frac = min(allow_frac, max(0,int(tick_decimals)))
    q2 = Decimal(f"1e-{allow_frac}") if allow_frac > 0 else Decimal("1")
    d2 = d.quantize(q2, rounding=ROUND_HALF_UP)
    s2 = format(d2, "f")
    return _strip_decimal_trailing_zeros(s2)

def format_size(amount: float, sz_dec: int) -> str:
    if int(sz_dec) > 0:
        q = Decimal(f"1e-{int(sz_dec)}")
        sz_d = Decimal(str(amount)).quantize(q, rounding=ROUND_HALF_UP)
    else:
        sz_d = Decimal(int(round(amount)))
    size_str = format(sz_d, "f")
    # [중요 수정] size도 정수부 0가 잘리지 않도록 소수부가 있을 때만 제거
    return _strip_decimal_trailing_zeros(size_str)