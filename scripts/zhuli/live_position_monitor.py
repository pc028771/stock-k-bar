"""即時持倉 + 開盤進場 screener (整合版 v3).

兩階段:
- Phase 1 (9:00-9:25): 開盤 entry screening、判主候選 / 備案
- Phase 2 (9:25 後): 已持倉 P&L + 停損監控

用法:
    python scripts/zhuli/live_position_monitor.py
    python scripts/zhuli/live_position_monitor.py --sort status
    python scripts/zhuli/live_position_monitor.py --sort priority
    python scripts/zhuli/live_position_monitor.py --sort risk
    python scripts/zhuli/live_position_monitor.py --sort trigger
    python scripts/zhuli/live_position_monitor.py --sort pnl
    python scripts/zhuli/live_position_monitor.py --sort sector

編輯下方:
- HELD: 已持倉部位 (Phase 2 監控)
- PLAN_PRIMARY: 鎖定的主候選 (Phase 1 開盤評估)
- PLAN_BACKUP: 備案 (主候選被 skip 時遞補)
- WATCH: 監控但已 skip 的標的

特性:
- dict-based 資料結構（兼容舊 tuple 格式、自動 convert）
- 9:00-9:25 自動 entry screening、紅線 #9 (前 5 分 >5% skip) 內建
- 9:25+ 切到持倉 P&L 監控
- 停損突破 macOS 通知
- 30s 更新、彩色 console
- priority 摘要 panel (⭐⭐⭐/⭐⭐/⭐)
- 即時 intraday StageTrigger 偵測 (T1/T2/TC)
- 排序模式: priority / risk / trigger / pnl / sector
- 快捷鍵: 1=priority 2=risk 3=trigger 4=pnl 5=sector q=退出
"""
from __future__ import annotations

import argparse
import subprocess
import sqlite3
import sys
import termios
import tty
import threading
import select
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# rich: display 層 (取代手刻 ANSI + alt-screen)
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

_REPO = Path(__file__).parent.parent.parent
_SYS  = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from clients.fubon_client import FubonClient  # noqa

DB = Path.home() / ".four_seasons" / "data.sqlite"

# ─────────────────────────────────────────────────────────────────────────
# 編輯區 (每天晚上鎖 plan 時改)
# ─────────────────────────────────────────────────────────────────────────

# 已進場部位 (Phase 2 P&L 監控)
# 格式: dict (必填: ticker, name, cost, shares, stop; 選填: tactic, priority, source, sector, note)
# 舊 tuple (ticker, name, cost, shares, stop) 自動 convert
HELD = [
    {
        'ticker': '6285', 'name': '啟碁',
        'cost': 315.0, 'shares': 1000, 'stop': 301.0,
        'strategy_mode': 'core',       # 核心持倉、結構底停損
        'tactic': '核心', 'priority': 2,
        'source': '老師明示',
        'sector': '低軌衛星',
        'note': '老師明示「兩檔選啟碁」、停損 MA10 動態'
    },
    {
        'ticker': '1605', 'name': '華新',
        'cost': 40.23, 'shares': 12000, 'stop': 38.75,
        'strategy_mode': 'core',       # 核心持倉、結構底停損
        'tactic': '核心', 'priority': 3,
        'source': '老師重壓',
        'sector': '紅海第二棒',
        'note': '6/2 8 張 @ $40.1 + 6/3 加 4 張 @ $40.5、均 $40.23'
    },
    {
        'ticker': '2885', 'name': '元大金',
        'cost': 58.0, 'shares': 10000, 'stop': 55.71,
        'strategy_mode': 'core',       # 核心配置、結構底停損
        'tactic': '配置', 'priority': 1,
        'source': '配置部位',
        'sector': '金融',
        'note': '6/2 收 $59.60 (+$16k 浮動)、停損 $55.71 結構底'
    },
    {
        'ticker': '3481', 'name': '群創',
        'cost': 58.7, 'shares': 2000, 'stop': 56.2,
        'strategy_mode': 'swing',  # 處置中、不能隔日沖、等 D+4-5 看站均線
        'tactic': '題材', 'priority': 3,
        'source': '老師明示 6/3 + 處置中',
        'sector': '面板/族群補漲',
        'note': '🔒 6/4 D+1 進處置、老師持有、等 D+4-5 看站均線 (6/9-6/10)、停 $56.2'
    },
    # 8046 南電 6/5 全清 (1000 @ $851 + 200 @ $838、共鎖 ~$57.7k 損)
]

# 已實現 (今日累計、每日歸零)
REALIZED = 0

# 鎖定主候選 (Phase 1 開盤 entry screening)
# 格式: dict (必填: ticker, name, shares, stop; 選填: tactic, priority, source, sector, note, reason)
# 舊 tuple (ticker, name, shares, stop, reason) 自動 convert
PLAN_PRIMARY: list = []  # 6/5 清空: 1605 加碼動作已執行 (HELD 12000 股)、無新進場 plan

# 備案 (Phase 1 主候選被 skip 時遞補)
# 6/3 全 skip、結構壞 + 籌碼弱
PLAN_BACKUP: list = []

# 觀察清單 (dict 格式、兼容舊 tuple)
WATCH = [
    # 老師明示重壓 / 第二棒 / GT 基底
    {
        'ticker': '2303', 'name': '聯電',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示 6/3 (條件式)',
        'sector': 'GT基底/成熟製程',
        'note': '⭐ 老師 6/3 條件式圈起來: 看 6/4 尾盤外資是否「黑 K 大買」連 2 天才升等'
    },
    {
        'ticker': '6770', 'name': '力積電',
        'ref_close': 84.6, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/3 (觀察)',
        'sector': 'GT基底/成熟製程',
        'note': '🔴 老師「立即店」、6/3 破 MA5 $85.4、看 6/4 紅 K 收復 MA5 才升等'
    },
    {
        'ticker': '3702', 'name': '大聯大',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示 6/3',
        'sector': 'IC通路',
        'note': '⭐⭐⭐ 老師 6/3 圈起來「守月線、很簡單的股票、外資持續大買」'
    },
    {
        'ticker': '3264', 'name': '欣銓',
        'ref_close': 229.5, 'stop': 214.0,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示 6/3',
        'sector': '半導體封測',
        'note': '⭐⭐⭐ 老師 6/3 圈起來、外資佈局上櫃、N 字回測完成 ($244→$214→$237 第二攻)、距 MA10 +4.4% 打擊區、停 $214 (6/2 回測底)'
    },
    # 老師 6/3 提到的個股 — 等 6/4 紅 K 收復所有均線才升等
    {
        'ticker': '6257', 'name': '矽格',
        'ref_close': 230.0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/3 (觀察)',
        'sector': '半導體封測',
        'note': '🟢 6/3 已站全均線、看 6/4 守住 + 紅 K 即升等'
    },
    {
        'ticker': '2451', 'name': '創見',
        'ref_close': 358.0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/3 (觀察)',
        'sector': '記憶體模組',
        'note': '🟢 6/3 已站全均線、外資+融資進、6/4 守住紅 K 升等'
    },
    {
        'ticker': '3042', 'name': '晶技',
        'ref_close': 217.5, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/3 (觀察)',
        'sector': '電子零組件',
        'note': '🟢 6/3 已站全均線、6/4 守住紅 K 升等'
    },
    {
        'ticker': '6239', 'name': '力成',
        'ref_close': 343.0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示 6/3 (觀察)',
        'sector': '半導體封測',
        'note': '🔒 處置 5/29-6/11、6/3 D+4 破 MA5、6/4 D+5 是最後機會、紅 K 收復 MA5 → 🔒A、否則降 🔒B/C'
    },
    {
        'ticker': '3036', 'name': '文曄',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': 'IC通路',
        'note': '⭐⭐ IC 通路 6/2 主流、老師明示 (3702 大聯大 / 3036 文曄)、持續監控'
    },
    {
        'ticker': '2376', 'name': '技嘉',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': 'AI PC/全資股',
        'note': '⭐⭐ 老師原話「我這波壓的」、AI PC 主流'
    },
    {
        'ticker': '8064', 'name': '東捷',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': '玻璃',
        'note': '⭐ 玻璃明示、frequent tier'
    },
    {
        'ticker': '6116', 'name': '彩晶',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': '紅海第二棒',
        'note': '⭐⭐ 紅海第二棒、管錢哥重押、外資挺'
    },
    # IC 設計 / 記憶體相關 (老師主流框架)
    {
        'ticker': '6147', 'name': '頎邦',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner',
        'sector': '記憶體封測',
        'note': '⭐ 記憶體封測、user 提醒'
    },
    {
        'ticker': '5351', 'name': '鈺創',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner',
        'sector': 'IC設計',
        'note': '⭐ IC 設計 / 記憶體、user 提醒'
    },
    {
        'ticker': '3006', 'name': '晶豪科',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner',
        'sector': '記憶體',
        'note': '⭐ 記憶體 IC、user 提醒'
    },
    {
        'ticker': '2344', 'name': '華邦電',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': '記憶體',
        'note': '⚠️ 漲多 50%、不主動推、等回測 MA10 才進、持續監控'
    },
    {
        'ticker': '1303', 'name': '南亞',
        'ref_close': 113.0, 'stop': None,
        'tactic': '題材', 'priority': 2,
        'source': '黃大推薦 6/4 (留尾盤確認)',
        'sector': '塑化/ABF載板',
        'note': '⭐ 黃大 6/4 推薦、ABF/塑化族群、距 MA10 +16.6% 偏遠等回測、進場條件: 13:00 Closing_check 3-4/5 watch (5/5 反而是過熱)'
    },
    # 6/2 收盤後三軸狀態追蹤
    {
        'ticker': '6207', 'name': '雷科',
        'ref_close': 127.0, 'stop': 115.0,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': '玻璃',
        'note': '🟡 老師 [25:08]「壓著、尾盤關注、跟東捷類似」、距 MA10 +9.4%'
    },
    # 8046 南電 — 6/4 已進 HELD、移除 WATCH
    # 老師 6/4 圈起來 + 均線全順向 (~44 檔之一) — user 列出 5 檔
    {
        'ticker': '6282', 'name': '康舒',
        'ref_close': 64.4, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/4 圈起來',
        'sector': 'AI電源/散熱',
        'note': '🛡️ 6/4 圈起來、大盤跌時守均價線 (relative_strength validation case)'
    },
    {
        'ticker': '2449', 'name': '京元電子',
        'ref_close': 0, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/4 圈起來',
        'sector': '半導體封測',
        'note': '🛡️ 6/4 圈起來'
    },
    # 6/5 重電族群 — 同學討論、老師未指名、自選追蹤
    {
        'ticker': '8222', 'name': '寶一',
        'ref_close': 37.3, 'stop': 36.1,
        'tactic': '短打', 'priority': 2,
        'source': '6/5 同學討論 重電',
        'sector': '重電',
        'note': '⚡ 重電打擊區、距 MA10 +2.5%、結構底 ~$36 (MA20)、老師未明示、追蹤'
    },
    {
        'ticker': '1519', 'name': '華城',
        'ref_close': 910.0, 'stop': 857.3,
        'tactic': '短打', 'priority': 2,
        'source': '6/5 同學討論 重電',
        'sector': '重電',
        'note': '⚡ 重電打擊區、距 MA10 +5.0%、結構底 MA20 ~$857、老師未明示、追蹤'
    },
    {
        'ticker': '2371', 'name': '大同',
        'ref_close': 32.0, 'stop': 29.7,
        'tactic': '短打', 'priority': 2,
        'source': '6/5 同學討論 重電',
        'sector': '重電',
        'note': '⚡ 重電打擊區、距 MA10 +6.3%、結構底 MA20 ~$29.7、老師未明示、追蹤'
    },
    {
        'ticker': '4967', 'name': '十銓',
        'ref_close': 0, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/4 圈起來',
        'sector': '記憶體模組',
        'note': '🛡️ 6/4 圈起來'
    },
    {
        'ticker': '3211', 'name': '順達',
        'ref_close': 0, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/4 圈起來',
        'sector': '電池模組',
        'note': '🛡️ 6/4 圈起來'
    },
    {
        'ticker': '6209', 'name': '今國光',
        'ref_close': 0, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/4 圈起來',
        'sector': '光學鏡頭',
        'note': '🛡️ 6/4 圈起來'
    },
    # 老師 6/3 圈起來中長期 補 4 檔 (其餘 4 檔已在上方 WATCH)
    {
        'ticker': '3037', 'name': '欣興',
        'ref_close': 0, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/3 圈起來',
        'sector': 'ABF載板',
        'note': '⭐ 老師 6/3 圈起來中長期 (ABF 主推、tier core)'
    },
    {
        'ticker': '2308', 'name': '台達電',
        'ref_close': 0, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/3 圈起來',
        'sector': 'AI電源/散熱',
        'note': '⭐ 老師 6/3 圈起來中長期 (AI 電源/散熱龍頭)'
    },
    {
        'ticker': '2368', 'name': '金像電',
        'ref_close': 0, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/3 圈起來',
        'sector': 'PCB',
        'note': '⭐ 老師 6/3 圈起來中長期 (PCB)'
    },
    {
        'ticker': '2345', 'name': '智邦',
        'ref_close': 0, 'stop': None,
        'tactic': '中長期', 'priority': 2,
        'source': '老師明示 6/3 圈起來',
        'sector': '網通',
        'note': '⭐ 老師 6/3 圈起來中長期 (網通/800G switch)'
    },
    # 6/3 scanner 新增 (Tier-B 打擊區、籌碼/型態符合)
    {
        'ticker': '1717', 'name': '長興',
        'ref_close': 78.70, 'stop': 75.50,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner (small_structure)',
        'sector': '封測/特化',
        'note': '🟡 ⭐管錢哥分點重押、距 MA10 -2.7% 打擊區、首提後 79d (二波期)'
    },
    # 4722 國精化 — 6/3 移出
    # 原因: D+7 跌破 MA5、不符處置課「站均線」條件
    # 老師「貴買要在所有均線之上、處置期間守住均線」(line 16/36)
    # D+4-5 切入窗口已過、現結構轉弱、6/4 不進
    {
        'ticker': '4526', 'name': '東台',
        'ref_close': 42.15, 'stop': 40.16,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner (w_bottom_launch)',
        'sector': '電機機械',
        'note': '🟢 W底 + 量比 2.2x + ⭐站前哥、距 MA10 +5.0%、MA10 停利 ~40.16'
    },
    {
        'ticker': '4540', 'name': '全球傳動',
        'ref_close': 77.30, 'stop': 70.84,
        'tactic': '題材', 'priority': 2,
        'source': 'scanner (w_bottom_launch)',
        'sector': '機器人',
        'note': '🟢 機器人主流 + W底 量比 2.0x、距 MA10 +9.1%、MA10 停利 ~70.84'
    },
    # 6/3 加 — 過去 5d shakeout 補進候選
    {
        'ticker': '6906', 'name': '微邦',
        'ref_close': 103.5, 'stop': 95.0,
        'tactic': '短打', 'priority': 2,
        'source': 'shakeout_strong (5/26 confirmed)',
        'sector': '電子小型',
        'note': '🟢 5/26 shakeout 確認、距 MA10 +5%、6/3 紅 K +2.5% 反轉、漲幅初期'
    },
]

# ─────────────────────────────────────────────────────────────────────────
# daily_watchlist JSON 自動 merge (scanner → WATCH)
# ─────────────────────────────────────────────────────────────────────────

def _merge_scanner_watchlist() -> tuple[int, int, str]:
    """讀 daily_watchlist JSON、merge 新 ticker 進 WATCH global list.

    - 優先找 today's JSON (docs/主力大課程/daily_watchlist/{today}.json)
    - 不存在則找最近一天的
    - 硬編碼 WATCH 已有的 ticker → 跳過 (不覆蓋)
    - 新 ticker → append 進 WATCH (source='scanner'、priority/note 從 JSON 帶)

    Returns:
        (added_count, existing_count, loaded_date)
    """
    import json as _json
    from datetime import date as _date

    global WATCH  # noqa: PLW0603

    watchlist_dir = _REPO / "docs" / "主力大課程" / "daily_watchlist"
    if not watchlist_dir.exists():
        return (0, 0, '')

    today_str = _date.today().isoformat()

    # 找目標 JSON: today 優先、否則最新
    target_json: Path | None = None
    today_path = watchlist_dir / f"{today_str}.json"
    if today_path.exists():
        target_json = today_path
        loaded_date = today_str
    else:
        jsons = sorted(watchlist_dir.glob("*.json"))
        if jsons:
            target_json = jsons[-1]
            loaded_date = target_json.stem
        else:
            return (0, 0, '')

    try:
        payload = _json.loads(target_json.read_text(encoding='utf-8'))
    except Exception:
        return (0, 0, loaded_date)

    candidates = payload.get('candidates', [])
    if not candidates:
        return (0, 0, loaded_date)

    # 建立現有 WATCH ticker set (hardcoded)
    existing_tickers: set[str] = set()
    for item in WATCH:
        if isinstance(item, dict) and item.get('ticker'):
            existing_tickers.add(str(item['ticker']))
        elif isinstance(item, (tuple, list)) and len(item) > 0:
            existing_tickers.add(str(item[0]))

    added = 0
    for c in candidates:
        ticker = str(c.get('ticker', ''))
        if not ticker or ticker in existing_tickers:
            continue

        sources = c.get('sources', [])
        priority = int(c.get('priority', 2))
        sector = c.get('sector', '')
        note = c.get('note', '')
        ref_close = float(c.get('ref_close', 0) or 0)
        dist = c.get('dist_ma10_pct')
        name = c.get('name', '')
        tactic = c.get('tactic', '短打')

        # 組合 note 加上 dist_ma10
        note_full = note
        if dist is not None:
            note_full = f"{note_full} | 距MA10 {dist:+.1f}%".strip(' |')

        WATCH.append({
            'ticker': ticker,
            'name': name,
            'ref_close': ref_close,
            'stop': None,
            'tactic': tactic,
            'priority': priority,
            'source': f'scanner ({", ".join(sources[:2])})',
            'sector': sector,
            'note': f'📊 {note_full}' if note_full else f'📊 scanner 命中 ({loaded_date})',
        })
        existing_tickers.add(ticker)
        added += 1

    existing_count = len(existing_tickers) - added
    return (added, existing_count, loaded_date)


# 老師 6/2 明示族群框架 (大方向、scanner 命中後加分):
TEACHER_SECTORS_20260602 = {
    'IC 通路': '⭐⭐ 6/2 主流 (3702 大聯大 / 3036 文曄)',
    'IC 設計': '⭐⭐ 6/2 主流 (5351 鈺創 / 3034 聯詠 / 2454 聯發科)',
    '模組': '⭐ 6/2 主流 (實權 / 威剛 / 宇瞻 / 林行 / 光罩)',
    '記憶體': '⭐⭐ 6/2 主流 (2344 華邦電[漲多] / 2408 南亞科 / 3006 晶豪科)',
    '記憶體封測': '⭐ 6/2 主流 (6147 頎邦)',
    '記憶體周邊': '⭐ 6/2 主流',
    'GT 基底/成熟製程': '⭐⭐⭐ 6/2 核心 (2303 聯電 / 2330 台積電)',
    'AI PC / 全資股': '⭐⭐ (2376 技嘉 [重壓] / 3231 緯創 / 2382 廣達 / 2379 瑞昱)',
    '紅海第二棒': '⭐⭐ (1605 華新 / 6116 彩晶)',
    '玻璃': '⭐ (8064 東捷)',
}

# ─────────────────────────────────────────────────────────────────────────
# 排序模式
# ─────────────────────────────────────────────────────────────────────────

SORT_MODES = ['status', 'priority', 'risk', 'trigger', 'pnl', 'sector']
SORT_KEY_LABEL = {
    'status':   '🎯 狀態分段',
    'priority': '⭐ 優先級',
    'risk':     '⚠️  停損距離',
    'trigger':  '🟢 Trigger',
    'pnl':      '💰 P&L',
    'sector':   '🏷️  族群',
}

