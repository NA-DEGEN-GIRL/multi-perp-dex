from typing import Optional,Dict
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP, ROUND_DOWN
import aiohttp

BASE_URL = "https://api.hyperliquid.xyz"
STABLES = ["USDC","USDT0","USDH","USDE"]

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

async def get_dex_list(s: aiohttp.ClientSession):
    url = f"{BASE_URL}/info"
    payload = {"type":"perpDexs"}
    headers = {"Content-Type": "application/json"}
    
    async with s.post(url, json=payload, headers=headers) as r:
        try:
            resp = await r.json()
        except aiohttp.ContentTypeError:
            return
    # 순서 유지 + 중복 제거 + lower 정규화
    order = ["hl"]  # HL 항상 선두
    seen = set(["hl"])
    if isinstance(resp, list):
        for e in resp:
            if not isinstance(e, dict):
                continue
            n = e.get("name")
            if not n:
                continue
            k = str(n).lower().strip()
            if k and k not in seen:
                order.append(k); seen.add(k)
    return order

async def init_spot_token_map(s: aiohttp.ClientSession,
                              spot_index_to_name:dict,
                              spot_name_to_index:dict,
                              spot_asset_index_to_pair:dict,
                              spot_asset_index_to_bq:dict,
                              spot_token_sz_decimals:dict,
                              ):
    """
    REST info(spotMeta)를 통해
    - 토큰 인덱스 <-> 이름(USDC, PURR, ...) 맵
    - 스팟 페어 인덱스(spotInfo.index) <-> 'BASE/QUOTE' 및 (BASE, QUOTE) 맵
    을 1회 로드/갱신한다.
    """
    url = f"{BASE_URL}/info"
    payload = {"type": "spotMeta"}
    headers = {"Content-Type": "application/json"}

    async with s.post(url, json=payload, headers=headers) as r:
        status = r.status
        try:
            resp = await r.json()
        except aiohttp.ContentTypeError:
            spot_index_to_name.clear()
            spot_name_to_index.clear()
            spot_asset_index_to_pair.clear()
            spot_asset_index_to_bq.clear()
            spot_token_sz_decimals.clear()
            return False
    
    # 안전 가드: dict 응답인지 확인
    if not isinstance(resp, dict):
        spot_index_to_name.clear()
        spot_name_to_index.clear()
        spot_asset_index_to_pair.clear()
        spot_asset_index_to_bq.clear()
        spot_token_sz_decimals.clear()
        return False
    
    tokens = (resp or {}).get("tokens") or []
    universe = (resp or {}).get("universe") or (resp or {}).get("spotInfos") or []

    # 1) 토큰 맵(spotMeta.tokens[].index -> name)
    idx2name: Dict[int, str] = {}
    name2idx: Dict[str, int] = {}
    token_szdec: Dict[str, int] = {}
    for t in tokens:
        if isinstance(t, dict) and "index" in t and "name" in t:
            try:
                idx = int(t["index"])
                name = str(t["name"]).upper().strip()
                szd = int(t.get("szDecimals") or 0)
                if not name:
                    continue
                idx2name[idx] = name
                name2idx[name] = idx
                token_szdec[name] = szd
            except Exception as ex:
                pass
        #print(name,idx)
    spot_index_to_name.update(idx2name)
    spot_name_to_index.update(name2idx)
    spot_token_sz_decimals.update(token_szdec)
    
    # 2) 페어 맵(spotInfo.index -> 'BASE/QUOTE' 및 (BASE, QUOTE))
    pair_by_index: Dict[int, str] = {}
    bq_by_index: Dict[int, tuple[str, str]] = {}
    ok = 0
    fail = 0
    for si in universe:
        if not isinstance(si, dict):
            continue
        # 필수: spotInfo.index
        try:
            s_idx = int(si.get("index"))
        except Exception:
            fail += 1
            continue

        # 우선 'tokens': [baseIdx, quoteIdx] 배열 처리
        base_idx = None
        quote_idx = None
        toks = si.get("tokens")
        if isinstance(toks, (list, tuple)) and len(toks) >= 2:
            try:
                base_idx = int(toks[0])
                quote_idx = int(toks[1])
            except Exception:
                base_idx, quote_idx = None, None

        # 보조: 환경별 키(base/baseToken/baseTokenIndex, quote/...)
        if base_idx is None:
            bi = si.get("base") or si.get("baseToken") or si.get("baseTokenIndex")
            try:
                base_idx = int(bi) if bi is not None else None
            except Exception:
                base_idx = None
        if quote_idx is None:
            qi = si.get("quote") or si.get("quoteToken") or si.get("quoteTokenIndex")
            try:
                quote_idx = int(qi) if qi is not None else None
            except Exception:
                quote_idx = None

        base_name = idx2name.get(base_idx) if base_idx is not None else None
        quote_name = idx2name.get(quote_idx) if quote_idx is not None else None

        # name 필드가 'BASE/QUOTE'면 그대로, '@N' 등인 경우 토큰명으로 합성
        name_field = si.get("name")
        pair_name = None
        if isinstance(name_field, str) and "/" in name_field:
            pair_name = name_field.strip().upper()
            # base/quote 이름 보완
            try:
                b, q = pair_name.split("/", 1)
                base_name = base_name or b
                quote_name = quote_name or q
            except Exception:
                pass
        else:
            if base_name and quote_name:
                pair_name = f"{base_name}/{quote_name}"

        if pair_name and base_name and quote_name:
            pair_by_index[s_idx] = pair_name
            bq_by_index[s_idx] = (base_name, quote_name)
            ok += 1
        else:
            fail += 1
        #print(base_name,quote_name)
    
    spot_asset_index_to_pair.update(pair_by_index)
    spot_asset_index_to_bq.update(bq_by_index)

    return True

