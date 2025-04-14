#!/bin/bash

# 사용법 안내
if [ -z "$1" ]; then
  echo "사용법: $0 <logfile> [interval] [lines]"
  echo "예시:   $0 /var/log/syslog 2 10"
  exit 1
fi

LOGFILE="$1"
INTERVAL="${2:-1}"   # 기본 주기 1초
LINES="${3:-20}"     # 기본 출력 줄 수 20줄

watch -n "$INTERVAL" "tail -n $LINES $LOGFILE"
