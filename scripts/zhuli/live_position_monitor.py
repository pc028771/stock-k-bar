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
        'tactic': '核心', 'priority': 2,
        'source': '老師明示',
        'sector': '低軌衛星',
        'note': '老師明示「兩檔選啟碁」、停損 MA10 動態'
    },
    {
        'ticker': '1605', 'name': '華新',
        'cost': 40.1, 'shares': 8000, 'stop': 38.75,
        'tactic': '核心', 'priority': 3,
        'source': '老師重壓',
        'sector': '紅海第二棒',
        'note': '6/2 EOD Trigger 1 確認、外資 +16k'
    },
    {
        'ticker': '2885', 'name': '元大金',
        'cost': 58.0, 'shares': 10000, 'stop': 55.71,
        'tactic': '配置', 'priority': 1,
        'source': '配置部位',
        'sector': '金融',
        'note': '6/2 收 $59.60 (+$16k 浮動)、停損 $55.71 結構底'
    },
]

# 已實現 (今日累計、每日歸零)
REALIZED = 0

# 鎖定主候選 (Phase 1 開盤 entry screening)
# 格式: dict (必填: ticker, name, shares, stop; 選填: tactic, priority, source, sector, note, reason)
# 舊 tuple (ticker, name, shares, stop, reason) 自動 convert
PLAN_PRIMARY = [
    {
        'ticker': '1605', 'name': '華新',
        'shares': 1000, 'stop': 38.75,
        'tactic': '核心 Stage 2', 'priority': 3,
        'source': '老師重壓 + Trigger 1',
        'sector': '紅海第二棒',
        'note': '6/3 開盤 ≥ 40.0 + 跳空 ≤+3% 加 1 張',
        'reason': '🟢 EOD Trigger 1 確認 (外資 +16k + 管錢 +1067)、加 1 張',
    },
    {
        'ticker': '4958', 'name': '臻鼎-KY',
        'shares': 1000, 'stop': 486.0,
        'tactic': '題材', 'priority': 3,
        'source': '處置框架 + scanner',
        'sector': 'ABF載板/PCB',
        'note': '🔒A D+5 老師「第 4-5 天最愛切入」最後一天、出關 6/10、core、⭐站前哥',
        'reason': '🔒A 處置 D+5 (窗口最後一天) + 老師最愛切入 + core + 站前哥、停損 486 (結構底)',
    },
]

# 備案 (Phase 1 主候選被 skip 時遞補)
# 6/3 全 skip、結構壞 + 籌碼弱
PLAN_BACKUP: list = []

