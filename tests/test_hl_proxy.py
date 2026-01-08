"""
Hyperliquid Proxy 주문 테스트

프록시를 통해 주문이 정상적으로 전송되는지 테스트
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_single_proxy(proxy_idx: int, proxy_url: str, hyperliquid_key) -> dict:
    """단일 프록시 테스트, 결과 dict 반환"""
    from wrappers.hyperliquid import HyperliquidExchange

    result = {
        "idx": proxy_idx,
        "ip": proxy_url.split("-ip-")[-1].split(":")[0] if "-ip-" in proxy_url else "unknown",
        "order_ms": None,
        "cancel_ms": None,
        "error": None,
    }

    try:
        ex = await HyperliquidExchange(
            wallet_address=hyperliquid_key.wallet_address,
            wallet_private_key=hyperliquid_key.wallet_private_key,
            agent_api_address=hyperliquid_key.agent_api_address,
            agent_api_private_key=hyperliquid_key.agent_api_private_key,
            by_agent=hyperliquid_key.by_agent,
            vault_address=hyperliquid_key.vault_address,
            builder_code=hyperliquid_key.builder_code,
            builder_fee_pair=hyperliquid_key.builder_fee_pair,
            FrontendMarket=hyperliquid_key.FrontendMarket,
            proxy=proxy_url,
        ).init()

        # WS 비활성화 (REST only 테스트)
        ex.ws_client = None
        ex._ws_disabled = True  # WS 재생성 방지

        try:
            symbol = "BTC"
            price = await ex.get_mark_price_rest(symbol)  # REST로 가격 조회
            limit_price = round(price * 0.95, 1)
            amount = 0.00025

            # 주문 (REST only - proxy 테스트니까)
            t0 = time.perf_counter()
            order_result = await ex.create_order(
                symbol=symbol,
                side="buy",
                amount=amount,
                price=limit_price,
                order_type="limit",
                prefer_ws=False,  # REST 강제
            )
            result["order_ms"] = (time.perf_counter() - t0) * 1000

            # 취소 (REST only)
            await asyncio.sleep(0.1)  # 잠시 대기
            t2 = time.perf_counter()
            await ex.cancel_orders(symbol, prefer_ws=False)  # REST 강제
            result["cancel_ms"] = (time.perf_counter() - t2) * 1000

        finally:
            await ex.close()

    except Exception as e:
        result["error"] = str(e)

    return result


async def test_proxy_connectivity():
    """프록시 연결 테스트 (IP 유효성 확인)"""
    import aiohttp

    from keys.pk_proxy import BRIGHTDATA_CONFIG, TEST_IPS

    results = []

    print(f"Testing {len(TEST_IPS)} proxies...\n")

    for idx, ip in enumerate(TEST_IPS):
        proxy_url = BRIGHTDATA_CONFIG.build_url(ip)
        print(f"[{idx:2d}] {ip:<18}", end=" ", flush=True)

        result = {"idx": idx, "ip": ip, "latency_ms": None, "error": None}

        try:
            async with aiohttp.ClientSession() as session:
                t0 = time.perf_counter()
                async with session.get(
                    "https://api.hyperliquid.xyz/info",
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    latency = (time.perf_counter() - t0) * 1000
                    if resp.status == 200:
                        result["latency_ms"] = latency
                        print(f"OK  {latency:.0f}ms")
                    else:
                        result["error"] = f"HTTP {resp.status}"
                        print(f"FAIL (HTTP {resp.status})")
        except asyncio.TimeoutError:
            result["error"] = "Timeout"
            print("FAIL (Timeout)")
        except Exception as e:
            result["error"] = str(e)[:30]
            print(f"FAIL ({str(e)[:30]})")

        results.append(result)

    # === 결과 요약 ===
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    ok_results = [r for r in results if not r["error"]]
    fail_results = [r for r in results if r["error"]]

    print(f"\n✓ Working IPs ({len(ok_results)}):")
    for r in ok_results:
        print(f"  {r['ip']:<18} {r['latency_ms']:.0f}ms")

    if fail_results:
        print(f"\n✗ Failed IPs ({len(fail_results)}):")
        for r in fail_results:
            print(f"  {r['ip']:<18} {r['error']}")

    print(f"\nTotal: {len(ok_results)}/{len(results)} working")

    # 잘 되는 IP 리스트 출력
    if ok_results:
        print("\n# Working IPs (copy-paste ready):")
        print("WORKING_IPS = [")
        for r in ok_results:
            print(f'    "{r["ip"]}",')
        print("]")


async def test_all_proxies():
    """0~18번 프록시 전체 주문 테스트"""
    from keys.pk_proxy import BRIGHTDATA_CONFIG, TEST_IPS
    from keys.pk_hyperliquid import HYPERLIQUID_KEY

    results = []

    for idx in range(0, len(TEST_IPS)):
        proxy_url = BRIGHTDATA_CONFIG.build_url(TEST_IPS[idx])
        ip = TEST_IPS[idx]
        print(f"[{idx:2d}/18] Testing {ip}...", end=" ", flush=True)

        res = await test_single_proxy(idx, proxy_url, HYPERLIQUID_KEY)
        results.append(res)

        if res["error"]:
            print(f"ERROR: {res['error'][:50]}")
        else:
            print(f"order={res['order_ms']:.0f}ms, cancel={res['cancel_ms']:.0f}ms")

        await asyncio.sleep(0.5)  # rate limit 방지

    # === 결과 요약 ===
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY (REST via Proxy)")
    print("=" * 60)
    print(f"{'IDX':<4} {'IP':<18} {'ORDER':>10} {'CANCEL':>10} {'STATUS':<8}")
    print("-" * 60)

    for r in results:
        if r["error"]:
            status = "FAIL"
            order_str = cancel_str = "-"
        else:
            status = "OK"
            order_str = f"{r['order_ms']:.0f}ms"
            cancel_str = f"{r['cancel_ms']:.0f}ms"

        print(f"{r['idx']:<4} {r['ip']:<18} {order_str:>10} {cancel_str:>10} {status:<8}")

    # 성공한 것만 통계
    ok_results = [r for r in results if not r["error"]]
    if ok_results:
        avg_order = sum(r["order_ms"] for r in ok_results) / len(ok_results)
        avg_cancel = sum(r["cancel_ms"] for r in ok_results) / len(ok_results)
        min_order = min(r["order_ms"] for r in ok_results)
        max_order = max(r["order_ms"] for r in ok_results)

        print("-" * 60)
        print(f"{'AVG':<4} {'':<18} {avg_order:>9.0f}ms {avg_cancel:>9.0f}ms")
        print(f"{'MIN':<4} {'':<18} {min_order:>9.0f}ms")
        print(f"{'MAX':<4} {'':<18} {max_order:>9.0f}ms")
        print(f"\nSuccess: {len(ok_results)}/{len(results)}")


async def test_proxy_order():
    """단일 프록시 테스트 (기존 호환)"""
    from keys.pk_proxy import BRIGHTDATA_CONFIG, TEST_IPS
    from keys.pk_hyperliquid import HYPERLIQUID_KEY

    proxy_url = BRIGHTDATA_CONFIG.build_url(TEST_IPS[0])
    print(f"Proxy: {TEST_IPS[0]}")

    res = await test_single_proxy(0, proxy_url, HYPERLIQUID_KEY)

    if res["error"]:
        print(f"Error: {res['error']}")
    else:
        print(f"Order: {res['order_ms']:.1f}ms")
        print(f"Cancel: {res['cancel_ms']:.1f}ms")


async def test_proxy_post():
    """프록시 POST 메서드 테스트"""
    import aiohttp

    from keys.pk_proxy import BRIGHTDATA_CONFIG, TEST_IPS

    print("Testing POST method through proxy...\n")

    for idx, ip in enumerate(TEST_IPS[:5]):  # 처음 5개만
        proxy_url = BRIGHTDATA_CONFIG.build_url(ip)
        print(f"[{idx}] {ip:<18}", end=" ", flush=True)

        try:
            async with aiohttp.ClientSession() as session:
                # POST 테스트 (info 엔드포인트)
                async with session.post(
                    "https://api.hyperliquid.xyz/info",
                    proxy=proxy_url,
                    json={"type": "meta"},
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 200:
                        print(f"POST OK ({resp.status})")
                    else:
                        text = await resp.text()
                        print(f"POST FAIL ({resp.status}) - {text[:50]}")
        except Exception as e:
            print(f"POST FAIL - {str(e)[:50]}")


async def test_direct_order():
    """프록시 없이 직접 주문 테스트"""
    from keys.pk_hyperliquid import HYPERLIQUID_KEY
    from wrappers.hyperliquid import HyperliquidExchange

    print("Testing direct order (no proxy)...\n")

    ex = await HyperliquidExchange(
        wallet_address=HYPERLIQUID_KEY.wallet_address,
        wallet_private_key=HYPERLIQUID_KEY.wallet_private_key,
        agent_api_address=HYPERLIQUID_KEY.agent_api_address,
        agent_api_private_key=HYPERLIQUID_KEY.agent_api_private_key,
        by_agent=HYPERLIQUID_KEY.by_agent,
        vault_address=HYPERLIQUID_KEY.vault_address,
        builder_code=HYPERLIQUID_KEY.builder_code,
        builder_fee_pair=HYPERLIQUID_KEY.builder_fee_pair,
        FrontendMarket=HYPERLIQUID_KEY.FrontendMarket,
        proxy=None,  # 프록시 없음
    ).init()

    try:
        price = await ex.get_mark_price("BTC")
        print(f"Price: {price}")

        result = await ex.create_order(
            symbol="BTC",
            side="buy",
            amount=0.00025,
            price=round(price * 0.95, 1),
            order_type="limit",
            prefer_ws=False,
        )
        print(f"Order result: {result}")

        await ex.cancel_orders("BTC", prefer_ws=False)
        print("Cancelled")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await ex.close()


async def test_geo_check_all():
    """모든 프록시 IP geo 체크 (살아있는지 확인)"""
    import aiohttp

    from keys.pk_proxy import BRIGHTDATA_CONFIG, TEST_IPS

    print(f"Checking {len(TEST_IPS)} proxies via geo...\n")

    results = []

    for idx, ip in enumerate(TEST_IPS):
        proxy_url = BRIGHTDATA_CONFIG.build_url(ip)
        print(f"[{idx:2d}] {ip:<18}", end=" ", flush=True)

        result = {"idx": idx, "ip": ip, "country": None, "error": None}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://geo.brdtest.com/mygeo.json",
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    geo = await resp.json()
                    country = geo.get("country", "?")
                    result["country"] = country
                    print(f"OK  ({country})")
        except asyncio.TimeoutError:
            result["error"] = "Timeout"
            print("FAIL (Timeout)")
        except Exception as e:
            result["error"] = str(e)[:30]
            print(f"FAIL ({str(e)[:30]})")

        results.append(result)

    # === 결과 요약 ===
    ok_results = [r for r in results if not r["error"]]
    fail_results = [r for r in results if r["error"]]

    print("\n" + "=" * 50)
    print(f"Working: {len(ok_results)}/{len(results)}")
    print("=" * 50)

    if ok_results:
        print("\n# Working IPs:")
        print("WORKING_IPS = [")
        for r in ok_results:
            print(f'    "{r["ip"]}",  # {r["country"]}')
        print("]")

        # Build URLs for working IPs
        print("\n# Working Proxy URLs (built):")
        print("WORKING_PROXY_URLS = [")
        for r in ok_results:
            url = BRIGHTDATA_CONFIG.build_url(r["ip"])
            print(f'    "{url}",  # {r["country"]}')
        print("]")

        # Save to file
        output_file = "working_proxies.txt"
        with open(output_file, "w") as f:
            f.write("# Working Proxy URLs\n")
            f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for r in ok_results:
                url = BRIGHTDATA_CONFIG.build_url(r["ip"])
                f.write(f"{url}  # {r['ip']} ({r['country']})\n")
        print(f"\nSaved to {output_file}")

    if fail_results:
        print(f"\n# Failed IPs ({len(fail_results)}):")
        for r in fail_results:
            print(f'#   {r["ip"]} - {r["error"]}')


if __name__ == "__main__":
    # Geo 체크로 살아있는 IP 확인
    asyncio.run(test_geo_check_all())

    # 기타 테스트
    # asyncio.run(test_direct_order())      # 프록시 없이 직접 주문
    # asyncio.run(test_proxy_post())        # 프록시 POST 테스트
    # asyncio.run(test_proxy_connectivity()) # API 연결 테스트
    # asyncio.run(test_proxy_order())       # 단일 프록시 주문
    # asyncio.run(test_all_proxies())       # 전체 프록시 주문
