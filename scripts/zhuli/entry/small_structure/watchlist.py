"""Watchlist 輸出模組 — 三級分類 + 老師族群 universe 過濾.

提供三個 universe 模式降低雜訊：
  - 'all'         — 全市場（預設、與舊版相容）
  - 'sector_all'  — 老師過去 6 個月族群 universe (~295 檔去重)
  - 'sector_week' — 該日所在週主推族群（從 teacher_sector_timeline.md 查）

Tier 分類（以 detect_with_diagnostics 條件命中數為準）：
  - 🔥 高機率: 6/6（等同 detect()=True）
  - ⚠️ 中機率: 5/6
  - 📊 觀察: 4/6
  - 不顯示: ≤3/6
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# ── 路徑設定 ─────────────────────────────────────────────────────────────────
# parent 5 = small-structure-module (worktree root)
_REPO = Path(__file__).parent.parent.parent.parent.parent
_DOCS = _REPO / "docs" / "主力大課程"
_SECTOR_TICKERS = _DOCS / "teacher_sector_tickers.json"
_SECTOR_TIMELINE = _DOCS / "teacher_sector_timeline.md"

for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.entry.small_structure.detector import detect_with_diagnostics


# ── 族群 universe 載入 ────────────────────────────────────────────────────────

def _load_sector_all() -> set[str]:
    """讀 teacher_sector_tickers.json，回傳全族群 ticker set."""
    if not _SECTOR_TICKERS.exists():
        return set()
    data = json.loads(_SECTOR_TICKERS.read_text())
    return {t for tickers in data.values() for t in tickers}


def _parse_sector_timeline() -> list[dict]:
    """Parse teacher_sector_timeline.md，回傳 [{date, sectors: [str]}].

    只解析表格列（| YYYY-MM-DD | 主推族群 | ... |）。
    """
    if not _SECTOR_TIMELINE.exists():
        return []

    rows = []
    for line in _SECTOR_TIMELINE.read_text().splitlines():
        # 符合 | date | sectors | ...
        m = re.match(r'\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+)\|', line)
        if not m:
            continue
        date_str = m.group(1)
        sector_str = m.group(2)
        # 解析族群名稱（中文逗號、頓號、英文逗號分隔）
        sectors = [s.strip() for s in re.split(r'[、，,（]', sector_str) if s.strip()]
        # 清理括號殘餘（如「黃金週」、「L5」等說明）
        sectors = [re.sub(r'[（(].*', '', s).strip() for s in sectors]
        sectors = [s for s in sectors if s]
        rows.append({"date": date_str, "sectors": sectors})

    # 按日期升冪
    rows.sort(key=lambda r: r["date"])
    return rows


def _get_week_sectors(target_date: str, timeline: list[dict]) -> set[str]:
    """找 target_date 所在週對應的老師主推族群（取最近一個不超過該日的記錄）."""
    # 找 target_date 當週開始（週一）
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    week_start = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")

    # 找最近一筆 <= target_date 的記錄
    best = None
    for row in timeline:
        if row["date"] <= target_date:
            best = row
        else:
            break

    if best is None:
        return set()
    return set(best["sectors"])


def _load_sector_tickers_json() -> dict[str, list[str]]:
    """回傳 {sector_name: [ticker, ...]} dict."""
    if not _SECTOR_TICKERS.exists():
        return {}
    return json.loads(_SECTOR_TICKERS.read_text())


def _sectors_to_tickers(sectors: set[str], sector_map: dict[str, list[str]]) -> set[str]:
    """將族群名稱集合轉成 ticker set（模糊對應：族群名包含 or 被包含）."""
    tickers: set[str] = set()
    for key, vals in sector_map.items():
        # 族群名稱模糊比對
        matched = any(
            s in key or key in s
            for s in sectors
        )
        if matched:
            tickers.update(vals)
    return tickers


# ── Info Layer ─────────────────────────────────────────────────────────────────

def _try_import_kou_helpers():
    """嘗試 import teacher_swing 的 kou/ma 工具，失敗時回傳 None."""
    try:
        from zhuli.entry.teacher_swing import (
            compute_kou_block,
            compute_ma_state,
            compute_signal_combo,
        )
        return compute_kou_block, compute_ma_state, compute_signal_combo
    except ImportError:
        return None, None, None


# ── Watchlist 主函式 ───────────────────────────────────────────────────────────

_COND_COLS = [
    'cond_prior_attack', 'cond_sideways', 'cond_vol_contracted',
    'cond_ma5_close', 'cond_above_ma10', 'cond_high_holding',
]


def run_watchlist(
    df: pd.DataFrame,
    universe: str = 'all',
    target_date: str | None = None,
    ticker_col: str = 'ticker',
) -> pd.DataFrame:
    """產出 watchlist DataFrame，按條件命中數分 tier.

    Parameters
    ----------
    df          : 已含所有必要欄位的 DataFrame（可多個 ticker 合併）
    universe    : 'all' | 'sector_all' | 'sector_week'
    target_date : 用於 sector_week 查週方向（格式 'YYYY-MM-DD'）
    ticker_col  : ticker 欄位名稱（預設 'ticker'）

    Returns
    -------
    DataFrame 含欄位:
        ticker, date, close, tier, hit_count,
        cond_prior_attack, ..., cond_high_holding,
        kou_5, kou_10, kou_20, kou_60, ma_state, signal_combo
    """
    # --- Universe 過濾 ---
    allowed_tickers: set[str] | None = None

    if universe == 'sector_all':
        allowed_tickers = _load_sector_all()
    elif universe == 'sector_week':
        if target_date is None:
            raise ValueError("target_date 必須提供（用於 sector_week universe）")
        timeline = _parse_sector_timeline()
        week_sectors = _get_week_sectors(target_date, timeline)
        sector_map = _load_sector_tickers_json()
        allowed_tickers = _sectors_to_tickers(week_sectors, sector_map)

    if allowed_tickers is not None and ticker_col in df.columns:
        df = df[df[ticker_col].isin(allowed_tickers)].copy()

    if df.empty:
        return pd.DataFrame()

    # --- 逐 ticker 跑 detect_with_diagnostics ---
    result_rows = []

    if ticker_col in df.columns:
        groups = df.groupby(ticker_col)
    else:
        # 單一 ticker 模式
        groups = [(None, df)]

    for tkr, gdf in groups:
        gdf = gdf.sort_values('trade_date' if 'trade_date' in gdf.columns else 'date')
        gdf = gdf.reset_index(drop=True)

        try:
            diag = detect_with_diagnostics(gdf)
        except Exception:
            continue

        # 只取最後一日（target_date 或最後一行）
        if target_date is not None and 'date' in diag.columns:
            row = diag[diag['date'] == target_date]
            if row.empty:
                # try trade_date
                if 'trade_date' in gdf.columns:
                    last_row_idx = gdf[gdf['trade_date'] <= target_date].index
                    if len(last_row_idx) == 0:
                        continue
                    diag_row = diag.iloc[last_row_idx[-1]]
                else:
                    diag_row = diag.iloc[-1]
            else:
                diag_row = row.iloc[-1]
        else:
            diag_row = diag.iloc[-1]

        hit_count = sum(bool(diag_row.get(c, False)) for c in _COND_COLS)

        if hit_count < 4:
            continue

        tier = (
            "🔥 高機率" if hit_count == 6 else
            "⚠️ 中機率" if hit_count == 5 else
            "📊 觀察"
        )

        row_dict = {
            ticker_col: tkr,
            'date': diag_row.get('date', ''),
            'close': diag_row.get('close', None),
            'tier': tier,
            'hit_count': hit_count,
        }
        for col in _COND_COLS:
            row_dict[col] = bool(diag_row.get(col, False))

        result_rows.append(row_dict)

    if not result_rows:
        return pd.DataFrame()

    result = pd.DataFrame(result_rows)
    result = result.sort_values(['hit_count', ticker_col], ascending=[False, True])
    result = result.reset_index(drop=True)
    return result


def format_watchlist_report(wl: pd.DataFrame, universe: str = 'all', target_date: str = '') -> str:
    """將 watchlist DataFrame 格式化成可讀報告."""
    if wl.empty:
        return f"[小結構 Watchlist] {target_date} universe={universe}: 無符合標的"

    lines = [
        f"[小結構 Watchlist] {target_date}  universe={universe}",
        f"總計 {len(wl)} 檔  (高機率: {(wl['tier']=='🔥 高機率').sum()}  中機率: {(wl['tier']=='⚠️ 中機率').sum()}  觀察: {(wl['tier']=='📊 觀察').sum()})",
        "",
    ]

    for tier_label in ["🔥 高機率", "⚠️ 中機率", "📊 觀察"]:
        subset = wl[wl['tier'] == tier_label]
        if subset.empty:
            continue
        lines.append(f"## {tier_label} ({len(subset)} 檔)")
        for _, r in subset.iterrows():
            tkr = r.get('ticker', r.get('股票代號', ''))
            close = r.get('close', '')
            close_str = f"${close:.1f}" if isinstance(close, float) else ''
            conds = [c.replace('cond_', '') for c in _COND_COLS if r.get(c, False)]
            lines.append(f"  {tkr} {close_str}  命中: {r['hit_count']}/6  [{', '.join(conds)}]")
        lines.append("")

    return "\n".join(lines)
