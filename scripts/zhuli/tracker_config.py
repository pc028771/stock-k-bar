"""主力大追蹤系統 — Notion / Slack endpoints + 系統設定."""

# === Notion ===
NOTION_PARENT_PAGE_ID = "3676ecfed0fa816dbd31e11b576a601c"
NOTION_PARENT_PAGE_URL = "https://www.notion.so/3676ecfed0fa816dbd31e11b576a601c"
NOTION_PARENT_TITLE = "主力大每日摘要"

# === Slack ===
SLACK_CHANNEL_ID = "C0B55KAF1PF"
SLACK_CHANNEL_NAME = "主力大"
SLACK_WORKSPACE = "howard-sah1552.slack.com"
SLACK_USER_DM_ID = "D08GZ6NMXR9"  # 個人 DM fallback
SLACK_USER_ID = "U08GZ6NMGSX"

# === 系統路徑 ===
DB_PATH = "~/.four_seasons/data.sqlite"
TMP_DIR = "/tmp"

# === launchd ===
LAUNCHD_MORNING = "com.howard.zhuli.morning_report.plist"
LAUNCHD_WATCHER = "com.howard.zhuli.article_watcher.plist"

# === 報告 cooldown ===
ARTICLE_CHECK_COOLDOWN_HOURS = 1  # 同小時不重複 check
