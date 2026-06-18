#!/bin/bash
# 每日 21:30 晚間資料抓取
# 依序執行：法人 → broker cache (老師 universe) → 1分K (老師 universe)
# 設計改變 (2026-06-10):
#   - broker prefetch 復活、讀老師 universe 而非 scanner candidates (打破循環依賴)
#   - 1分K 也改為老師 universe、不再等 scanner candidates md
# log: ~/Library/Logs/zhuli_evening_fetch.log
# 由 launchd com.howard.zhuli.evening_fetch 觸發

set -e

PYTHON="/Users/howard/.pyenv/shims/python3"
REPO="/Users/howard/Repository/stock-k-bar"
DATE=$(date +%Y-%m-%d)
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LOG_DIR"

echo "=== 21:30 evening_fetch === $DATE ===" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"

# 1/3 法人買賣超 (FinMind TaiwanStockInstitutionalInvestorsBuySell)
echo "[1/3] backfill_institutional..." | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
if $PYTHON "$REPO/scripts/zhuli/backfill_institutional.py" \
    --start-date "$DATE" \
    2>&1 | tee -a "$LOG_DIR/zhuli_evening_fetch.log"; then
    echo "[1/3] backfill_institutional OK" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
else
    echo "[1/3] backfill_institutional FAILED (exit $?)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
fi

# 2/3 broker cache 預熱 (老師 universe ~428 檔)
echo "[2/3] daily_fetcher (broker cache, 老師 universe)..." | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
if $PYTHON "$REPO/scripts/zhuli/daily_fetcher.py" --date "$DATE" \
    2>&1 | tee -a "$LOG_DIR/zhuli_evening_fetch.log"; then
    echo "[2/3] daily_fetcher OK" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
else
    echo "[2/3] daily_fetcher FAILED (exit $?)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
fi

# 3/3 1分K (FinMind TaiwanStockKBar) — 老師 universe
echo "[3/3] backfill_minute_kbar (老師 universe)..." | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
TICKERS=$($PYTHON -c "
import sys, json
sys.path.insert(0, '$REPO/scripts')
from zhuli.entry.small_structure.watchlist import _load_sector_all
print(','.join(sorted(_load_sector_all())))
")
if [ -n "$TICKERS" ]; then
    if $PYTHON "$REPO/scripts/zhuli/backfill_minute_kbar.py" \
        --tickers "$TICKERS" \
        --start-date "$DATE" \
        --end-date "$DATE" \
        --skip-existing \
        2>&1 | tee -a "$LOG_DIR/zhuli_evening_fetch.log"; then
        echo "[3/3] backfill_minute_kbar OK" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
    else
        echo "[3/3] backfill_minute_kbar FAILED (exit $?)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
    fi
else
    echo "[3/3] backfill_minute_kbar SKIP — 老師 universe 為空" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
fi

echo "=== evening_fetch 完成 === $DATE ===" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"

# 4/5 重生 overnight_static_features.json (EOD baseline、用今日 close)
# 修 stale prev_close 問題 (週末以前 13:00 plist 只用前一日 close、EOD 後沒更新)
echo "[4/5] precompute_overnight_static..." | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
if $PYTHON "$REPO/scripts/zhuli/precompute_overnight_static.py" 2>&1 | tee -a "$LOG_DIR/zhuli_evening_fetch.log"; then
    echo "[4/5] precompute_overnight_static OK" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
else
    echo "[4/5] precompute_overnight_static FAILED (exit $?)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
fi

# 5/6 推 DB snapshot 到 iCloud (給 office 機 monitor 讀)
echo "[5/6] sync_db_to_icloud..." | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
if "$REPO/scripts/zhuli/sync_db_to_icloud.sh" 2>&1 | tee -a "$LOG_DIR/zhuli_evening_fetch.log"; then
    echo "[5/6] sync_db_to_icloud OK" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
else
    echo "[5/6] sync_db_to_icloud FAILED (exit $?)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
fi

# 6/6 evening_data_validator (確認資料完整、防 stale 污染下游)
echo "[6/6] evening_data_validator..." | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
if $PYTHON "$REPO/scripts/zhuli/evening_data_validator.py" --date "$DATE" 2>&1 | tee -a "$LOG_DIR/zhuli_evening_fetch.log"; then
    echo "[6/6] evening_data_validator OK (all data fresh)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
else
    VAL_EXIT=$?
    echo "[6/6] evening_data_validator FAILED (exit $VAL_EXIT、有 critical/warning 資料缺失、下游 scanner 結果可能 stale)" | tee -a "$LOG_DIR/zhuli_evening_fetch.log"
fi