# ─────────────────────────────────────────────────────────────────────────
# Strategy mode chip (決定出場規則、與 trigger 無關)
# ─────────────────────────────────────────────────────────────────────────
# strategy_mode 選項：
#   'intraday'  當沖、13:30 出 (backtest -0.80%、不推薦)
#   'overnight' 隔日沖、隔日 9:00 出 (backtest +1.85%、⭐主推)
#   'swing'     波段、3-5 天看結構 (現有 default)
#   'core'      核心持倉、結構底停損

STRATEGY_CHIP = {
    'intraday':  '⚡ 當沖',
    'overnight': '🌅 隔日沖',
    'swing':     '📈 波段',
    'core':      '🏛️ 核心',
}

STRATEGY_EXIT_LABEL = {
    'intraday':  '[exit: 13:30]',
    'overnight': '[exit: 明日 9:00]',
    'swing':     '[exit: 結構底/MA10]',
    'core':      '[exit: 結構底]',
}

STRATEGY_EXIT_STYLE = {
    'intraday':  'bold red',
    'overnight': 'bold cyan',
    'swing':     'dim',
    'core':      'dim',
}

# 沒填 strategy_mode 時的 fallback (向後相容)
_DEFAULT_STRATEGY_MODE = 'swing'


def get_strategy_mode(item: dict) -> str:
    """取 item 的 strategy_mode，未填則由 tactic 推斷。"""
    mode = item.get('strategy_mode')
    if mode in STRATEGY_CHIP:
        return mode
    # 向後相容：依 tactic 推斷
    tactic = (item.get('tactic') or '').lower()
    if '核心' in tactic or 'core' in tactic:
        return 'core'
    if '配置' in tactic:
        return 'core'
    return _DEFAULT_STRATEGY_MODE


def r_strategy_chip(item: dict, now: datetime | None = None) -> Text:
    """Strategy mode chip + exit 提醒文字、rich Text。

    根據 strategy_mode 顯示：
    - intraday:  ⚡ 當沖  [exit: 13:30 ← Xh Ym 後]
    - overnight: 🌅 隔日沖 [exit: 明日 9:00]
    - swing:     📈 波段  [exit: 結構底/MA10]
    - core:      🏛️ 核心  [exit: 結構底]
    """
    now = now or datetime.now()
    mode = get_strategy_mode(item)
    chip = STRATEGY_CHIP.get(mode, mode)
    exit_label = STRATEGY_EXIT_LABEL.get(mode, '')
    exit_style = STRATEGY_EXIT_STYLE.get(mode, 'dim')

    t = Text()
    if mode == 'intraday':
        t.append(chip, style='bold yellow')
        # 計算距 13:30 剩餘
        close_min = 13 * 60 + 30
        cur_min   = now.hour * 60 + now.minute
        remaining = close_min - cur_min
        if remaining > 0:
            h, m = divmod(remaining, 60)
            remain_str = f"{h}h{m:02d}m後" if h else f"{m}m後"
            t.append(f" [exit: 13:30 ← {remain_str}]", style=exit_style)
        else:
            t.append(" [exit: 13:30 ← 已到時限!]", style='bold red blink')
    elif mode == 'overnight':
        t.append(chip, style='bold cyan')
        # 計算距隔日 9:00
        h_now, m_now = now.hour, now.minute
        if h_now < 9:
            # 還沒開盤（隔日）
            remain_min = (9 * 60) - (h_now * 60 + m_now)
            h, m = divmod(remain_min, 60)
            remain_str = f"{h}h{m:02d}m後" if h else f"{m}m後"
            t.append(f" [exit: 09:00 ← {remain_str}]", style=exit_style)
        elif h_now >= 9 and h_now < 13:
            # 今天盤中持有中
            t.append(f" {exit_label}", style=exit_style)
        else:
            # 今天收盤後、隔日開盤前
            # 距明日 9:00 = 24h - (now - 9:00 yesterday) → 簡單算
            remain_to_next_open = ((24 - h_now) * 60 - m_now) + 9 * 60
            h, m = divmod(remain_to_next_open, 60)
            remain_str = f"{h}h{m:02d}m後" if h else f"{m}m後"
            t.append(f" [exit: 明日 09:00 ← {remain_str}]", style=exit_style)
    else:
        t.append(chip, style='dim')
        t.append(f" {exit_label}", style=exit_style)
    return t


def check_strategy_exit_alert(item: dict, now: datetime | None = None) -> str | None:
    """檢查是否需要發出出場提醒。回傳提醒標題或 None。

    - intraday: 13:25 預警 / 13:30 強制
    - overnight: 8:45 預警 / 9:00 強制
    - swing/core: None（現有結構底監控）
    """
    now = now or datetime.now()
    mode = get_strategy_mode(item)
    h, m = now.hour, now.minute
    ticker = item.get('ticker', '')
    name   = item.get('name', ticker)

    if mode == 'intraday':
        if h == 13 and m >= 30:
            return f"🚨 {ticker} {name} 當沖時限到、請立即出場！"
        if h == 13 and m >= 25:
            return f"⚡ {ticker} {name} 當沖 5 分鐘後收盤、準備出場"
    elif mode == 'overnight':
        if h == 9 and m >= 0 and m < 5:
            return f"🌅 {ticker} {name} 隔日沖 9:00 開盤出場時間到"
        if h == 8 and m >= 45:
            return f"🌅 {ticker} {name} 隔日沖 15 分鐘後 9:00 要出場"
    return None

# ── Win rate by session (v8 backtest 2026-06-04) ────────────────────────────
# 來源: phase3_v8_intraday_vs_closing_compare.py  commit b7e56fe
# 更新此 dict 即可讓整個 monitor 數字同步
WIN_RATE_BY_SESSION: dict[str, int] = {
    "pump_dump":  41,   # 09:15-09:45 拉高出貨期
    "healthy":    58,   # 09:45-11:00 健康時段
    "closing":    80,   # 13:00-13:25 老師尾盤
}

# Trigger 顯示格式 (新中文命名 primary、舊英文名 alias 向後相容)
TRIGGER_DISPLAY = {
    # 新中文命名 (primary)
    '首攻':          '🟢 首攻 confirmed (守住進場)',
    '首攻_pullback': '🟡 首攻 pullback (回踩中)',
    '首攻_signal':   '🟡 首攻 signal (訊號、等回踩)',
    '續攻':          '🟢 續攻 confirmed',
    '續攻_watch':    '🟡 續攻 watch (等 9:45+)',
    '反彈':          '🎯 反彈 confirmed',
    '反彈_watch':    '🟡 反彈 watch (等 9:45+)',
    '破底':          '🔴 破底 confirmed',
    # 尾盤進場確認 (13:00-13:25) — v7 backtest 校正命名
    '尾盤_confirmed': '🟢 ⭐ 尾盤 confirmed 3-4/5 Win 82% (最佳進場)',
    '尾盤_過熱':      '🔴 尾盤過熱 5/5 Win 40% (已被拉走、別追)',
    '尾盤_skip':      '⚪ 尾盤 skip <3/5 (不進)',
    # 舊英文名 alias (向後相容)
    'Ch5-3':             '🟢 首攻 confirmed (守住進場)',
    'Ch5-3_pullback':    '🟡 首攻 pullback (回踩中)',
    'Ch5-3_signal':      '🟡 首攻 signal (訊號、等回踩)',
    'T1':                '🟢 續攻 confirmed',
    'T1_watch':          '🟡 續攻 watch (等 9:45+)',
    'T2':                '🎯 反彈 confirmed',
    'T2_watch':          '🟡 反彈 watch (等 9:45+)',
    'TC':                '🔴 破底 confirmed',
    'Closing_confirmed': '🟢 ⭐ 尾盤 confirmed 3-4/5 Win 82% (最佳進場)',
    'Closing_overheated': '🔴 尾盤過熱 5/5 Win 40% (已被拉走、別追)',
    'Closing_watch':     '🟡 尾盤 watch (3-4/5)',  # legacy alias
    'Closing_skip':      '⚪ 尾盤 skip <3/5 (不進)',
    'none': '⚪ 無訊號',
    None: '⚪ 無訊號',
}

# sort by trigger 優先順序: 首攻 confirmed > pullback > signal > 尾盤 > 反彈 > 續攻 > 破底 > none
TRIGGER_RANK = {
    # 新中文命名 (primary)
    '首攻':           0,
    '首攻_pullback':  1,
    '首攻_signal':    2,
    '尾盤_confirmed': 3,   # 3-4/5 Win 82% 最佳進場、高優先
    '反彈':           4,
    '續攻':           5,
    '破底':           6,
    '尾盤_過熱':      7,   # 5/5 Win 40% 警示、低優先
    '尾盤_skip':      8,
    '續攻_watch':     9,
    '反彈_watch':     10,
    # 舊英文名 alias (向後相容)
    'Ch5-3':             0,
    'Ch5-3_pullback':    1,
    'Ch5-3_signal':      2,
    'Closing_confirmed': 3,
    'Closing_overheated': 7,
    'Closing_watch':     4,  # legacy
    'T2':                4,
    'T1':                5,
    'TC':                6,
    'Closing_skip':      8,
    'T1_watch':          9,
    'T2_watch':          10,
    'none': 11,
    None: 12,
}

# 全域排序切換（快捷鍵 1-6 更新這個）
_current_sort: list[str] = ['status']
_quit_flag: list[bool] = [False]
_watch_min_priority: list[int] = [2]
_watch_limit: list[int] = [5]   # 每個分類最多顯示 N 檔、超過 collapse、0 = 全顯

# Render request flag: kb / WS push set True、main loop 0.1s polling 立即重畫
_render_request: list[bool] = [True]
_last_ws_render_signal: list[float] = [0.0]

# Demo mode 全域 state
_demo_idx: list[int] = [0]
_demo_paused: list[bool] = [True]  # 預設暫停 auto-cycle、手動切
_demo_jump: list[bool] = [False]   # set 後主迴圈立刻 re-render
_demo_total: list[int] = [0]

# Cheat sheet 模式 (按 ? 切到 reference 畫面)
_cheat_mode: list[bool] = [False]
_cheat_idx: list[int] = [0]
_cheat_jump: list[bool] = [False]

# Trigger cooldown 避免重複通知 (key: "{ticker}_{T1/T2/TC}")
_trigger_cooldown: dict[str, datetime] = {}
TRIGGER_COOLDOWN_MIN = 30

# Trigger 觸發時間追蹤 (ticker, trig_key) → 第一次點亮 datetime
# 用於顯示「Nm前」、判斷時機是否還新鮮
_trigger_fired_at: dict[tuple[str, str], datetime] = {}
# ticker → 當前 trigger key、偵測切換用
_trigger_current: dict[str, str] = {}

# Demo 模式 trigger 起算時間 override (給 demo scenario 設假時間用)
_demo_trigger_age_override: dict[str, int] = {}  # ticker -> 分鐘數

# ─────────────────────────────────────────────────────────────────────────
# Tuple → dict 自動 convert (向後相容)
# ─────────────────────────────────────────────────────────────────────────

def _normalize_held(items: list) -> list[dict]:
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        else:
            tk, name, cost, shares, stop = item
            out.append({'ticker': tk, 'name': name, 'cost': cost,
                        'shares': shares, 'stop': stop,
                        'tactic': '核心', 'priority': 2,
                        'source': '?', 'sector': '?', 'note': ''})
    return out


def _normalize_plan(items: list) -> list[dict]:
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        else:
            tk, name, shares, stop, reason = item
            out.append({'ticker': tk, 'name': name, 'shares': shares,
                        'stop': stop, 'reason': reason,
                        'tactic': '核心', 'priority': 2,
                        'source': '?', 'sector': '?', 'note': reason})
    return out


def _normalize_watch(items: list) -> list[dict]:
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        else:
            tk, name, ref_close, stop, kind = item
            out.append({'ticker': tk, 'name': name,
                        'ref_close': ref_close, 'stop': stop,
                        'tactic': '短打', 'priority': 2,
                        'source': '?', 'sector': '?', 'note': kind})
    return out


# ─────────────────────────────────────────────────────────────────────────
# Intraday StageTrigger 即時偵測
# ─────────────────────────────────────────────────────────────────────────

def _load_stage_trigger():
    """Lazy import StageTrigger。"""
    try:
        from zhuli.intraday_stage_helper import StageTrigger, fetch_5min_kbar, _get_prev_levels
        return StageTrigger(), fetch_5min_kbar, _get_prev_levels
    except ImportError:
        try:
            # fallback: 直接從同目錄 import
            _here = Path(__file__).parent
            if str(_here) not in sys.path:
                sys.path.insert(0, str(_here))
            from intraday_stage_helper import StageTrigger, fetch_5min_kbar, _get_prev_levels
            return StageTrigger(), fetch_5min_kbar, _get_prev_levels
        except Exception as e:
            return None, None, None


_stage_engine, _fetch_5min, _get_prev = _load_stage_trigger()


def _get_market_regime_chip() -> tuple[str, str]:
    """取大盤環境 chip。回傳 (label, style)。"""
    try:
        if _stage_engine is None:
            return "市場: ⚪ 未知", "dim"
        today_str = date.today().isoformat()
        regime = _stage_engine._detect_market_regime(today_str)
        if regime == "strong":
            return "市場: 🟢 強勢", "bold green"
        elif regime == "weak":
            return "市場: 🔴 弱勢", "bold red"
        else:
            return "市場: ⚪ 正常", "white"
    except Exception:
        return "市場: ⚪ ?", "dim"


def _get_session_chip(now: datetime | None = None) -> tuple[str, str]:
    """依當前時間回傳時段分類 chip (label, style)。

    時段定義 (v8 backtest 2026-06-04、含 Win rate):
      09:00-09:15  ⏳ 觀察期 (紅線 #3)
      09:15-09:45  ⛔ 拉高出貨期  Win 41%  (v8 backtest)
      09:45-11:00  🟡 健康時段   Win 58%
      11:00-13:00  ⚪ 整理/殺盤考驗
      13:00-13:25  🟢 ⭐ 老師尾盤  Win 80%  (最佳)
      13:25-13:30  🎯 試撮限價接
    """
    t = (now or datetime.now()).time()
    from datetime import time as _time
    wd = WIN_RATE_BY_SESSION  # 縮短引用
    if t < _time(9, 0):
        return "⏸ 盤前", "dim"
    elif t < _time(9, 15):
        return "⏳ 觀察期 (紅線 #3)", "yellow"
    elif t < _time(9, 45):
        return f"⛔ 拉高出貨期 Win {wd['pump_dump']}%", "bold yellow"
    elif t < _time(11, 0):
        return f"🟡 健康時段 Win {wd['healthy']}%", "bold green"
    elif t < _time(12, 0):
        return "⚪ 整理時段", "white"
    elif t < _time(13, 0):
        return "🌀 殺盤考驗", "cyan"
    elif t < _time(13, 25):
        return f"🟢 ⭐ 老師尾盤 Win {wd['closing']}%", "bold magenta"
    elif t < _time(13, 30):
        return "🎯 試撮限價接", "magenta"
    else:
        return "⏹ 盤後", "dim"

# 抑制 stage_helper 的 log 訊息、避免噴到 monitor alt-screen 破版
import logging as _logging
_logging.getLogger('zhuli.intraday_stage_helper').setLevel(_logging.ERROR)
_logging.getLogger('intraday_stage_helper').setLevel(_logging.ERROR)
_logging.getLogger('clients.fubon_client').setLevel(_logging.ERROR)


# ─────────────────────────────────────────────────────────────────────────
# WebSocket 即時報價快取 (取代 sequential REST snapshot)
# ─────────────────────────────────────────────────────────────────────────

class WSPriceCache:
    """訂閱 Fubon WebSocket aggregates channel、cache 最新報價。

    monitor 每次 refresh 從 cache 拿、O(1)、不再 sequential REST。
    REST 用於初始 warm-up + WS 失敗時 fallback。
    """
    STALE_SEC = 30  # cache 超過 30 秒沒 update → REST fallback

    def __init__(self, client, tickers: list[str]):
        self.client = client
        self.tickers = list(set(tickers))
        self.cache: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.last_update: dict[str, float] = {}
        self.ws = None
        self.ws_ok = False
        self.errors = 0
        self._warm()
        self._connect()

    @staticmethod
    def _normalize_rest_snap(snap: dict) -> dict:
        """REST snapshot 單位修正：FubonClient.get_realtime_snapshot 回傳的
        total_volume 是 tradeVolume(千股) // 1000 = 千張，而非張。
        乘以 1000 統一成張 (lots)，與 WS trades stream int(shares)//1000 一致。
        """
        entry = dict(snap)
        tv = entry.get('total_volume')
        if tv is not None:
            try:
                entry['total_volume'] = int(tv) * 1000  # 千張 → 張
            except Exception:
                pass
        return entry

    def _warm(self):
        """REST 初始抓一輪、確保 cache 有資料 + 記錄 _warm_close 供反推 prev_close."""
        for tk in self.tickers:
            try:
                snap = self.client.get_realtime_snapshot(tk)
                if snap:
                    with self.lock:
                        entry = self._normalize_rest_snap(snap)
                        # 留底用於反推 prev_close (close - change_price)
                        if 'close' in entry:
                            entry['_warm_close'] = entry['close']
                        self.cache[tk] = entry
                        self.last_update[tk] = time.time()
            except Exception:
                pass

    def _connect(self):
        """Connect WebSocket、subscribe 全部 tickers (trades channel — Speed mode 支援)."""
        try:
            # 注意: Fubon Speed mode 不支援 aggregates/candles、只能用 trades/books
            self.ws = self.client.subscribe_quotes(
                self.tickers, self._on_message, channel='trades'
            )
            self.ws_ok = self.ws is not None
        except Exception:
            self.ws_ok = False

    def _on_message(self, msg):
        """WS 推送 callback。實測 trades channel 訊息格式 (Fubon Speed mode)：
            {"event": "data", "data": {
                "symbol": "3481", "type": "EQUITY", "exchange": "TWSE", "market": "TSE",
                "price": 59.1, "size": 5, "bid": 59, "ask": 59.1, "volume": 532557,
                "isContinuous": true, "session": "Regular",
                "time": 1780454658908318, "serial": 11214722
            }}
        其他事件: authenticated / pong / heartbeat / subscribed → 忽略。
        trades stream 沒有 OHLC、只有逐筆 price + 當日累積 volume (股數).
        我們本地維護 high/low (max/min seen)、close=最新 price、volume=cumulative/1000 (張).
        open / change_price / change_rate 由 REST warm 初始化、WS 不覆寫.
        """
        try:
            data = msg
            if isinstance(msg, str):
                import json as _json
                data = _json.loads(msg)
            if not isinstance(data, dict):
                return
            # 只處理 data event、忽略 authenticated/pong/heartbeat/subscribed
            event = data.get('event')
            if event != 'data':
                return
            payload = data.get('data')
            if not isinstance(payload, dict):
                return
            symbol = payload.get('symbol')
            if not symbol:
                return
            symbol = str(symbol)
            price = payload.get('price')
            if price is None:
                return
            price = float(price)
            volume_shares = payload.get('volume')  # 累積成交股數
            bid = payload.get('bid')
            ask = payload.get('ask')
            with self.lock:
                existing = self.cache.get(symbol) or {}
                # close = 最新成交價
                existing['close'] = price
                # high/low 本地維護 (trades stream 沒有 OHLC)
                cur_high = existing.get('high') or 0
                cur_low = existing.get('low') or 0
                if not cur_high or price > cur_high:
                    existing['high'] = price
                if not cur_low or price < cur_low:
                    existing['low'] = price
                # volume: cumulative shares → 張 (÷1000)
                if volume_shares is not None:
                    try:
                        existing['total_volume'] = int(volume_shares) // 1000
                    except Exception:
                        pass
                # bid/ask 補充欄位
                if bid is not None:
                    try:
                        existing['bid'] = float(bid)
                    except Exception:
                        pass
                if ask is not None:
                    try:
                        existing['ask'] = float(ask)
                    except Exception:
                        pass
                # change_price / change_rate 由 prev_close 推算
                # REST warm 給的 close + change_price → prev_close = close_at_warm - change_at_warm
                # 用 cached prev_close 推 new change
                prev_close = existing.get('_prev_close')
                if prev_close is None:
                    # 首次: 從 warm cache 反推 prev_close
                    warm_close = existing.get('_warm_close')
                    warm_change = existing.get('change_price')
                    if warm_close is not None and warm_change is not None:
                        try:
                            prev_close = float(warm_close) - float(warm_change)
                            existing['_prev_close'] = prev_close
                        except Exception:
                            prev_close = None
                if prev_close:
                    try:
                        existing['change_price'] = price - float(prev_close)
                        existing['change_rate'] = (price - float(prev_close)) / float(prev_close) * 100
                    except Exception:
                        pass
                self.cache[symbol] = existing
                self.last_update[symbol] = time.time()
            # WS push 觸發 redraw、限速 100ms 避免太頻繁
            _now = time.time()
            if _now - _last_ws_render_signal[0] > 0.1:
                _render_request[0] = True
                _last_ws_render_signal[0] = _now
        except Exception:
            self.errors += 1

    def get_realtime_snapshot(self, ticker: str) -> dict | None:
        """模擬 FubonClient.get_realtime_snapshot 介面、回傳 cached snapshot.

        若 cache stale > STALE_SEC、用 REST 補一筆。
        """
        ticker = str(ticker)
        with self.lock:
            snap = self.cache.get(ticker)
            ts   = self.last_update.get(ticker, 0)
        if snap and (time.time() - ts) < self.STALE_SEC:
            return dict(snap)
        # Stale or missing → REST fallback
        try:
            fresh = self.client.get_realtime_snapshot(ticker)
            if fresh:
                normalized = self._normalize_rest_snap(fresh)
                with self.lock:
                    self.cache[ticker] = normalized
                    self.last_update[ticker] = time.time()
                return normalized
        except Exception:
            pass
        return snap  # 回傳舊資料總比 None 好

    def stats(self) -> tuple[int, int, int]:
        """回傳 (cached_count, stale_count, error_count)."""
        now = time.time()
        with self.lock:
            total = len(self.cache)
            stale = sum(1 for ts in self.last_update.values()
                        if (now - ts) > self.STALE_SEC)
        return total, stale, self.errors


