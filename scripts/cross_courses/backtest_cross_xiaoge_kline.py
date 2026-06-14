"""Backtest cross_xiaoge_kline on extended period.

Goal: validate Phase 4's +5.70% / 58.3% cross signal under:
1. Longer period (cross-month robustness)
2. C6 exit rules (production default — to be wired in once agent finishes)

For now uses xiaoge's `leave_upper_band` exit + adds tracking for cross-month
and cross-ticker counts per new methodology.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.xiaoge.bars import load_bars, add_squeeze_flag
from scripts.xiaoge.entry.bb_squeeze_breakout import detect as detect_bb
from scripts.xiaoge.entry.main_chip_holder_v2 import detect as detect_v2
from scripts.xiaoge.backtest_phase3 import simulate_trades
from scripts.cross_courses.xiaoge_kline_cross import cross_signal, cross_signal_strict

# Import kline detectors
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from kline.entry.breakout import detect as detect_kline_breakout  # noqa


REPO = Path(__file__).resolve().parents[2]


def _build_kline_features(df: pd.DataFrame) -> pd.DataFrame:
    """kline_course detectors require certain feature columns. Compute the
    minimum needed for tweezer_top_breakout. Best-effort — if column missing,
    add NaN so detect() can fail gracefully."""
    out = df.copy()
    grp_close = out.groupby("ticker")["close"]
    grp_high = out.groupby("ticker")["high"]
    grp_low = out.groupby("ticker")["low"]

    # prior_high_60: 過去 60 根 K 棒最高
    out["prior_high_60"] = grp_high.transform(
        lambda s: s.shift(1).rolling(60, min_periods=1).max()
    )
    # is_first_breakout_above_level: 過去 60 根第一次 close > prior_high_60
    out["is_breakout"] = (out["close"] > out["prior_high_60"]).fillna(False)
    out["is_first_breakout_above_level"] = out.groupby("ticker")["is_breakout"].transform(
        lambda s: (s.astype(int).cumsum() == 1) & s
    )
    # is_attack_bar: 紅 K 收高 OR 跳空 OR 新高
    prev_close = grp_close.shift(1)
    is_red = out["close"] > out["open"]
    closes_above_prev = out["close"] > prev_close
    is_gap_up = out["open"] > prev_close
    is_new_high = out["close"] > out["prior_high_60"]
    out["is_attack_bar"] = ((is_red & closes_above_prev) | is_gap_up | is_new_high).fillna(False)
    # is_in_breakdown_pattern: 簡化 — close < ma60 連續 5 天
    out["is_in_breakdown_pattern"] = False  # placeholder
    return out


def main():
    start, end = "2026-04-01", "2026-06-12"  # extend to ~2 months for cross-month check
    df = load_bars(start, end)
    df = add_squeeze_flag(df, lookback=10, threshold=15.0)
    in_window = df["trade_date"] >= pd.Timestamp(start)

    # xiaoge side: detector 2 v2 (真三軸 10%)
    try:
        xiaoge_sig = detect_v2(df, min_chip_ratio=0.10) & in_window
        xiaoge_n = xiaoge_sig.sum()
        print(f"xiaoge signals: {xiaoge_n}")
    except FileNotFoundError as e:
        print(f"⚠️ shareholding cache 不夠 {start} 到 {end}: {e}")
        print("→ fallback to detector 1 (bb_squeeze) for xiaoge side")
        xiaoge_sig = detect_bb(df, breakout_mode="shenglongquan") & in_window
        xiaoge_n = xiaoge_sig.sum()
        print(f"xiaoge bb signals: {xiaoge_n}")

    # kline side: simple breakout (course-defined first-breakout entry)
    df_with_feat = _build_kline_features(df)
    try:
        kline_sig = detect_kline_breakout(df_with_feat) & in_window
        kline_n = kline_sig.sum()
        print(f"kline breakout signals: {kline_n}")
    except Exception as e:
        print(f"⚠️ kline detector 跑不起來: {e}")
        return

    # Cross signal — strict (same day) AND 5d window
    cross_strict = cross_signal_strict(xiaoge_sig, kline_sig)
    cross_5d = cross_signal(xiaoge_sig.reset_index(drop=True),
                            kline_sig.reset_index(drop=True),
                            df.reset_index(drop=True), window=5)
    cross_5d.index = df.index
    print(f"cross strict (same-day): {cross_strict.sum()}")
    print(f"cross 5d window: {cross_5d.sum()}")

    # Backtest each
    print("\n=== Backtesting ===")
    xiaoge_trades = simulate_trades(df, xiaoge_sig)
    kline_trades = simulate_trades(df, kline_sig)
    cross_strict_trades = simulate_trades(df, cross_strict & in_window)
    cross_trades = simulate_trades(df, cross_5d & in_window)

    out_dir = REPO / "data/analysis/xiaoge/backtest"
    cross_trades.to_csv(out_dir / "cross_xiaoge_kline_extended.csv", index=False)

    def summarize(name, t):
        if len(t) == 0:
            return f"{name}: n=0"
        tickers = t["ticker"].nunique()
        months = pd.to_datetime(t["signal_date"]).dt.to_period("M").nunique()
        return (f"{name}: n={len(t)} 跨股={tickers} 跨月={months} "
                f"avg={t['ret_pct'].mean():.2f}% "
                f"wr={(t['ret_pct'] > 0).mean()*100:.1f}% "
                f"hold={t['hold_days'].mean():.1f}d")

    print(summarize("xiaoge alone", xiaoge_trades))
    print(summarize("kline alone", kline_trades))
    print(summarize("CROSS xiaoge ∩ kline (strict same-day)", cross_strict_trades))
    print(summarize("CROSS xiaoge ∩ kline (5d window)", cross_trades))

    # Robustness check per new methodology
    def actionable(t):
        if len(t) < 5: return "n<5 不夠記"
        wr = (t['ret_pct'] > 0).mean() * 100
        tickers = t["ticker"].nunique()
        months = pd.to_datetime(t["signal_date"]).dt.to_period("M").nunique()
        if wr >= 65 and tickers >= 5 and months >= 2:
            return "✅ ACTIONABLE"
        if wr <= 35 and tickers >= 5:
            return "🚫 反向訊號 (skip 清單)"
        if 50 <= wr < 65:
            return "👁️ watch-only"
        return "⚠️ 未達標"

    print(f"\nCross strict status: {actionable(cross_strict_trades)}")
    print(f"Cross 5d   status: {actionable(cross_trades)}")

    # Save quick report
    report_path = REPO / "docs/權證小哥/籌碼技術分析/backtest_cross_xiaoge_kline.md"
    report = f"""# cross_xiaoge_kline backtest (extended)

> 區間: {start} ~ {end}
> 出場: leave_upper_band (待 agent 完成 C6 simulator 後升級)

## 結果

- {summarize('xiaoge alone', xiaoge_trades)}
- {summarize('kline alone', kline_trades)}
- {summarize('CROSS xiaoge ∩ kline (5d window)', cross_trades)}

## 三維 robustness 結論

Cross: {actionable(cross_trades)}

## 跟 Phase 4 對比

Phase 4 同期但只跑 5/1-6/12、cross 36 筆 +5.70%/58.3%。
本次延長到 4/1-6/12、檢驗跨月。

## 後續

待 C6 simulator 完成 (agent af5ef8db70966e8e6) 後重跑、用 production 出場規則。
"""
    report_path.write_text(report)
    print(f"\n→ {report_path}")


if __name__ == "__main__":
    main()
