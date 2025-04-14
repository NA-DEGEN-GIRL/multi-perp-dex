import os
import time
import glob

MAX_LINES = 300  # 최대 줄 수
REMOVE_LINES = 100  # 초과 시 삭제할 오래된 줄 수
LOG_DIR = "."  # 로그 파일이 있는 디렉토리

def trim_log_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_LINES:
            start_index = len(lines) - (MAX_LINES - REMOVE_LINES)
            new_lines = lines[start_index:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)  # 파일 덮어쓰기, 삭제 아님!
            print(f"{path} trimmed ({len(lines)} → {len(new_lines)} lines)")
    except Exception as e:
        print(f"Error trimming {path}: {e}")

while True:
    log_files = glob.glob(os.path.join(LOG_DIR, "*.log"))
    for log_file in log_files:
        trim_log_file(log_file)
    time.sleep(1)  # 60초마다 실행