def check_trigger_inline(ticker: str, tactic: str = '核心') -> tuple[str, str]:
    """即時跑 composite_check cascade，回傳 (trigger_key, reason)。

    trigger_key: '首攻' / '續攻' / '反彈' / '破底' / 'none'  (新中文名)
    舊英文名 alias: 'Ch5-3' / 'T1' / 'T2' / 'TC' 亦接受 (向後相容)
    category 依 tactic 決定: 核心/題材 → HELD；其他 → WATCH
    """
    if _stage_engine is None or _fetch_5min is None or _get_prev is None:
        return 'none', '(StageTrigger unavailable)'

    try:
        now = datetime.now()
        k5 = _fetch_5min(ticker, now.date())
        if k5 is None or k5.empty:
            return 'none', '(無 5K 資料)'

        prev = _get_prev(ticker, DB) if _get_prev else {}
        prev_close = float(prev.get('prev_close') or 0)

        # 紀律過濾
        pass_disc, disc_reason = _stage_engine.check_discipline_filter(
            ticker, k5, now, prev_close or None
        )

        # category 決定
        category = 'HELD' if tactic in ('核心', '題材') else 'WATCH'

        # Cascade composite_check
        result = _stage_engine.composite_check(
            ticker=ticker,
            k5=k5,
            prev_close=prev_close,
            prev_levels=prev,
            category=category,
        )

        det = result.get('detector', 'none')
        reason = result.get('reason', '')
        triggered = result.get('triggered', False)

        if not triggered:
            # 若紀律擋住也回報
            if not pass_disc:
                return 'none', disc_reason
            return 'none', reason

        return det, reason

    except Exception as e:
        return 'none', f'(err: {e})'