# 觀察清單 (dict 格式、兼容舊 tuple)
WATCH = [
    # 6/3 早盤老師新訊號 — 夜盤期貨/美股觸發、面板族群續強、找相對便宜
    {
        'ticker': '3481', 'name': '群創',
        'ref_close': 56.2, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示 6/3 (夜盤訊號)',
        'sector': '面板/族群補漲',
        'discipline_override': '族群續強、紅線 #2 放寬到 +20%',
        'note': '⭐⭐⭐ 老師 6/3 夜盤訊號、面板續強、彩晶 +41% 已噴出、'
                '群創 +12% 相對便宜 = 補漲標的、投信 6/2 +24k 接手'
    },
    # 老師明示重壓 / 第二棒 / GT 基底
    {
        'ticker': '2303', 'name': '聯電',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 3,
        'source': '老師明示',
        'sector': 'GT基底/成熟製程',
        'note': '⭐ GT 基底、立即店、「直接參與最大組」、user 提醒'
    },
    {
        'ticker': '3702', 'name': '大聯大',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': 'IC通路',
        'note': '⭐ IC 通路「那個大科」、user 提醒'
    },
    {
        'ticker': '3036', 'name': '文曄',
        'ref_close': 0, 'stop': None,
        'tactic': '短打', 'priority': 2,
        'source': '老師明示',
        'sector': 'IC通路',
        'note': '⭐ IC 通路、user 提醒 (注意 5/26 排除清單翻轉?)'
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
        'note': '⚠️ 主流但「已 50%、不要再追」、觀察回測'
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
    {
        'ticker': '8046', 'name': '南電',
        'ref_close': 862.0, 'stop': 834.0,
        'tactic': '短打', 'priority': 1,
        'source': '老師明示',
        'sector': 'ABF',
        'note': '🔴 老師「ABF 需要洗牌」、MA5/10/20 全破、外資 -3,125'
    },
    # 6/3 scanner 新增 (Tier-B 打擊區、籌碼/型態符合)
    {
        'ticker': '1717', 'name': '長興',
        'ref_close': 78.70, 'stop': 75.50,
        'tactic': '短打', 'priority': 2,
        'source': 'scanner (small_structure)',
        'sector': '封測/特化',
        'note': '🟡 投信 5d +1,726 + ⭐管錢哥、距 MA10 -2.7% 打擊區、首提後 79d (二波期)'
    },
    {
        'ticker': '4722', 'name': '國精化',
        'ref_close': 279.0, 'stop': 268.0,
        'tactic': '題材', 'priority': 2,
        'source': '處置框架',
        'sector': '化工',
        'note': '🔒A D+6 觀察中、出關前 4 天、等 6/5 (D-2 出關前 2 天) 切入時機'
    },
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
]

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

# Trigger 顯示格式
TRIGGER_DISPLAY = {
    'Ch5-3':  '🟡 Ch5-3 當沖 SOP',
    'T1':     '🟢 T1 confirmed',
    'T2':     '🎯 T2 confirmed',
    'TC':     '🔴 TC confirmed',
    'T2_watch': '🟡 T2 watch',
    'none': '⚪ 無訊號',
    None: '⚪ 無訊號',
}

# sort by trigger 優先順序: Ch5-3 > T2 > T1 > TC (warning) > none
TRIGGER_RANK = {
    'Ch5-3': 0,
    'T2':    1,
    'T1':    2,
    'TC':    3,
    'T2_watch': 4,
    'none': 5,
    None: 6,
}

# 全域排序切換（快捷鍵 1-6 更新這個）
_current_sort: list[str] = ['status']
_quit_flag: list[bool] = [False]
_watch_min_priority: list[int] = [2]

# Trigger cooldown 避免重複通知 (key: "{ticker}_{T1/T2/TC}")
_trigger_cooldown: dict[str, datetime] = {}
TRIGGER_COOLDOWN_MIN = 30

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

# 抑制 stage_helper 的 log 訊息、避免噴到 monitor alt-screen 破版
import logging as _logging
_logging.getLogger('zhuli.intraday_stage_helper').setLevel(_logging.ERROR)
_logging.getLogger('intraday_stage_helper').setLevel(_logging.ERROR)
_logging.getLogger('clients.fubon_client').setLevel(_logging.ERROR)


def check_trigger_inline(ticker: str, tactic: str = '核心') -> tuple[str, str]:
    """即時跑 composite_check cascade，回傳 (trigger_key, reason)。

    trigger_key: 'Ch5-3' / 'T1' / 'T2' / 'TC' / 'none'
    category 依 tactic 決定: 核心/題材 → HELD；其他 → WATCH
    向後相容: 舊 TRIGGER_DISPLAY / TRIGGER_RANK 保持不變。
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
    """Trigger 觸發時、30 分鐘 cooldown 通知。"""
    if not do_notify:
        return
    if trig_key not in ('Ch5-3', 'T1', 'T2', 'TC'):
        return
    cd_key = f"{ticker}_{trig_key}"
    now = datetime.now()
    if now <= _trigger_cooldown.get(cd_key, datetime.min):
        return
    _trigger_cooldown[cd_key] = now + timedelta(minutes=TRIGGER_COOLDOWN_MIN)

    titles = {
        'Ch5-3': f"🟡 {ticker} {name} Ch5-3 當沖 SOP",
        'T1': f"🟢 {ticker} {name} T1 強勢延續",
        'T2': f"🎯 {ticker} {name} T2 反彈訊號",
        'TC': f"🚨 {ticker} {name} TC 結構失敗",
    }
    sounds = {'Ch5-3': 'Glass', 'T1': 'Glass', 'T2': 'Glass', 'TC': 'Sosumi'}
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
# DB helper
# ─────────────────────────────────────────────────────────────────────────

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
    if trig_key == 'Ch5-3':
        return f"{C.Y}{label}{C.END}" + (f" {C.DIM}({short}){C.END}" if short else '')
    if trig_key in ('T1', 'T2'):
        return f"{C.G}{label}{C.END}" + (f" {C.DIM}({short}){C.END}" if short else '')
    if trig_key == 'TC':
        return f"{C.R}{label}{C.END}" + (f" {C.DIM}({short[:40]}){C.END}" if reason else '')
    if trig_key == 'T2_watch':
        return f"{C.Y}{label}{C.END}" + (f" {C.DIM}({reason[:30]}){C.END}" if reason else '')
    return f"{C.DIM}{label}{C.END}"


# ─────────────────────────────────────────────────────────────────────────
# Priority panel summary
# ─────────────────────────────────────────────────────────────────────────

def render_priority_panel(held: list[dict], watch: list[dict],
                          live_data: dict) -> list[str]:
    """高/中/低優先級摘要 panel。"""
    lines = []

    def group(items):
        p3 = [x for x in items if x.get('priority', 2) == 3]
        p2 = [x for x in items if x.get('priority', 2) == 2]
        p1 = [x for x in items if x.get('priority', 2) == 1]
        return p3, p2, p1

    held_p3, held_p2, held_p1 = group(held)
    watch_p3, watch_p2, watch_p1 = group(watch)

    # Trigger 觸發中的
    triggered_map = {}
    for x in held + watch:
        tk = x.get('ticker', '')
        trig = live_data.get(tk, {}).get('trigger', 'none')
        if trig in ('T1', 'T2', 'TC'):
            triggered_map[tk] = trig

    # 警示 (距停損 < +1%)
    warnings = []
    for x in held:
        tk = x.get('ticker', '')
        dist = live_data.get(tk, {}).get('dist_to_stop', 999)
        if dist < 1:
            warnings.append(f"{tk}({dist:+.1f}%)")

    def _render_group(label: str, h_list: list, w_list: list):
        all_list = h_list + w_list
        h_tks = [x['ticker'] for x in h_list]
        w_tks = [x['ticker'] for x in w_list]
        all_tks = h_tks + w_tks
        trig_info = [f"{tk}({triggered_map[tk]})" for tk in all_tks if tk in triggered_map]
        warn_info = [w for w in warnings if any(w.startswith(x['ticker']) for x in h_list)]
        if not all_list:
            return
        h_part = f"持{'/'.join(h_tks)}" if h_tks else ''
        w_part = f"候{'/'.join(w_tks)}" if w_tks else ''
        trig_part = f" {C.G}🟢{'/'.join(trig_info)}{C.END}" if trig_info else ''
        warn_part = f" {C.R}⚠️{','.join(warn_info)}{C.END}" if warn_info else ''
        parts = [p for p in (h_part, w_part) if p]
        lines.append(
            f"{C.BOLD}{label}{C.END} {len(all_list)}檔  {' / '.join(parts)}{trig_part}{warn_part}"
        )

    _render_group('🎯⭐⭐⭐', held_p3, watch_p3)
    _render_group('⚠️ ⭐⭐',  held_p2, watch_p2)
    _render_group('🟢⭐',    held_p1, watch_p1)

    return lines


# ─────────────────────────────────────────────────────────────────────────
# Phase 1: 開盤 Entry Screening
# ─────────────────────────────────────────────────────────────────────────

def render_phase1_screener(client, now_str: str, sort_mode: str,
                           do_notify: bool) -> list[str]:
    """Phase 1 開盤 entry screening (9:00-9:25)."""
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

    lines = [
        f"{C.BOLD}━━━ {now_str}  PHASE 1: 開盤 ENTRY SCREENING  "
        f"(排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)}) ━━━{C.END}"
    ]

    # Priority panel
    watch_norm = _normalize_watch(WATCH)
    lines.append("")
    lines.extend(render_priority_panel(held, watch_norm, live_data))
    lines.append("")

    # 已持倉開盤健康度
    if held:
        lines.append(f"{C.BOLD}📊 已持倉開盤健康度{C.END}")
        for item in sort_items(held, sort_mode, live_data):
            tk     = item['ticker']
            name   = item['name']
            entry  = item.get('cost', 0)
            shares = item.get('shares', 0)
            stop   = item.get('stop', 0)
            tactic = item.get('tactic', '—')
            pri    = item.get('priority', 2)
            sector = item.get('sector', '?')
            d      = live_data.get(tk, {})
            trig_key    = d.get('trigger', 'none')
            trig_reason = d.get('trigger_reason', '')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                o    = float(snap.get('open') or 0)
                c    = float(snap.get('close') or 0)
                prev = load_prev_close(tk)
                level, msg, sev = classify_open(o, prev) if prev else ('?', '無前收', 'unknown')
                entry_vs_open = (entry - o)/o*100 if o else 0
                if entry_vs_open < -1:
                    entry_tag = f"{C.G}🎯 進得好 (低 open {entry_vs_open:.1f}%){C.END}"
                elif entry_vs_open > 1:
                    entry_tag = f"{C.Y}⚠️  追高了 (高 open {entry_vs_open:+.1f}%){C.END}"
                else:
                    entry_tag = f"{C.DIM}入價貼開盤{C.END}"
                pnl = (c - entry)*shares
                trig_compact = fmt_trigger(trig_key, trig_reason)
                lines.append(
                    f"  {level} {stars(pri):3} {tk} {name:6}  "
                    f"開${o:.1f}→${c:.1f} 入${entry:.1f} {fmt_pnl(pnl)}  "
                    f"{C.DIM}停${stop} | {trig_compact}{C.END}"
                )
                lines.append(f"      {msg} | {entry_tag}")
            except Exception as e:
                lines.append(f"  {tk} err: {e}")
        lines.append("")

    if not plan:
        if not held:
            lines.append(f"{C.DIM}PLAN_PRIMARY 空、編輯腳本開頭設定{C.END}")
        return lines

    lines.append(f"{C.BOLD}🎯 待進場主候選{C.END}")
    skipped = []
    for item in sort_items(plan, sort_mode, live_data):
        tk     = item['ticker']
        name   = item['name']
        shares = item.get('shares', 0)
        stop   = item.get('stop', 0)
        reason = item.get('reason') or item.get('note', '')
        pri    = item.get('priority', 2)
        tactic = item.get('tactic', '—')
        sector = item.get('sector', '?')
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
            trig_compact = fmt_trigger(trig_key, trig_reason)
            lines.append(
                f"  {level} {stars(pri):3} {tk} {name:6}  "
                f"前${prev or 0:.1f}→開${o:.1f} ({chg_open:+.1f}%) 現${c:.1f}  "
                f"{C.DIM}停${stop} | {trig_compact}{C.END}"
            )
            lines.append(f"      {msg} | sizing {shares}股 ${cost:,.0f} | {reason[:60]}")
            if sev in ('skip', 'warn'):
                skipped.append(tk)
        except Exception as e:
            lines.append(f"  {tk} {name}: err {e}")

    if skipped:
        lines.append("")
        lines.append(f"{C.BOLD}{C.Y}⚠️  {len(skipped)} 主候選 skip/警示、推薦備案 (按穩定強排序){C.END}")
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
                backup_evaluated.append((sev, -chg_open, tk, name, shares, prev, o, c, level, msg, reason, stop))
            except Exception:
                pass
        backup_evaluated.sort(key=lambda x: (sev_order.get(x[0], 9), x[1]))
        for bitem in backup_evaluated[:3]:
            sev, _, tk, name, shares, prev, o, c, level, msg, reason, stop = bitem
            chg_open = (o - (prev or 1))/(prev or 1)*100
            cost = o * shares
            lines.append(f"  {level} {tk} {name:6}  前${prev or 0:.1f}→開${o:.1f} ({chg_open:+.1f}%)  現${c:.1f}")
            lines.append(f"      {msg}")
            lines.append(f"      sizing: {shares} 股 ≈ ${cost:,.0f}、停損 ${stop}、{reason}")
    else:
        lines.append(f"{C.G}✅ 主候選全部 OK、無需備案{C.END}")

    # Phase 1: WATCH 分段 (status mode 才顯示、避免干擾 entry focus)
    if sort_mode == 'status' and watch_norm:
        lines.append("")
        lines.append(f"{C.DIM}── WATCH (開盤後觸發才進) ──{C.END}")
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
                watch_live[tk] = {
                    'c': c, 'pnl_pct': chg, 'dist_to_stop': dist,
                    'trigger': trig_key, 'trigger_reason': trig_reason,
                }
            except Exception:
                watch_live[tk] = {}
        # 只顯示 confirmed + watching、Phase 1 不列 excluded 避免干擾
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
            lines.append(f"{C.BOLD}{C.G}🎯 WATCH 可進場:{C.END}")
            for item, d in confirmed_p1:
                tk = item['ticker']; name = item['name']
                trig = d.get('trigger', 'none'); reason = d.get('trigger_reason', '')
                c = d.get('c', 0); pri = item.get('priority', 1)
                lines.append(
                    f"  {stars(pri):3} {tk} {name:6}  "
                    f"${c:.1f}  {fmt_trigger(trig, reason[:50])}"
                )
        if watching_p1:
            lines.append(f"{C.BOLD}🔍 WATCH 觀察:{C.END}")
            for item, d in watching_p1:
                tk = item['ticker']; name = item['name']
                c = d.get('c', 0); pri = item.get('priority', 1)
                note = item.get('note', '')[:35]
                lines.append(
                    f"  {stars(pri):3} {tk} {name:6}  "
                    f"${c:.1f}  {C.DIM}{note}{C.END}"
                )

    return lines


# ─────────────────────────────────────────────────────────────────────────
# WATCH 3-section 分類邏輯
# ─────────────────────────────────────────────────────────────────────────

def _classify_watch_item(item: dict, d: dict) -> str:
    """依 composite_check 結果分流: confirmed / watching / excluded."""
    trig_key = d.get('trigger', 'none')
    pri      = item.get('priority', 1)

    if trig_key in ('T1', 'T2', 'Ch5-3'):
        return 'confirmed'
    if trig_key == 'TC':
        return 'excluded'
    if trig_key == 'T2_watch':
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
    lines: list[str],
    emit_fn,
    sort_mode: str,
) -> None:
    """WATCH 分 3 段顯示 (status mode)。直接 append 到 lines。"""
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

    if pre_mkt:
        lines.append(f"  {C.DIM}⏳ 開盤前、5K 累積中 — Trigger 判定尚未啟動{C.END}")

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
            lines.append(f"  {C.DIM}({hidden} 檔低優先/排除暫不顯示){C.END}")
    elif filtered_out:
        lines.append(f"  {C.DIM}({filtered_out} 檔 priority < {min_pri} 過濾){C.END}")

    if confirmed:
        lines.append(f"{C.BOLD}{C.G}🎯 WATCH 可進場 (composite confirmed):{C.END}")
        for item, d in confirmed:
            tk      = item['ticker']
            name    = item['name']
            pri     = item.get('priority', 1)
            trig    = d.get('trigger', 'none')
            reason  = d.get('trigger_reason', '')
            c       = d.get('c', 0)
            stop    = item.get('stop')
            dist    = d.get('dist_to_stop', 999)
            sector  = item.get('sector', '?')
            dist_s  = fmt_dist(dist) if stop else f"{C.DIM}無停損設定{C.END}"
            price_s = f"${c:.1f}" if c else f"{C.DIM}無報價{C.END}"
            action  = reason[:50] if reason else ''
            lines.append(
                f"  {stars(pri):3} {tk} {name:6}  "
                f"{price_s}  距停 {dist_s}  "
                f"{fmt_trigger(trig, action)}  [{sector}]"
            )
        lines.append("")

    if watching:
        lines.append(f"{C.BOLD}🔍 WATCH 觀察可能:{C.END}")
        for item, d in watching:
            tk     = item['ticker']
            name   = item['name']
            pri    = item.get('priority', 1)
            trig   = d.get('trigger', 'none')
            c      = d.get('c', 0)
            chg    = d.get('pnl_pct', 0)
            sector = item.get('sector', '?')
            note   = item.get('note', '')[:22]
            price_s = f"${c:.1f}" if c else f"{C.DIM}—{C.END}"
            chg_color = C.R if chg < 0 else C.G
            trig_s = fmt_trigger(trig) if trig not in ('none', None) else f"{C.DIM}—{C.END}"
            lines.append(
                f"  {stars(pri):3} {tk} {name:6}  "
                f"{price_s} ({chg_color}{chg:+.1f}%{C.END})  "
                f"{trig_s} {C.DIM}{note}{C.END}"
            )
        lines.append("")

    if excluded:
        lines.append(f"{C.DIM}⛔ WATCH 排除/低優先:{C.END}")
        for item, d in excluded:
            tk     = item['ticker']
            name   = item['name']
            trig   = d.get('trigger', 'none')
            reason_s = ''
            if trig == 'TC':
                reason_s = ' - TC 結構壞'
            elif item.get('note', '').startswith('🔴'):
                reason_s = ' - ' + item['note'][:30]
            elif item.get('priority', 1) == 1:
                reason_s = ' - 低優先'
            lines.append(f"  {C.DIM}{tk} {name}{reason_s}{C.END}")
        lines.append("")


# ─────────────────────────────────────────────────────────────────────────
# Phase 2: 持倉 P&L 監控
# ─────────────────────────────────────────────────────────────────────────

def render_phase2_holdings(client, now_str: str, prev_prices: dict,
                           notified: set, sort_mode: str,
                           do_notify: bool) -> list[str]:
    """Phase 2 持倉 P&L 監控 (9:25 後)."""
    held  = _normalize_held(HELD)
    watch = _normalize_watch(WATCH)

    lines = [
        f"{C.BOLD}━━━ {now_str}  PHASE 2: 持倉 P&L  "
        f"(排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)}) ━━━{C.END}"
    ]

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
                if _market_open:
                    data_status = f"{C.R}❌ API err{C.END}"
                else:
                    data_status = f"{C.DIM}盤前{C.END}"
                c = load_prev_close(tk) or entry
            else:
                data_status = f"{C.G}LIVE{C.END}"
                c = float(snap['close'])
            prev_prices[tk] = c
            pnl     = (c - entry) * shares
            pnl_pct = (c - entry)/entry*100 if entry else 0
            dist    = (c - stop)/c*100 if c else 0
            if not no_data:
                total_pnl += pnl
            # Inline trigger check
            trig_key, trig_reason = check_trigger_inline(tk, tactic)
            maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
            live_data[tk] = {
                'c': c, 'pnl': pnl, 'pnl_pct': pnl_pct,
                'dist_to_stop': dist, 'no_data': no_data,
                'data_status': data_status,
                'trigger': trig_key, 'trigger_reason': trig_reason,
            }
            held_enriched.append(item)
        except Exception as e:
            live_data[tk] = {'error': str(e)}
            held_enriched.append(item)

    # Priority panel (3 lines compact)
    lines.extend(render_priority_panel(held_enriched, watch, live_data))
    lines.append("")

    # Held detail table (no header row to save space — emoji 自帶語意)
    if not held_enriched:
        lines.append(f"{C.DIM}未進場、無持倉監控{C.END}")
    else:
        pass  # 直接列 held rows、省 2 行 header + separator

        for item in sort_items(held_enriched, sort_mode, live_data):
            tk     = item['ticker']
            name   = item['name']
            entry  = item['cost']
            shares = item['shares']
            stop   = item['stop']
            tactic = item.get('tactic', '—')
            pri    = item.get('priority', 2)
            sector = item.get('sector', '?')
            d = live_data.get(tk, {})
            if 'error' in d:
                lines.append(f"  {tk} {name}: err {d['error']}")
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

            stop_tag = '🔴破!' if dist < 0 else ('⚠️緊' if dist < 1 else '🟢')
            trig_fmt = fmt_trigger(trig_key, trig_reason)

            lines.append(
                f"  {tactic:8}  {stars(pri):3}  {tk} {name:6}  "
                f"{'昨' if no_data else '現'}${c:.1f}  "
                f"{fmt_pnl(pnl, pnl_pct):>32}  "
                f"{fmt_dist(dist):>16}  "
                f"{trig_fmt}  [{sector}]  {stop_tag}"
            )

    today = total_pnl + REALIZED
    lines.append("")
    lines.append(f"  帳面 {fmt_pnl(total_pnl)} | 已實現 {fmt_pnl(REALIZED)} | 💰 今日 {fmt_pnl(today)}")

    # Watchlist
    if watch:
        lines.append("")
        lines.append(
            f"{C.DIM}── Watchlist (SKIP)  "
            f"(排序: {SORT_KEY_LABEL.get(sort_mode, sort_mode)}) ──{C.END}"
        )

        watch_enriched = []
        for item in watch:
            tk   = item['ticker']
            ref  = item.get('ref_close') or 0
            stop = item.get('stop')
            tactic = item.get('tactic', '短打')
            try:
                snap = client.get_realtime_snapshot(tk) or {}
                c = float(snap.get('close') or 0)
                pre = False
                if c == 0:
                    c = load_prev_close(tk) or ref
                    pre = True
                chg  = (c - ref)/ref*100 if ref else 0
                dist = (c - stop)/c*100 if (c and stop) else 999
                trig_key, trig_reason = check_trigger_inline(tk, tactic)
                maybe_notify_trigger(tk, item.get('name', tk), trig_key, trig_reason, do_notify)
                live_data[tk] = {
                    'c': c, 'pnl_pct': chg, 'dist_to_stop': dist,
                    'pre': pre, 'trigger': trig_key, 'trigger_reason': trig_reason,
                }
            except Exception:
                live_data[tk] = {}
            watch_enriched.append(item)

        if sort_mode == 'status':
            render_watch_sectioned(watch_enriched, live_data, lines, None, sort_mode)
        else:
            for item in sort_items(watch_enriched, sort_mode, live_data):
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
                chg_color = C.R if chg < 0 else C.G
                wall_tag  = f"{C.DIM}盤前{C.END}" if pre else ('🔴弱' if (stop and dist < 0) else '🟡守')
                trig_fmt  = fmt_trigger(trig_key, trig_reason)
                lines.append(
                    f"  {stars(pri):3} {tactic:6} {tk} {name:6}  "
                    f"${c:.1f} ({chg_color}{chg:+.1f}%{C.END})  "
                    f"距停 {fmt_dist(dist):>16}  "
                    f"{trig_fmt}  [{sector}]  {wall_tag}"
                )

    return lines


# ─────────────────────────────────────────────────────────────────────────
# 快捷鍵 stdin 偵測 (non-blocking)
# ─────────────────────────────────────────────────────────────────────────

def _kb_listener():
    """Background thread: 讀 stdin single char、更新 _current_sort。"""
    mode_map = {'1': 'status', '2': 'priority', '3': 'risk', '4': 'trigger', '5': 'pnl', '6': 'sector'}
    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)
    except Exception:
        return

    try:
        while not _quit_flag[0]:
            try:
                r, _, _ = select.select([sys.stdin], [], [], 0.3)
                if r:
                    ch = sys.stdin.read(1)
                    if ch == 'q':
                        _quit_flag[0] = True
                        break
                    elif ch in mode_map:
                        _current_sort[0] = mode_map[ch]
            except Exception:
                break
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--interval',    type=int, default=30)
    p.add_argument('--no-clear',    action='store_true')
    p.add_argument('--no-notify',   action='store_true')
    p.add_argument('--force-phase', choices=['1', '2'], help='強制階段、debug 用')
    p.add_argument('--sort', choices=SORT_MODES, default='status',
                   help='初始排序模式 (status/priority/risk/trigger/pnl/sector)')
    p.add_argument('--watch-min-priority', type=int, default=2,
                   choices=[1, 2, 3],
                   help='開盤前 WATCH 顯示門檻 (1=全顯/2=預設/3=只看核心)')
    args = p.parse_args()
    _watch_min_priority[0] = args.watch_min_priority

    _current_sort[0] = args.sort
    do_notify = not args.no_notify

    # StageTrigger 載入狀態
    trigger_ok = _stage_engine is not None

    client = FubonClient()
    prev_prices: dict = {}
    notified:    set  = set()

    use_alt = not args.no_clear
    if use_alt:
        sys.stdout.write(C.ALT_ON + C.HIDE)
        sys.stdout.flush()

    kb_thread = threading.Thread(target=_kb_listener, daemon=True)
    kb_thread.start()

    def _emit(line: str):
        sys.stdout.write(line + C.EOL + '\r\n')

    try:
        while not _quit_flag[0]:
            try:
                now     = datetime.now()
                now_str = now.strftime('%H:%M:%S')
                h, m    = now.hour, now.minute

                in_phase1 = h == 9 and m <= 25
                if args.force_phase == '1':
                    in_phase1 = True
                elif args.force_phase == '2':
                    in_phase1 = False

                sort_mode = _current_sort[0]

                if use_alt:
                    sys.stdout.write(C.HOME)

                trig_status = f"{C.G}StageTrigger OK{C.END}" if trigger_ok else f"{C.R}StageTrigger unavailable{C.END}"
                _emit(f"{C.BOLD}{C.B}=== 即時 monitor (interval {args.interval}s)  {now_str} ===  {trig_status}{C.END}")
                _emit(f"{C.DIM}快捷鍵: 1=status(分段) 2=priority 3=risk 4=trigger 5=pnl 6=sector q=退出{C.END}")
                _emit("")

                if in_phase1:
                    for line in render_phase1_screener(client, now_str, sort_mode, do_notify):
                        _emit(line)
                else:
                    for line in render_phase2_holdings(client, now_str, prev_prices,
                                                       notified, sort_mode, do_notify):
                        _emit(line)

                _emit("")
                _emit(f"{C.DIM}下次 {args.interval}s | 排序 [{sort_mode}] | Ctrl+C 或 q 結束{C.END}")
                sys.stdout.write('\033[J')
                sys.stdout.flush()
                time.sleep(args.interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                _emit(f"[ERROR] {e}")
                sys.stdout.flush()
                time.sleep(5)
    finally:
        _quit_flag[0] = True
        if use_alt:
            sys.stdout.write(C.SHOW + C.ALT_OFF)
            sys.stdout.flush()
        print(f"{C.B}結束{C.END}")


if __name__ == '__main__':
    main()
