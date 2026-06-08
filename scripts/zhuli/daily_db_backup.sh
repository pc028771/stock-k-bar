#!/bin/bash
# 每晚備份本地 DB 到 iCloud (cross-machine sync 用)
# 用 sqlite3 .backup 安全複製、避免 WAL 衝突

set -e

LOCAL_DB="$HOME/four_seasons_local/data.sqlite"
ICLOUD_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/four_seasons_investment"
TODAY=$(date +%Y-%m-%d)

mkdir -p "$ICLOUD_DIR/backups"

# 用 sqlite3 .backup 確保 transaction-consistent snapshot
sqlite3 "$LOCAL_DB" ".backup '$ICLOUD_DIR/data.sqlite'"
echo "  ✅ DB 備份到 iCloud: $ICLOUD_DIR/data.sqlite ($(date))"

# 保留每週日結 weekly snapshot
if [ "$(date +%u)" = "5" ]; then  # 週五
    cp "$ICLOUD_DIR/data.sqlite" "$ICLOUD_DIR/backups/data.sqlite.${TODAY}"
    echo "  ✅ weekly snapshot: backups/data.sqlite.${TODAY}"
    # 保留最近 4 週
    ls -t "$ICLOUD_DIR/backups/data.sqlite."* 2>/dev/null | tail -n +5 | xargs rm -f
fi
