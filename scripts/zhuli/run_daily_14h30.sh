#!/bin/bash
# 每日 14:30 盤後批次：scanner only
# 大哥追蹤改在 18:00 evening_brief 內跑（FinMind 分點資料 17:00 後才 ready）
# 由 launchd com.howard.zhuli.daily_scanner 觸發

set -e

PYTHON="/Users/howard/.pyenv/shims/python3"
REPO="/Users/howard/Repository/stock-k-bar"
DATE=$(date +%Y-%m-%d)

echo "=== 14:30 盤後批次 === $DATE ==="

echo "[1/1] 跑 scanner..."
$PYTHON "$REPO/scripts/zhuli/daily_scanner_job.py" --date "$DATE"

echo "=== 14:30 批次完成 ==="