def maybe_notify_trigger(ticker: str, name: str, trig_key: str, reason: str, do_notify: bool):
    """Trigger 觸發時、30 分鐘 cooldown 通知。支援新中文名及舊英文名 alias。"""
    if not do_notify:
        return
    # 支援新中文名及舊英文名 alias
    valid_keys = (
        '首攻', '首攻_signal', '首攻_pullback',
        '續攻', '續攻_watch',
        '反彈', '反彈_watch',
        '破底',
        '尾盤_confirmed', '尾盤_過熱', '尾盤_skip',
        # 舊英文名 alias
        'Ch5-3', 'Ch5-3_signal', 'Ch5-3_pullback', 'T1', 'T1_watch',
        'T2', 'T2_watch', 'TC',
        'Closing_confirmed', 'Closing_overheated', 'Closing_watch', 'Closing_skip',
    )
    if trig_key not in valid_keys:
        return
    cd_key = f"{ticker}_{trig_key}"
    now = datetime.now()
    if now <= _trigger_cooldown.get(cd_key, datetime.min):
        return
    _trigger_cooldown[cd_key] = now + timedelta(minutes=TRIGGER_COOLDOWN_MIN)

    titles = {
        # 新中文命名 (primary)
        '首攻':          f"🟢 {ticker} {name} 首攻 守住 → 可進場",
        '首攻_pullback': f"🟡 {ticker} {name} 首攻 回踩 MA10 中",
        '首攻_signal':   f"🟡 {ticker} {name} 首攻 訊號觸發、等回踩",
        '續攻':          f"🟢 {ticker} {name} 續攻 強勢延續",
        '續攻_watch':    f"🟡 {ticker} {name} 續攻 watch → 等 9:45+",
        '反彈':          f"🎯 {ticker} {name} 反彈 訊號",
        '反彈_watch':    f"🟡 {ticker} {name} 反彈 watch → 等 9:45+",
        '破底':          f"🚨 {ticker} {name} 破底 結構失敗",
        '尾盤_confirmed': f"🟢 ⭐ {ticker} {name} 尾盤 3-4/5 Win 82% → 最佳進場",
        '尾盤_過熱':      f"🔴 {ticker} {name} 尾盤 5/5 過熱 Win 40% → 別追",
        '尾盤_skip':      f"⚪ {ticker} {name} 尾盤 <3/5 → 不進",
        # 舊英文名 alias
        'Ch5-3':             f"🟢 {ticker} {name} 首攻 守住 → 可進場",
        'Ch5-3_pullback':    f"🟡 {ticker} {name} 首攻 回踩 MA10 中",
        'Ch5-3_signal':      f"🟡 {ticker} {name} 首攻 訊號觸發、等回踩",
        'T1':                f"🟢 {ticker} {name} 續攻 強勢延續",
        'T1_watch':          f"🟡 {ticker} {name} 續攻 watch → 等 9:45+",
        'T2':                f"🎯 {ticker} {name} 反彈 訊號",
        'T2_watch':          f"🟡 {ticker} {name} 反彈 watch → 等 9:45+",
        'TC':                f"🚨 {ticker} {name} 破底 結構失敗",
        'Closing_confirmed': f"🟢 ⭐ {ticker} {name} 尾盤 3-4/5 Win 82% → 最佳進場",
        'Closing_overheated': f"🔴 {ticker} {name} 尾盤 5/5 過熱 Win 40% → 別追",
        'Closing_watch':     f"🟡 {ticker} {name} 尾盤 3-4/5 → 觀察",  # legacy
        'Closing_skip':      f"⚪ {ticker} {name} 尾盤 <3/5 → 不進",
    }
    sounds = {
        '首攻': 'Glass', '首攻_signal': 'Tink', '首攻_pullback': 'Tink',
        '續攻': 'Glass', '續攻_watch': 'Tink',
        '反彈': 'Glass', '反彈_watch': 'Tink',
        '破底': 'Sosumi',
        '尾盤_confirmed': 'Glass', '尾盤_過熱': 'Sosumi', '尾盤_skip': 'Basso',
        # 舊英文名 alias
        'Ch5-3': 'Glass', 'Ch5-3_signal': 'Tink', 'Ch5-3_pullback': 'Tink',
        'T1': 'Glass', 'T1_watch': 'Tink',
        'T2': 'Glass', 'T2_watch': 'Tink',
        'TC': 'Sosumi',
        'Closing_confirmed': 'Glass', 'Closing_overheated': 'Sosumi',
        'Closing_watch': 'Tink', 'Closing_skip': 'Basso',
    }
    try:
        subprocess.run(
            ['osascript', '-e',
             f'display notification "{reason[:80]}" with title "{titles[trig_key]}" '
             f'sound name "{sounds[trig_key]}"'],
            check=False, timeout=3
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────
# 排序 helper
# ─────────────────────────────────────────────────────────────────────────

def sort_items(items: list[dict], mode: str, live_data: dict | None = None) -> list[dict]:
    ld = live_data or {}

    def key(x: dict):
        tk = x.get('ticker', '')
        d = ld.get(tk, {})
        if mode == 'priority':
            return (-x.get('priority', 2), x.get('sector', ''), tk)
        elif mode == 'risk':
            dist = d.get('dist_to_stop', 999.0)
            return (dist,)
        elif mode == 'trigger':
            trig = d.get('trigger') or 'none'
            return (TRIGGER_RANK.get(trig, 5), -x.get('priority', 2))
        elif mode == 'pnl':
            return (-d.get('pnl_pct', 0),)
        elif mode == 'sector':
            return (x.get('sector', '?'), -x.get('priority', 2), tk)
        return (tk,)

    return sorted(items, key=key)


# ─────────────────────────────────────────────────────────────────────────
# 顏色 / 格式 helper
# ─────────────────────────────────────────────────────────────────────────

class C:
    R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; B = '\033[94m'
    BOLD = '\033[1m'; DIM = '\033[2m'; END = '\033[0m'
    HOME = '\033[H'
    EOL  = '\033[K'
    ALT_ON  = '\033[?1049h'
    ALT_OFF = '\033[?1049l'
    HIDE = '\033[?25l'
    SHOW = '\033[?25h'
    CLR = HOME


def notify_mac(title: str, msg: str):
    try:
        subprocess.run(['osascript', '-e',
                       f'display notification "{msg}" with title "{title}" sound name "Glass"'],
                       check=False, timeout=3)
    except Exception:
        print('\a', end='', flush=True)


def fmt_pnl(pnl: float, pct: float = 0) -> str:
    color = C.G if pnl >= 0 else C.R
    sign = '+' if pnl >= 0 else ''
    if pct != 0:
        return f"{color}{sign}{pnl:,.0f} ({sign}{pct:.1f}%){C.END}"
    return f"{color}{sign}{pnl:,.0f}{C.END}"


def fmt_dist(dist: float) -> str:
    if dist < 0: return f"{C.R}{dist:+.1f}%{C.END}"
    if dist < 1: return f"{C.Y}{dist:+.1f}%{C.END}"
    return f"{C.G}{dist:+.1f}%{C.END}"


def stars(priority: int) -> str:
    return '⭐' * max(0, priority)


# ─────────────────────────────────────────────────────────────────────────
# rich helper (新 display 層)
# ─────────────────────────────────────────────────────────────────────────

def r_pnl(pnl: float, pct: float = 0) -> Text:
    """rich 版的 fmt_pnl、回傳 Text。"""
    style = 'green' if pnl >= 0 else 'red'
    sign = '+' if pnl >= 0 else ''
    if pct != 0:
        return Text(f"{sign}{pnl:,.0f} ({sign}{pct:.1f}%)", style=style)
    return Text(f"{sign}{pnl:,.0f}", style=style)


def r_dist(dist: float) -> Text:
    """距停損百分比、依危險度上色。"""
    if dist >= 999:
        return Text("—", style="dim")
    if dist < 0:
        return Text(f"{dist:+.1f}%", style="red")
    if dist < 1:
        return Text(f"{dist:+.1f}%", style="yellow")
    return Text(f"{dist:+.1f}%", style="green")


def record_trigger_fire(ticker: str, new_trig_key: str,
                        now: datetime | None = None) -> None:
    """偵測 trigger 切換、新 key 第一次出現時記時間。

    Called by background DataCache refresh (一個 ticker 一輪一次)。
    """
    now = now or datetime.now()
    prev = _trigger_current.get(ticker)
    if new_trig_key == prev:
        return
    _trigger_current[ticker] = new_trig_key
    if new_trig_key and new_trig_key != 'none':
        # 新 trigger 點亮、記時間 (若已記過、不覆蓋)
        key = (ticker, new_trig_key)
        if key not in _trigger_fired_at:
            _trigger_fired_at[key] = now


def fmt_trigger_age(ticker: str, trig_key: str,
                    now: datetime | None = None) -> tuple[str, str]:
    """回傳 (age_text, style)。空字串若不適用。

    style 依新鮮度: ≤5m 綠、5-15m 黃、15-30m 灰 dim、>30m 紅 dim
    """
    if not trig_key or trig_key == 'none':
        return ('', 'dim')

    now = now or datetime.now()
    # Demo override: ticker 指定固定 age (分鐘)
    if ticker in _demo_trigger_age_override:
        age_min = _demo_trigger_age_override[ticker]
        t = now - timedelta(minutes=age_min)
    else:
        t = _trigger_fired_at.get((ticker, trig_key))
        if not t:
            return ('', 'dim')
        age_min = int((now - t).total_seconds() / 60)

    if age_min < 1:
        text = f' [{t.strftime("%H:%M")}, 剛剛]'
    elif age_min < 60:
        text = f' [{t.strftime("%H:%M")}, {age_min}分前]'
    else:
        text = f' [{t.strftime("%H:%M")}, {age_min // 60}h{age_min % 60}m前]'

    if age_min <= 5:
        style = 'bold green'
    elif age_min <= 15:
        style = 'yellow'
    elif age_min <= 30:
        style = 'dim'
    else:
        style = 'red dim'
    return (text, style)


def fmt_trigger_warning(trig_key: str, fire_time: datetime | None = None) -> str:
    """進場類 trigger 附加時段警示 + Win rate 提示文字。

    Args:
        trig_key:  trigger key (Ch5-3 / T1 / T2 / TC / …)
        fire_time: 觸發時間 (datetime)、None 則用 now

    Returns:
        時段警示字串、或空字串。
    """
    if trig_key not in ('首攻', '續攻', '反彈', 'Ch5-3', 'T1', 'T2'):
        return ''
    t = (fire_time or datetime.now()).time()
    from datetime import time as _time
    wd = WIN_RATE_BY_SESSION
    # 9:15-9:45 拉高出貨期
    if _time(9, 15) <= t < _time(9, 45):
        return (f' ⚠️ Win {wd["pump_dump"]}% (拉高出貨、等 9:45+ Win {wd["healthy"]}%、'
                f'等尾盤 Win {wd["closing"]}%)')
    # 9:45-13:00 健康/整理時段
    if _time(9, 45) <= t < _time(13, 0):
        return (f' Win {wd["healthy"]}% (等 13:00 尾盤可達 Win {wd["closing"]}%)')
    # 13:00-13:25 尾盤
    if _time(13, 0) <= t < _time(13, 25):
        return f' ⭐ Win {wd["closing"]}% (最佳進場時機)'
    return ''


def r_trigger(trig_key: str, reason: str = '', short: int = 40,
              ticker: str = '') -> Text:
    """Trigger label + reason + 觸發時間 + 時段警示 + Win rate、rich Text。

    ticker 給的話會附 [HH:MM, Nm前]、依新鮮度上色。
    進場類 trigger 附時段 Win rate 提示 (9:15-9:45/9:45-13:00/尾盤 3 段)。
    Closing_confirmed 加 ⭐ Win 80% 標記。
    """
    label = TRIGGER_DISPLAY.get(trig_key, '⚪ 無訊號')
    if trig_key in ('首攻', 'Ch5-3'):
        style = 'green'
    elif trig_key in ('首攻_signal', '首攻_pullback', 'Ch5-3_signal', 'Ch5-3_pullback'):
        style = 'yellow'
    elif trig_key in ('續攻', '反彈', 'T1', 'T2'):
        style = 'green'
    elif trig_key in ('破底', 'TC'):
        style = 'red'
    elif trig_key in ('續攻_watch', '反彈_watch', 'T1_watch', 'T2_watch'):
        style = 'yellow'
    elif trig_key in ('尾盤_confirmed', 'Closing_confirmed'):
        style = 'bold magenta'
    elif trig_key in ('尾盤_過熱', 'Closing_overheated'):
        style = 'bold red'
    elif trig_key in ('尾盤_watch', 'Closing_watch'):
        style = 'yellow'
    elif trig_key in ('尾盤_skip', 'Closing_skip'):
        style = 'red dim'
    else:
        style = 'dim'
    t = Text(label, style=style)
    if reason and trig_key != 'none' and trig_key is not None:
        t.append(f" ({reason[:short]})", style='dim')
    if ticker:
        age_text, age_style = fmt_trigger_age(ticker, trig_key)
        if age_text:
            t.append(age_text, style=age_style)
        # 時段警示 + Win rate 提示
        fire_t = _trigger_fired_at.get((ticker, trig_key))
        warn = fmt_trigger_warning(trig_key, fire_t)
        if warn:
            # 尾盤用 magenta bold、拉高出貨用 yellow bold、其他時段用 dim cyan
            if '⭐' in warn:
                t.append(warn, style='bold magenta')
            elif '⚠️' in warn:
                t.append(warn, style='bold yellow')
            else:
                t.append(warn, style='dim cyan')
    return t


def r_trigger_subrow(trig_key: str, reason: str = '', ticker: str = '',
                     now: datetime | None = None) -> Text:
    """第 2 行 trigger 顯示文字 (固定佔位、永遠回傳非空 Text)。

    亮度規則 (依「該行動」明確度):
      bold yellow — 有 confirmed trigger、非尾盤 → 強調「等 13:00」
      bold green  — 尾盤時段 + Closing confirmed → 強調「最佳進場」
      green       — 尾盤時段 + Closing watch (3-4/5) → 普通綠
      yellow      — 有 watch/signal trigger (T*_watch, Ch5-3_signal/pullback)
      red         — TC 結構壞、等修復
      dim         — 無訊號 / Closing_skip (純提示、不推銷 Win 80%)

    核心原則:
      - 「Win 80%」只在「有 confirmed + 需等到 13:00」場景出現
      - 無訊號 ≠ 該等 13:00 (純 dim 提示)
      - 強亮度 ∝ 該行動的明確度
    """
    now = now or datetime.now()
    from datetime import time as _time
    wd = WIN_RATE_BY_SESSION
    is_closing = _time(13, 0) <= now.time() < _time(13, 25)

    prefix = Text("└ ", style="dim")
    age_text, age_style = fmt_trigger_age(ticker, trig_key, now) if trig_key else ('', 'dim')

    # ── 1. 尾盤_confirmed / Closing_confirmed (3-4/5 Win 82%) → bold green ⭐ 最佳 ──
    if trig_key in ('尾盤_confirmed', 'Closing_confirmed'):
        # 加「剩 N 分到 13:25」截止提示
        remain_min = max(0, (13 * 60 + 25) - (now.hour * 60 + now.minute))
        remain_str = f"、剩 {remain_min} 分到 13:25" if remain_min > 0 else "、13:25 截止!"
        t = Text()
        t.append_text(prefix)
        t.append(f"🟢 ⭐ 尾盤 3-4/5 Win 82% (最佳進場{remain_str})", style="bold green")
        if age_text:
            t.append(age_text, style=age_style)
        return t

    # ── 1b. 尾盤_過熱 / Closing_overheated (5/5 Win 40%) → bold red 警示 ──
    if trig_key in ('尾盤_過熱', 'Closing_overheated'):
        t = Text()
        t.append_text(prefix)
        t.append("🔴 尾盤過熱 5/5 Win 40% (已被拉走、別追)", style="bold red")
        if age_text:
            t.append(age_text, style=age_style)
        return t

    # ── 2. 尾盤_watch / Closing_watch (legacy) → yellow 普通觀察 ─────────
    if trig_key in ('尾盤_watch', 'Closing_watch'):
        remain_min = max(0, (13 * 60 + 25) - (now.hour * 60 + now.minute))
        remain_str = f"、剩 {remain_min} 分到 13:25" if remain_min > 0 else "、13:25 截止!"
        t = Text()
        t.append_text(prefix)
        t.append(f"🟡 尾盤 watch (觀察{remain_str})", style="yellow")
        if age_text:
            t.append(age_text, style=age_style)
        return t

    # ── 3. 尾盤_skip / Closing_skip → dim、純提示 ─────────────────────────
    if trig_key in ('尾盤_skip', 'Closing_skip'):
        t = Text()
        t.append_text(prefix)
        t.append("⚪ 尾盤 <3/5 不進", style="dim")
        return t

    # ── 4. 破底 / TC 結構壞 → red ───────────────────────────────────────
    if trig_key in ('破底', 'TC'):
        t = Text()
        t.append_text(prefix)
        t.append("🔴 破底 結構壞、等修復", style="red")
        return t

    # ── 5. 無訊號 → dim、不推銷 Win 80% ──────────────────────────────────
    if not trig_key or trig_key in ('none', None):
        t = Text()
        t.append_text(prefix)
        if is_closing:
            t.append("⚪ 尾盤無訊號、不進", style="dim")
        else:
            t.append("⚪ 無訊號、待 13:00 評估", style="dim")
        return t

    # ── 6. 有 confirmed trigger (續攻/反彈/首攻 或舊英文名) ─────────────────
    label = TRIGGER_DISPLAY.get(trig_key, trig_key)

    if trig_key in ('首攻', '續攻', '反彈', 'T1', 'T2', 'Ch5-3'):
        if is_closing:
            # 尾盤 + confirmed trigger → bold green ⭐ 最佳進場
            t = Text()
            t.append_text(prefix)
            t.append(f"🟢 ⭐ 最佳進場 Win {wd['closing']}%", style="bold green")
            t.append(f" (現 {label}", style="dim")
            if age_text:
                t.append(age_text, style=age_style)
            t.append(")", style="dim")
            return t
        else:
            # 非尾盤 + confirmed trigger → bold yellow 強調「等 13:00」
            t_now = now.time()
            if _time(9, 15) <= t_now < _time(9, 45):
                cur_label = f"Win {wd['pump_dump']}% ⚠️ 拉高出貨"
            else:
                cur_label = f"Win {wd['healthy']}%"
            t = Text()
            t.append_text(prefix)
            t.append(f"⏱️ 等 13:00 Win {wd['closing']}%", style="bold yellow")
            t.append(f" (現 {label} {cur_label}", style="dim")
            if age_text:
                t.append(age_text, style=age_style)
            t.append(")", style="dim")
            return t

    # ── 7. watch 類 (T1_watch, T2_watch, Ch5-3_signal, Ch5-3_pullback) ──
    #     普通 yellow、不強調「等 80%」(因為尚未 confirm)
    #     label 已含 emoji (例: "🟡 T2 watch (等 9:45+)")、不再重複加
    t = Text()
    t.append_text(prefix)
    t.append(label, style="yellow")
    t.append(" (等確認後再評估)", style="dim")
    if age_text:
        t.append(age_text, style=age_style)
    return t


def r_change_pct(chg: float) -> Text:
    """漲跌幅 % 上色。"""
    style = 'red' if chg < 0 else 'green'
    return Text(f"{chg:+.1f}%", style=style)


# ─────────────────────────────────────────────────────────────────────────
# Aligned mini-table helper (per-ticker Group 方案)
# ─────────────────────────────────────────────────────────────────────────
# 每檔 ticker = 1 個 mini-table (固定 column widths) + 1 個 Text subrow
# 所有 mini-tables 用相同 widths → 視覺上對齊
# trigger 是獨立 Text (Padding 縮排)、不在 table 內、不必對齊
#
# 各區塊的 column spec (name, width, justify, no_wrap):

# 持倉表 (Phase 2 t_h)
COLS_HELD_P2 = [
    ("Stock",     14, "left",  True),
    ("開→現 (%)", 22, "left",  True),
    ("量比",       8, "left",  True),
    ("P&L",       16, "right", True),
    ("距停",       8, "right", True),
    ("狀",         3, "left",  True),
    ("Trigger",    0, "left",  False),
]

# 已持倉開盤健康度 (Phase 1 t_held)
COLS_HELD_P1 = [
    ("Lv",         4, "left",  True),
    ("Stock",     14, "left",  True),
    ("開→現 (%)", 22, "left",  True),
    ("量比",       8, "left",  True),
    ("入",         8, "right", True),
    ("P&L",       16, "right", True),
    ("停",         8, "right", True),
    ("開盤評語",  28, "left",  True),
    ("Trigger",    0, "left",  False),
]

# WATCH confirmed/watching: 同 HELD 風格、更豐富資訊
# - 策略 (戰術) / ⭐ / Ticker / Name 主資訊
# - 開→現 (%) / 量比 / 距 MA10 (健康度) / 距 ref (vs 加入監控時)
# - 族群 (sector)
COLS_WATCH_CONFIRMED = [
    ("策略",       6, "left",  True),
    ("",           6, "left",  True),
    ("Stock",     14, "left",  True),
    ("開→現 (%)", 22, "left",  True),
    ("量比",       8, "left",  True),
    ("距MA10",     8, "right", True),
    ("距ref",      8, "right", True),
    ("族群",      14, "left",  True),
    ("Trigger",    0, "left",  False),
]

COLS_WATCH_WATCHING = [
    ("策略",       6, "left",  True),
    ("",           6, "left",  True),
    ("Stock",     14, "left",  True),
    ("開→現 (%)", 22, "left",  True),
    ("量比",       8, "left",  True),
    ("距MA10",     8, "right", True),
    ("距ref",      8, "right", True),
    ("族群",      14, "left",  True),
    ("Trigger",    0, "left",  False),
]

# Phase 2 watchlist (非 status mode)
COLS_WATCH_P2 = [
    ("",           6, "left",  True),
    ("戰術",       6, "left",  True),
    ("Stock",     14, "left",  True),
    ("現",         8, "right", True),
    ("漲跌",       8, "right", True),
    ("量比",       8, "left",  True),
    ("距停",       8, "right", True),
    ("族群",      16, "left",  True),
    ("狀",         5, "left",  True),
    ("Trigger",    0, "left",  False),
]


def _mk_aligned_table(cols: list, show_header: bool) -> Table:
    """建固定 column widths 的 mini-table、所有 mini 共用同一份 spec → align。

    box=None 不畫邊框、padding=(0,1) 維持欄距、show_edge=False
    """
    t = Table(
        show_header=show_header,
        header_style="bold" if show_header else None,
        box=None,
        padding=(0, 1),
        show_edge=False,
        expand=False,
    )
    for name, width, justify, no_wrap in cols:
        kw = {"justify": justify, "no_wrap": no_wrap}
        if width:
            kw["width"] = width
        else:
            kw["overflow"] = "fold"  # auto width、容許折行
        t.add_column(name, **kw)
    return t


def _render_subrow(trig_key: str, trig_reason: str, ticker: str,
                   now: datetime | None = None) -> "Padding":
    """trigger 第 2 行、用 Padding 縮排對齊 mini-table 左側欄距。

    Padding(text, (top, right, bottom, left))
    """
    from rich.padding import Padding
    txt = r_trigger_subrow(trig_key, trig_reason, ticker=ticker, now=now)
    return Padding(txt, (0, 0, 0, 4))


def _mk_trigger_cell(trig_key: str, trig_reason: str,
                     exit_alert: str | None = None,
                     ticker: str | None = None,
                     current_price: float = 0.0,
                     held_shares: int = 0) -> Text:
    """Trigger 末欄 Text (單行、含出場提醒 + TRIGGER_DISPLAY + reason + live chip)。

    組成優先順序:
      1. 若有出場提醒 → 先顯示 (紅色強調)
      2. TRIGGER_DISPLAY[trig_key]
      3. trig_reason (dim)
      4. mk_chip_signal_text(ticker) 若有 ticker (live 計算、有才顯示)
      5. mk_sizing_suggestion(ticker, price, held) 若有 ticker + price (live 計算)
    若 trig_key 為 'none'/None 且無出場提醒 → dim '-'
    """
    t = Text()
    has_exit = bool(exit_alert)
    has_trig = trig_key and trig_key not in ('none', None)
    parts_added = False  # 追蹤是否已 append 任何東西、決定是否需要 "-"

    if has_exit:
        t.append(exit_alert, style="bold red")  # type: ignore[arg-type]
        parts_added = True

    if has_trig:
        if parts_added:
            t.append(" | ", style="dim")
        disp = TRIGGER_DISPLAY.get(trig_key, trig_key)
        t.append(disp)
        parts_added = True

    if trig_reason:
        if parts_added:
            t.append(" | ", style="dim")
        t.append(trig_reason, style="dim")
        parts_added = True

    # chip + sizing 即使沒 trigger 也要顯示 (live 計算、過門檻才顯示)
    if ticker:
        chip = mk_chip_signal_text(ticker)
        if chip:
            if parts_added:
                t.append(" | ", style="dim")
            t.append_text(chip)
            parts_added = True
        if current_price > 0:
            sizing = mk_sizing_suggestion(ticker, current_price, held_shares)
            if sizing:
                if parts_added:
                    t.append(" | ", style="dim")
                t.append_text(sizing)
                parts_added = True

    if not parts_added:
        t.append("-", style="dim")

    return t


# ─────────────────────────────────────────────────────────────────────────
# DB helper
# ─────────────────────────────────────────────────────────────────────────

def load_5d_avg_volume(ticker: str) -> float | None:
    """5d 平均日成交量 (張)。讀 standard_daily_bar 近 5 日 (排除今天)。

    cache: 同個 ticker 不重複查 DB。
    """
    cached = _avg_vol_cache.get(ticker)
    if cached is not None:
        return cached
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        rows = con.execute(
            "SELECT volume FROM standard_daily_bar "
            "WHERE ticker=? AND trade_date < date('now', 'localtime') "
            "ORDER BY trade_date DESC LIMIT 5",
            (ticker,)
        ).fetchall()
        con.close()
        if not rows:
            _avg_vol_cache[ticker] = None
            return None
        # DB volume 是股、轉張 (÷1000)
        vols_lots = [r[0] / 1000.0 for r in rows if r[0]]
        if not vols_lots:
            _avg_vol_cache[ticker] = None
            return None
        avg = sum(vols_lots) / len(vols_lots)
        _avg_vol_cache[ticker] = avg
        return avg
    except Exception:
        _avg_vol_cache[ticker] = None
        return None


# ─────────────────────────────────────────────────────────────────────────
# Live chip signal helper
# ─────────────────────────────────────────────────────────────────────────

_chip_cache: dict[str, "Text | None"] = {}


def mk_chip_signal_text(
    ticker: str,
    db_path: Path = DB,
    threshold_foreign: int = 3000,   # 張、外資 5d 累計顯示門檻
    threshold_sitc: int = 500,        # 張、投信 5d 累計顯示門檻
    days: int = 5,
) -> "Text | None":
    """從 institutional_investors 計算近 N 日累計籌碼、過門檻才回 Text、否則 None。

    單位: 張 (volume / 1000)。
    DB foreign_net / sitc_net 欄位已是「張」(FinMind institutional_investors)。
    """
    if ticker in _chip_cache:
        return _chip_cache[ticker]
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        rows = con.execute(
            "SELECT trade_date, foreign_net, sitc_net "
            "FROM institutional_investors "
            "WHERE ticker=? "
            "ORDER BY trade_date DESC LIMIT ?",
            (ticker, days),
        ).fetchall()
        con.close()
    except Exception:
        _chip_cache[ticker] = None
        return None

    if not rows:
        _chip_cache[ticker] = None
        return None

    foreign_sum = sum(r[1] or 0 for r in rows)
    sitc_sum    = sum(r[2] or 0 for r in rows)

    # 日期區間 stamp
    dates = sorted(r[0] for r in rows)
    date_start = dates[0][5:]   # MM-DD
    date_end   = dates[-1][5:]  # MM-DD

    foreign_over = abs(foreign_sum) >= threshold_foreign
    sitc_over    = abs(sitc_sum)    >= threshold_sitc

    if not foreign_over and not sitc_over:
        _chip_cache[ticker] = None
        return None

    def _fmt(val: float, unit_label: str) -> str:
        sign = '+' if val >= 0 else ''
        if abs(val) >= 1000:
            return f"{unit_label} {sign}{val/1000:.0f}k"
        return f"{unit_label} {sign}{val:.0f}張"

    parts: list[str] = []
    if foreign_over:
        parts.append(_fmt(foreign_sum, '外資'))
    if sitc_over:
        parts.append(_fmt(sitc_sum, '投信'))

    chip_str = ' + '.join(parts) + f" [{days}d: {date_start}~{date_end}]"
    result = Text(chip_str, style="cyan dim")
    _chip_cache[ticker] = result
    return result


# ─────────────────────────────────────────────────────────────────────────
# Live sizing suggestion helper
# ─────────────────────────────────────────────────────────────────────────

def mk_sizing_suggestion(
    ticker: str,
    current_price: float,
    held_shares: int = 0,
    target_water_pct: float = 20.0,   # 目標水位 (預設 1/5 = 20%)
    total_capital: float = 3_200_000,
) -> "Text | None":
    """依 sizing 規則 + 當前價 + 已持股、回傳建議加碼股數 Text、否則 None。

    目標股數 = total_capital * target_water_pct / 100 / current_price
    高價股 (> $600) 建議零股、細分到 100 股。
    低價股 (<= $300) 建議整張 (1000 股)。
    中間 ($300–$600) 建議 500 股 (半張)。
    """
    if not current_price or current_price <= 0:
        return None

    target_value  = total_capital * target_water_pct / 100
    target_shares = target_value / current_price

    if current_price > 600:
        unit = 100
    elif current_price <= 300:
        unit = 1000
    else:
        unit = 500

    # round down to nearest unit
    import math
    target_rounded = math.floor(target_shares / unit) * unit

    if target_rounded <= 0:
        return None

    if held_shares >= target_rounded:
        return Text(f"已達 {held_shares} 股水位、不加", style="dim")

    add_shares = target_rounded - held_shares
    add_lots   = add_shares / 1000
    cost_est   = add_shares * current_price

    if add_lots >= 1:
        lots_str = f"{add_lots:.0f}張 ({add_shares:,}股)"
    else:
        lots_str = f"{add_shares:,}股"

    result = Text(f"建議加 {lots_str} ≈${cost_est:,.0f}", style="yellow dim")
    return result


def _session_elapsed_ratio(now: datetime | None = None) -> float:
    """09:00-13:30 session 已過比例 (0.0 ~ 1.0)。盤前=0、盤後=1。"""
    now = now or datetime.now()
    h, m = now.hour, now.minute
    minutes = h * 60 + m
    open_min  = 9 * 60      # 540
    close_min = 13 * 60 + 30  # 810
    if minutes <= open_min:
        return 0.0
    if minutes >= close_min:
        return 1.0
    return (minutes - open_min) / (close_min - open_min)


def compute_vol_ratio(ticker: str, total_volume_lots: float | None,
                      now: datetime | None = None) -> float | None:
    """量比 = 今日截至現在累積量 / (5d 日均 × session 已過比例)。

    回 None 表示資料不夠 (盤前 / 無 DB 5d avg)。
    """
    if not total_volume_lots or total_volume_lots <= 0:
        return None
    elapsed = _session_elapsed_ratio(now)
    if elapsed <= 0:
        return None
    avg5d = load_5d_avg_volume(ticker)
    if not avg5d or avg5d <= 0:
        return None
    expected_so_far = avg5d * elapsed
    if expected_so_far <= 0:
        return None
    return total_volume_lots / expected_so_far


def fmt_vol_ratio(ratio: float | None) -> Text:
    """量比 → rich Text、依倍數上色 + emoji。"""
    if ratio is None:
        return Text("—", style="dim")
    if ratio >= 3.0:
        return Text(f"🚀 {ratio:.1f}x", style="bold red")
    if ratio >= 2.0:
        return Text(f"🟢 {ratio:.1f}x", style="bold green")
    if ratio >= 1.5:
        return Text(f"🟡 {ratio:.1f}x", style="yellow")
    if ratio >= 0.5:
        return Text(f"⚪ {ratio:.1f}x", style="dim")
    return Text(f"❄ {ratio:.1f}x", style="dim cyan")


class DataCache:
    """背景計算 + cache derived 資料 (trigger / vol_ratio)、render 純讀。

    用 monkey-patch 把 check_trigger_inline / compute_vol_ratio 改成讀 cache,
    所以既有 render 程式碼不用改、自然取到快取值 (背景 thread 更新)。
    """

    def __init__(self, tickers: list[str], client, tactic_map: dict[str, str]):
        self.tickers = list(tickers)
        self.client = client
        self.tactic_map = tactic_map  # ticker → tactic (for trigger category)
        self.triggers: dict[str, tuple[str, str]] = {}
        self.vol_ratios: dict[str, float | None] = {}
        self.lock = threading.Lock()
        self.last_refresh: float = 0.0
        self.errors: int = 0

    def refresh_all(self, real_check, real_vol):
        """單輪刷新所有 ticker (real_check / real_vol = 未 patch 的原函式)。"""
        for tk in self.tickers:
            try:
                tactic = self.tactic_map.get(tk, '核心')
                trig = real_check(tk, tactic)
                snap = self.client.get_realtime_snapshot(tk) or {}
                vol_lots = snap.get('total_volume')
                vr = real_vol(tk, float(vol_lots) if vol_lots else None)
                with self.lock:
                    self.triggers[tk] = trig
                    self.vol_ratios[tk] = vr
                # 偵測 trigger 切換、記第一次點亮時間
                record_trigger_fire(tk, trig[0] if trig else 'none')
            except Exception:
                self.errors += 1
        self.last_refresh = time.time()
        # 資料更新完、請求 redraw
        _render_request[0] = True

    def get_trigger(self, ticker: str) -> tuple[str, str]:
        with self.lock:
            return self.triggers.get(ticker, ('none', ''))

    def get_vol_ratio(self, ticker: str) -> float | None:
        with self.lock:
            return self.vol_ratios.get(ticker)


def _data_refresh_thread(cache: 'DataCache', real_check, real_vol, interval: float):
    """背景 thread: 每 interval 秒重算所有 ticker 的 trigger + vol_ratio。"""
    # 啟動立刻跑一輪
    cache.refresh_all(real_check, real_vol)
    while not _quit_flag[0]:
        end = time.time() + interval
        while time.time() < end and not _quit_flag[0]:
            time.sleep(0.2)
        if _quit_flag[0]:
            break
        cache.refresh_all(real_check, real_vol)


def fmt_open_to_now_pct(o: float, c: float) -> Text:
    """開→現 漲跌%、上色。0 = 灰 / +n = 綠 / -n = 紅。"""
    if not o or not c:
        return Text("", style="dim")
    pct = (c - o) / o * 100
    if abs(pct) < 0.05:
        return Text(" (0.0%)", style="dim")
    if pct > 0:
        return Text(f" (+{pct:.1f}%)", style="green")
    return Text(f" ({pct:.1f}%)", style="red")


def mk_open_to_now_cell(o: float, c: float) -> Text:
    """組「o → c (pct%)」cell。o 缺則顯示 c、皆缺顯 dim「—」。
    所有 table 共用 (HELD P1/P2、WATCH confirmed/watching)。
    """
    if o:
        cell = Text(f"{o:.1f}→{c:.1f}")
        cell.append_text(fmt_open_to_now_pct(o, c))
        return cell
    if c:
        return Text(f"{c:.1f}")
    return Text("—", style="dim")


_avg_vol_cache: dict[str, float | None] = {}
_ma10_cache: dict[str, float | None] = {}


def load_ma10(ticker: str) -> float | None:
    """MA10 close (排除今天)。讀 standard_daily_bar.ma10 欄位、cache."""
    if ticker in _ma10_cache:
        return _ma10_cache[ticker]
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        r = con.execute(
            "SELECT ma10 FROM standard_daily_bar "
            "WHERE ticker=? AND trade_date < date('now', 'localtime') "
            "ORDER BY trade_date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        con.close()
        val = float(r[0]) if r and r[0] else None
        _ma10_cache[ticker] = val
        return val
    except Exception:
        _ma10_cache[ticker] = None
        return None


def r_dist_ma10(c: float, ticker: str) -> Text:
    """距 MA10 % + 上色 (打擊區判斷):
       -3% ~ +5%: 綠 (打擊區)
       +5% ~ +10%: 黃 (偏遠)
       > +10%: 紅 dim (太遠、不追)
       < -3%: 紅 (跌深)
    """
    ma10 = load_ma10(ticker)
    if not ma10 or not c:
        return Text("—", style="dim")
    pct = (c - ma10) / ma10 * 100
    if -3 <= pct <= 5:
        return Text(f"{pct:+.1f}%", style="green")
    if 5 < pct <= 10:
        return Text(f"{pct:+.1f}%", style="yellow")
    if pct > 10:
        return Text(f"{pct:+.1f}%", style="red dim")
    return Text(f"{pct:+.1f}%", style="red")


def r_dist_ref(c: float, ref: float) -> Text:
    """距 ref_close (加入監控時的價) %、紅綠中性顯示。"""
    if not ref or not c:
        return Text("—", style="dim")
    pct = (c - ref) / ref * 100
    if pct >= 1:
        return Text(f"{pct:+.1f}%", style="green")
    if pct <= -1:
        return Text(f"{pct:+.1f}%", style="red")
    return Text(f"{pct:+.1f}%", style="dim")


def load_prev_close(ticker: str) -> float | None:
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        r = con.execute(
            "SELECT close FROM standard_daily_bar WHERE ticker=? ORDER BY trade_date DESC LIMIT 1",
            (ticker,)
        ).fetchone()
        con.close()
        return float(r[0]) if r else None
    except Exception:
        return None


def classify_open(open_price: float, prev_close: float) -> tuple[str, str, str]:
    """回 (level_emoji, msg, severity)."""
    if open_price <= 0 or prev_close <= 0:
        return ('?', '無資料', 'unknown')
    chg = (open_price - prev_close) / prev_close * 100
    if open_price >= prev_close * 1.095:
        return ('❌', f'接近漲停 ({chg:+.1f}%)、鎖死買不到', 'skip')
    if chg > 5.0:
        return ('❌', f'開盤 {chg:+.1f}% > +5% (紅線 #9)', 'skip')
    if chg > 3.0:
        return ('⚠️', f'開盤 {chg:+.1f}% (gap-up 警示)', 'warn')
    if chg >= 0:
        return ('✅', f'開盤 {chg:+.1f}% (穩定強、可進)', 'ok')
    if chg >= -3.0:
        return ('🟡', f'開盤 {chg:+.1f}% (小弱)', 'neutral')
    return ('🔴', f'開盤 {chg:+.1f}% (顯著弱、慎入)', 'weak')


# ─────────────────────────────────────────────────────────────────────────
# Trigger 欄位 格式化
# ─────────────────────────────────────────────────────────────────────────

def fmt_trigger(trig_key: str, reason: str = '') -> str:
    label = TRIGGER_DISPLAY.get(trig_key, '⚪ 無訊號')
    short = reason[:40] if reason else ''
    if trig_key in ('首攻', 'Ch5-3'):
        return f"{C.G}{label}{C.END}" + (f" {C.DIM}({short}){C.END}" if short else '')
    if trig_key in ('首攻_signal', '首攻_pullback', 'Ch5-3_signal', 'Ch5-3_pullback'):
        return f"{C.Y}{label}{C.END}" + (f" {C.DIM}({short}){C.END}" if short else '')
    if trig_key in ('續攻', '反彈', 'T1', 'T2'):
        return f"{C.G}{label}{C.END}" + (f" {C.DIM}({short}){C.END}" if short else '')
    if trig_key in ('破底', 'TC'):
        return f"{C.R}{label}{C.END}" + (f" {C.DIM}({short[:40]}){C.END}" if reason else '')
    if trig_key in ('反彈_watch', 'T2_watch'):
        return f"{C.Y}{label}{C.END}" + (f" {C.DIM}({reason[:30]}){C.END}" if reason else '')
    return f"{C.DIM}{label}{C.END}"


# ─────────────────────────────────────────────────────────────────────────
# Priority panel summary
# ─────────────────────────────────────────────────────────────────────────

def render_priority_panel(held: list[dict], watch: list[dict],
                          live_data: dict) -> Table:
    """高/中/低優先級摘要 panel — rich.Table (3 列)。"""
    def group(items):
        p3 = [x for x in items if x.get('priority', 2) == 3]
        p2 = [x for x in items if x.get('priority', 2) == 2]
        p1 = [x for x in items if x.get('priority', 2) == 1]
        return p3, p2, p1

    held_p3, held_p2, held_p1 = group(held)
    watch_p3, watch_p2, watch_p1 = group(watch)

    triggered_map: dict[str, str] = {}
    for x in held + watch:
        tk = x.get('ticker', '')
        trig = live_data.get(tk, {}).get('trigger', 'none')
        if trig in ('續攻', '反彈', '破底', 'T1', 'T2', 'TC'):
            triggered_map[tk] = trig

    warnings: list[str] = []
    for x in held:
        tk = x.get('ticker', '')
        dist = live_data.get(tk, {}).get('dist_to_stop', 999)
        if dist < 1:
            warnings.append(f"{tk}({dist:+.1f}%)")

    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1), expand=False)
    table.add_column("優先級", style="bold", no_wrap=True)
    table.add_column("數", justify="right", no_wrap=True)
    table.add_column("持倉", no_wrap=False)
    table.add_column("候選/觀察", no_wrap=False)
    table.add_column("Trigger/警示", no_wrap=False)

    def _row(label: str, h_list: list, w_list: list):
        all_list = h_list + w_list
        if not all_list:
            return
        h_tks = [x['ticker'] for x in h_list]
        w_tks = [x['ticker'] for x in w_list]
        all_tks = h_tks + w_tks
        trig_info = [f"{tk}({triggered_map[tk]})" for tk in all_tks if tk in triggered_map]
        warn_info = [w for w in warnings if any(w.startswith(x['ticker']) for x in h_list)]
        right = Text()
        if trig_info:
            right.append("🟢 " + "/".join(trig_info), style="green")
        if warn_info:
            if trig_info:
                right.append("  ")
            right.append("⚠️ " + ",".join(warn_info), style="red")
        table.add_row(
            label,
            str(len(all_list)),
            "/".join(h_tks),
            "/".join(w_tks),
            right,
        )

    _row("🎯 P3", held_p3, watch_p3)
    _row("⚠️  P2", held_p2, watch_p2)
    _row("🟢 P1", held_p1, watch_p1)
    return table


