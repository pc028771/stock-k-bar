"""每日盤後 scanner 批次任務 — 跑三個結構 scanner 找明日打擊區候選.

依 daily scanner enforcement 規則（每個開盤日前晚-早上未跑要提醒）。

每個交易日 14:30 由 launchd 觸發跑此 script:
  1. 跑 shakeout_strong + small_structure + w_bottom_launch 全市場
  2. 取聯集 → 候選清單
  3. shakeout_strong 命中 + 老師常駐族群 → 標 ⭐（EV +10.1% vs +5.1% baseline）
  4. 輸出 markdown 到 /tmp/scanner_candidates_<DATE>.md
  5. 寫 flag 到 /tmp/scanner_done_<DATE>.flag（給 morning_report 跟 Claude session 檢查）

Usage:
  python scripts/zhuli/daily_scanner_job.py [--date YYYY-MM-DD] [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Path setup
_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.extras.shakeout_strong import detect as detect_shakeout        # noqa
from zhuli.entry.small_structure import run_scan as small_structure_scan  # noqa
from zhuli.entry.small_structure import run_post_attack_watchlist, format_post_attack_report  # noqa
from zhuli.entry.small_structure.ma5_pivot_breakout import detect_ma5_pivot  # noqa
from zhuli.entry.small_structure.glued_ma5_platform import detect_glued_ma5_series as detect_glued_ma5  # noqa
from zhuli.entry.w_bottom_launch import detect as detect_wbottom          # noqa
from zhuli.entry.foreign_buy_on_black_k import detect_batch as detect_foreign_black_k_batch  # noqa

# 以下 scanner 尚未驗證門檻值，暫不加入 daily job
# from zhuli.entry.bbands_upper_break import detect as detect_bbands
# from zhuli.entry.bollinger_pullback import detect as detect_bb_pullback
# from zhuli.entry.intraday import detect as detect_intraday
# from zhuli.entry.overnight_swing import detect as detect_overnight
# from zhuli.entry.open_signal_entry import detect as detect_open_entry
# from zhuli.entry.open_signal_exit import detect as detect_open_exit
# from zhuli.entry.open_signal_filter import detect as detect_open_filter
# from zhuli.entry.pennant_flag import detect as detect_pennant
# from zhuli.entry.reversal_breakout import detect as detect_reversal
# from zhuli.entry.suffocation import detect as detect_suffocation

_DB   = Path.home() / ".four_seasons" / "data.sqlite"
_TMP  = Path("/tmp")
_REPO = Path(__file__).parent.parent.parent

# 老師族群對應表（teacher_sector_tickers.json）
# ticker → [族群1, 族群2, ...]
def _load_teacher_sectors() -> dict[str, list[str]]:
    import json
    p = _REPO / "docs" / "主力大課程" / "teacher_sector_tickers.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    mapping: dict[str, list[str]] = {}
    for sector, tickers in data.items():
        for t in tickers:
            mapping.setdefault(t, []).append(sector)
    return mapping

TEACHER_SECTOR_MAP: dict[str, list[str]] = _load_teacher_sectors()


def _load_teacher_picks() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """讀 teacher_picks_2026.json. 回傳 (tier, name, first_mention) per ticker."""
    import json
    p = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"
    if not p.exists():
        return {}, {}, {}
    raw = json.loads(p.read_text())
    tier, name, first = {}, {}, {}
    for t, info in raw.items():
        if t == '_meta':
            continue
        tier[t] = info.get('tier_signal', '')
        name[t] = info.get('name', '')
        mentions = info.get('mentions', [])
        if mentions:
            first[t] = min(m['date'] for m in mentions)
    return tier, name, first


TEACHER_TIER, TEACHER_NAME, TEACHER_FIRST = _load_teacher_picks()


# ── 法人籌碼批次查詢 ─────────────────────────────────────────────────────────────

class MissingChipDataError(RuntimeError):
    """籌碼資料缺失 — strict 模式禁止 fallback / 靜默補值."""


def _load_institutional_chip(tickers: list[str], target_date: str, db_path: Path) -> dict[str, dict]:
    """批次查詢 institutional_investors 近 5 個交易日外資/投信淨買（單位：張）.

    Strict mode: 任一 ticker 沒 row、或 foreign_net/sitc_net 為 NULL → raise.
    """
    if not tickers:
        return {}

    db_uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(db_uri, uri=True, timeout=10)
    ph = ",".join("?" * len(tickers))
    rows = con.execute(
        f"""SELECT ticker, SUM(foreign_net) AS f5d, SUM(sitc_net) AS s5d
            FROM institutional_investors
            WHERE ticker IN ({ph})
              AND trade_date >= date(?, '-7 days')
              AND trade_date <= ?
            GROUP BY ticker""",
        tickers + [target_date, target_date],
    ).fetchall()
    con.close()

    result: dict[str, dict] = {}
    for ticker, f5d, s5d in rows:
        if f5d is None or s5d is None:
            raise MissingChipDataError(
                f"institutional NULL for {ticker} @ {target_date} (f5d={f5d}, s5d={s5d})"
            )
        f5d = float(f5d)
        s5d = float(s5d)
        result[ticker] = {
            "foreign_5d": round(f5d),
            "sitc_5d": round(s5d),
            "tag": _chip_tag(f5d, s5d),
        }

    missing = set(tickers) - set(result.keys())
    if missing:
        raise MissingChipDataError(
            f"institutional 缺 {len(missing)} 檔 @ {target_date}: {sorted(missing)}"
        )
    return result


def _chip_tag(foreign_5d: float, sitc_5d: float) -> str:
    """依外資/投信 5 日淨買（張）計算籌碼 tag."""
    if foreign_5d >= 2000 and sitc_5d >= 0:
        return "🟢 外資強買"
    if 500 <= foreign_5d < 2000 and sitc_5d >= 0:
        return "🟡 外資中買"
    if foreign_5d < 0 and sitc_5d >= 200:
        return "🟡 投信買"
    if foreign_5d < -2000:
        return "🔴 外資強賣"
    return "⚪ 中性"


def _foreign_black_k_chip_tag(foreign_5d: float, sitc_5d: float) -> str:
    """外資大買黑K 條件觀察專用 tag (老師 6/3 教法)."""
    base = _chip_tag(foreign_5d, sitc_5d)
    # 外資 5d 為負但每日大買是可能的（黑K壓盤期），加 🐂 標記
    return f"🐂 條件觀察 ({base})"


def _fmt_chip_cols(chip: dict) -> tuple[str, str, str]:
    """回傳 (外資5d, 投信5d, tag) 三個欄位字串. Strict: chip 必須是 dict."""
    f = chip["foreign_5d"]
    s = chip["sitc_5d"]
    tag = chip["tag"]
    broker_tag = chip.get("broker_tag", "")
    if broker_tag:
        tag = f"{tag} {broker_tag}"
    return f"{f:+,}", f"{s:+,}", tag


# ── 老師分點 tier 1 快取掃描 ──────────────────────────────────────────────────

_BROKER_CACHE_DIR = Path.home() / ".zhuli_cache" / "broker"

# 老師分點 patterns（與 teacher_broker_signal.py 對齊，加入 5/31 新分點）
_TEACHER_BROKER_PATTERNS: dict[str, str] = {
    "站前哥（凱基站前）": r"凱基.*站前",
    "管錢哥（元大館前）": r"元大.*館前",
    "永豐金惠利":         r"永豐.*惠利",
    "永豐金潮州":         r"永豐.*潮州",
    "永豐金屏東":         r"永豐.*屏東",
    "台新屏東":           r"台新.*屏東",
    "富邦新店":           r"富邦.*新店",    # 5/31 影片新加
    "富邦南港":           r"富邦.*南港",    # 5/31 影片新加
}

# Tier 1: 站前哥/管錢哥 (老師原話「非常厲害」)
_BROKER_TIER1_LABELS = frozenset(["站前哥（凱基站前）", "管錢哥（元大館前）"])


def _load_broker_chip(tickers: list[str], target_date: str) -> dict[str, str]:
    """從磁碟快取查 ticker 是否有老師分點 tier 1 在 target_date 買入.

    Strict mode:
      - 快取目錄不存在 → raise
      - 該 ticker target_date 沒檔案 → raise (沒 fallback)
      - 壞 json → raise
      - 檔案存在但無 tier 命中 → "" (合法零訊號)
    """
    import json
    import re as _re

    if not _BROKER_CACHE_DIR.exists():
        raise MissingChipDataError(f"broker cache dir 不存在: {_BROKER_CACHE_DIR}")

    result: dict[str, str] = {}
    for ticker in tickers:
        cache = _BROKER_CACHE_DIR / f"{ticker}_{target_date}.json"
        if not cache.exists():
            raise MissingChipDataError(f"broker cache 缺 {ticker} @ {target_date}: {cache}")
        data = json.loads(cache.read_text())

        broker_net: dict[str, int] = {}
        for row in data:
            name = row.get("securities_trader", "")
            buy  = row.get("buy", 0) or 0
            sell = row.get("sell", 0) or 0
            net  = (buy - sell) // 1000
            broker_net[name] = broker_net.get(name, 0) + net

        tier1_hits = []
        tier2_hits = []
        for label, pattern in _TEACHER_BROKER_PATTERNS.items():
            for name, net_lots in broker_net.items():
                if _re.search(pattern, name) and net_lots > 0:
                    if label in _BROKER_TIER1_LABELS:
                        tier1_hits.append((label, net_lots))
                    else:
                        tier2_hits.append((label, net_lots))

        if tier1_hits:
            tier1_hits.sort(key=lambda x: -x[1])
            top = tier1_hits[0][0].split("（")[0]  # "站前哥"
            result[ticker] = f"⭐ {top}"
        elif tier2_hits:
            tier2_hits.sort(key=lambda x: -x[1])
            top = tier2_hits[0][0]
            result[ticker] = f"🔸 {top}"
        else:
            result[ticker] = ""

    return result


# Tier-A ticker 清單（從 cross_reference.py 統計：老師指名 × P90+ rate ≥30%, n≥2）
TIER_A_WBOTTOM = {
    '3016', '3037', '3189', '3481', '4919', '8027', '6173',
    '2454', '3026', '4576', '4958', '8064', '2327', '6285',
}
TIER_A_SMALLSTR = {
    '2303', '3189', '4958', '2454', '3036', '8103', '3702', '4919',
}

# 老師 core 但回測未抓到的 ticker（單獨觀察清單）
CORE_UNCOVERED = ['1605', '6664', '6217', '6207', '1785']

# 距 MA10 score (6/3 校正、不再 hard rule、改為「籌碼優先 → 距離次之」)
# 來源: 老師「離軍線很遠不追」(5/19 line 676) + Ch5-2「離 MA20 <30%」
# 規則 (見 feedback_trading_discipline_checklist):
#   Step 1 看籌碼:
#     雙籌碼 (外資 + 投信都加) → 忽略距 MA10
#     單籌碼                    → 距 MA10 當提醒、不擋
#     無籌碼                    → 進入 Step 2 score
#   Step 2 score (僅在無籌碼時):
MA10_DIST_SCORE_TIERS = [
    (5,   '🥇',  '打擊區'),
    (10,  '🥈',  '健康延續'),
    (15,  '🥉',  '偏遠、配合族群評估'),
    (25,  '⚠️',  '右上角第 3-4 段、慎入'),
    (999, '❌',  '末段、不追'),
]
# 籌碼門檻 (5d 累計)
FOREIGN_BUY_THRESHOLD = 1000   # 外資 5d ≥ +1000 張 = 有買盤
SITC_BUY_THRESHOLD = 200       # 投信 5d ≥ +200 張 = 有買盤

# Backward compat (其他段落仍引用)
MA10_DIST_ENTRY_OK = 5.0    # 🥇 打擊區門檻
MA10_DIST_RISKY = 15.0      # 改為 15、舊版 10 太嚴、配合 score 化
# 老師明示族群續強 (夜盤訊號) 時、可放寬到 +20% (見 feedback_night_session_signal_relative_value)
MA10_DIST_OVERRIDE_RELAXED = 20.0


def evaluate_dist_ma10(dist_pct, foreign_5d=None, sitc_5d=None):
    """
    籌碼優先評估距 MA10.
    回傳 (level, icon, label):
      level: 'ignore' / 'remind' / 'score'
      雙籌碼 → ignore 距 MA10
      單籌碼 → remind (僅顯示、不擋)
      無籌碼 → score (打擊區 / 健康 / 偏遠 / 慎入 / 末段)
    """
    if dist_pct is None:
        return ('score', '—', '無 MA10')
    has_foreign = foreign_5d is not None and foreign_5d >= FOREIGN_BUY_THRESHOLD
    has_sitc = sitc_5d is not None and sitc_5d >= SITC_BUY_THRESHOLD
    if has_foreign and has_sitc:
        return ('ignore', '🟢', f'雙籌碼 (外+{foreign_5d:,}/投+{sitc_5d:,})、距 MA10 忽略')
    if has_foreign or has_sitc:
        return ('remind', '🟡', f'單籌碼、距 MA10 {dist_pct:+.1f}% 提醒')
    # 無籌碼、進入 score
    for threshold, icon, label in MA10_DIST_SCORE_TIERS:
        if dist_pct <= threshold:
            return ('score', icon, label)
    return ('score', '❌', '末段')


def dist_ma10_score(dist_pct):
    """舊 API、不考慮籌碼、僅 score (向後相容)"""
    if dist_pct is None:
        return ('—', '無資料')
    for threshold, icon, label in MA10_DIST_SCORE_TIERS:
        if dist_pct <= threshold:
            return (icon, label)
    return ('❌', '末段')


def _db_uri(path: Path) -> str:
    return f"file:{path}?mode=ro"


def load_stock_info(db_path: Path) -> dict[str, dict]:
    """回傳 {ticker: {name, industry}} 對照表."""
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=5)
    rows = con.execute(
        "SELECT ticker, stock_name, industry_category FROM stock_info"
    ).fetchall()
    con.close()
    return {r[0]: {"name": r[1], "industry": r[2] or ""} for r in rows}


def _build_hit_dict(
    t: str,
    df: pd.DataFrame,
    scanner_name: str,
    stock_info: dict,
    target_date: str,
    vol_ratio_min: float,
    exit_strategy: str,
) -> dict | None:
    """單 ticker + scanner 命中後建立 hit dict，回傳 None 表示過濾掉."""
    last_row = df.iloc[-1]
    last_close = last_row['close']
    last_vol_ratio = float(last_row['vol_ratio_20']) if pd.notna(last_row.get('vol_ratio_20')) else 0

    if last_vol_ratio < vol_ratio_min:
        return None

    info = stock_info.get(t, {"name": "", "industry": ""})
    teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])

    ma10 = float(last_row['ma10']) if pd.notna(last_row.get('ma10')) else None
    if scanner_name in ('w_bottom_launch', 'shakeout_strong') and ma10:
        stop_note = f"MA10停利 ~{ma10:.2f}"
    else:
        stop_px = round(float(df.iloc[-6:-1]['close'].min()), 2)
        stop_note = f"守底{stop_px:.2f}"

    dist_ma10 = None
    if ma10 and ma10 > 0:
        dist_ma10 = round((float(last_close) - ma10) / ma10 * 100, 1)

    teacher_tier = TEACHER_TIER.get(t, '')
    days_since = None
    if t in TEACHER_FIRST:
        days_since = (pd.to_datetime(target_date) - pd.to_datetime(TEACHER_FIRST[t])).days

    tier = '一般'
    timing_bonus = ''
    if scanner_name == 'w_bottom_launch':
        if t in TIER_A_WBOTTOM:
            tier = '🔥 Tier-A'
        elif teacher_tier in ('core', 'frequent'):
            tier = '⭐ Tier-B'
        if days_since is not None and 8 <= days_since <= 30:
            timing_bonus = ' ✨黃金期'
    elif scanner_name == 'small_structure':
        if t in TIER_A_SMALLSTR:
            tier = '🔥 Tier-A'
        elif teacher_tier in ('core', 'frequent'):
            tier = '⭐ Tier-B'
        if days_since is not None and days_since > 30:
            timing_bonus = ' ✨二波期'
    elif scanner_name == 'shakeout_strong':
        tier = '➕ 加碼用'

    return {
        'ticker': t,
        'name': info['name'],
        'industry': info['industry'],
        'teacher_sectors': teacher_sectors,
        'close': float(last_close),
        'vol_ratio': round(last_vol_ratio, 1),
        'stop_note': stop_note,
        'exit_strategy': exit_strategy,
        'tier': tier,
        'timing_bonus': timing_bonus,
        'teacher_tier': teacher_tier,
        'days_since_first_mention': days_since,
        'dist_ma10_pct': dist_ma10,
    }


def run_scanners(target_date: str, db_path: Path) -> dict[str, list[dict]]:
    """跑三個 scanner 並回傳每個的命中清單.

    small_structure 改用 run_scan(combined_df, universe='sector_week')，
    由 watchlist.py 統一處理族群過濾 + tier 分類。
    shakeout_strong + w_bottom_launch 維持原有 per-ticker 邏輯。
    """
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=15)
    stock_info = load_stock_info(db_path)

    # 全市場 ticker
    all_tickers = [
        r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar WHERE trade_date=?",
            (target_date,)
        ).fetchall()
    ]

    results = {
        'shakeout_strong': [], 'small_structure': [], 'w_bottom_launch': [],
        'ma5_pivot': [], 'glued_ma5': [],
        'institutional_firstbuy': [], 'institutional_swing': [],
        'foreign_buy_on_black_k': [],
    }

    # ⚠️ 只放已驗證門檻的 scanner
    VOL_RATIO_MIN = {
        'w_bottom_launch': 2.0,
        'shakeout_strong': 2.0,
    }
    EXIT_STRATEGY = {
        'w_bottom_launch': 'ma5_trail',
        'small_structure': 'structural_low',
        'shakeout_strong': 'ma5_trail',
    }

    # ── shakeout_strong + w_bottom_launch：維持 per-ticker 邏輯 ─────────────
    per_ticker_scanners = {
        'w_bottom_launch': detect_wbottom,   # 84% 上漲、平均 +2.54%（已驗證）
        'shakeout_strong': detect_shakeout,  # 3/3 案例命中（已驗證，需 overhead 特徵）
    }

    # 同時載入 df，供 small_structure combined df 使用
    ticker_dfs: dict[str, pd.DataFrame] = {}

    for t in all_tickers:
        df = pd.read_sql("""
            SELECT ? as ticker,
                   trade_date, trade_date as date,
                   open, high, low, close, volume,
                   vol_ratio_20, ma5, ma10, ma20, ma60,
                   vol_ma20, bb_upper, bb_lower, bb_mid,
                   ma20_slope, ma20_slope_proxy
            FROM standard_daily_bar
            WHERE ticker=? AND trade_date >= date(?, '-200 days') AND trade_date <= ?
            ORDER BY trade_date
        """, con, params=(t, t, target_date, target_date))
        if len(df) < 100:
            continue

        # 補充 derived columns
        df['prev_close'] = df['close'].shift(1)
        df['prev_open'] = df['open'].shift(1)
        df['prev_high'] = df['high'].shift(1)
        df['prev_low'] = df['low'].shift(1)
        df['ma5_slope_5d'] = df['ma5'].diff(5)
        df['volume_ratio'] = df['vol_ratio_20']  # alias

        # ── shakeout_strong 需要的衍生欄位 ──────────────────────────────────
        # prior_high_60：過去 60 根 K 棒最高點（不含當日），突破基準
        df['prior_high_60'] = df['high'].rolling(60, min_periods=20).max().shift(1)
        # breakout_strength_pct：突破幅度（%）
        df['breakout_strength_pct'] = (
            df['close'] / df['prior_high_60'].replace(0, float('nan')) - 1
        ) * 100
        # breakout_next_low_open：次日開低（次日開盤 < 今日收盤）
        df['breakout_next_low_open'] = (df['open'].shift(-1) < df['close']).fillna(False)
        # overhead_supply_layer：過去 240 根中仍在當日收盤以上的 swing-high 峰數
        # 使用簡化向量化計算（等效 features.py 邏輯，但 per-ticker df 不需 groupby）
        LOOKBACK = 240
        _n = len(df)
        _peak_count = np.zeros(_n, dtype=float)
        _close_arr = df['close'].to_numpy()
        _high_arr = df['high'].to_numpy()
        for _lag in range(1, LOOKBACK + 1):
            _past_high = pd.Series(_high_arr).shift(_lag).to_numpy()
            _past_max5 = pd.Series(_high_arr).shift(_lag).rolling(5, min_periods=5).max().to_numpy()
            _is_peak = (_past_high == _past_max5) & ~np.isnan(_past_max5)
            _peak_count += ((_past_high > _close_arr) & _is_peak).astype(float)
        _has_history = np.arange(_n) >= 20
        df['overhead_supply_layer'] = np.where(_has_history, _peak_count, np.nan)
        # ────────────────────────────────────────────────────────────────────

        ticker_dfs[t] = df

        for scanner_name, fn in per_ticker_scanners.items():
            try:
                sig = fn(df)
                if hasattr(sig, 'iloc') and sig.iloc[-1]:
                    hit = _build_hit_dict(
                        t, df, scanner_name, stock_info, target_date,
                        VOL_RATIO_MIN[scanner_name], EXIT_STRATEGY[scanner_name],
                    )
                    if hit is not None:
                        results[scanner_name].append(hit)
            except Exception:
                pass

    con.close()

    # ── 批次載入外資/投信近 10 日資料 → 注入 ticker_dfs ───────────────────────────
    print(f"  [institutional] 批次載入近 10 日外資/投信資料...", flush=True)
    try:
        con_inst = sqlite3.connect(_db_uri(db_path), uri=True, timeout=15)
        inst_tickers = list(ticker_dfs.keys())
        _ph = ",".join("?" * len(inst_tickers)) if inst_tickers else "''"
        inst_rows = con_inst.execute(
            f"""SELECT ticker, trade_date, foreign_net, sitc_net
                FROM institutional_investors
                WHERE ticker IN ({_ph})
                  AND trade_date >= date(?, '-10 days')
                  AND trade_date <= ?
                ORDER BY ticker, trade_date""",
            inst_tickers + [target_date, target_date],
        ).fetchall() if inst_tickers else []
        con_inst.close()

        # 建 (ticker, date) → foreign_net/sitc_net 對照
        _inst_map: dict[tuple[str, str], tuple[float, float]] = {}
        for row in inst_rows:
            _inst_map[(row[0], str(row[1])[:10])] = (float(row[2] or 0), float(row[3] or 0))

        for t, df_t in ticker_dfs.items():
            dates_str = df_t['trade_date'].astype(str).str[:10]
            df_t['foreign_net'] = dates_str.apply(lambda d: _inst_map.get((t, d), (0.0, 0.0))[0])
            df_t['sitc_net_daily'] = dates_str.apply(lambda d: _inst_map.get((t, d), (0.0, 0.0))[1])

        print(f"  [institutional] 注入完成 ({len(_inst_map)} rows)", flush=True)
    except Exception as _e:
        print(f"  [institutional] 批次載入失敗: {_e}（foreign_net 設 0）", flush=True)
        for df_t in ticker_dfs.values():
            if 'foreign_net' not in df_t.columns:
                df_t['foreign_net'] = 0.0
            if 'sitc_net_daily' not in df_t.columns:
                df_t['sitc_net_daily'] = 0.0

    # ── 外資大買黑K連2天 scanner ───────────────────────────────────────────────
    print(f"  [foreign_buy_on_black_k] 掃描外資大買黑K連2天...", flush=True)
    try:
        fbk_hits = detect_foreign_black_k_batch(
            ticker_dfs=ticker_dfs,
            stock_info=stock_info,
            teacher_sector_map=TEACHER_SECTOR_MAP,
            target_date=target_date,
        )
        results['foreign_buy_on_black_k'] = fbk_hits
        print(f"  [foreign_buy_on_black_k] 找到 {len(fbk_hits)} 檔", flush=True)
    except Exception as _e:
        print(f"  [foreign_buy_on_black_k] 失敗: {_e}", flush=True)

    # ── J 投信首買 scanner ─────────────────────────────────────────────────────
    print(f"  [institutional_firstbuy] 掃描 J 投信首買...", flush=True)
    try:
        from zhuli.entry.institutional_firstbuy import (
            detect as detect_j_firstbuy,
            load_institutional as load_inst_j,
        )
        from zhuli.config import InstitutionalFirstBuyConfig
        if ticker_dfs:
            combined_inst_df = pd.concat(list(ticker_dfs.values()), ignore_index=True)
            # 補 ideal_ma_align / is_red / is_black（J scanner 需要）
            combined_inst_df['is_black'] = combined_inst_df['close'] < combined_inst_df['open']
            combined_inst_df['is_red'] = combined_inst_df['close'] > combined_inst_df['open']
            # ideal_ma_align: ma5 > ma10 > ma20 > ma60 全上彎 (proxy: slope > 0)
            combined_inst_df['ideal_ma_align'] = (
                (combined_inst_df['ma5'] > combined_inst_df['ma10'])
                & (combined_inst_df['ma10'] > combined_inst_df['ma20'])
                & (combined_inst_df['ma20'] > combined_inst_df['ma60'].fillna(0))
            )
            combined_inst_df['trade_date'] = pd.to_datetime(combined_inst_df['trade_date'])

            inst_raw_df = load_inst_j(db_path)
            j_cfg = InstitutionalFirstBuyConfig()
            j_signals = detect_j_firstbuy(
                df=combined_inst_df,
                cfg=j_cfg,
                inst_df=inst_raw_df,
                db_path=db_path,
            )
            # 過濾只取 target_date 的訊號
            if not j_signals.empty:
                j_today = j_signals[
                    j_signals['signal_date'].astype(str).str[:10] == target_date
                ]
            else:
                j_today = j_signals

            for _, row in j_today.iterrows():
                t = row['ticker']
                info = stock_info.get(t, {"name": "", "industry": ""})
                teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])
                teacher_tier = TEACHER_TIER.get(t, '')
                days_since = None
                if t in TEACHER_FIRST:
                    days_since = (pd.to_datetime(target_date) - pd.to_datetime(TEACHER_FIRST[t])).days
                close_val = float(row.get('close') or 0)
                ma10_val = float(row.get('ma10') or 0) if pd.notna(row.get('ma10')) else None
                dist_ma10 = round((close_val - ma10_val) / ma10_val * 100, 1) if ma10_val else None
                tier = '⭐ Tier-B' if teacher_tier in ('core', 'frequent') else '一般'
                results['institutional_firstbuy'].append({
                    'ticker': t,
                    'name': info['name'],
                    'industry': info['industry'],
                    'teacher_sectors': teacher_sectors,
                    'close': close_val,
                    'sitc_net': float(row.get('sitc_net') or 0),
                    'price_divergence': bool(row.get('price_divergence', False)),
                    'ideal_ma_align': bool(row.get('ideal_ma_align', False)),
                    'entry_note': str(row.get('entry_note', '')),
                    'stop_note': f"MA10停損 {ma10_val:.2f}" if ma10_val else '—',
                    'tier': tier,
                    'timing_bonus': '',
                    'teacher_tier': teacher_tier,
                    'days_since_first_mention': days_since,
                    'dist_ma10_pct': dist_ma10,
                    'vol_ratio': 0.0,
                })
        print(f"  [institutional_firstbuy] 找到 {len(results['institutional_firstbuy'])} 檔", flush=True)
    except Exception as _e:
        print(f"  [institutional_firstbuy] 失敗: {_e}", flush=True)

    # ── I 投信跟單 scanner ─────────────────────────────────────────────────────
    print(f"  [institutional_swing] 掃描 I 投信跟單...", flush=True)
    try:
        from zhuli.entry.institutional_swing import detect as detect_i_swing
        from zhuli.config import InstitutionalSwingConfig
        if ticker_dfs:
            combined_swing_df = pd.concat(list(ticker_dfs.values()), ignore_index=True)
            # 確保 trade_date 為 datetime
            combined_swing_df['trade_date'] = pd.to_datetime(combined_swing_df['trade_date'])
            # 補 ma5_slope_5d（若已有直接用）
            if 'ma5_slope_5d' not in combined_swing_df.columns:
                combined_swing_df['ma5_slope_5d'] = combined_swing_df.groupby('ticker')['ma5'].transform(lambda s: s.diff(5))

            i_cfg = InstitutionalSwingConfig()
            i_signals = detect_i_swing(
                df=combined_swing_df,
                cfg=i_cfg,
                db_path=db_path,
            )
            if not i_signals.empty:
                i_today = i_signals[
                    i_signals['signal_date'].astype(str).str[:10] == target_date
                ]
            else:
                i_today = i_signals

            for _, row in i_today.iterrows():
                t = row['ticker']
                info = stock_info.get(t, {"name": "", "industry": ""})
                teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])
                teacher_tier = TEACHER_TIER.get(t, '')
                days_since = None
                if t in TEACHER_FIRST:
                    days_since = (pd.to_datetime(target_date) - pd.to_datetime(TEACHER_FIRST[t])).days
                close_val = float(row.get('close') or 0)
                stop_val = float(row.get('stop_loss') or 0) if pd.notna(row.get('stop_loss')) else None
                dist_ma10 = None
                if stop_val:
                    dist_ma10 = round((close_val - stop_val) / stop_val * 100, 1)
                tier = '⭐ Tier-B' if teacher_tier in ('core', 'frequent') else '一般'
                results['institutional_swing'].append({
                    'ticker': t,
                    'name': info['name'],
                    'industry': info['industry'],
                    'teacher_sectors': teacher_sectors,
                    'close': close_val,
                    'sitc_buy_5d': float(row.get('sitc_buy_5d') or 0),
                    'buy_pct_of_shares': float(row.get('buy_pct_of_shares') or 0),
                    'is_first_appearance': bool(row.get('is_first_appearance', False)),
                    'ma_alignment_ok': bool(row.get('ma_alignment_ok', False)),
                    'entry_note': str(row.get('entry_note', '')),
                    'stop_note': f"MA10停損 {stop_val:.2f}" if stop_val else '—',
                    'tier': tier,
                    'timing_bonus': '',
                    'teacher_tier': teacher_tier,
                    'days_since_first_mention': days_since,
                    'dist_ma10_pct': dist_ma10,
                    'vol_ratio': 0.0,
                })
        print(f"  [institutional_swing] 找到 {len(results['institutional_swing'])} 檔", flush=True)
    except Exception as _e:
        print(f"  [institutional_swing] 失敗: {_e}", flush=True)

    # ── small_structure：改用 run_scan(combined_df, universe='sector_week') ──
    # run_scan 在 watchlist_mode=True 時呼叫 run_watchlist，
    # 內部處理 sector_week 過濾 + 條件命中分 tier，不再需要 per-ticker iteration。
    print(f"  [small_structure] 使用 run_scan(universe='sector_week')...")
    try:
        if ticker_dfs:
            combined_df = pd.concat(list(ticker_dfs.values()), ignore_index=True)
            ss_wl = small_structure_scan(
                combined_df,
                target_date=target_date,
                universe='sector_week',
                watchlist_mode=True,
            )
        else:
            ss_wl = pd.DataFrame()

        if ss_wl is None or (hasattr(ss_wl, 'empty') and ss_wl.empty):
            print("  [small_structure] sector_week 無主推族群或無命中 → 候選數 0")
            ss_wl = pd.DataFrame()

        # 將 watchlist DataFrame 轉成與其他 scanner 相同格式的 hit dict list
        for _, row in ss_wl.iterrows():
            t = row.get('ticker', '')
            if not t:
                continue
            df_t = ticker_dfs.get(t)
            if df_t is None or df_t.empty:
                # 沒有載入此 ticker 的 df（可能 <100 筆被過濾），用 row 欄位補
                last_close = row.get('close', 0)
                ma10_val = None
                last_vol_ratio = 0.0
                stop_note = '—'
                dist_ma10 = None
            else:
                last_row = df_t.iloc[-1]
                last_close = last_row['close']
                last_vol_ratio = float(last_row['vol_ratio_20']) if pd.notna(last_row.get('vol_ratio_20')) else 0
                ma10_val = float(last_row['ma10']) if pd.notna(last_row.get('ma10')) else None
                stop_px = round(float(df_t.iloc[-6:-1]['close'].min()), 2)
                stop_note = f"守底{stop_px:.2f}"
                dist_ma10 = round((float(last_close) - ma10_val) / ma10_val * 100, 1) if ma10_val else None

            info = stock_info.get(t, {"name": "", "industry": ""})
            teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])
            teacher_tier = TEACHER_TIER.get(t, '')
            days_since = None
            if t in TEACHER_FIRST:
                days_since = (pd.to_datetime(target_date) - pd.to_datetime(TEACHER_FIRST[t])).days

            # Tier mapping：watchlist tier → daily_scanner_job tier
            wl_tier = row.get('tier', '')
            if wl_tier == '🔥 高機率':
                tier = '🔥 Tier-A' if t in TIER_A_SMALLSTR else ('⭐ Tier-B' if teacher_tier in ('core', 'frequent') else '一般')
            elif wl_tier == '⚠️ 中機率':
                tier = '⭐ Tier-B' if teacher_tier in ('core', 'frequent') else '一般'
            else:
                tier = '一般'

            timing_bonus = ' ✨二波期' if (days_since is not None and days_since > 30) else ''

            hit = {
                'ticker': t,
                'name': info['name'],
                'industry': info['industry'],
                'teacher_sectors': teacher_sectors,
                'close': float(last_close),
                'vol_ratio': round(last_vol_ratio, 1),
                'stop_note': stop_note,
                'exit_strategy': EXIT_STRATEGY['small_structure'],
                'tier': tier,
                'timing_bonus': timing_bonus,
                'teacher_tier': teacher_tier,
                'days_since_first_mention': days_since,
                'dist_ma10_pct': dist_ma10,
            }
            results['small_structure'].append(hit)

    except Exception as e:
        print(f"  [small_structure] run_scan 失敗: {e}（小結構候選數 0）")

    # ── post_attack watchlist（攻擊後盤整早期追蹤）────────────────────────────
    # universe='sector_all'：涵蓋老師「曾明示過」的所有族群（包含 IPC、低軌衛星、航太國防等）
    # 不限「本週主推」(sector_week)，避免漏抓如 4916 事欣科類型的非當週主推但強勢標的
    # 根因：4916 5/15-6/3 +84% 但 5/28 scanner 以 sector_week 漏抓
    print(f"  [post_attack] 攻擊後盤整追蹤 (sector_all — 老師曾明示所有族群)...")
    results['post_attack_watchlist'] = pd.DataFrame()
    try:
        if ticker_dfs:
            combined_df2 = pd.concat(list(ticker_dfs.values()), ignore_index=True)
            pa_wl = run_post_attack_watchlist(
                combined_df2,
                universe='sector_all',
                target_date=target_date,
                ticker_col='ticker',
            )
            if pa_wl is not None and not pa_wl.empty:
                # 加名稱欄位
                pa_wl['name'] = pa_wl['ticker'].map(lambda t: stock_info.get(t, {}).get('name', ''))
                # 加族群欄位
                pa_wl['teacher_sectors'] = pa_wl['ticker'].map(
                    lambda t: '/'.join(TEACHER_SECTOR_MAP.get(t, [])) or ''
                )
                results['post_attack_watchlist'] = pa_wl
                print(f"  [post_attack] 找到 {len(pa_wl)} 檔攻擊後盤整候選")
            else:
                print(f"  [post_attack] 無命中")
        else:
            print(f"  [post_attack] 無資料")
    except Exception as e:
        print(f"  [post_attack] 失敗: {e}")

    # ── ma5_pivot_breakout：攻擊→平台→攻擊型長線多頭 ─────────────────────────
    # 用 sector_week universe 過濾 (跟 small_structure 一致)
    print(f"  [ma5_pivot] 掃描 MA5 pivot 突破 (MA60/120/240 全🟢、sector_week 過濾)...")
    try:
        from zhuli.entry.small_structure.watchlist import (
            _parse_sector_timeline, _get_week_sectors,
            _load_sector_tickers_json, _sectors_to_tickers,
        )
        _timeline = _parse_sector_timeline()
        _week_sectors = _get_week_sectors(target_date, _timeline)
        _sector_map = _load_sector_tickers_json()
        _sector_week_universe = _sectors_to_tickers(_week_sectors, _sector_map)
        if not _sector_week_universe:
            print("  [ma5_pivot] sector_week 無主推族群、跳過")
            results['ma5_pivot'] = []
            raise StopIteration
    except (ImportError, StopIteration):
        _sector_week_universe = set()

    try:
        con2 = sqlite3.connect(_db_uri(db_path), uri=True, timeout=15)
        for t in all_tickers:
            # sector_week 過濾
            if _sector_week_universe and t not in _sector_week_universe:
                continue
            # 需要 ma60/ma240 + 自算 ma120 (rolling 120)
            # 需要較長歷史 (500天) 確保 ma120/ma240 穩定
            df_p = pd.read_sql("""
                SELECT trade_date, close, ma5, ma60, ma240
                FROM standard_daily_bar
                WHERE ticker=? AND trade_date >= date(?, '-500 days') AND trade_date <= ?
                ORDER BY trade_date
            """, con2, params=(t, target_date, target_date))
            if len(df_p) < 130:
                continue
            try:
                sig = detect_ma5_pivot(df_p)
                if hasattr(sig, 'iloc') and sig.iloc[-1]:
                    last_row = df_p.iloc[-1]
                    info = stock_info.get(t, {"name": "", "industry": ""})
                    teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])
                    ma10_val = None
                    # get ma10 from ticker_dfs if available
                    if t in ticker_dfs:
                        last_main = ticker_dfs[t].iloc[-1]
                        ma10_val = float(last_main['ma10']) if pd.notna(last_main.get('ma10')) else None
                    dist_ma10 = round((float(last_row['close']) - ma10_val) / ma10_val * 100, 1) if ma10_val else None
                    teacher_tier = TEACHER_TIER.get(t, '')
                    days_since = None
                    if t in TEACHER_FIRST:
                        days_since = (pd.to_datetime(target_date) - pd.to_datetime(TEACHER_FIRST[t])).days

                    # MA5 slope % of close (平台深度 proxy)
                    ma5_slope_today = float(df_p['ma5'].diff().iloc[-1])
                    ma5_slope_pct = round(abs(ma5_slope_today) / float(last_row['close']) * 100, 3)

                    results['ma5_pivot'].append({
                        'ticker': t,
                        'name': info['name'],
                        'industry': info['industry'],
                        'teacher_sectors': teacher_sectors,
                        'close': float(last_row['close']),
                        'ma5_slope_pct': ma5_slope_pct,
                        'dist_ma10_pct': dist_ma10,
                        'teacher_tier': teacher_tier,
                        'days_since_first_mention': days_since,
                    })
            except Exception:
                pass
        con2.close()
        print(f"  [ma5_pivot] 找到 {len(results['ma5_pivot'])} 檔")
    except Exception as e:
        print(f"  [ma5_pivot] 失敗: {e}")

    # ── glued_ma5_platform：黏 MA5 平台中（watchlist，等突破）─────────────────
    # 跟 ma5_pivot 互補：此為「平台中」、ma5_pivot 為「突破當下」
    print(f"  [glued_ma5] 掃描黏 MA5 平台 (sector_week 過濾)...")
    try:
        con3 = sqlite3.connect(_db_uri(db_path), uri=True, timeout=15)
        for t in all_tickers:
            if _sector_week_universe and t not in _sector_week_universe:
                continue
            # 需要 600 天歷史確保 MA240 穩定（自算）
            df_g = pd.read_sql("""
                SELECT trade_date, close, ma5, ma10
                FROM standard_daily_bar
                WHERE ticker=? AND trade_date >= date(?, '-600 days') AND trade_date <= ?
                ORDER BY trade_date
            """, con3, params=(t, target_date, target_date))
            if len(df_g) < 250:  # 至少 240 天歷史
                continue
            try:
                sig = detect_glued_ma5(df_g)
                if hasattr(sig, 'iloc') and sig.iloc[-1]:
                    last_row = df_g.iloc[-1]
                    info = stock_info.get(t, {"name": "", "industry": ""})
                    teacher_sectors = TEACHER_SECTOR_MAP.get(t, [])
                    teacher_tier = TEACHER_TIER.get(t, '')
                    days_since = None
                    if t in TEACHER_FIRST:
                        days_since = (pd.to_datetime(target_date) - pd.to_datetime(TEACHER_FIRST[t])).days

                    # 計算黏 MA5 天數 streak
                    from zhuli.entry.small_structure.glued_ma5_platform import get_streak_length
                    streak_ser = get_streak_length(df_g)
                    streak_days = int(streak_ser.iloc[-1]) if not streak_ser.empty else 0

                    # 平均距 MA5（最近 streak 天）
                    dist_ma5_now = abs(float(last_row['close']) - float(last_row['ma5'])) / float(last_row['ma5']) * 100

                    # 距 MA10
                    ma10_val = None
                    if t in ticker_dfs:
                        last_main = ticker_dfs[t].iloc[-1]
                        ma10_val = float(last_main['ma10']) if pd.notna(last_main.get('ma10')) else None
                    dist_ma10_g = round((float(last_row['close']) - ma10_val) / ma10_val * 100, 1) if ma10_val else None

                    results['glued_ma5'].append({
                        'ticker': t,
                        'name': info['name'],
                        'industry': info['industry'],
                        'teacher_sectors': teacher_sectors,
                        'close': float(last_row['close']),
                        'streak_days': streak_days,
                        'dist_ma5_pct': round(dist_ma5_now, 2),
                        'dist_ma10_pct': dist_ma10_g,
                        'teacher_tier': teacher_tier,
                        'days_since_first_mention': days_since,
                    })
            except Exception:
                pass
        con3.close()
        print(f"  [glued_ma5] 找到 {len(results['glued_ma5'])} 檔")
    except Exception as e:
        print(f"  [glued_ma5] 失敗: {e}")

    return results


def _primary_stop(stop_notes: dict) -> str:
    """多 scanner 命中時取主要停損備注（shakeout > w_bottom > small_structure）."""
    for s in ('shakeout_strong', 'w_bottom_launch', 'small_structure'):
        if s in stop_notes:
            return stop_notes[s]
    return '—'


def _tier_rank(hit: dict) -> int:
    """Tier 排序鍵（越小越優先）."""
    t = hit.get('tier', '一般')
    bonus = hit.get('timing_bonus', '')
    if t == '🔥 Tier-A' and bonus:
        return 0
    if t == '🔥 Tier-A':
        return 1
    if t == '⭐ Tier-B' and bonus:
        return 2
    if t == '⭐ Tier-B':
        return 3
    if t == '➕ 加碼用':
        return 4
    return 5


def _wantgoo_link(ticker: str) -> str:
    """產生 wantgoo 技術圖連結."""
    return f"[chart](https://www.wantgoo.com/stock/{ticker}/technical-chart)"


def _format_hit_row(h: dict, show_scanner=False) -> str:
    """單列輸出 markdown (含 wantgoo)."""
    ticker = h['ticker']
    parts = [ticker, h.get('name', '')]
    if show_scanner:
        parts.append(h.get('scanner_name', ''))
    sectors = h.get('teacher_sectors', [])
    parts.append('/'.join(sectors) if sectors else h.get('industry', ''))
    parts.append(f"{h['close']:.2f}")
    parts.append(f"{h.get('vol_ratio', '—')}x")
    d = h.get('dist_ma10_pct')
    parts.append(f"{d:+.1f}%" if d is not None else '—')
    days = h.get('days_since_first_mention')
    parts.append(f"{days}d" if days is not None else '—')
    tt = h.get('teacher_tier', '')
    parts.append(tt if tt else '—')
    parts.append(h.get('stop_note', '—'))
    parts.append(_wantgoo_link(ticker))
    return '| ' + ' | '.join(parts) + ' |'


def _run_disposal_check(
    all_tickers: list[str],
    target_date: str,
    db_path: Path,
) -> dict[str, dict]:
    """對所有候選 ticker 跑處置股分型（--enable-disposal 啟用時呼叫）.

    Returns:
        dict[ticker, classify_result]  （只含處置中的 ticker）
    """
    from zhuli.extras.disposal_data_source import fetch_disposal_list
    from zhuli.disposal_framework import classify_disposal

    try:
        disposal_list = fetch_disposal_list(target_date)
    except Exception as exc:
        print(f"  [disposal] ⚠️ TWSE API 失敗，跳過: {exc}", flush=True)
        return {}

    print(f"  [disposal] 處置中股票共 {len(disposal_list)} 檔", flush=True)

    result: dict[str, dict] = {}
    # 只對候選 ticker 分型（避免對全市場跑 DB 查詢）
    candidates_in_disposal = [t for t in all_tickers if t in disposal_list]
    print(f"  [disposal] 候選 ticker 中有 {len(candidates_in_disposal)} 檔處置中", flush=True)

    for ticker in candidates_in_disposal:
        try:
            cl = classify_disposal(ticker, target_date, db_path, disposal_list[ticker])
            result[ticker] = cl
        except Exception as exc:
            result[ticker] = {
                "type": None,
                "label": "🔒? 需人工判定",
                "reason": f"分型失敗: {exc}",
                "pre_high": None, "disposal_max": None, "pullback_pct": None,
                "times": 0, "disposal_day": 0, "days_to_end": 0,
                "entry_hint": "—",
                "start_date": "", "end_date": "",
                "name": disposal_list[ticker].get("name", ""),
            }

    return result


def _render_disposal_section(
    disposal_map: dict[str, dict],
    all_hits: list[dict],
) -> list[str]:
    """產出 ## 🔒 處置股專區 markdown 段落."""
    # 找所有候選 ticker 中處置中的
    candidate_tickers = {h['ticker'] for h in all_hits}
    disposal_candidates = {t: v for t, v in disposal_map.items() if t in candidate_tickers}

    if not disposal_candidates:
        return [
            "## 🔒 處置股專區",
            "",
            "> 今日候選中無處置股",
            "",
        ]

    md = [
        "## 🔒 處置股專區",
        "",
        "| Ticker | 名稱 | 型態 | 處置前高 | 期間最高 | 回落% | 第幾次 | 第N天 | 出關前 | 進場時機 | 處置期間 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    # 排序：C 優先顯示（警示），然後 A，然後 B，然後 None
    def _sort_key(item):
        t, v = item
        order = {"C": 0, "A": 1, "B": 2, None: 3}
        return order.get(v.get("type"), 3)

    for ticker, cl in sorted(disposal_candidates.items(), key=_sort_key):
        label = cl.get("label") or "🔒?"
        pre_high = cl.get("pre_high")
        disposal_max = cl.get("disposal_max")
        pullback = cl.get("pullback_pct")
        times = cl.get("times", "?")
        day = cl.get("disposal_day", "?")
        to_end = cl.get("days_to_end", "?")
        entry_hint = cl.get("entry_hint", "—")
        start_date = cl.get("start_date", "")
        end_date = cl.get("end_date", "")
        name = cl.get("name", "")

        pre_high_str = f"{pre_high:.1f}" if pre_high else "—"
        disp_max_str = f"{disposal_max:.1f}" if disposal_max else "—"
        pullback_str = f"{pullback:.1f}%" if pullback is not None else "—"
        period_str = f"{start_date} → {end_date}" if start_date else "—"

        md.append(
            f"| **{ticker}** | {name} | {label} | "
            f"{pre_high_str} | {disp_max_str} | {pullback_str} | "
            f"第{times}次 | D+{day} | 前{to_end}天 | "
            f"{entry_hint} | {period_str} |"
        )

    md.append("")
    return md


def render_markdown(target_date: str, results: dict, db_path: Path | None = None, allow_missing_broker: bool = False, allow_missing_institutional: bool = False, disposal_map: dict | None = None) -> str:
    """產出 Tier-based 打擊區候選 markdown."""
    # 分離 post_attack_watchlist (DataFrame) + ma5_pivot/glued_ma5 (list) vs 其他 scanner (list[dict])
    pa_wl = results.pop('post_attack_watchlist', pd.DataFrame())
    ma5_pivot_hits = results.pop('ma5_pivot', [])
    glued_ma5_hits = results.pop('glued_ma5', [])
    # 法人 scanner 獨立段落、不進 all_hits
    j_hits = results.pop('institutional_firstbuy', [])
    i_hits = results.pop('institutional_swing', [])
    fbk_hits = results.pop('foreign_buy_on_black_k', [])

    # 把每個 hit 帶 scanner_name 後 flatten 成單一 list
    all_hits = []
    for scanner, hits in results.items():
        for h in hits:
            h = dict(h)
            h['scanner_name'] = scanner
            all_hits.append(h)

    # ── 處置股標記（--enable-disposal 啟用時）──────────────────────────────────
    # disposal_map 已由 main() 傳入；這裡只做標記和備用空 dict
    if disposal_map is None:
        disposal_map = {}
    # 把 disposal label 注入 all_hits（ticker 後面加標記）
    for h in all_hits:
        t = h['ticker']
        if t in disposal_map:
            cl = disposal_map[t]
            dtype = cl.get('type')
            if dtype == 'A':
                h['disposal_label'] = '🔒A'
            elif dtype == 'B':
                h['disposal_label'] = '🔒B'
            elif dtype == 'C':
                h['disposal_label'] = '🔒C'
            else:
                h['disposal_label'] = '🔒?'
        else:
            h['disposal_label'] = ''

    # ── 法人籌碼批次查詢 ────────────────────────────────────────────────────────
    all_chip_tickers = (
        [h['ticker'] for h in all_hits]
        + [h['ticker'] for h in ma5_pivot_hits]
        + [h['ticker'] for h in glued_ma5_hits]
        + [h['ticker'] for h in j_hits]
        + [h['ticker'] for h in i_hits]
        + [h['ticker'] for h in fbk_hits]
    )
    pa_tickers = []
    if pa_wl is not None and not pa_wl.empty and 'ticker' in pa_wl.columns:
        pa_tickers = pa_wl['ticker'].tolist()
    all_chip_tickers = list(set(all_chip_tickers + pa_tickers))

    chip_map: dict[str, dict] = {}
    if db_path and all_chip_tickers:
        print(f"  [chip] 查詢 {len(all_chip_tickers)} 檔法人籌碼 5d...", flush=True)
        try:
            chip_map = _load_institutional_chip(all_chip_tickers, target_date, db_path)
        except MissingChipDataError as exc:
            if allow_missing_institutional:
                print(f"  [chip] ⚠️ institutional 缺、--allow-missing-institutional 容忍: {exc}", flush=True)
                # 取得有資料的部分；缺的 ticker 從候選清單剔除
                import re as _re
                m = _re.search(r"缺 \d+ 檔.*?: \[(.*?)\]", str(exc))
                missing_tickers = set()
                if m:
                    missing_tickers = {t.strip().strip("'\"") for t in m.group(1).split(",")}
                all_chip_tickers = [t for t in all_chip_tickers if t not in missing_tickers]
                chip_map = _load_institutional_chip(all_chip_tickers, target_date, db_path)
                # 把 hits / ma5_pivot / glued_ma5 / pa_wl 內 missing ticker 也過濾掉
                all_hits = [h for h in all_hits if h['ticker'] not in missing_tickers]
                ma5_pivot_hits = [h for h in ma5_pivot_hits if h['ticker'] not in missing_tickers]
                glued_ma5_hits = [h for h in glued_ma5_hits if h['ticker'] not in missing_tickers]
                if isinstance(pa_wl, pd.DataFrame) and not pa_wl.empty and 'ticker' in pa_wl.columns:
                    pa_wl = pa_wl[~pa_wl['ticker'].isin(missing_tickers)].reset_index(drop=True)
            else:
                raise
        tag_counts: dict[str, int] = {}
        for v in chip_map.values():
            tag_counts[v['tag']] = tag_counts.get(v['tag'], 0) + 1
        print(f"  [chip] tag 分布: {tag_counts}", flush=True)

        # 老師分點快取掃描（只讀磁碟快取，不呼叫 API）
        try:
            broker_tags = _load_broker_chip(all_chip_tickers, target_date)
        except MissingChipDataError as exc:
            if allow_missing_broker:
                print(f"  [chip] ⚠️ broker cache 缺、--allow-missing-broker 容忍: {exc}", flush=True)
                broker_tags = {t: "" for t in all_chip_tickers}
            else:
                raise
        broker_hit_count = sum(1 for v in broker_tags.values() if v)
        print(f"  [chip] 老師分點命中（快取內）: {broker_hit_count} 檔", flush=True)
        # 把 broker_tag 合併進 chip_map (strict: broker ticker 必須在 chip_map 內)
        for ticker, btag in broker_tags.items():
            if ticker not in chip_map:
                raise MissingChipDataError(
                    f"broker 有 {ticker} 但 institutional chip_map 無此 ticker"
                )
            chip_map[ticker]["broker_tag"] = btag

    # 加碼判斷：shakeout 命中且該 ticker 30 天內有 W底/小結構訊號 → 標 ➕
    prior_entries = set()
    for h in all_hits:
        if h['scanner_name'] in ('w_bottom_launch', 'small_structure'):
            prior_entries.add(h['ticker'])
    for h in all_hits:
        if h['scanner_name'] == 'shakeout_strong' and h['ticker'] in prior_entries:
            h['has_prior_entry'] = True
        else:
            h['has_prior_entry'] = False

    # 分組 (6/3 校正、籌碼優先)
    def in_section(h, section):
        d = h.get('dist_ma10_pct')
        tier = h.get('tier', '一般')
        # 查籌碼: 雙籌碼 / 單籌碼 → 進場區、無籌碼 → score
        chip = chip_map.get(h['ticker'], {})
        f5d = chip.get('foreign_5d')
        s5d = chip.get('sitc_5d')
        level, _icon, _label = evaluate_dist_ma10(d, f5d, s5d)
        if section == 'entry':
            if tier not in ('🔥 Tier-A', '⭐ Tier-B'):
                return False
            # 有籌碼 (ignore/remind) → 一律進場
            if level in ('ignore', 'remind'):
                return True
            # 無籌碼、看距離 score (≤ 15% = 🥇🥈🥉、進場)
            return d is None or d <= MA10_DIST_RISKY
        if section == 'extended':  # 已起漲（後續觀察、無籌碼且距離 >15）
            if tier not in ('🔥 Tier-A', '⭐ Tier-B'):
                return False
            return level == 'score' and d is not None and d > MA10_DIST_RISKY
        if section == 'add_position':
            return h['scanner_name'] == 'shakeout_strong' and h.get('has_prior_entry')
        if section == 'general':
            return tier == '一般' and h['scanner_name'] != 'shakeout_strong'
        return False

    entry_hits = sorted([h for h in all_hits if in_section(h, 'entry')],
                       key=lambda h: (_tier_rank(h), h.get('dist_ma10_pct') or 999))
    extended_hits = sorted([h for h in all_hits if in_section(h, 'extended')],
                          key=lambda h: (_tier_rank(h), h.get('dist_ma10_pct') or 999))
    add_position_hits = sorted([h for h in all_hits if in_section(h, 'add_position')],
                              key=lambda h: h['ticker'])
    general_hits = sorted([h for h in all_hits if in_section(h, 'general')],
                         key=lambda h: -(h.get('vol_ratio') or 0))

    md = [
        f"# 打擊區候選 — {target_date} 收盤後",
        f"",
        f"> Tier 排序：🔥 Tier-A（P90+ 高機率）→ ⭐ Tier-B（老師指名）→ ➕ 加碼 → 一般",
        f"> ✨黃金期 = W底 + 老師首提 8-30天；✨二波期 = 小結構 + 老師首提 >30天",
        f"> 「距MA10」> 10% 表示已起漲、移至「後續觀察名單」",
        f"",
        f"## 各 scanner 統計",
        f"",
        f"| Scanner | 命中數 |",
        f"|---|---|",
    ]
    for s, hits in results.items():
        md.append(f"| {s} | {len(hits)} |")
    pa_count = len(pa_wl) if pa_wl is not None and not pa_wl.empty else 0
    md.append(f"| post_attack_watchlist | {pa_count} |")
    md.append(f"| ma5_pivot | {len(ma5_pivot_hits)} |")
    md.append(f"| glued_ma5_platform | {len(glued_ma5_hits)} |")
    md.append(f"| institutional_firstbuy (J) | {len(j_hits)} |")
    md.append(f"| institutional_swing (I) | {len(i_hits)} |")
    md.append(f"| 🐂 外資黑K連2天 | {len(fbk_hits)} |")
    md.append(f"| **可進場** (Tier-A/B 距MA10≤15%) | **{len(entry_hits)}** |")
    md.append(f"| **後續觀察** (Tier-A/B 但已起漲) | **{len(extended_hits)}** |")
    md.append(f"| **加碼候選** (Shakeout + 已有訊號) | **{len(add_position_hits)}** |")
    md += [f""]

    # === 可進場區 ===
    if entry_hits:
        md += [
            f"## 🎯 可進場 — Tier-A/B 候選（距 MA10 ≤ 15%、6/3 校正放寬）",
            f"",
            f"| Ticker | 名稱 | Scanner | 族群 | 收盤 | 量比 | 距MA10 | 首提後 | 老師 | 停損 | 外資5d | 投信5d | 籌碼 | wantgoo |",
            f"|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in entry_hits:
            tier_label = h.get('tier', '') + h.get('timing_bonus', '')
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            days = h.get('days_since_first_mention')
            days_str = f"{days}d" if days is not None else '—'
            chip = chip_map[h['ticker']]
            f_str, s_str, tag = _fmt_chip_cols(chip)
            disposal_label = h.get('disposal_label', '')
            ticker_display = f"**{h['ticker']}**{(' ' + disposal_label) if disposal_label else ''}"
            md.append(f"| {ticker_display} {tier_label} | {h['name']} | {h['scanner_name']} | "
                      f"{sectors_str} | {h['close']:.2f} | {h.get('vol_ratio', '—')}x | "
                      f"{h.get('dist_ma10_pct', 0):+.1f}% | {days_str} | "
                      f"{h.get('teacher_tier') or '—'} | {h.get('stop_note', '—')} | "
                      f"{f_str} | {s_str} | {tag} | "
                      f"{_wantgoo_link(h['ticker'])} |")
        md.append(f"")

    # === 後續觀察區（已起漲）===
    if extended_hits:
        md += [
            f"## ⚠️ 後續觀察 — Tier-A/B 但已起漲（距 MA10 > 10%）",
            f"",
            f"> 等回測 MA10 附近再進場；現在追進場潛在虧損 = 距 MA10",
            f"",
            f"| Ticker | 名稱 | Scanner | 族群 | 收盤 | 距MA10 | 老師 | 外資5d | 投信5d | 籌碼 | wantgoo |",
            f"|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in extended_hits:
            tier_label = h.get('tier', '') + h.get('timing_bonus', '')
            chip = chip_map[h['ticker']]
            f_str, s_str, tag = _fmt_chip_cols(chip)
            md.append(f"| {h['ticker']} {tier_label} | {h['name']} | {h['scanner_name']} | "
                      f"{'/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')} | "
                      f"{h['close']:.2f} | {h.get('dist_ma10_pct', 0):+.1f}% | "
                      f"{h.get('teacher_tier') or '—'} | "
                      f"{f_str} | {s_str} | {tag} | {_wantgoo_link(h['ticker'])} |")
        md.append(f"")

    # === 加碼候選 ===
    if add_position_hits:
        md += [
            f"## ➕ 加碼候選 — Shakeout × 已有 W底/小結構訊號",
            f"",
            f"> 30 天內已有進場訊號的 ticker 出現 shakeout（主力洗盤後爆量）= 加碼確認",
            f"> 沒持倉者不要當第一次進場用（Shakeout 冷進場效果差）",
            f"",
            f"| Ticker | 名稱 | 族群 | 收盤 | 量比 | 距MA10 | 外資5d | 投信5d | 籌碼 | wantgoo |",
            f"|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in add_position_hits:
            chip = chip_map[h['ticker']]
            f_str, s_str, tag = _fmt_chip_cols(chip)
            md.append(f"| {h['ticker']} | {h['name']} | "
                      f"{'/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')} | "
                      f"{h['close']:.2f} | {h.get('vol_ratio', '—')}x | "
                      f"{h.get('dist_ma10_pct', 0):+.1f}% | "
                      f"{f_str} | {s_str} | {tag} | {_wantgoo_link(h['ticker'])} |")
        md.append(f"")

    # === 攻擊後盤整早期追蹤 ===
    if pa_wl is not None and not pa_wl.empty:
        pa_stock_info = {}
        if 'name' in pa_wl.columns:
            for _, r in pa_wl.iterrows():
                pa_stock_info[r.get('ticker', '')] = r.get('name', '')
        pa_section = format_post_attack_report(
            pa_wl,
            stock_info=pa_stock_info,
            target_date=target_date,
            universe='sector_all',
        )
        md.append(pa_section)
    else:
        md += [
            f"## 🔬 攻擊後盤整 watchlist (人力辨識 + 問老師)",
            f"",
            f"> {target_date} 無符合標的",
            f"",
        ]

    # === MA5 Pivot Breakout ===
    md += [
        f"## 🎯 MA5 Pivot Breakout（今日翻正、長線多頭確認）",
        f"",
        f"> 條件：MA60/MA120/MA240 全🟢 + MA5 slope 今日翻正（昨日≤0→今日>0）+ 過去 60 天有平台期",
        f"> MA5 slope% = 今日 MA5 斜率 / 收盤價，反映突破力道",
        f"> 隔日確認：next day open > today close → ✓；否則 ✗；尚未開盤 → 等明日 open 確認",
        f"",
    ]
    if ma5_pivot_hits:
        # Sort: teacher_tier core/frequent first, then by dist_ma10_pct
        def _pivot_sort_key(h):
            tt = h.get('teacher_tier', '')
            rank = 0 if tt in ('core', 'frequent') else 1
            d = h.get('dist_ma10_pct') or 999
            return (rank, d)

        sorted_pivot_hits = sorted(ma5_pivot_hits, key=_pivot_sort_key)
        md += [
            f"| Ticker | 名稱 | 族群 | 收盤 | MA5 slope% | 距MA10 | 老師 | 外資5d | 投信5d | 籌碼 | 隔日確認 |",
            f"|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in sorted_pivot_hits:
            ticker = h['ticker']
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            d = h.get('dist_ma10_pct')
            d_str = f"{d:+.1f}%" if d is not None else '—'
            tt = h.get('teacher_tier') or '—'
            slope_pct = h.get('ma5_slope_pct', 0)
            chip = chip_map[ticker]
            f_str, s_str, tag = _fmt_chip_cols(chip)
            md.append(
                f"| {ticker} | {h['name']} | {sectors_str} | {h['close']:.2f} | "
                f"{slope_pct:.3f}% | {d_str} | {tt} | {f_str} | {s_str} | {tag} | 等明日 open 確認 |"
            )
        md.append(f"")
    else:
        md += [f"> {target_date} 無 MA5 Pivot 命中", f""]

    # === 黏 MA5 平台 Watchlist ===
    def _consolidation_stage(days: int) -> str:
        """整理階段分類（依黏 MA5 天數）."""
        if days <= 4:    return "🟡 早期"
        elif days <= 7:  return "🟢 中期"
        elif days <= 14: return "🔵 末期"
        else:            return "🟣 長平台"

    md += [
        f"## 📊 黏 MA5 平台 watchlist（人力觀察 + 等突破）",
        f"",
        f"> 條件: close 連續 N 天距 MA5 ≤ 2% + 不破 MA10 + 三長線全🟢 + 過去有攻擊段",
        f"> sector_week universe 過濾",
        f"> 跟 ma5_pivot 互補：此為「平台中」、ma5_pivot 為「突破當下」",
        f">",
        f"> 整理階段: 🟡 早期 (3-4 天、剛攻擊完、觀察) / 🟢 中期 (5-7 天、打擊區、進 watchlist)",
        f">           🔵 末期 (8-14 天、突破壓力累積、ma5_pivot trigger 進場) / 🟣 長平台 (15+ 天、textbook、準備重壓)",
        f"",
    ]
    if glued_ma5_hits:
        # Sort: teacher_tier core/frequent first, then by streak_days desc (longer platforms first)
        def _glued_sort_key(h):
            tt = h.get('teacher_tier', '')
            rank = 0 if tt in ('core', 'frequent') else 1
            return (rank, -(h.get('streak_days') or 0))

        sorted_glued = sorted(glued_ma5_hits, key=_glued_sort_key)
        md += [
            f"| Ticker | 名稱 | 族群 | 收盤 | 黏MA5天數 | 整理階段 | 平均距MA5 | 距MA10 | 老師 | 外資5d | 投信5d | 籌碼 | wantgoo |",
            f"|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in sorted_glued:
            ticker = h['ticker']
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            d = h.get('dist_ma10_pct')
            d_str = f"{d:+.1f}%" if d is not None else '—'
            tt = h.get('teacher_tier') or '—'
            streak = h.get('streak_days', 0)
            stage = _consolidation_stage(streak)
            dist_ma5 = h.get('dist_ma5_pct', 0)
            chip = chip_map[ticker]
            f_str, s_str, tag = _fmt_chip_cols(chip)
            md.append(
                f"| {ticker} | {h['name']} | {sectors_str} | {h['close']:.2f} | "
                f"{streak}天 | {stage} | {dist_ma5:.2f}% | {d_str} | {tt} | "
                f"{f_str} | {s_str} | {tag} | {_wantgoo_link(ticker)} |"
            )
        md.append(f"")
    else:
        md += [f"> {target_date} 無黏 MA5 平台命中", f""]

    # === 老師 core 但 scanner 未抓到 ===
    md += [
        f"## 📋 老師 core 級指名（scanner 未命中，手動關注）",
        f"",
        f"| Ticker | 名稱 | wantgoo |",
        f"|---|---|---|",
    ]
    for t in CORE_UNCOVERED:
        n = TEACHER_NAME.get(t, '')
        md.append(f"| {t} | {n} | {_wantgoo_link(t)} |")
    md += [f""]

    # === 一般候選（壓縮顯示）===
    if general_hits:
        md += [
            f"## 一般命中（無老師指名/非常勝軍，量比降冪前 30）",
            f"",
            f"| Ticker | 名稱 | Scanner | 族群 | 收盤 | 量比 | 距MA10 | 外資5d | 投信5d | 籌碼 | wantgoo |",
            f"|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in general_hits[:30]:
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            d = h.get('dist_ma10_pct')
            d_str = f"{d:+.1f}%" if d is not None else '—'
            chip = chip_map[h['ticker']]
            f_str, s_str, tag = _fmt_chip_cols(chip)
            md.append(f"| {h['ticker']} | {h['name']} | {h['scanner_name']} | "
                      f"{sectors_str} | {h['close']:.2f} | {h.get('vol_ratio', '—')}x | {d_str} | "
                      f"{f_str} | {s_str} | {tag} | "
                      f"{_wantgoo_link(h['ticker'])} |")
        md.append(f"")

    # === J 投信首買 ===
    md += [
        f"## 🏛 投信首買 (J) — 前 30 天空白 → 今日首買 ≥ 200 張",
        f"",
        f"> 老師教法 (Ex2-3): 「前面完全乾淨、今天突然大買 → 明天 5分K SOP 或等回 MA10 站穩」",
        f"> 價籌背離 (💡) = 收黑K 但投信大買 → 吸貨訊號",
        f"",
    ]
    if j_hits:
        md += [
            f"| Ticker | 名稱 | 族群 | 收盤 | 投信買(張) | 價籌背離 | MA多頭 | 距MA10 | 老師 | 外資5d | 投信5d | 籌碼 | wantgoo |",
            f"|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in j_hits:
            ticker = h['ticker']
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            d = h.get('dist_ma10_pct')
            d_str = f"{d:+.1f}%" if d is not None else '—'
            tt = h.get('teacher_tier') or '—'
            chip = chip_map.get(ticker, {})
            f_str = f"{chip.get('foreign_5d', 0):+,}" if chip else '—'
            s_str = f"{chip.get('sitc_5d', 0):+,}" if chip else '—'
            tag = chip.get('tag', '—') if chip else '—'
            diverge = '💡' if h.get('price_divergence') else ''
            ma_align = '✅' if h.get('ideal_ma_align') else ''
            md.append(
                f"| {ticker} | {h['name']} | {sectors_str} | {h['close']:.2f} | "
                f"{h.get('sitc_net', 0):+.0f} | {diverge} | {ma_align} | "
                f"{d_str} | {tt} | {f_str} | {s_str} | {tag} | {_wantgoo_link(ticker)} |"
            )
        md.append(f"")
    else:
        md += [f"> {target_date} 無投信首買命中", f""]

    # === I 投信跟單 ===
    md += [
        f"## 🏛 投信跟單 (I) — 5d 累計投信買/股本 ≥ 1.5% + MA 多頭",
        f"",
        f"> 老師教法 (Ex2-1/2-2): 「投信連續 5 天買超股本 1.5% = 跟單機會」",
        f"> 首次上榜 (🆕) 優先；MA5>MA10>MA20 全上彎才進",
        f"",
    ]
    if i_hits:
        md += [
            f"| Ticker | 名稱 | 族群 | 收盤 | 5d投信買(張) | 股本% | 首次 | 距MA10 | 老師 | 外資5d | 投信5d | 籌碼 | wantgoo |",
            f"|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in i_hits:
            ticker = h['ticker']
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            d = h.get('dist_ma10_pct')
            d_str = f"{d:+.1f}%" if d is not None else '—'
            tt = h.get('teacher_tier') or '—'
            chip = chip_map.get(ticker, {})
            f_str = f"{chip.get('foreign_5d', 0):+,}" if chip else '—'
            s_str = f"{chip.get('sitc_5d', 0):+,}" if chip else '—'
            tag = chip.get('tag', '—') if chip else '—'
            first = '🆕' if h.get('is_first_appearance') else ''
            buy_pct = h.get('buy_pct_of_shares', 0) or 0
            md.append(
                f"| {ticker} | {h['name']} | {sectors_str} | {h['close']:.2f} | "
                f"{h.get('sitc_buy_5d', 0):+.0f} | {buy_pct:.3f}% | {first} | "
                f"{d_str} | {tt} | {f_str} | {s_str} | {tag} | {_wantgoo_link(ticker)} |"
            )
        md.append(f"")
    else:
        md += [f"> {target_date} 無投信跟單命中", f""]

    # === 🐂 外資黑K連2天 ===
    md += [
        f"## 🐂 外資黑K連2天確認（隔天尾盤評估）",
        f"",
        f"> 老師 6/3 教法：「外資大買黑K 連兩天、明天尾盤就開始圈起來」",
        f"> 黑K + 外資大買 = 主力低檔吸貨 (殺散戶接籌碼)、連2天才算策略性建倉",
        f"> 流動性門檻：小型 500 張 / 中型 2000 張 / 大型 5000 張",
        f"> 加分：MA10 上方 (✅) + 無破底型態 (🛡)",
        f"",
    ]
    if fbk_hits:
        md += [
            f"| Ticker | 名稱 | 族群 | 收盤 | D0外資(張) | D-1外資(張) | 連天數 | Tier | 距MA10 | ✅MA10上 | 🛡無破底 | 老師 | 外資5d | 投信5d | 籌碼 | wantgoo |",
            f"|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for h in fbk_hits[:30]:  # 最多顯示 30 筆
            ticker = h['ticker']
            sectors_str = '/'.join(h.get('teacher_sectors', [])) or h.get('industry', '')
            d = h.get('dist_ma10_pct')
            d_str = f"{d:+.1f}%" if d is not None else '—'
            tt = h.get('teacher_tier') or '—'
            chip = chip_map.get(ticker, {})
            f_str = f"{chip.get('foreign_5d', 0):+,}" if chip else '—'
            s_str = f"{chip.get('sitc_5d', 0):+,}" if chip else '—'
            # 🐂 chip_tag for foreign black k
            base_tag = chip.get('tag', '—') if chip else '—'
            fbk_tag = f"🐂 條件觀察 ({base_tag})"
            above = '✅' if h.get('above_ma10') else ''
            no_break = '🛡' if h.get('not_breakdown') else ''
            teacher_tier = h.get('teacher_tier', '')
            tier_label = '⭐ Tier-B' if teacher_tier in ('core', 'frequent') else '一般'
            md.append(
                f"| **{ticker}** | {h['name']} | {sectors_str} | {h['close']:.2f} | "
                f"{h.get('foreign_net_d0', 0):+.0f} | {h.get('foreign_net_d1', 0):+.0f} | "
                f"{h.get('streak_days', 2)}天 | {tier_label} | {d_str} | {above} | {no_break} | "
                f"{tt} | {f_str} | {s_str} | {fbk_tag} | {_wantgoo_link(ticker)} |"
            )
        md.append(f"")
    else:
        md += [f"> {target_date} 無外資黑K連2天命中", f""]

    # === 處置股專區（--enable-disposal 啟用時）===
    if disposal_map:
        md += _render_disposal_section(disposal_map, all_hits)

    md += [
        f"---",
        f"",
        f"## 出場策略 + Tier 來源",
        f"",
        f"- W底/Shakeout: **MA10 收盤跌破 → 隔日 open 出**",
        f"- 小結構: **整理底收盤跌破出**（或同 MA10 兩擇一）",
        f"- Tier-A 來源：2026 回測（P90+ ≥30% 命中率 + 老師 core/frequent，n≥2）",
        f"",
        f"產生時間: {datetime.now():%Y-%m-%d %H:%M:%S}",
    ]
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="目標收盤日（預設今天）")
    ap.add_argument("--db", default=str(_DB))
    ap.add_argument("--output-dir", default="/tmp")
    ap.add_argument("--allow-missing-broker", action="store_true",
                    help="broker cache 缺也通過 (13:45 跑時 broker 還沒釋出用)")
    ap.add_argument("--allow-missing-institutional", action="store_true",
                    help="institutional 缺也通過 (KY 股等結構性缺資料用)")
    ap.add_argument("--disable-disposal", action="store_true",
                    help=(
                        "停用處置股分型（預設 ON）。"
                        "TWSE API 端 down 時可用此 flag 跳過、不擋主流程。"
                        "標記：🔒A 主升續攻 / 🔒B 反彈段 / 🔒C ❌ 不可進 / 🔒? 需人工"
                    ))
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    db_path = Path(args.db)
    out_dir = Path(args.output_dir)

    print(f"=== Daily Scanner Job ===")
    print(f"目標日期: {target_date}")
    print(f"DB: {db_path}")
    if (not args.disable_disposal):
        print(f"處置股分型: ✅ 啟用 (default)")
    else:
        print(f"處置股分型: ❌ 停用 (--disable-disposal)")
    print()

    results = run_scanners(target_date, db_path)

    print(f"\n結果:")
    for s, hits in results.items():
        print(f"  {s}: {len(hits)} 檔")

    # 處置股分型（--enable-disposal 啟用時）
    disposal_map: dict = {}
    if (not args.disable_disposal):
        print(f"\n[disposal] 開始處置股分型...", flush=True)
        # 收集所有候選 ticker
        all_candidate_tickers = list({
            h['ticker']
            for scanner_hits in results.values()
            if isinstance(scanner_hits, list)
            for h in scanner_hits
        })
        disposal_map = _run_disposal_check(all_candidate_tickers, target_date, db_path)
        disposal_cnt = len(disposal_map)
        type_counts = {}
        for v in disposal_map.values():
            t = v.get('type') or '?'
            type_counts[t] = type_counts.get(t, 0) + 1
        print(f"[disposal] 候選中處置股: {disposal_cnt} 檔，分型: {type_counts}", flush=True)

    md = render_markdown(target_date, results, db_path=db_path,
                         allow_missing_broker=args.allow_missing_broker,
                         allow_missing_institutional=args.allow_missing_institutional,
                         disposal_map=disposal_map if (not args.disable_disposal) else None)

    out_md = out_dir / f"scanner_candidates_{target_date}.md"
    out_md.write_text(md, encoding="utf-8")
    print(f"\n→ 寫入 {out_md}")

    flag = out_dir / f"scanner_done_{target_date}.flag"
    flag.write_text(f"done at {datetime.now().isoformat()}\n")
    print(f"→ flag {flag}")


if __name__ == "__main__":
    main()
