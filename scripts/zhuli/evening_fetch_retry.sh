#!/bin/bash
# 每日 21:30 晚間資料補完 retry
# 檢查今日法人 / broker / 1分K 是否完整，不完整則補跑
# log: ~/Library/Logs/zhuli_evening_fetch_retry.log
# 由 launchd com.howard.zhuli.evening_fetch_retry 觸發

PYTHON="/Users/howard/.pyenv/shims/python3"
REPO="/Users/howard/Repository/stock-k-bar"
DATE=$(date +%Y-%m-%d)
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/zhuli_evening_fetch_retry.log"
DB="$HOME/.four_seasons/data.sqlite"

echo "=== 21:30 evening_fetch_retry === $DATE ===" | tee -a "$LOG"

NEED_RETRY=0

# ── 1. 檢查法人資料 ────────────────────────────────────────────────────────
echo "[check] 法人 institutional_investors..." | tee -a "$LOG"
INST_COUNT=$($PYTHON - <<'PYEOF' 2>/dev/null
import sqlite3, sys, os
db = os.path.expanduser("~/.four_seasons/data.sqlite")
date = os.environ.get("CHECK_DATE", "")
try:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    n = con.execute("SELECT COUNT(DISTINCT ticker) FROM institutional_investors WHERE trade_date=?", (date,)).fetchone()[0]
    con.close()
    print(n)
except Exception as e:
    print(0)
PYEOF
)
export CHECK_DATE="$DATE"
INST_COUNT=$(CHECK_DATE="$DATE" $PYTHON - <<'PYEOF' 2>/dev/null
import sqlite3, sys, os
db = os.path.expanduser("~/.four_seasons/data.sqlite")
date = os.environ.get("CHECK_DATE", "")
try:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    n = con.execute("SELECT COUNT(DISTINCT ticker) FROM institutional_investors WHERE trade_date=?", (date,)).fetchone()[0]
    con.close()
    print(n)
except Exception as e:
    print(0)
PYEOF
)

echo "  法人今日筆數: $INST_COUNT" | tee -a "$LOG"
if [ "$INST_COUNT" -lt 1500 ] 2>/dev/null; then
    echo "  [RETRY] 法人不完整 ($INST_COUNT < 1500)，補跑 backfill_institutional..." | tee -a "$LOG"
    NEED_RETRY=1
    $PYTHON "$REPO/scripts/zhuli/backfill_institutional.py" \
        --start-date "$DATE" \
        2>&1 | tee -a "$LOG"
    echo "  [RETRY] backfill_institutional 完成" | tee -a "$LOG"
else
    echo "  [OK] 法人資料齊全" | tee -a "$LOG"
fi

# ── 2. 檢查 broker cache (daily_fetcher) ───────────────────────────────────
echo "[check] broker cache..." | tee -a "$LOG"
CANDIDATES_FILE="/tmp/scanner_candidates_${DATE}.md"
BROKER_CACHE_DIR="$HOME/.four_seasons/broker_cache"

BROKER_MISSING=0
if [ -f "$CANDIDATES_FILE" ]; then
    # 解析 4 碼 ticker
    TICKERS_LIST=$(grep -oE '^[[:space:]]*\|[[:space:]]*([0-9]{4})[[:space:]]*\|' "$CANDIDATES_FILE" \
                   | grep -oE '[0-9]{4}' | sort -u)
    TICKER_COUNT=$(echo "$TICKERS_LIST" | grep -c '[0-9]' 2>/dev/null || echo 0)
    # 簡單檢查：cache 目錄下今日檔案數量
    if [ -d "$BROKER_CACHE_DIR" ]; then
        CACHED_TODAY=$(find "$BROKER_CACHE_DIR" -name "*${DATE}*" 2>/dev/null | wc -l | tr -d ' ')
    else
        CACHED_TODAY=0
    fi
    echo "  candidates: $TICKER_COUNT 檔，broker cache 今日: $CACHED_TODAY 筆" | tee -a "$LOG"
    # 若 cache 今日筆數 < 候選 tickers 的 50% 視為不完整
    HALF_COUNT=$((TICKER_COUNT / 2))
    if [ "$TICKER_COUNT" -gt 0 ] && [ "$CACHED_TODAY" -lt "$HALF_COUNT" ]; then
        BROKER_MISSING=1
    fi