# ─────────────────────────────────────────────────────────────────────────
# Phase 1: 開盤 Entry Screening
# ─────────────────────────────────────────────────────────────────────────

def render_phase1_screener(client, now_str: str, sort_mode: str,
                           do_notify: bool) -> Group:
    """Phase 1 開盤 entry screening (9:00-9:25)、回傳 rich Group。"""
    held   = _normalize_held(HELD)
    plan   = _normalize_plan(PLAN_PRIMARY)
    backup = _normalize_plan(PLAN_BACKUP)

    # --- collect live data including triggers ---
    live_data: dict = {}
    for item in held + plan:
        tk = item.get('ticker', '')
        try:
            snap = client.get_realtime_snapshot(tk) or {}
            c = float(snap.get('close') or 0)
            entry = item.get('cost') or 0
            stop  = item.get('stop')  or 0
            pnl_pct = (c - entry)/entry*100 if entry and c else 0
            dist    = (c - stop)/c*100 if c and stop else 999
            trig_key, trig_reason = check_trigger_inline(tk, item.get('tactic', '核心'))
            maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
            live_data[tk] = {
                'c': c, 'pnl_pct': pnl_pct, 'dist_to_stop': dist,
                'trigger': trig_key, 'trigger_reason': trig_reason,
            }
        except Exception:
            live_data[tk] = {}

    watch_norm = _normalize_watch(WATCH)

    renderables: list = []
    # Priority panel
    renderables.append(render_priority_panel(held, watch_norm, live_data))

    # 已持倉開盤健康度 — per-ticker Group (固定 widths)
    if held:
        sorted_held = sort_items(held, sort_mode, live_data)
        t_held = _mk_aligned_table(COLS_HELD_P1, show_header=True)
        for item in sorted_held:
            tk     = item['ticker']
            name   = item['name']
            entry  = item.get('cost', 0)
            shares = item.get('shares', 0)
            stop   = item.get('stop', 0)
            d      = live_data.get(tk, {})
            trig_key    = d.get('trigger', 'none')
            trig_reason = d.get('trigger_reason', '')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                o    = float(snap.get('open') or 0)
                c    = float(snap.get('close') or 0)
                prev = load_prev_close(tk)
                level, msg, _sev = classify_open(o, prev) if prev else ('?', '無前收', 'unknown')
                entry_vs_open = (entry - o)/o*100 if o else 0
                if entry_vs_open < -1:
                    entry_tag = Text(f"🎯 進得好 ({entry_vs_open:.1f}%)", style="green")
                elif entry_vs_open > 1:
                    entry_tag = Text(f"⚠️ 追高 ({entry_vs_open:+.1f}%)", style="yellow")
                else:
                    entry_tag = Text("入價貼開盤", style="dim")
                pnl = (c - entry)*shares
                pnl_pct = (c - entry)/entry*100 if entry else 0
                opening_comment = Text()
                opening_comment.append(msg, style="dim")
                opening_comment.append(" | ")
                opening_comment.append_text(entry_tag)
                vol_lots = snap.get('total_volume')
                vol_ratio = compute_vol_ratio(tk, float(vol_lots) if vol_lots else None)
                t_held.add_row(
                    level, f"{tk} {name}",
                    mk_open_to_now_cell(o, c),
                    fmt_vol_ratio(vol_ratio),
                    f"{entry:.1f}",
                    r_pnl(pnl, pnl_pct),
                    f"{stop}",
                    opening_comment,
                    _mk_trigger_cell(trig_key, trig_reason,
                                     ticker=tk, current_price=c, held_shares=shares),
                )
            except Exception as e:
                t_held.add_row("?", f"{tk} {name}", "err", "", "", Text(str(e), style="red"), "", "", "")
        renderables.append(Group(Text("📊 已持倉開盤健康度", style="bold"), t_held))

    # 待進場主候選
    if plan:
        t_plan = Table(
            title="🎯 待進場主候選",
            title_style="bold",
            box=box.SIMPLE,
            expand=True,
        )
        t_plan.add_column("Lv", no_wrap=True)
        t_plan.add_column("", no_wrap=True)
        t_plan.add_column("Stock", no_wrap=True)
        t_plan.add_column("前→開 (%) →現 (%)", no_wrap=True)
        t_plan.add_column("量比", no_wrap=True)
        t_plan.add_column("停", justify="right", no_wrap=True)
        t_plan.add_column("Sizing", no_wrap=True)
        t_plan.add_column("Trigger / 評語 / reason")

        skipped = []
        for item in sort_items(plan, sort_mode, live_data):
            tk     = item['ticker']
            name   = item['name']
            shares = item.get('shares', 0)
            stop   = item.get('stop', 0)
            reason = item.get('reason') or item.get('note', '')
            pri    = item.get('priority', 2)
            d      = live_data.get(tk, {})
            trig_key    = d.get('trigger', 'none')
            trig_reason = d.get('trigger_reason', '')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                o    = float(snap.get('open') or 0)
                c    = float(snap.get('close') or 0)
                prev = load_prev_close(tk)
                level, msg, sev = classify_open(o, prev) if prev else ('?', '無前收', 'unknown')
                chg_open = (o - prev)/prev*100 if prev else 0
                cost = o * shares
                detail = Text()
                detail.append_text(r_trigger(trig_key, trig_reason, short=25, ticker=tk))
                detail.append("  ")
                detail.append(msg, style="dim")
                if reason:
                    detail.append(" | ")
                    detail.append(reason[:50], style="dim")
                vol_lots = snap.get('total_volume')
                vol_ratio = compute_vol_ratio(tk, float(vol_lots) if vol_lots else None)
                # 前→開 (跳空%) →現 (盤中%)
                chg_pct_str = Text(f"{prev or 0:.1f}→{o:.1f} ")
                if chg_open > 0:
                    chg_pct_str.append(f"({chg_open:+.1f}%)", style="green")
                elif chg_open < 0:
                    chg_pct_str.append(f"({chg_open:+.1f}%)", style="red")
                else:
                    chg_pct_str.append("(0.0%)", style="dim")
                chg_pct_str.append(f" →{c:.1f}")
                chg_pct_str.append_text(fmt_open_to_now_pct(o, c))
                t_plan.add_row(
                    level,
                    stars(pri),
                    f"{tk} {name}",
                    chg_pct_str,
                    fmt_vol_ratio(vol_ratio),
                    f"{stop}",
                    f"{shares}股 ${cost:,.0f}",
                    detail,
                )
                if sev in ('skip', 'warn'):
                    skipped.append(tk)
            except Exception as e:
                t_plan.add_row("?", "", f"{tk} {name}", "err", "", "", "", Text(str(e), style="red"))
        renderables.append(t_plan)

        # 備案推薦
        if skipped and backup:
            sev_order = {'ok': 0, 'neutral': 1, 'warn': 2, 'weak': 3, 'skip': 4, 'unknown': 5}
            backup_evaluated = []
            for item in backup:
                tk     = item['ticker']
                name   = item['name']
                shares = item.get('shares', 0)
                stop   = item.get('stop', 0)
                reason = item.get('reason') or item.get('note', '')
                try:
                    snap = client.get_realtime_snapshot(tk) or {}
                    o    = float(snap.get('open') or 0)
                    c    = float(snap.get('close') or 0)
                    prev = load_prev_close(tk)
                    level, msg, sev = classify_open(o, prev) if prev else ('?', 'no prev', 'unknown')
                    chg_open = (o-prev)/prev*100 if prev else 0
                    backup_evaluated.append(
                        (sev, -chg_open, tk, name, shares, prev, o, c, level, msg, reason, stop)
                    )
                except Exception:
                    pass
            backup_evaluated.sort(key=lambda x: (sev_order.get(x[0], 9), x[1]))
            t_bk = Table(
                title=f"⚠️  {len(skipped)} 主候選 skip / 備案推薦",
                title_style="bold yellow",
                box=box.SIMPLE,
                expand=True,
            )
            t_bk.add_column("Lv")
            t_bk.add_column("Stock")
            t_bk.add_column("前→開 (%) →現 (%)")
            t_bk.add_column("停", justify="right")
            t_bk.add_column("Sizing")
            t_bk.add_column("評語")
            for bitem in backup_evaluated[:3]:
                sev, _, tk, name, shares, prev, o, c, level, msg, reason, stop = bitem
                chg_open = (o - (prev or 1))/(prev or 1)*100
                cost = o * shares
                bk_str = Text(f"{prev or 0:.1f}→{o:.1f} ")
                if chg_open > 0:
                    bk_str.append(f"({chg_open:+.1f}%)", style="green")
                elif chg_open < 0:
                    bk_str.append(f"({chg_open:+.1f}%)", style="red")
                else:
                    bk_str.append("(0.0%)", style="dim")
                bk_str.append(f" →{c:.1f}")
                bk_str.append_text(fmt_open_to_now_pct(o, c))
                t_bk.add_row(
                    level, f"{tk} {name}",
                    bk_str,
                    f"{stop}",
                    f"{shares}股 ${cost:,.0f}",
                    Text(f"{msg} | {reason[:40]}", style="dim"),
                )
            renderables.append(t_bk)
        elif not skipped:
            renderables.append(Text("✅ 主候選全部 OK、無需備案", style="green"))
    elif not held:
        renderables.append(Text("PLAN_PRIMARY 空、編輯腳本開頭設定", style="dim"))

    # Phase 1: WATCH 分段 (status mode 才顯示、避免干擾 entry focus)
    if sort_mode == 'status' and watch_norm:
        watch_live: dict = {}
        for item in watch_norm:
            tk     = item['ticker']
            tactic = item.get('tactic', '短打')
            ref    = item.get('ref_close') or 0
            stop   = item.get('stop')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                c = float(snap.get('close') or 0) or (load_prev_close(tk) or ref)
                chg = (c - ref)/ref*100 if ref else 0
                dist = (c - stop)/c*100 if (c and stop) else 999
                trig_key, trig_reason = check_trigger_inline(tk, tactic)
                maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
                vol_lots = snap.get('total_volume')
                vol_ratio = compute_vol_ratio(tk, float(vol_lots) if vol_lots else None)
                watch_live[tk] = {
                    'c': c, 'pnl_pct': chg, 'dist_to_stop': dist,
                    'trigger': trig_key, 'trigger_reason': trig_reason,
                    'vol_ratio': vol_ratio,
                }
            except Exception:
                watch_live[tk] = {}

        confirmed_p1, watching_p1 = [], []
        for item in watch_norm:
            tk = item['ticker']
            d  = watch_live.get(tk, {})
            bucket = _classify_watch_item(item, d)
            if bucket == 'confirmed':
                confirmed_p1.append((item, d))
            elif bucket == 'watching':
                watching_p1.append((item, d))
        confirmed_p1.sort(key=lambda x: (
            -x[0].get('priority', 1),
            TRIGGER_RANK.get(x[1].get('trigger', 'none'), 6),
        ))
        watching_p1.sort(key=lambda x: -x[0].get('priority', 1))

        if confirmed_p1:
            t_wc = Table(title="🎯 WATCH 可進場 (confirmed)",
                         title_style="bold green", box=box.SIMPLE, expand=True)
            t_wc.add_column(""); t_wc.add_column("Stock")
            t_wc.add_column("現", justify="right")
            t_wc.add_column("Trigger")
            for item, d in confirmed_p1:
                trig = d.get('trigger', 'none'); reason = d.get('trigger_reason', '')
                c = d.get('c', 0); pri = item.get('priority', 1)
                t_wc.add_row(
                    stars(pri), f"{item['ticker']} {item['name']}",
                    f"{c:.1f}" if c else "—",
                    r_trigger(trig, reason, short=50, ticker=item['ticker']),
                )
            renderables.append(t_wc)

        if watching_p1:
            t_ww = Table(title="🔍 WATCH 觀察中",
                         title_style="bold", box=box.SIMPLE, expand=True)
            t_ww.add_column(""); t_ww.add_column("Stock")
            t_ww.add_column("現", justify="right")
            t_ww.add_column("Note")
            for item, d in watching_p1:
                c = d.get('c', 0); pri = item.get('priority', 1)
                t_ww.add_row(
                    stars(pri), f"{item['ticker']} {item['name']}",
                    f"{c:.1f}" if c else "—",
                    Text(item.get('note', '')[:60], style="dim"),
                )
            renderables.append(t_ww)

    panel = Panel(
        Group(*renderables),
        title=f"PHASE 1: 開盤 ENTRY SCREENING  {now_str}  (排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)})",
        border_style="cyan",
    )
    return Group(panel)


# ─────────────────────────────────────────────────────────────────────────
# WATCH 3-section 分類邏輯
# ─────────────────────────────────────────────────────────────────────────

def _classify_watch_source(item: dict) -> str:
    """依 source 欄位分 4 類 (給 WATCH watching 段分組顯示)。"""
    src = (item.get('source') or '').lower()
    if '老師' in (item.get('source') or '') or 'teacher' in src:
        return '🎓 老師明示'
    if 'shakeout' in src:
        return '💥 Shakeout 補進'
    if 'scanner' in src or '框架' in (item.get('source') or '') or '處置' in (item.get('source') or ''):
        return '🔍 Scanner 命中'
    if '自' in (item.get('source') or '') or '消息' in (item.get('source') or ''):
        return '🙋 自選'
    return '📌 其他'


def _classify_watch_item(item: dict, d: dict) -> str:
    """依 composite_check 結果分流: confirmed / watching / excluded."""
    trig_key = d.get('trigger', 'none')
    pri      = item.get('priority', 1)

    if trig_key in ('T1', 'T2', 'Ch5-3'):
        return 'confirmed'
    if trig_key == 'TC':
        return 'excluded'
    if trig_key in ('T1_watch', 'T2_watch'):
        return 'watching'
    # 無訊號: 依 priority 分
    if pri >= 2:
        return 'watching'
    return 'excluded'


