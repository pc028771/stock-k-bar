#!/bin/bash
# 把本機 data.sqlite checkpoint 後 atomic 推到 iCloud、給 office 機讀
#
# 設計重點：
#   1. PRAGMA wal_checkpoint(TRUNCATE) 強制把 WAL 合併回主檔、確保 cp 出來是完整 snapshot
#   2. atomic cp via temp + mv（同檔案系統 mv 是 atomic）— 避免 office 端讀到半寫狀態
#   3. 清掉 destination 的 -shm / -wal（防止 office 端用殘留 WAL 對到新主檔造成 corruption）
#   4. iCloud 是「單向 distribution channel」：本機寫、office 讀；office 不可寫回
#
# 由 evening_fetch.sh 末段呼叫
set -e

SRC="$HOME/four_seasons_local/data.sqlite"
DST_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/four_seasons_investment"
DST="$DST_DIR/data.sqlite"
LOG_DIR="$HOME/Library/Logs"
LOG="$LOG_DIR/zhuli_db_icloud_sync.log"
mkdir -p "$LOG_DIR" "$DST_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

log "=== sync_db_to_icloud start ==="
log "src=$SRC ($(du -h "$SRC" | cut -f1))"

# 0. 清掉上次 mv 失敗殘留的孤兒 .tmp（cron/背景無 iCloud 寫權限時會累積、每個 ~2.7G）
_orphans=$(ls "$DST_DIR"/data.sqlite.tmp.* 2>/dev/null | wc -l | tr -d ' ')
if [ "$_orphans" != "0" ]; then
    rm -f "$DST_DIR"/data.sqlite.tmp.* 2>/dev/null || true
    log "清掉 $_orphans 個孤兒 .tmp（上次 mv 失敗殘留）"
fi

# 1. WAL checkpoint TRUNCATE — 強制把所有 pending writes 合併回主檔
if /usr/bin/sqlite3 "$SRC" "PRAGMA wal_checkpoint(TRUNCATE);" >> "$LOG" 2>&1; then
    log "wal_checkpoint OK"
else
    log "wal_checkpoint FAILED — abort"
    exit 1
fi

# 2. 清掉 destination 殘留 -wal / -shm（不能跟新主檔混搭）
# 用 || true 容忍 launchd 環境下 iCloud sandbox 「Operation not permitted」錯誤
# (set -e 在 launchd 環境會 silent kill script、user shell session 不會)
rm -f "$DST-wal" "$DST-shm" 2>/dev/null || true

# 3. atomic copy: 寫到 .tmp 再 mv
TMP="$DST.tmp.$$"
if cp "$SRC" "$TMP"; then
    # mv 失敗 = iCloud 寫入被擋（cron/背景無 GUI session iCloud 權限）。
    # 明確 log + 清掉自己的 .tmp（不靜默 set -e 死、不留孤兒）。
    if mv -f "$TMP" "$DST"; then
        log "copy OK → $DST ($(du -h "$DST" | cut -f1))"
    else
        rm -f "$TMP" 2>/dev/null || true
        log "mv FAILED — iCloud 寫入被擋（需 GUI session 權限、cron 背景拿不到）。.tmp 已清、未更新主檔。"
        exit 1
    fi
else
    rm -f "$TMP"
    log "copy FAILED"
    exit 1
fi

# iCloud 會自動偵測新檔上傳、不需手動 trigger
log "=== sync_db_to_icloud done ==="
