"""主力大追蹤系統 — Notion / Slack endpoints + 系統設定."""

# === Notion ===
NOTION_PARENT_PAGE_ID = "3676ecfed0fa816dbd31e11b576a601c"
NOTION_PARENT_PAGE_URL = "https://www.notion.so/3676ecfed0fa816dbd31e11b576a601c"
NOTION_PARENT_TITLE = "主力大每日摘要"

# === Slack ===
SLACK_WORKSPACE = "howard-sah1552.slack.com"
SLACK_USER_DM_ID = "D08GZ6NMXR9"  # 個人 DM fallback
SLACK_USER_ID = "U08GZ6NMGSX"

# 雙 channel 分工 (依 user 5/21 拍板)
# - 交易策略 channel：盤中可執行的「預備動作」（停損 level / 進場 level / 觸發條件）
# - 主力大課程 channel：警示 + 文章摘要 + 教學 + stance shift（一切資訊與警告）
# ⚠️ 警示送「課程」channel，盤中操作 levels 送「交易策略」— 不混雜

SLACK_CHANNEL_TRADING_ID = "C0B55KAF1PF"   # #交易策略 — 盤中操作指令
SLACK_CHANNEL_TRADING_NAME = "交易策略"
SLACK_CHANNEL_COURSE_ID = "C0B55L1PH1B"    # #主力大課程 — 警示 + 課程 + 文章摘要
SLACK_CHANNEL_COURSE_NAME = "主力大課程"

# Backward compat (legacy refs)
SLACK_CHANNEL_ID = SLACK_CHANNEL_TRADING_ID
SLACK_CHANNEL_NAME = SLACK_CHANNEL_TRADING_NAME

# === 系統路徑 ===
DB_PATH = "~/.four_seasons/data.sqlite"
TMP_DIR = "/tmp"

# === launchd ===
LAUNCHD_MORNING = "com.howard.zhuli.morning_report.plist"
LAUNCHD_WATCHER = "com.howard.zhuli.article_watcher.plist"

# === 報告 cooldown ===
ARTICLE_CHECK_COOLDOWN_HOURS = 1  # 同小時不重複 check