def _pre_market_mode() -> bool:
    now = datetime.now()
    return not ((now.hour, now.minute) >= (9, 0))


def render_watch_sectioned(
    watch_enriched: list[dict],
    live_data: dict,
    sort_mode: str,
) -> list:
    """WATCH 分 3 段顯示 (status mode)、回傳 rich renderables list。"""
    confirmed: list[tuple] = []
    watching:  list[tuple] = []
    excluded:  list[tuple] = []

    pre_mkt = _pre_market_mode()

    for item in watch_enriched:
        tk = item['ticker']
        d  = live_data.get(tk, {})
        bucket = _classify_watch_item(item, d)
        if bucket == 'confirmed':
            confirmed.append((item, d))
        elif bucket == 'watching':
            watching.append((item, d))
        else:
            excluded.append((item, d))

    confirmed.sort(key=lambda x: (
        -x[0].get('priority', 1),
        TRIGGER_RANK.get(x[1].get('trigger', 'none'), 6),
    ))
    watching.sort(key=lambda x: -x[0].get('priority', 1))
    excluded.sort(key=lambda x: -x[0].get('priority', 1))

    out: list = []

    if pre_mkt:
        out.append(Text("⏳ 開盤前、5K 累積中 — Trigger 判定尚未啟動", style="dim"))

    # --watch-min-priority 過濾 watching (confirmed 永遠顯示、不過濾)
    min_pri = _watch_min_priority[0]
    pre_filter_count = len(watching)
    watching = [(it, d) for (it, d) in watching if it.get('priority', 1) >= min_pri]
    filtered_out = pre_filter_count - len(watching)

    if pre_mkt:
        excluded_count = len(excluded)
        excluded = []  # 開盤前不顯示排除清單、開盤後再判
        if excluded_count or filtered_out:
            hidden = excluded_count + filtered_out
            out.append(Text(f"({hidden} 檔低優先/排除暫不顯示)", style="dim"))
    elif filtered_out:
        out.append(Text(f"({filtered_out} 檔 priority < {min_pri} 過濾)", style="dim"))

    # --watch-limit = 每分類最多顯示行數 (confirmed/excluded 不受限、0 = 全顯)
    limit = _watch_limit[0]
    watching_total = len(watching)

    if confirmed:
        # confirmed: 單一 Table、所有 row 共用 COLS_WATCH_CONFIRMED
        t_confirmed = _mk_aligned_table(COLS_WATCH_CONFIRMED, show_header=True)
        for item, d in confirmed:
            tk = item['ticker']
            pri = item.get('priority', 1)
            tactic = item.get('tactic', '短打')
            trig = d.get('trigger', 'none'); reason = d.get('trigger_reason', '')
            c = d.get('c', 0)
            o = d.get('o', 0)
            ref = item.get('ref_close') or 0
            open_cell = mk_open_to_now_cell(o, c)
            t_confirmed.add_row(
                Text(tactic, style="dim"),
                stars(pri), f"{tk} {item['name']}",
                open_cell,
                fmt_vol_ratio(d.get('vol_ratio')),
                r_dist_ma10(c, tk),
                r_dist_ref(c, ref),
                Text(item.get('sector', '?'), style="dim"),
                _mk_trigger_cell(trig, reason, ticker=tk, current_price=c),
            )
        out.append(Group(Text("🎯 WATCH 可進場 (confirmed)", style="bold green"), t_confirmed))

    if watching:
        # 依 source 關鍵字分類
        groups: dict[str, list] = {}
        for item, d in watching:
            cat = _classify_watch_source(item)
            groups.setdefault(cat, []).append((item, d))
        # 顯示順序、所有分類統一規則 (每類最多 limit 檔)
        order = ['🎓 老師明示', '💥 Shakeout 補進', '🔍 Scanner 命中',
                 '🙋 自選', '📌 其他']
        out.append(Text(f"🔍 WATCH 觀察可能 (共 {watching_total} 檔、分類顯示)",
                        style="bold"))
        for cat in order:
            items = groups.get(cat, [])
            if not items:
                continue
            cat_total = len(items)
            if limit == 0:
                shown = items
                title = f"{cat} ({cat_total} 檔、全顯)"
            elif cat_total > limit:
                shown = items[:limit]
                hidden = cat_total - limit
                title = f"{cat} ({cat_total} 檔、顯示前 {limit}、{hidden} 檔暫不顯、按 0 全顯)"
            else:
                shown = items
                title = f"{cat} ({cat_total} 檔)"
            # watching: 單一 Table per cat、所有 row 共用 COLS_WATCH_WATCHING
            t_watching = _mk_aligned_table(COLS_WATCH_WATCHING, show_header=True)
            for item, d in shown:
                tk = item['ticker']
                pri = item.get('priority', 1)
                tactic = item.get('tactic', '短打')
                trig = d.get('trigger', 'none')
                reason = d.get('trigger_reason', '')
                c = d.get('c', 0)
                o = d.get('o', 0)
                ref = item.get('ref_close') or 0
                open_cell = mk_open_to_now_cell(o, c)
                t_watching.add_row(
                    Text(tactic, style="dim"),
                    stars(pri), f"{tk} {item['name']}",
                    open_cell,
                    fmt_vol_ratio(d.get('vol_ratio')),
                    r_dist_ma10(c, tk),
                    r_dist_ref(c, ref),
                    Text(item.get('sector', '?'), style="dim"),
                    _mk_trigger_cell(trig, reason, ticker=tk, current_price=c),
                )
            out.append(Group(Text(title, style="bold"), t_watching))
        if limit > 0:
            out.append(Text(
                f"(按 0 = 全顯所有檔、+/- 調 limit、目前 limit={limit}/分類)",
                style="dim",
            ))

    if excluded:
        t = Table(title="⛔ WATCH 排除/低優先",
                  title_style="dim", box=box.SIMPLE, expand=True)
        t.add_column("Stock"); t.add_column("原因")
        for item, d in excluded:
            trig = d.get('trigger', 'none')
            reason_s = ''
            if trig == 'TC':
                reason_s = 'TC 結構壞'
            elif item.get('note', '').startswith('🔴'):
                reason_s = item['note'][:30]
            elif item.get('priority', 1) == 1:
                reason_s = '低優先'
            t.add_row(f"{item['ticker']} {item['name']}", Text(reason_s, style="dim"))
        out.append(t)

    return out


# ─────────────────────────────────────────────────────────────────────────
# Phase 2: 持倉 P&L 監控
# ─────────────────────────────────────────────────────────────────────────

def render_phase2_holdings(client, now_str: str, prev_prices: dict,
                           notified: set, sort_mode: str,
                           do_notify: bool) -> Group:
    """Phase 2 持倉 P&L 監控 (9:25 後)、回傳 rich Group。"""
    held  = _normalize_held(HELD)
    watch = _normalize_watch(WATCH)

    from datetime import datetime as _dt
    _now = _dt.now()
    _market_open = (_now.hour, _now.minute) >= (9, 0) and (_now.hour, _now.minute) < (13, 30)

    live_data: dict = {}
    total_pnl = 0.0
    held_enriched: list[dict] = []

    for item in held:
        tk     = item['ticker']
        entry  = item['cost']
        shares = item['shares']
        stop   = item['stop']
        tactic = item.get('tactic', '核心')
        try:
            snap = client.get_realtime_snapshot(tk)
            no_data = snap is None or not snap.get('close')
            if no_data:
                c = load_prev_close(tk) or entry
            else:
                c = float(snap['close'])
            prev_prices[tk] = c
            pnl     = (c - entry) * shares
            pnl_pct = (c - entry)/entry*100 if entry else 0
            dist    = (c - stop)/c*100 if c else 0
            if not no_data:
                total_pnl += pnl
            trig_key, trig_reason = check_trigger_inline(tk, tactic)
            maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
            live_data[tk] = {
                'c': c, 'pnl': pnl, 'pnl_pct': pnl_pct,
                'dist_to_stop': dist, 'no_data': no_data,
                'trigger': trig_key, 'trigger_reason': trig_reason,
            }
            held_enriched.append(item)
        except Exception as e:
            live_data[tk] = {'error': str(e)}
            held_enriched.append(item)

    renderables: list = []
    renderables.append(render_priority_panel(held_enriched, watch, live_data))

    if not held_enriched:
        renderables.append(Text("未進場、無持倉監控", style="dim"))
    else:
        # 持倉表: 單一 Table、所有 row 共用 COLS_HELD_P2、Rich 自動對齊
        _now_render = datetime.now()
        t_held_p2 = _mk_aligned_table(COLS_HELD_P2, show_header=True)
        sorted_held = sort_items(held_enriched, sort_mode, live_data)
        for item in sorted_held:
            tk     = item['ticker']
            name   = item['name']
            entry  = item['cost']
            stop   = item['stop']
            d = live_data.get(tk, {})

            if 'error' in d:
                t_held_p2.add_row(
                    f"{tk} {name}",
                    Text(f"err {d['error']}", style="red"),
                    "", "", "", "?",
                    Text("└ ⚠️ 無法取得資料", style="dim"))
                continue

            c        = d.get('c', entry)
            pnl      = d.get('pnl', 0)
            pnl_pct  = d.get('pnl_pct', 0)
            dist     = d.get('dist_to_stop', 0)
            no_data  = d.get('no_data', False)
            trig_key    = d.get('trigger', 'none')
            trig_reason = d.get('trigger_reason', '')

            # 停損 alert
            key = f"{tk}_break"
            if dist < 0:
                if key not in notified:
                    notified.add(key)
                    notify_mac(f"🚨 {tk} {name} 跌破停損 ${stop}",
                               f"現 ${c:.1f}、損 ${pnl:,.0f}")
            else:
                notified.discard(key)

            # 策略出場提醒 (intraday / overnight)
            exit_alert_msg = check_strategy_exit_alert(item, _now_render)
            if exit_alert_msg and do_notify:
                exit_key = f"{tk}_exit_{get_strategy_mode(item)}"
                if exit_key not in notified:
                    notified.add(exit_key)
                    notify_mac(exit_alert_msg, f"{tk} {name} 現 ${c:.1f}")

            stop_tag = '🔴' if dist < 0 else ('⚠️' if dist < 1 else '🟢')
            snap2 = client.get_realtime_snapshot(tk) or {}
            o = float(snap2.get('open') or 0)
            vol_lots = snap2.get('total_volume')
            vol_ratio = compute_vol_ratio(tk, float(vol_lots) if vol_lots else None)
            if no_data:
                open_cell = Text(f"昨{c:.1f}", style="dim")
            else:
                open_cell = mk_open_to_now_cell(o, c)
            shares_held = item.get('shares', 0)
            t_held_p2.add_row(
                f"{tk} {name}",
                open_cell,
                fmt_vol_ratio(vol_ratio),
                r_pnl(pnl, pnl_pct),
                r_dist(dist),
                stop_tag,
                _mk_trigger_cell(trig_key, trig_reason, exit_alert_msg,
                                 ticker=tk, current_price=c, held_shares=shares_held),
            )
        renderables.append(Group(Text("📊 持倉", style="bold"), t_held_p2))

    today = total_pnl + REALIZED
    summary = Text()
    summary.append("帳面 ")
    summary.append_text(r_pnl(total_pnl))
    summary.append(" | 已實現 ")
    summary.append_text(r_pnl(REALIZED))
    summary.append(" | 💰 今日 ")
    summary.append_text(r_pnl(today))
    renderables.append(summary)

    # Watchlist
    if watch:
        watch_enriched = []
        for item in watch:
            tk   = item['ticker']
            ref  = item.get('ref_close') or 0
            stop = item.get('stop')
            tactic = item.get('tactic', '短打')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                c = float(snap.get('close') or 0)
                o = float(snap.get('open') or 0)
                pre = False
                if c == 0:
                    c = load_prev_close(tk) or ref
                    pre = True
                # 漲跌計算優先用 snapshot.change_rate (WS/REST 已基於真實前收計算)
                # 否則 fallback ref_close 或 DB prev (DB 可能含今日 bar、會 = c → 0%)
                snap_chg = snap.get('change_rate')
                if snap_chg is not None:
                    try:
                        chg = float(snap_chg)
                    except Exception:
                        chg = 0
                else:
                    if not ref:
                        ref = load_prev_close(tk) or 0
                    chg = (c - ref)/ref*100 if ref else 0
                dist = (c - stop)/c*100 if (c and stop) else 999
                trig_key, trig_reason = check_trigger_inline(tk, tactic)
                maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
                vol_lots = snap.get('total_volume')
                vol_ratio = compute_vol_ratio(tk, float(vol_lots) if vol_lots else None)
                live_data[tk] = {
                    'c': c, 'o': o, 'pnl_pct': chg, 'dist_to_stop': dist,
                    'pre': pre, 'trigger': trig_key, 'trigger_reason': trig_reason,
                    'vol_ratio': vol_ratio,
                }
            except Exception:
                live_data[tk] = {}
            watch_enriched.append(item)

        if sort_mode == 'status':
            renderables.extend(render_watch_sectioned(watch_enriched, live_data, sort_mode))
        else:
            # Watchlist: 單一 Table、所有 row 共用 COLS_WATCH_P2
            t_watch_p2 = _mk_aligned_table(COLS_WATCH_P2, show_header=True)
            sorted_watch = sort_items(watch_enriched, sort_mode, live_data)
            for item in sorted_watch:
                tk     = item['ticker']
                name   = item['name']
                ref    = item.get('ref_close') or 0
                stop   = item.get('stop')
                pri    = item.get('priority', 2)
                tactic = item.get('tactic', '—')
                sector = item.get('sector', '?')
                d = live_data.get(tk, {})
                c    = d.get('c', ref)
                chg  = d.get('pnl_pct', 0)
                dist = d.get('dist_to_stop', 999)
                pre  = d.get('pre', True)
                trig_key    = d.get('trigger', 'none')
                trig_reason = d.get('trigger_reason', '')
                wall_tag = '盤前' if pre else ('🔴' if (stop and dist < 0) else '🟡')
                snap_w = client.get_realtime_snapshot(tk) or {}
                vol_lots = snap_w.get('total_volume')
                vol_ratio = compute_vol_ratio(tk, float(vol_lots) if vol_lots else None)
                t_watch_p2.add_row(
                    stars(pri), tactic, f"{tk} {name}",
                    f"{c:.1f}" if c else "—",
                    r_change_pct(chg),
                    fmt_vol_ratio(vol_ratio),
                    r_dist(dist),
                    sector,
                    wall_tag,
                    _mk_trigger_cell(trig_key, trig_reason, ticker=tk, current_price=c),
                )
            renderables.append(Group(
                Text(f"Watchlist (排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)})", style="dim"),
                t_watch_p2))

    panel = Panel(
        Group(*renderables),
        title=f"PHASE 2: 持倉 P&L  {now_str}  (排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)})",
        border_style="magenta",
    )
    return Group(panel)


# ─────────────────────────────────────────────────────────────────────────
# 快捷鍵 stdin 偵測 (non-blocking)
# ─────────────────────────────────────────────────────────────────────────

def _kb_listener(demo_mode: bool = False):
    """Background thread: 讀 stdin single char、更新 _current_sort。

    demo_mode=True 時、額外處理 arrow/home/end/space 控制 scenario。
    """
    mode_map = {'1': 'status', '2': 'priority', '3': 'risk', '4': 'trigger', '5': 'pnl', '6': 'sector'}
    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)  # cbreak 保留 NL→CRNL 輸出翻譯、避免 rich 階梯狀
    except Exception:
        return

    def _advance_demo(delta: int):
        total = _demo_total[0] or 1
        _demo_idx[0] = (_demo_idx[0] + delta) % total
        _demo_jump[0] = True
        _render_request[0] = True

    def _advance_cheat(delta: int):
        total = len(CHEAT_SHEET_PAGES) or 1
        _cheat_idx[0] = (_cheat_idx[0] + delta) % total
        _cheat_jump[0] = True
        _render_request[0] = True

    def _read_avail() -> str:
        """讀出 stdin 緩衝目前所有 bytes (避免 line-buffer 卡住 escape sequence)。"""
        try:
            import os as _os
            data = _os.read(fd, 32)
            return data.decode('utf-8', errors='replace')
        except Exception:
            return ''

    def _handle_arrow(ch3: str):
        """處理 ESC [ X 序列、依當前 mode 分流。"""
        if _cheat_mode[0]:
            if ch3 == 'D':
                _advance_cheat(-1)
            elif ch3 == 'C':
                _advance_cheat(1)
            elif ch3 == 'H':
                _cheat_idx[0] = 0
                _cheat_jump[0] = True
                _render_request[0] = True
            elif ch3 == 'F':
                _cheat_idx[0] = max(0, len(CHEAT_SHEET_PAGES) - 1)
                _cheat_jump[0] = True
                _render_request[0] = True
            return
        if not demo_mode:
            return
        if ch3 == 'D':
            _advance_demo(-1)
        elif ch3 == 'C':
            _advance_demo(1)
        elif ch3 == 'H':
            _demo_idx[0] = 0
            _demo_jump[0] = True
            _render_request[0] = True
        elif ch3 == 'F':
            _demo_idx[0] = max(0, (_demo_total[0] or 1) - 1)
            _demo_jump[0] = True
            _render_request[0] = True

    def _handle_char(ch: str):
        """處理單字元 (非 escape sequence)。任何狀態改動都觸發 _render_request。"""
        if ch == 'q':
            if _cheat_mode[0]:
                _cheat_mode[0] = False
                if demo_mode:
                    _demo_jump[0] = True
                _render_request[0] = True
                return
            _quit_flag[0] = True
            return
        if ch == 'h':
            _cheat_mode[0] = not _cheat_mode[0]
            if _cheat_mode[0]:
                _cheat_jump[0] = True
            elif demo_mode:
                _demo_jump[0] = True
            _render_request[0] = True
            return
        if demo_mode and not _cheat_mode[0]:
            if ch == ' ':
                _demo_paused[0] = not _demo_paused[0]
                _demo_jump[0] = True
                _render_request[0] = True
                return
            if ch == '0':
                # demo 模式: 0 跳第一個 scenario
                _demo_idx[0] = 0
                _demo_jump[0] = True
                _render_request[0] = True
                return
        # 主 monitor 模式 + 非 cheat sheet: +/-/0 調 watch-limit
        if not demo_mode and not _cheat_mode[0]:
            if ch in ('+', '='):  # `=` 是 `+` 無 shift
                _watch_limit[0] = _watch_limit[0] + 1
                _render_request[0] = True
                return
            if ch == '-':
                _watch_limit[0] = max(0, _watch_limit[0] - 1)
                _render_request[0] = True
                return
            if ch == '0':
                _watch_limit[0] = 0  # 0 = 不限
                _render_request[0] = True
                return
        if ch in mode_map and not _cheat_mode[0]:
            _current_sort[0] = mode_map[ch]
            _render_request[0] = True

    try:
        while not _quit_flag[0]:
            try:
                r, _, _ = select.select([sys.stdin], [], [], 0.3)
                if not r:
                    continue
                buf = _read_avail()
                if not buf:
                    continue
                # process buffer; escape sequence (ESC [ X) 一口氣處理
                i = 0
                n = len(buf)
                while i < n and not _quit_flag[0]:
                    c = buf[i]
                    if c == '\x1b' and i + 2 < n and buf[i + 1] == '[':
                        _handle_arrow(buf[i + 2])
                        i += 3
                    else:
                        _handle_char(c)
                        i += 1
            except Exception:
                break
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────
# Cheat Sheet: 策略 / 型態 reference (按 h 切換)
# ─────────────────────────────────────────────────────────────────────────