else
    echo "  [SKIP] $CANDIDATES_FILE 不存在，無法判斷 broker cache 完整度" | tee -a "$LOG"
fi

if [ "$BROKER_MISSING" -eq 1 ]; then
    echo "  [RETRY] broker cache 不完整，補跑 daily_fetcher..." | tee -a "$LOG"
    NEED_RETRY=1
    $PYTHON "$REPO/scripts/zhuli/daily_fetcher.py" \
        --date "$DATE" \
        2>&1 | tee -a "$LOG"
    echo "  [RETRY] daily_fetcher 完成" | tee -a "$LOG"
else
    echo "  [OK] broker cache 資料齊全" | tee -a "$LOG"
fi

# ── 3. 檢查 1分K (scanner candidates 清單內的 tickers) ─────────────────────
echo "[check] 1分K minute_kbar..." | tee -a "$LOG"
if [ -f "$CANDIDATES_FILE" ]; then
    TICKERS=$(grep -oE '^[[:space:]]*\|[[:space:]]*([0-9]{4})[[:space:]]*\|' "$CANDIDATES_FILE" \
              | grep -oE '[0-9]{4}' | sort -u | tr '\n' ',' | sed 's/,$//')
    if [ -n "$TICKERS" ]; then
        MINUTE_COUNT=$(CHECK_DATE="$DATE" CHECK_TICKERS="$TICKERS" $PYTHON - <<'PYEOF' 2>/dev/null
import sqlite3, os
db = os.path.expanduser("~/.four_seasons/data.sqlite")
date = os.environ.get("CHECK_DATE", "")
tickers = os.environ.get("CHECK_TICKERS", "").split(",")
try:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    placeholders = ",".join("?" * len(tickers))
    n = con.execute(
        f"SELECT COUNT(DISTINCT ticker) FROM stock_minute_kbar WHERE DATE(trade_datetime)=? AND ticker IN ({placeholders})",
        [date] + tickers
    ).fetchone()[0]
    con.close()
    print(n)
except Exception:
    print(0)
PYEOF
)
        TOTAL_TICKERS=$(echo "$TICKERS" | tr ',' '\n' | grep -c '[0-9]' 2>/dev/null || echo 1)
        echo "  1分K 今日已有: $MINUTE_COUNT / $TOTAL_TICKERS 檔" | tee -a "$LOG"
        HALF_TOTAL=$((TOTAL_TICKERS / 2))
        if [ "$MINUTE_COUNT" -lt "$HALF_TOTAL" ] 2>/dev/null; then
            echo "  [RETRY] 1分K 不完整，補跑 backfill_minute_kbar..." | tee -a "$LOG"
            NEED_RETRY=1
            $PYTHON "$REPO/scripts/zhuli/backfill_minute_kbar.py" \
                --tickers "$TICKERS" \
                --start-date "$DATE" \
                2>&1 | tee -a "$LOG"
            echo "  [RETRY] backfill_minute_kbar 完成" | tee -a "$LOG"
        else
            echo "  [OK] 1分K 資料齊全" | tee -a "$LOG"
        fi
    else
        echo "  [SKIP] 無法從 candidates 解析 tickers" | tee -a "$LOG"
    fi
else
    echo "  [SKIP] $CANDIDATES_FILE 不存在" | tee -a "$LOG"
fi

# ── 總結 ───────────────────────────────────────────────────────────────────
if [ "$NEED_RETRY" -eq 0 ]; then
    echo "=== retry 完成：所有資料已齊全，無需補跑 === $DATE ===" | tee -a "$LOG"
else
    echo "=== retry 完成：已補跑缺漏部分 === $DATE ===" | tee -a "$LOG"
fi