async def init_perp_meta_cache(s: aiohttp.ClientSession, 
                               perp_metas_raw: dict, 
                               perp_asset_map: dict,
                               ) -> bool:
    """
    /info {"type":"allPerpMetas"}를 1회 호출해 런타임 캐시를 만든다.
    - 메인(HL, meta_idx==0):  key='BTC' (대문자), asset_id = local_idx
    - HIP-3(meta_idx>0):      key='dex:COIN' (원문), asset_id = 100000 + meta_idx*10000 + local_idx
    """

    url = f"{BASE_URL}/info"
    payload = {"type": "allPerpMetas"}
    try:
        async with s.post(url, json=payload, headers={"Content-Type": "application/json"}) as r:
            metas = await r.json()
    except Exception:
        metas = []

    # 원본 저장
    perp_metas_raw.clear()
    perp_metas_raw.extend(metas if isinstance(metas, list) else [])
    #print(perp_metas_raw)
    
    perp_asset_map.clear()
    

    for meta_idx, meta in enumerate(perp_metas_raw):
        uni = (meta or {}).get("universe") or []
        collateral_token_id = (meta or {}).get("collateralToken") or 0
        for local_idx, a in enumerate(uni):
            if not isinstance(a, dict):
                continue
            name = a.get("name")
            if not isinstance(name, str) or not name:
                continue
            if a.get("isDelisted", False):
                continue
            try:
                szd = int(a.get("szDecimals") or 0)
            except Exception:
                szd = 0

            try:
                max_lev = int(a.get("maxLeverage") or 1)
            except Exception:
                max_lev = 1

            try:
                isolated = int(a.get("onlyIsolated") or False)
            except Exception:
                isolated = False
            
            if meta_idx == 0:
                key = name.upper()                 # 메인(HL)
                asset_id = int(local_idx)
            else:
                key = name                         # HIP-3: 'dex:COIN'
                asset_id = 100000 + meta_idx * 10000 + local_idx

            perp_asset_map[key] = (asset_id, szd, max_lev, isolated, collateral_token_id)

    return True