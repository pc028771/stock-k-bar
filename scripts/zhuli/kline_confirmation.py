"""K 線力量課程內 Tier-A 升等訊號 (long-only zhuli 框架).

實際 backtest (kline_tier_a_boost_backtest.md、2024-01 → 2026-05、332 universe)：

  1. attack_cost_displayed    — bull entry-observation (明日 K 線 §20)
                                突破前 60 日高點 + 鎖漲停 + 量爆
                                raw EV: n=640, mean_5d=+3.95%, wr=58%, cap10=26%
  2. morning_star_island_reversal — bull exit (空單回補、低檔反轉)
                                raw EV: n=599, mean_5d=+2.39%, wr=62%, cap10=10%

合併效果 (K1+K2 × scanner = boosted, vs scanner-only control)：
  5d delta +3.11pp, 20d delta +7.87pp, wr_5d +8.4pp, cap10 28.8% vs 11.3% (2.5x)

— morning_star_harami (K3) 已移除：phase4 follow-through 82% 但 5d mean=-0.43%、
  follow-through 定義 (close > 前日中值) 過鬆、跟 scanner 交集 n≤50 太小、
  反而稀釋 boost (含 K3 mean_5d=+2.63% vs 去掉 K3=+4.20%、cap10 21.7→28.8%)。
  詳見 data/analysis/kline_patterns/kline_tier_a_boost_backtest.md.

用法：作為「升等訊號」— 已被 zhuli 課程內 scanner (W底/小結構/J/I 等)
命中的候選 + 同日亮這個 pattern → tier 升等 + 加 ✨ K 線確認標記.

morning_star_island_reversal 是課程明示「非進場訊號 / 空單回補」、不能獨立當 entry trigger.
attack_cost_displayed 是 entry-observation、但 zhuli 紅線 (位階、跳空 +3%)
另管、所以實務上也接成升等用.

CLI: 由 daily_scanner_job.py --enable-kline-tier-a flag 啟用 (default OFF).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

_REPO = Path(__file__).parent.parent.parent
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


KLINE_TIER_A_PATTERNS: list[str] = [
    "attack_cost_displayed",
    "morning_star_island_reversal",
]

# 顯示用中文名稱 (markdown badge)
KLINE_TIER_A_NAMES_CN: dict[str, str] = {
    "attack_cost_displayed": "攻擊成本顯現",
    "morning_star_island_reversal": "晨星島反轉",
}

# add_features 需要的最小 groups (依兩支 detector 的欄位依賴)
# - attack_cost_displayed: prior_high_60 (basic), is_limit_up_locked (pattern),
#                          avg_volume_20 (volume)
# - morning_star_island_reversal: is_gap_down_today, is_gap_up_today (pattern),
#                                 attack_intensity (historical), prior_high_60 (basic)
_REQUIRED_FEATURE_GROUPS: list[str] = ["basic", "volume", "historical", "pattern"]


def _build_combined_df(ticker_dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """把 ticker_dfs 合併成 add_features 可吃的 long-format df."""
    if not ticker_dfs:
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    for t, df in ticker_dfs.items():
        if df is None or df.empty:
            continue
        # ticker_dfs 來自 daily_scanner_job 的 per-ticker 載入、已有 ticker col、
        # 但保險起見再 set 一次 (避免 query 改 schema)
        if "ticker" not in df.columns or (df["ticker"] != t).any():
            df = df.copy()
            df["ticker"] = t
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    # add_features 預期 (ticker, trade_date) 排序
    if "trade_date" in combined.columns:
        combined = combined.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    return combined


def detect_kline_tier_a(
    ticker_dfs: dict[str, pd.DataFrame],
    target_date: str,
    patterns: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    """跑 Tier-A K 線 detector、回傳 {ticker: [pattern_name, ...]} (僅 target_date 命中).

    target_date: 'YYYY-MM-DD' (僅在當日命中的 ticker 才入 map).
    patterns: override 哪幾支 detector 跑、預設跑全部 3 支.

    沒命中 / ticker_dfs 為空 / features 失敗 → 回傳 {}.
    """
    if not ticker_dfs:
        return {}

    combined = _build_combined_df(ticker_dfs)
    if combined.empty:
        return {}

    # features 補欄位 (覆蓋 ticker_dfs 已有的 prior_high_60 等)
    from kline.features import add_features
    combined = add_features(combined, groups=_REQUIRED_FEATURE_GROUPS)

    # 跑 detector
    if patterns is None:
        patterns = KLINE_TIER_A_PATTERNS

    import importlib
    target_str = str(target_date)[:10]
    # 比對日期：把 trade_date 字串化只取前 10 碼，避免 dtype (datetime/str) 干擾
    date_str = combined["trade_date"].astype(str).str[:10]
    today_mask = date_str == target_str

    result: dict[str, list[str]] = {}
    for pat in patterns:
        try:
            mod = importlib.import_module(f"kline.patterns.{pat}")
            sig = mod.detect(combined)
        except Exception as exc:
            print(f"  [kline_tier_a] {pat} 失敗: {exc}", flush=True)
            continue
        if sig is None or len(sig) == 0:
            continue
        hits = combined.loc[today_mask & sig.fillna(False), "ticker"].tolist()
        for t in hits:
            result.setdefault(str(t), []).append(pat)

    return result


# ── Tier boost helpers ────────────────────────────────────────────────────────

# 升等規則：一般 → ⭐ Tier-B；⭐ Tier-B → 🔥 Tier-A；🔥 Tier-A 保持
_TIER_BOOST_MAP: dict[str, str] = {
    "一般": "⭐ Tier-B",
    "⭐ Tier-B": "🔥 Tier-A",
    "🔥 Tier-A": "🔥 Tier-A",
    "➕ 加碼用": "➕ 加碼用",  # 加碼類別不參與升等 (語義不同)
}


def boost_tier(current_tier: str) -> str:
    """升一級 (若已是 🔥 Tier-A / ➕ 加碼用 / 未知 tier 則維持)."""
    return _TIER_BOOST_MAP.get(current_tier, current_tier)


def format_confirmation_badge(patterns: list[str]) -> str:
    """產出 markdown badge 字串：'✨晨星島反轉+攻擊成本顯現' 等."""
    if not patterns:
        return ""
    names = [KLINE_TIER_A_NAMES_CN.get(p, p) for p in patterns]
    return "✨" + "+".join(names)


def apply_confirmations(
    hits: list[dict],
    confirmations: dict[str, list[str]],
) -> int:
    """對 hits 套用升等 + 加 kline_confirms / kline_badge 欄位.

    回傳實際被升等的 hit 數.
    """
    if not confirmations:
        return 0
    boosted = 0
    for h in hits:
        ticker = h.get("ticker", "")
        pats = confirmations.get(ticker)
        if not pats:
            continue
        h["kline_confirms"] = list(pats)
        h["kline_badge"] = format_confirmation_badge(pats)
        old = h.get("tier", "一般")
        new = boost_tier(old)
        h["tier"] = new
        if new != old:
            boosted += 1
    return boosted
