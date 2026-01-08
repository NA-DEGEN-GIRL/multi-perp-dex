"""
Lighter get_collateral 무한루프 테스트
REST fallback 발생 여부 확인용
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mpdex import create_exchange
from keys.pk_lighter import LIGHTER_KEY

async def main():
    ex = await create_exchange("lighter", LIGHTER_KEY)

    print("=== get_collateral 무한루프 테스트 시작 ===")
    print("REST fallback 발생 시 '[lighter] get_collateral: using REST fallback' 출력됨")
    print("Ctrl+C로 종료\n")

    count = 0
    while True:
        count += 1
        try:
            coll = await ex.get_collateral()
            print(f"[{count}] available: {coll.get('available_collateral')}, total: {coll.get('total_collateral')}")
        except Exception as e:
            print(f"[{count}] ERROR: {e}")

        await asyncio.sleep(0.1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n종료")