# Hardcoded 內容、跟著 codebase 走、不 reload memory file
CHEAT_SHEET_PAGES: list[tuple[str, list[tuple[str, str]]]] = [
    # Page 1
    ("🚫 紅線 (entry 紀律)", [
        ("#1 漲停隔日跳空",     "≥ +3% 一律不推 (4526 教訓 -$12,860)"),
        ("#2 距 MA10 (6/3 校正)", "雙籌碼 (外≥+1000 + 投≥+200)=忽略距離; 單籌碼=提醒不擋; 無籌碼=score 計分"),
        ("#3 09:10 後切入",     "前 10 分鐘觀察、等回踩 MA10"),
        ("#4 前 5 分鐘 >5% skip", "一票否決、整檔今天不碰"),
        ("#5 開盤站賣方",       "尾盤做事情 (9:00 不追、13:00 後再進)"),
        ("#6 加碼必先脫離成本",  "+10% + 回測支撐才加 (老師 5/29 全面性規則)"),
        ("#7 警示族群",         "PCB / 散熱 / 連接器: 不追、有持倉 50% sizing"),
        ("#8 試撮絕對忽略",     "試撮 ≠ 真實開盤 (6/1 嘉晶 -$21,388 教訓)"),
        ("#9 夜盤訊號 override", "夜盤強→族群續強、紅線 #2 可放寬到 +20%"),
    ]),
    # Page 2
    ("🎯 進場路徑 (composite cascade)", [
        ("Layer 1: 首攻 (Ch5-3) 當沖 SOP", "第一根 5K 6/6 條件 (收高開、量足、突破前高...)"),
        ("Layer 2: 續攻 (T1) 強勢延續",    "4 觸發任一 (強勢/回撤反彈/+10%通則/老師明示)"),
        ("Layer 3: 反彈 (T2) 跌深反彈",    "3 紅K confirm; 路徑 B (5m diff) 已 FAIL 不用"),
        ("Layer 4: 破底 (TC) 結構失敗",    "excluded、出場訊號"),
        ("尾盤 (Closing) 13:00-13:25",     "5 項確認、v7 backtest: 3-4/5=Win 82% ⭐ / 5/5=Win 40% 過熱別追"),
        ("category 分流",                  "核心/題材 → HELD; 短打/觀察 → WATCH"),
        ("紀律 filter",                    "discipline_filter 先過、紅線觸發整個 cascade skip"),
    ]),
    # Page 3
    ("📦 Stage 1/2/3 分批進場 SOP", [
        ("Stage 1: 試水",     "老師明示後第一次切入、小 sizing (1/3 標準位)"),
        ("Stage 2: 加碼 (4 觸發)", "任一即可、不必硬等 +10%:"),
        ("  (a) 強勢延續",    "Trigger 續攻 confirmed"),
        ("  (b) 回撤反彈",    "Trigger 反彈 confirmed"),
        ("  (c) +10% 通則",   "脫離成本 +10% + 回測支撐 (老師 5/29 全面性)"),
        ("  (d) 老師明示",    "老師再次點名同檔"),
        ("Stage 3: 突破加碼",  "波段創新高 + 量能配合"),
        ("不分批的例外",      "信心分級高 (黑盒老師明示時點) 可一次到位"),
    ]),
    # Page 4
    ("🚪 出場 4 條 (老師教法)", [
        ("基本原則",          "收盤確認、不用盤中價判停損"),
        ("1. 大黑包覆",       "大黑 K 完整包覆前段漲幅 → 停損訊號"),
        ("2. 結構底跌破",     "收盤跌破關鍵低點 / 頸線 → 停損出清"),
        ("3. 趨勢特徵消失",   "低點越來越高的規律不再成立 → 出清"),
        ("4. 跳空缺口回補失敗", "攻擊失敗、跳空缺口當天回補失敗 → 出場"),
        ("Core 持倉",         "用結構底、不是 MA5 (8064 東捷教訓)"),
        ("短線/波段先停利",   "5/23-5/28 連 6 天教、老師連續訊號 = 必跟"),
    ]),
    # Page 5
    ("🔒 處置股 ABC 框架", [
        ("🔒A 主升續攻",      "D+4-5 切入 / D-2~D-1 / 出關當天開均線上"),
        ("🔒B 反彈段",        "回落 25-30% + 出關前漲兩根、賺 15% 閃"),
        ("🔒C 不可進",        "處置中過前高 = 出關當天慘"),
        ("持有者出場",        "出關前一天賣一半 + 出關當天開低全出"),
        ("4722 國精化案例",   "D+6 觀察中、6/5 (D-2) 切入時機"),
    ]),
    # Page 6
    ("⚡🌅 策略模式 (strategy_mode)", [
        ("⚡ intraday 當沖",    "13:30 出清、backtest -0.80%/筆 ❌ 不推薦"),
        ("13:25 預警",          "macOS 通知「準備出當沖」"),
        ("13:30 強制",          "macOS alert「當沖時限到、請出場」"),
        ("🌅 overnight 隔日沖", "隔日 9:00 開盤出、backtest +1.85%/筆 ⭐ 主推"),
        ("8:45 預警",           "macOS 通知「9:00 開盤要出、隔日沖」"),
        ("9:00 強制",           "macOS alert「開盤出場時間到」"),
        ("📈 swing 波段",       "3-5 天、結構底/MA10 停損 (現有規則)"),
        ("🏛️ core 核心",        "結構底停損、長持倉 (現有規則)"),
        ("切換方式",            "HELD dict 加 'strategy_mode' 欄位、編輯腳本即可"),
        ("--strategy filter",   "CLI: --strategy intraday/overnight/swing/core/all"),
    ]),
    # Page 7 (原 Page 6)
    ("🎭 老師信號分級", [
        ("黑盒 vs 白盒",      "黑盒=老師明示時點 (sizing 走 Stage); 白盒=技術派訊號 (館前哥小結構可 all-in)"),
        ("明示時點",          "「看進場」/「今天買」≠ 只 mention; 必須明確時點"),
        ("Broker tier 1 confirm", "館前哥 (元大館前) / 站前哥 (凱基站前) 近 5d 淨買"),
        ("代名詞指向",        "5347 vs 2476 不准搞混; 講稿/Line 必對人"),
        ("訊號連續性",        "連 N 天教同一觀念 = 必跟 (5/23-5/28「先停利」案例)"),
        ("講稿=準則、Line=驗證", "Line 對話絕對不更新 spec、只能比對驗證"),
    ]),
    # Page 7
    ("📊 市場/族群 (6/3 框架)", [
        ("2026 AI 大趨勢",    "Universe ~500 支、AI 主軸、不做全市場"),
        ("6/2 主流",          "GT 基底 (2303/2330) / IC 通路 (3702/3036)"),
        ("",                  "記憶體 (2344/2408/3006) / AI PC (2376/3231/2382)"),
        ("",                  "紅海第二棒 (1605/6116) / 玻璃 (8064)"),
        ("5/31 警示族群",     "PCB / 散熱 / 連接器 (5/17 起連 4 週)"),
        ("夜盤訊號",          "找族群相對便宜補漲、紅線 #2 可放寬"),
        ("持續觀察",          "南亞科系 / 文曄系 5/26 排除已過 2 週 → stale、持續監控等回測"),
    ]),
    # Page 8
    ("⚠️ 拉高出貨 / 大盤訊號", [
        ("大盤訊號優先",      "看大盤拉高就賣、不等個股訊號"),
        ("9:15-9:30",         "賣高黃金時段 (老師多次教)"),
        ("9:20 預估量",       "老師當日 risk gauge"),
        ("12:00 殺盤考驗",    "加分項、不否決進場 (大盤/個股有跌才能看)"),
        ("賣完買回 3 框架",   "砍錯補回 / 高賣低接 / 停對沒買回=錯"),
        ("趨勢 vs 震盪",      "震盪盤鎖利門檻緊 (+3%~+10%)、別用趨勢思維抱波段"),
    ]),
    # Page 9
    ("💰 資金 / Sizing", [
        ("User 水位",         "~$3.2M (2026 Q2)"),
        ("標準 sizing",       "10% = $320k = 1 張中型股"),
        ("信心分級",          "老師明示=黑盒走 Stage; 館前哥小結構=白盒可 all-in"),
        ("尷尬量避免",        "2 張 = 尷尬量、避免"),
        ("標準位",            "3-4 張才能「鎖 1 留 2-3」"),
        ("沒漲停隔日跳空",    "≥+3% 一律不推 (紅線 #1)"),
        ("打擊區哲學",        "平常小錢耕耘、打擊區大口吃肉"),
        ("補回損失策略",      "2026 Q2 保守、東捷/鈦昇沒補回前不追高"),
    ]),
]


def _build_cheat_frame(args) -> Group:
    """組 cheat sheet 一頁 (用 rich Panel + Table)。"""
    idx = _cheat_idx[0]
    total = len(CHEAT_SHEET_PAGES)
    title, rows = CHEAT_SHEET_PAGES[idx]

    t = Table(show_header=False, box=box.SIMPLE, expand=True, padding=(0, 1))
    t.add_column("項目", style="bold cyan", no_wrap=True, ratio=2)
    t.add_column("內容", ratio=5)
    for key, val in rows:
        t.add_row(key, val)

    header = Text()
    header.append(f"📖 CHEAT SHEET  ", style="bold magenta")
    header.append(f"[{idx+1}/{total}] {title}", style="bold yellow")
    hint = Text(
        "← → 翻頁 | home 首頁 | end 末頁 | h 退出 | q 結束",
        style="dim",
    )
    footer = Text(
        f"← → 翻頁 | h 退出 | {idx+1}/{total} page",
        style="dim",
    )

    panel = Panel(
        t,
        title=f"{title}",
        border_style="cyan",
    )
    return Group(header, hint, panel, footer)


# ─────────────────────────────────────────────────────────────────────────
# Demo mode: mock client + scenario 循環
# ─────────────────────────────────────────────────────────────────────────

class MockClient:
    """模擬 FubonClient.get_realtime_snapshot 介面、回傳 scenario 設計好的 snapshot."""

    def __init__(self):
        # tk -> snapshot dict (含 open/close/high/low/change_price/change_rate)
        self.scenario: dict[str, dict] = {}
        # tk -> trigger override: (key, reason)
        self.trigger_overrides: dict[str, tuple[str, str]] = {}

    def get_realtime_snapshot(self, ticker: str) -> dict | None:
        ticker = str(ticker)
        snap = self.scenario.get(ticker)
        return dict(snap) if snap else None

    # 給 WSPriceCache 介面相容性 (demo 不會用、但避免 attr error)
    def subscribe_quotes(self, *_a, **_kw):
        return None

    def stats(self):
        return (len(self.scenario), 0, 0)


def _mk_snap(prev: float, open_: float, close: float,
             high: float | None = None, low: float | None = None,
             vol: int = 5000) -> dict:
    """生 snapshot dict、含 change_price/change_rate + total_volume (張)."""
    h = high if high is not None else max(open_, close)
    l = low  if low  is not None else min(open_, close)
    chg_p = close - prev
    chg_r = (chg_p / prev * 100) if prev else 0
    return {
        'open': open_, 'close': close, 'high': h, 'low': l,
        'change_price': chg_p, 'change_rate': chg_r,
        'total_volume': vol,
    }


def _demo_load_prev_close_patch(orig_load_prev):
    """Monkey-patch load_prev_close 用 scenario 的 _prev 欄位."""
    def patched(ticker: str):
        # demo 模式統一從 mock client 拿; 找不到時回 None
        snap = _demo_mock_ref.get(str(ticker)) if _demo_mock_ref else None
        if snap and '_prev' in snap:
            return float(snap['_prev'])
        return orig_load_prev(ticker)
    return patched


# 全域 ref 給 patch 用
_demo_mock_ref: dict | None = None


def _build_scenarios() -> list[tuple]:
    """設計 21+ 個 scenarios、覆蓋所有 layout 狀態。

    每個 tuple: (name, force_phase, snaps_dict_with_prev, sort_mode, watch_min_pri,
                trigger_overrides_dict)
    snaps_dict: tk -> {'_prev': float, ...snap fields}
    trigger_overrides: tk -> (trig_key, reason)
    """
    # 預設 prev_close 對照 (來自 HELD/PLAN/WATCH 編輯區附近的合理值)
    PREV = {
        '6285': 312.0, '1605': 40.5, '2885': 59.6, '3481': 58.7,
        '2303': 51.0, '6770': 24.0, '3702': 92.0, '3036': 78.0,
        '2376': 380.0, '8064': 65.0, '6116': 19.5, '6147': 88.0,
        '5351': 42.0, '3006': 110.0, '2344': 28.0, '6207': 127.0,
        '8046': 862.0, '1717': 78.7, '4722': 279.0, '4526': 42.15,
        '4540': 77.3, '1303': 113.0,  # 南亞 (scenario 33/34 尾盤演示用)
    }

    def base(adjust: dict[str, tuple[float, float]] | None = None,
             highlow: dict[str, tuple[float, float]] | None = None) -> dict:
        """生 baseline snapshot dict。adjust: tk -> (open_pct, close_pct) 相對 prev."""
        adjust = adjust or {}
        highlow = highlow or {}
        out: dict[str, dict] = {}
        for tk, prev in PREV.items():
            op_pct, cl_pct = adjust.get(tk, (0.0, 0.0))
            op = round(prev * (1 + op_pct/100), 2)
            cl = round(prev * (1 + cl_pct/100), 2)
            hi, lo = highlow.get(tk, (None, None))
            snap = _mk_snap(prev, op, cl, hi, lo)
            snap['_prev'] = prev
            out[tk] = snap
        return out

    scenarios = []

    # 1. Pre-market: open=close=prev
    snaps = base()
    for tk in snaps:
        snaps[tk]['open'] = 0  # 無開盤
        snaps[tk]['close'] = PREV[tk]
        snaps[tk]['change_price'] = 0
        snaps[tk]['change_rate'] = 0
    scenarios.append(("1. Pre-market 盤前無報價", 1, snaps, 'status', 2, {}))

    # 2. Open normal: 全部 +1~2%
    adj = {tk: (1.0 + (i % 3) * 0.5, 1.5 + (i % 3) * 0.5)
           for i, tk in enumerate(PREV)}
    scenarios.append(("2. Open +1~2% 健康延續", 1, base(adj), 'status', 2, {}))

    # 3. Open gap-up warn: 1605 主候選跳空 +4%
    adj = {tk: (0.5, 1.0) for tk in PREV}
    adj['1605'] = (4.0, 4.2)
    scenarios.append(("3. Gap-up +4% 警示 (紅線#1 邊緣)", 1, base(adj), 'status', 2, {}))

    # 4. Open gap-up skip: 1605 主候選跳空 +6%
    adj = {tk: (0.3, 0.8) for tk in PREV}
    adj['1605'] = (6.0, 6.5)
    scenarios.append(("4. Gap-up +6% Skip (紅線#1 觸發)", 1, base(adj), 'status', 2, {}))

    # 5. Held stop loss approach: 1605 距停損 +0.5%
    # stop=38.75, want close ~ 38.94 → close/prev = 38.94/40.5 ≈ -3.85%
    adj = {tk: (0.5, 0.8) for tk in PREV}
    adj['1605'] = (-2.0, -3.85)
    scenarios.append(("5. 1605 接近停損 (距停 +0.5%)", 2, base(adj), 'status', 2, {}))

    # 6. Held stop loss breach: 1605 跌破停損 38.75 → close=38.5
    adj = {tk: (0.2, 0.5) for tk in PREV}
    adj['1605'] = (-2.5, -4.94)  # 38.5
    scenarios.append(("6. 1605 跌破停損 🔴", 2, base(adj), 'status', 2, {}))

    # 7. Trigger fired: 2885 續攻 confirmed (mock override)
    adj = {tk: (0.5, 1.2) for tk in PREV}
    adj['2885'] = (1.0, 3.5)
    trig = {'2885': ('續攻', '🟢 強勢延續、外資 +16k 確認')}
    scenarios.append(("7. 2885 續攻 confirmed (Stage 2 加碼訊號)", 2, base(adj), 'trigger', 2, trig))

    # 8. 破底 structure fail: 8064 watch 破底 觸發 → excluded
    adj = {tk: (0.3, 0.6) for tk in PREV}
    adj['8064'] = (-1.0, -3.5)
    trig = {'8064': ('破底', '結構底跌破、出場')}
    scenarios.append(("8. 8064 破底 結構失敗 (excluded)", 2, base(adj), 'status', 2, trig))

    # 9. Mixed PnL: 1605 +5% / 2885 +8% / 6285 -2% / 3481 平
    adj = {tk: (0.0, 0.0) for tk in PREV}
    adj['1605'] = (1.0, 5.0)
    adj['2885'] = (2.0, 8.0)
    adj['6285'] = (-0.5, -2.0)
    adj['3481'] = (0.0, 0.2)
    scenarios.append(("9. Mixed PnL (有賺有賠)", 2, base(adj), 'pnl', 2, {}))

    # 10. All green
    adj = {tk: (1.5 + (i % 4), 3.0 + (i % 5)) for i, tk in enumerate(PREV)}
    scenarios.append(("10. 全部綠 (強勢盤)", 2, base(adj), 'pnl', 2, {}))

    # 11. All red
    adj = {tk: (-1.0 - (i % 3), -2.5 - (i % 4)) for i, tk in enumerate(PREV)}
    scenarios.append(("11. 全部紅 (弱勢盤)", 2, base(adj), 'pnl', 2, {}))

    # 12. Watchlist cascade: 3-4 watch 同時首攻 confirmed
    adj = {tk: (0.5, 1.5) for tk in PREV}
    trig = {
        '2303': ('首攻', '當沖 SOP 確認'),
        '3702': ('首攻', '量價齊揚、突破近 5 日高'),
        '6116': ('首攻', '紅海第二棒、管錢哥進場'),
        '6147': ('首攻', '記憶體封測續強'),
    }
    scenarios.append(("12. Watchlist cascade (4 檔首攻)", 2, base(adj), 'status', 2, trig))

    # 13. 各 trigger 級別並列
    adj = {tk: (0.3, 0.8) for tk in PREV}
    trig = {
        '2303': ('續攻', '續攻 強勢延續'),
        '3702': ('反彈', '反彈 跌深反彈訊號'),
        '6116': ('首攻', '首攻 當沖 SOP'),
        '6147': ('反彈_watch', '反彈 watch 觀察中'),
        '8064': ('破底', '破底 結構失敗'),
    }
    scenarios.append(("13. 各 Trigger 級別並列", 2, base(adj), 'trigger', 2, trig))

    # 14-19. 排序模式輪播
    adj = {tk: (0.5, 1.5 + (i % 5) * 0.6) for i, tk in enumerate(PREV)}
    adj['1605'] = (1.0, 3.0)
    adj['6285'] = (-0.5, -1.5)
    trig_mix = {
        '2885': ('續攻', '續攻'),
        '6116': ('首攻', '首攻'),
        '3702': ('反彈', '反彈'),
    }
    for sort in SORT_MODES:
        scenarios.append((f"14-19. 排序模式: {SORT_KEY_LABEL[sort]}",
                          2, base(adj), sort, 2, trig_mix))

    # 20a/b/c. WATCH min priority 1/2/3
    adj = {tk: (0.5, 1.2) for tk in PREV}
    for mp in [1, 2, 3]:
        scenarios.append((f"20. WATCH min priority = {mp}",
                          2, base(adj), 'status', mp, {}))

    # 21. STALE data 警示 — 用 phase2、scenarios 大部分為空模擬 cache stale
    snaps = base({tk: (0.5, 1.0) for tk in PREV})
    # 只保留少數 ticker 有資料、其他清空模擬 stale
    keep = {'1605', '2885'}
    for tk in list(snaps):
        if tk not in keep:
            snaps[tk] = {'_prev': PREV[tk]}  # 無 close
    scenarios.append(("21. STALE data 警示 (大部分 ticker 無報價)",
                      2, snaps, 'status', 2, {}))

    # 22. 首攻_signal (cascade 早段)
    adj = {tk: (0.5, 1.2) for tk in PREV}
    trig = {'2303': ('首攻_signal', '第一根 5K 過 high、量足、待回測')}
    scenarios.append(("22. 首攻_signal (cascade 早段、等回測)",
                      2, base(adj), 'status', 2, trig))

    # 23. 首攻_pullback (回測中)
    adj = {tk: (0.5, 0.8) for tk in PREV}
    trig = {'2303': ('首攻_pullback', '回測 MA10 中、守住為續強')}
    scenarios.append(("23. 首攻_pullback (回測 MA10 中)",
                      2, base(adj), 'status', 2, trig))

    # 24. 首攻 confirmed (回測守住、進場 SOP)
    adj = {tk: (0.5, 1.5) for tk in PREV}
    trig = {'2303': ('首攻', '回測守住、量配合、進場 SOP confirmed')}
    scenarios.append(("24. 首攻 confirmed (回測守住、進場)",
                      2, base(adj), 'status', 2, trig))

    # 25. 量比五等級並列 — 用不同 vol 設定 PREV 各 ticker
    snaps_vol: dict[str, dict] = {}
    # 5d avg from real DB; volume 設成不同比例: ❄(0.2)/⚪(1.0)/🟡(1.7)/🟢(2.5)/🚀(4.0)
    # 取出 9:00 開盤、現在假設 11:15 (session ratio 0.5)
    vol_targets = [
        ('1605', 0.2, '❄ 萎縮'),
        ('2885', 1.0, '⚪ 普通'),
        ('6285', 1.7, '🟡 放大'),
        ('3481', 2.5, '🟢 爆量'),
        ('2376', 4.0, '🚀 大爆量'),
    ]
    for tk, prev in PREV.items():
        # default 普通
        snap = _mk_snap(prev, prev*1.005, prev*1.012, vol=int(_load_5d_for_demo(tk) * 0.5))
        snap['_prev'] = prev
        snaps_vol[tk] = snap
    for tk, mult, _ in vol_targets:
        if tk not in PREV:
            continue
        prev = PREV[tk]
        avg5d = _load_5d_for_demo(tk)
        # session ratio = 0.5、想要 vol_ratio = mult → vol = avg5d * 0.5 * mult
        vol = int(avg5d * 0.5 * mult)
        snap = _mk_snap(prev, prev*1.005, prev*1.015, vol=vol)
        snap['_prev'] = prev
        snaps_vol[tk] = snap
    scenarios.append(("25. 量比五等級並列 (❄/⚪/🟡/🟢/🚀)",
                      2, snaps_vol, 'status', 2, {}))

    # 26. 開→現 +5% 續強
    adj = {tk: (0.0, 5.0) for tk in PREV}
    adj['1605'] = (0.0, 7.5)
    scenarios.append(("26. 開→現 大幅續強 (+5%~+7%)",
                      2, base(adj), 'pnl', 2, {}))

    # 27. 開→現 -3% 回吐
    adj = {tk: (3.0, 0.0) for tk in PREV}  # 開 +3%、現在回到 prev → 開→現 約 -3%
    adj['1605'] = (4.0, 0.5)
    scenarios.append(("27. 開→現 回吐 (開高拉回)",
                      2, base(adj), 'pnl', 2, {}))

    # 28. Trigger 時間戳「剛剛」(< 1 min)
    adj = {tk: (0.5, 1.5) for tk in PREV}
    trig = {'2885': ('T1', 'T1 confirmed')}
    age = {'2885': 0}  # 0 分 → 剛剛
    scenarios.append(("28. Trigger 時間戳「剛剛」(綠、最新鮮)",
                      2, base(adj), 'trigger', 2, trig, age))

    # 29. Trigger 時間戳 5 分前 (綠邊界)
    adj = {tk: (0.5, 1.5) for tk in PREV}
    trig = {'2885': ('T1', 'T1 confirmed')}
    age = {'2885': 5}
    scenarios.append(("29. Trigger 時間戳 5 分前 (綠邊界)",
                      2, base(adj), 'trigger', 2, trig, age))

    # 30. Trigger 時間戳 12 分前 (黃)
    adj = {tk: (0.5, 1.2) for tk in PREV}
    trig = {'6116': ('Ch5-3', 'Ch5-3 confirmed')}
    age = {'6116': 12}
    scenarios.append(("30. Trigger 時間戳 12 分前 (黃、仍 OK)",
                      2, base(adj), 'status', 2, trig, age))

    # 31. Trigger 時間戳 25 分前 (灰、時機過)
    adj = {tk: (0.5, 1.0) for tk in PREV}
    trig = {'6116': ('Ch5-3', 'Ch5-3 confirmed')}
    age = {'6116': 25}
    scenarios.append(("31. Trigger 時間戳 25 分前 (灰、時機過)",
                      2, base(adj), 'status', 2, trig, age))

    # 32. Trigger 時間戳 45 分前 (紅、太晚)
    adj = {tk: (0.5, 0.8) for tk in PREV}
    trig = {'8064': ('TC', 'TC 結構失敗')}
    age = {'8064': 45}
    scenarios.append(("32. Trigger 時間戳 45 分前 (紅、太晚)",
                      2, base(adj), 'status', 2, trig, age))

    # 33. 尾盤 confirmed 3-4/5 Win 82% (最佳進場)
    adj = {tk: (0.0, 0.8) for tk in PREV}
    adj['1303'] = (0.0, 1.2)  # 南亞 稍漲
    trig = {
        '1303': ('尾盤_confirmed', '結構✓殺盤✓反彈✓量縮✓ (4/5 pass Win 82%)'),
        '3702': ('尾盤_confirmed', '結構✓反彈✓量縮✓ (3/5 pass Win 82%)'),
    }
    scenarios.append(("33. 尾盤 confirmed 3-4/5 Win 82% ⭐ 最佳進場",
                      2, base(adj), 'trigger', 2, trig))

    # 34. 尾盤過熱 5/5 Win 40% (警示不追)
    adj = {tk: (0.0, 1.5) for tk in PREV}
    adj['1303'] = (2.0, 4.5)  # 南亞 強漲、已被拉走
    trig = {
        '1303': ('尾盤_過熱', '5/5 全 pass → 已被拉走 Win 40% 別追'),
    }
    scenarios.append(("34. 尾盤過熱 5/5 Win 40% 🔴 別追",
                      2, base(adj), 'trigger', 2, trig))

    return scenarios


