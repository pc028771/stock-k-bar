#!/bin/bash
# Daily scanner K 線 Tier-A 升等訊號通知 — Apple Notification 推播.
#
# 由 launchd com.howard.zhuli.daily_scanner_evening (21:45) 結尾呼叫.
# 直接讀 scanner_candidates_YYYY-MM-DD.md (entry section 含 ✨ badge),
# 不依賴 launchd log buffer 刷新時序.
#
# 找到 ≥1 檔升等才推；0 檔靜默 (避免天天被打擾).

set -u

DATE=$(date +%Y-%m-%d)
MD="/tmp/scanner_candidates_${DATE}.md"

if [ ! -f "$MD" ]; then
    osascript -e "display notification \"❌ ${DATE} markdown 不存在: $MD\" with title \"Daily Scanner 失敗\"" >/dev/null 2>&1
    exit 0
fi

# 抓 ✨ 升等行 → 取 ticker (粗體 **NNNN**) + pattern 名稱
# 範例行: | **3296** ⭐ Tier-B ✨攻擊成本顯現 | 勝德 | w_bottom_launch ...
HITS=$(grep -E "✨(攻擊成本顯現|晨星島反轉)" "$MD" 2>/dev/null \
       | grep -E '\*\*[0-9]+\*\*' \
       | head -8)

COUNT=$(echo "$HITS" | grep -c '\*\*' || true)
[ -z "$HITS" ] && COUNT=0

if [ "$COUNT" -eq 0 ]; then
    # 0 升等 — 不推 (避免噪音), 但寫 log 留證據
    echo "[notify_kline_tier_a] ${DATE}: 0 檔升等、不推播" >&2
    exit 0
fi

# 取 ticker + name + pattern (簡化、放得進 notification body)
SUMMARY=$(echo "$HITS" | awk -F'|' '
{
    # field 2 = ticker+tier+badge, field 3 = name
    gsub(/\*\*/, "", $2)
    gsub(/^[ \t]+|[ \t]+$/, "", $2)
    gsub(/^[ \t]+|[ \t]+$/, "", $3)
    # 從 $2 取 ticker (前 4 碼數字) + badge
    match($2, /[0-9]+/)
    tk = substr($2, RSTART, RLENGTH)
    if (match($2, /✨[^ ]+/)) {
        bg = substr($2, RSTART, RLENGTH)
    } else { bg = "" }
    printf "%s %s%s\n", tk, $3, (bg ? " " bg : "")
}' | head -5)

# Apple notification: title + subtitle + body (body 限 ~250 字)
osascript -e "display notification \"${SUMMARY}\" with title \"K線 Tier-A 升等 ${COUNT} 檔\" subtitle \"${DATE} 收盤\"" >/dev/null 2>&1

echo "[notify_kline_tier_a] ${DATE}: 推播 ${COUNT} 檔升等" >&2
