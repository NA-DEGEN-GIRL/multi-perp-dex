from collections import defaultdict

# 파일 경로 지정
file_path = "volume_log.txt"

# 거래소별 합산 저장할 dict
volume_sum = defaultdict(float)

with open(file_path, "r", encoding="utf-8") as f:
    for line in f:
        parts = line.strip().split(" | ")
        if len(parts) == 4 and parts[2] == "BTC":
            exchange = parts[1].strip()
            volume = float(parts[3].strip())
            volume_sum[exchange] += volume

# 결과 출력
for exchange, total in volume_sum.items():
    print(f"{exchange}: {total:.8f} BTC")
