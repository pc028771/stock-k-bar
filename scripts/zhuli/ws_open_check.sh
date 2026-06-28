#!/bin/zsh
# 開盤後自動驗 WS live 連線 + tick + volume 單位。cron 在 09:01/09:06 跑。
# PASS/FAIL 寫 RESULT log、FAIL 時 user 戳主 agent 在 09:30 前修。
cd /Users/howard/Repository/stock-k-bar || exit 1
ts=$(date +%H%M%S)
out=/tmp/ws_open_check_${ts}.log
PYTHONPATH=scripts python3 scripts/zhuli/verify_ws_live.py 2454 3037 2330 > "$out" 2>&1
res=/tmp/ws_open_check_RESULT.log
# PASS 核心 = ws_ok=True + 至少一檔收到 WS tick (✅)。
# 量級合理是 bonus (開盤初量小、ratio 可能 <0.01 還沒到、不當 FAIL 條件、只記 log)。
vol_ok=""; grep -q "量級合理" "$out" && vol_ok=" + volume量級OK"
if grep -q "ws_ok = True" "$out" && grep -q "WS 更新=✅" "$out"; then
  echo "[$ts] ✅ PASS — WS 連上 + 收到 tick${vol_ok}  log=$out" >> "$res"
else
  echo "[$ts] ❌ FAIL — 戳主 agent 修、log=$out" >> "$res"
fi
# 把 volume 單位判定行也撈進 RESULT、讓主 agent 一眼確認『張』
grep -E "total_volume|量級|盤中量" "$out" | sed "s/^/    [$ts] /" >> "$res"
