#!/bin/bash
# 每日 21:00 晚間資料抓取
# 依序執行：法人 → 1分K → broker cache
# log: ~/Library/Logs/zhuli_evening_fetch.log
# 由 launchd com.howard.zhuli.evening_fetch 觸發

set -e

PYTHON="/Users/howard/.pyenv/shims/python3"
REPO="/Users/howard/Repository/stock-k-bar"
DATE=$(date +%Y-%m-%d)
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LOG_DIR"

echo "=== 21:00 evening_fetch === $DATE ===" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"

# 1/3 法人買賣超 (FinMind TaiwanStockInstitutionalInvestorsBuySell)
echo "[1/3] backfill_institutional..." | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
if $PYTHON "$REPO/scripts/zhuli/backfill_institutional.py" \
    --start-date "$DATE" \
    2>&1 | tee -a "$LOG_DIR/zhuli_evening_fetch.log"; then
    echo "[1/3] backfill_institutional OK" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
else
    echo "[1/3] backfill_institutional FAILED (exit $?)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
fi

# 2/3 1分K (FinMind TaiwanStockKBar) — 需要 tickers 清單
# 從當日 scanner 候選讀取，若沒有則略過並記 log
CANDIDATES_FILE="/tmp/scanner_candidates_${DATE}.md"
if [ -f "$CANDIDATES_FILE" ]; then
    # 解析 4 碼 ticker（table 第一欄）
    TICKERS=$(grep -oE '^[[:space:]]*\|[[:space:]]*([0-9]{4})[[:space:]]*\|' "$CANDIDATES_FILE" \
              | grep -oE '[0-9]{4}' | sort -u | tr '\n' ',' | sed 's/,$//')
    if [ -n "$TICKERS" ]; then
        echo "[2/3] backfill_minute_kbar tickers=$TICKERS ..." | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
        if $PYTHON "$REPO/scripts/zhuli/backfill_minute_kbar.py" \
            --tickers "$TICKERS" \
            --start-date "$DATE" \
            2>&1 | tee -a "$LOG_DIR/zhuli_evening_fetch.log"; then
            echo "[2/3] backfill_minute_kbar OK" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
        else
            echo "[2/3] backfill_minute_kbar FAILED (exit $?)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
        fi
    else
        echo "[2/3] backfill_minute_kbar SKIP — 無法從 $CANDIDATES_FILE 解析 tickers" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
    fi
else
    echo "[2/3] backfill_minute_kbar SKIP — $CANDIDATES_FILE 不存在" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
fi

# (deprecated 6/8: 3/3 broker cache 預熱、daily_fetcher 已移除、邊際價值低 + 時序錯)

echo "=== evening_fetch 完成 === $DATE ===" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