def _load_5d_for_demo(ticker: str) -> float:
    """Demo 用、讀 5d avg、若無回 default 50000 張。"""
    try:
        v = load_5d_avg_volume(ticker)
        return v if v else 50000.0
    except Exception:
        return 50000.0


def _run_demo(args):
    """Demo mode entry: 循環顯示所有 scenarios、每 interval 秒切一個。"""
    global _demo_mock_ref

    mock = MockClient()
    scenarios = _build_scenarios()

    # Monkey-patch check_trigger_inline 用 mock.trigger_overrides
    global check_trigger_inline
    orig_check = check_trigger_inline

    def mock_check(ticker: str, tactic: str = '核心') -> tuple[str, str]:
        if ticker in mock.trigger_overrides:
            return mock.trigger_overrides[ticker]
        return 'none', ''
    check_trigger_inline = mock_check

    # Monkey-patch load_prev_close 用 scenario 的 _prev 欄位
    global load_prev_close
    orig_load = load_prev_close
    load_prev_close = _demo_load_prev_close_patch(orig_load)

    # Monkey-patch notify (demo 不真的通知)
    global maybe_notify_trigger, notify_mac
    maybe_notify_trigger = lambda *a, **kw: None
    notify_mac = lambda *a, **kw: None

    # 啟動 keyboard listener (q 退出 + arrow key 切 scenario)
    _demo_total[0] = len(scenarios)
    _demo_idx[0] = 0
    _demo_paused[0] = True  # 預設暫停 auto-cycle
    kb_thread = threading.Thread(target=_kb_listener, kwargs={'demo_mode': True}, daemon=True)
    kb_thread.start()

    console = Console()
    do_notify = False
    prev_prices: dict = {}
    notified: set = set()

    def _unpack(sc):
        # scenario tuple 可能是 6 或 7 元素 (含 age override)
        if len(sc) == 7:
            return sc[0], sc[1], sc[2], sc[3], sc[4], sc[5], sc[6]
        return sc[0], sc[1], sc[2], sc[3], sc[4], sc[5], {}

    def _build_demo_frame() -> Group:
        idx = _demo_idx[0]
        name, phase, snaps, sort_mode, _min_pri, _trig, _age = _unpack(scenarios[idx])
        now = datetime.now()
        now_str = now.strftime('%H:%M:%S')

        pause_tag = "⏸ paused" if _demo_paused[0] else f"▶ auto {args.interval}s"
        header = Text()
        header.append(f"=== DEMO MODE  {now_str} === ", style="bold magenta")
        header.append(f"[Scenario {idx+1}/{len(scenarios)}: {name}]  ", style="bold yellow")
        header.append(f"({pause_tag})", style="cyan")
        hint = Text(
            "← → 切換 | home/0 首個 | end 末個 | space 切 auto-cycle | h cheat sheet | q 退出 | "
            f"Phase {phase}",
            style="dim",
        )

        if phase == 1:
            content = render_phase1_screener(mock, now_str, sort_mode, do_notify)
        else:
            content = render_phase2_holdings(
                mock, now_str, prev_prices, notified, sort_mode, do_notify
            )

        footer = Text(
            f"sort={sort_mode} | watch-limit={_watch_limit[0]}",
            style="dim",
        )
        return Group(header, hint, content, footer)

    def _apply_current():
        idx = _demo_idx[0]
        name, phase, snaps, sort_mode, min_pri, trig, age_override = _unpack(scenarios[idx])
        global _demo_mock_ref
        mock.scenario = snaps
        mock.trigger_overrides = trig
        _demo_mock_ref = snaps
        _watch_min_priority[0] = min_pri
        _current_sort[0] = sort_mode
        # 套用 demo trigger age override
        _demo_trigger_age_override.clear()
        _demo_trigger_age_override.update(age_override)
        # demo 模式: 也要把 trigger 推到 _trigger_current/_trigger_fired_at
        # 讓非-override 的 ticker 有正確「剛點亮」時間戳
        now = datetime.now()
        for tk, (tkey, _r) in trig.items():
            if tk in age_override:
                continue  # 已 override、不重複記
            record_trigger_fire(tk, tkey, now)

    # 預先套用第一個 scenario、避免初始 frame 顯示空資料
    _apply_current()

    try:
        with Live(
            _build_demo_frame(),
            console=console,
            screen=not args.no_clear,
            refresh_per_second=2,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        ) as live:
            while not _quit_flag[0]:
                _apply_current()
                if _cheat_mode[0]:
                    live.update(_build_cheat_frame(args))
                else:
                    live.update(_build_demo_frame())

                _elapsed = 0.0
                _step = 0.3
                while not _quit_flag[0]:
                    time.sleep(_step)
                    _elapsed += _step
                    if _cheat_jump[0]:
                        _cheat_jump[0] = False
                        break
                    if _demo_jump[0]:
                        _demo_jump[0] = False
                        break
                    # auto-cycle (非 paused 且不在 cheat sheet 模式) → 推下一個
                    if (not _cheat_mode[0]) and (not _demo_paused[0]) and _elapsed >= args.interval:
                        _demo_idx[0] = (_demo_idx[0] + 1) % len(scenarios)
                        break
                    # 持續刷新時鐘
                    if _cheat_mode[0]:
                        live.update(_build_cheat_frame(args))
                    else:
                        live.update(_build_demo_frame())
    finally:
        _quit_flag[0] = True
        # 還原 patch (測試友善)
        check_trigger_inline = orig_check
        load_prev_close = orig_load
        print(f"Demo 結束 (停在 {_demo_idx[0]+1} / {len(scenarios)} scenarios)")


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    # --data-interval = 背景資料更新頻率 (預設 3s)、--interval 為向後相容 alias
    p.add_argument('--data-interval', type=float, default=3.0,
                   help='背景資料更新頻率秒 (預設 3s、跟畫面操作解耦)')
    p.add_argument('--interval',    type=float, default=None,
                   help='(deprecated) 等同 --data-interval')
    p.add_argument('--no-clear',    action='store_true')
    p.add_argument('--no-notify',   action='store_true')
    p.add_argument('--force-phase', choices=['1', '2'], help='強制階段、debug 用')
    p.add_argument('--sort', choices=SORT_MODES, default='status',
                   help='初始排序模式 (status/priority/risk/trigger/pnl/sector)')
    p.add_argument('--watch-min-priority', type=int, default=2,
                   choices=[1, 2, 3],
                   help='開盤前 WATCH 顯示門檻 (1=全顯/2=預設/3=只看核心)')
    p.add_argument('--demo', action='store_true',
                   help='Demo 模式: 循環顯示所有 mock scenarios、驗證 layout')
    p.add_argument('--watch-limit', type=int, default=5,
                   help='WATCH 觀察可能段「每分類」最多顯示 N 檔 (預設 5、超過 collapse、0=全顯、+/-/0 鍵即時調)')
    p.add_argument('--strategy', default='all',
                   choices=['all', 'intraday', 'overnight', 'swing', 'core'],
                   help='篩選 strategy_mode (預設 all、可指定 intraday/overnight/swing/core)')
    args = p.parse_args()
    # backward compat: --interval 覆寫 --data-interval
    if args.interval is not None:
        args.data_interval = args.interval
    else:
        args.interval = args.data_interval  # 保留欄位給 demo 等用
    _watch_min_priority[0] = args.watch_min_priority
    _watch_limit[0] = args.watch_limit

    _current_sort[0] = args.sort
    do_notify = not args.no_notify

    # --strategy filter: 過濾 HELD (PLAN/WATCH 不過濾、保持完整觀察)
    if args.strategy != 'all':
        global HELD  # noqa: PLW0603
        HELD = [it for it in HELD
                if get_strategy_mode(it if isinstance(it, dict) else {}) == args.strategy
                or (isinstance(it, tuple))]  # tuple 格式向後相容、不過濾
        if not HELD:
            print(f"[warn] --strategy {args.strategy!r} 過濾後 HELD 為空", flush=True)

    # ── daily_watchlist JSON → WATCH merge (預設啟用) ──────────────────────
    _wl_added, _wl_existing, _wl_date = _merge_scanner_watchlist()
    if _wl_date:
        print(
            f"📂 載入 watchlist {_wl_date}: 新增 {_wl_added} 檔 "
            f"(existing {_wl_existing} 檔保留)",
            flush=True,
        )
    else:
        print("📂 daily_watchlist 目錄不存在或無 JSON、跳過 merge", flush=True)

    # Demo 模式: 不連 Fubon、跑 mock scenarios
    if args.demo:
        _run_demo(args)
        return

    # StageTrigger 載入狀態
    trigger_ok = _stage_engine is not None

    rest_client = FubonClient()

    # 收集所有 tickers (HELD + PLAN_PRIMARY + PLAN_BACKUP + WATCH) 給 WS 訂閱
    _all_tk = set()
    for src in [HELD, PLAN_PRIMARY, PLAN_BACKUP, WATCH]:
        for it in src:
            if isinstance(it, dict) and it.get('ticker'):
                _all_tk.add(str(it['ticker']))
            elif isinstance(it, (tuple, list)) and len(it) > 0:
                _all_tk.add(str(it[0]))

    print(f"初始化 WSPriceCache、訂閱 {len(_all_tk)} 檔...", flush=True)
    _cache = WSPriceCache(rest_client, list(_all_tk))
    print(f"  WS 連線: {'OK' if _cache.ws_ok else 'FAIL — 將全程 REST fallback'}", flush=True)
    print(f"  Warm cache: {len(_cache.cache)} 檔", flush=True)

    # client 給 render 用、實際走 cache (內含 stale fallback)
    client = _cache
    prev_prices: dict = {}
    notified:    set  = set()

    use_alt = not args.no_clear

    # ─── Layer 1: Data Cache + 背景 refresh thread ───
    # 收集 ticker → tactic map (給 trigger category 用)
    tactic_map: dict[str, str] = {}
    for src in [HELD, PLAN_PRIMARY, PLAN_BACKUP, WATCH]:
        for it in src:
            if isinstance(it, dict) and it.get('ticker'):
                tactic_map[str(it['ticker'])] = it.get('tactic', '核心')

    # Monkey-patch render-side functions → 純讀 cache (極快)
    global check_trigger_inline, compute_vol_ratio
    _real_check = check_trigger_inline
    _real_vol = compute_vol_ratio

    data_cache = DataCache(list(_all_tk), client, tactic_map)

    def _cached_check(ticker: str, tactic: str = '核心') -> tuple[str, str]:
        return data_cache.get_trigger(ticker)
    def _cached_vol(ticker: str, total_volume_lots: float | None,
                    now: datetime | None = None) -> float | None:
        return data_cache.get_vol_ratio(ticker)
    check_trigger_inline = _cached_check
    compute_vol_ratio = _cached_vol

    refresh_thread = threading.Thread(
        target=_data_refresh_thread,
        args=(data_cache, _real_check, _real_vol, args.data_interval),
        daemon=True,
    )
    refresh_thread.start()
    print(f"  Data refresh thread 啟動 (interval {args.data_interval}s)", flush=True)

    # ─── Layer 2: Render loop 純讀 cache ───
    kb_thread = threading.Thread(target=_kb_listener, daemon=True)
    kb_thread.start()

    console = Console()

    def _build_frame() -> Group:
        """組整個 frame: header + content panel + footer。"""
        # cheat sheet 模式優先
        if _cheat_mode[0]:
            return _build_cheat_frame(args)
        now = datetime.now()
        now_str = now.strftime('%H:%M:%S')
        h, m = now.hour, now.minute

        in_phase1 = h == 9 and m <= 25
        if args.force_phase == '1':
            in_phase1 = True
        elif args.force_phase == '2':
            in_phase1 = False

        sort_mode = _current_sort[0]

        # Header
        header = Text()
        header.append(f"=== 即時 monitor (data {args.data_interval}s)  {now_str} === ",
                      style="bold blue")
        if trigger_ok:
            header.append("StageTrigger OK", style="green")
        else:
            header.append("StageTrigger unavailable", style="red")
        # 大盤環境 chip
        regime_label, regime_style = _get_market_regime_chip()
        header.append(f"  [{regime_label}]", style=regime_style)
        # 時段 chip
        session_label, session_style = _get_session_chip(now)
        header.append(f"  [{session_label}]", style=session_style)
        # WS cache stats + data cache stats
        try:
            tot, stale, errs = _cache.stats()
            header.append(f"  [WS {tot}, stale {stale}, err {errs}]",
                          style="dim")
            age = time.time() - data_cache.last_refresh if data_cache.last_refresh else -1
            header.append(f"  [data age {age:.1f}s]", style="dim")
        except Exception:
            pass

        hint = Text(
            "1-6=排序 +/-=watch-limit (每分類) 0=全顯 h=cheat q=退出  "
            f"(watch-limit={_watch_limit[0]}/分類)",
            style="dim",
        )

        if in_phase1:
            content = render_phase1_screener(client, now_str, sort_mode, do_notify)
        else:
            content = render_phase2_holdings(
                client, now_str, prev_prices, notified, sort_mode, do_notify
            )

        footer = Text(
            f"data refresh {args.data_interval}s | 排序 [{sort_mode}] | watch-limit {_watch_limit[0]} | "
            "Ctrl+C 或 q 結束",
            style="dim",
        )
        return Group(header, hint, content, footer)

    # ─── Render loop: 鍵盤事件 < 50ms redraw、資料背景 thread 更新 ───
    RENDER_MIN_INTERVAL = 0.05      # 50ms cooldown 避免閃爍
    FORCE_REDRAW_MAX = 1.0          # 1s 沒事件也強制 redraw (時鐘走 + age tag)
    last_render = 0.0

    try:
        with Live(
            _build_frame(),
            console=console,
            screen=use_alt,
            refresh_per_second=10,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        ) as live:
            while not _quit_flag[0]:
                try:
                    now = time.time()
                    elapsed_since_render = now - last_render
                    need_redraw = (
                        (_render_request[0] and elapsed_since_render >= RENDER_MIN_INTERVAL)
                        or elapsed_since_render >= FORCE_REDRAW_MAX
                    )
                    if need_redraw:
                        live.update(_build_frame())
                        last_render = now
                        _render_request[0] = False
                    time.sleep(0.02)  # 20ms polling
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    try:
                        live.update(Text(f"[ERROR] {e}", style="red"))
                    except Exception:
                        pass
                    time.sleep(2)
    finally:
        _quit_flag[0] = True
        print("結束")


if __name__ == '__main__':
    main()
