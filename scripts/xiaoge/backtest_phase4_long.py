"""Phase 4 long-sample — D5 flying_stock_screener + ch13 老師原組合 + 長 sample.

Sample window: 2024-01-01 ~ 2026-06-12 (~600 trading days, 30 months).
Universe: teacher 99 (有 lookahead 但測 edge 影響小)。

新加變體 (vs phase4 短 sample 版):
  - M6 volatility / KD golden cross individually
  - 老師 ch13 原組合: M3 ∩ M6 ∩ KD (M1 真分點不在 universe-wide、跳過)
  - 6-sub combinator score>=3, >=4
  - 短 sample (2026-05-01 ~ 2026-06-12) vs 長 sample 兩段平行對比

Exit: C6.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.xiaoge.bars import load_bars
from scripts.xiaoge.entry.flying_stock_screener import (
    attach_institutional,
    m3_main_buy_streak, m4_foreign_buy_streak, m5_invest_trust_buy_streak,
    m6_volatility_rising_strong, m7_break_high,
    s3_main_sell_streak, s4_foreign_sell_streak, s5_invest_trust_sell_streak,
    s6_volatility_rising_weak, s7_break_low,
    kd_golden_cross, kd_death_cross,
    long_score, short_score, screener_long, screener_short,
)
from scripts.xiaoge.backtest_phase3c import (
    simulate_trades_c6, simulate_trades_short_c6,
    summarize, robustness_verdict,
)


REPO = Path(__file__).resolve().parents[2]


def _load_teacher_universe() -> list[str]:
    """Compute teacher universe inline: picks_2026 ∪ teacher_sector_tickers,
    intersected with bb_squeeze ∪ chip_v2 候選 (limit to D5 backtest scope)."""
    import json

    base = REPO / "docs/主力大課程"
    picks = json.loads((base / "teacher_picks_2026.json").read_text())
    sectors = json.loads((base / "teacher_sector_tickers.json").read_text())

    picks_tickers = {k for k in picks.keys() if k.isdigit() and len(k) == 4}

    sector_tickers: set[str] = set()
    def collect(o):
        if isinstance(o, dict):
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for v in o:
                collect(v)
        elif isinstance(o, str) and o.isdigit() and len(o) == 4 and o[0] != "0":
            sector_tickers.add(o)
    collect(sectors)

    teacher = picks_tickers | sector_tickers

    # Intersect with bb/chip candidate set (computed using 2026 H1 data — same
    # 99-ticker set we used in phase3c/phase4)
    from scripts.xiaoge.fetch_broker_trades import _candidate_tickers
    cands = set(_candidate_tickers("2026-05-01", "2026-06-12"))
    return sorted(teacher & cands)


def run_for_window(start: str, end: str, universe: list[str], tag: str):
    print(f"\n{'='*72}\n{tag}: {start} ~ {end}\n{'='*72}")
    df = load_bars(start, end, tickers=universe)
    df = attach_institutional(df)
    in_window = df["trade_date"] >= pd.Timestamp(start)
    print(f"Bars: {len(df):,} rows, {df['ticker'].nunique()} tickers, "
          f"{df['trade_date'].nunique()} dates "
          f"(in-window: {in_window.sum():,})")

    def _run(name: str, sig: pd.Series, short: bool = False) -> dict:
        s = sig & in_window
        sim = simulate_trades_short_c6 if short else simulate_trades_c6
        trades = sim(df, s)
        slug = name.replace(" ", "_").replace("/", "_").replace(":", "").replace("∩", "and").replace(">=", "ge")
        out_csv = REPO / "data/analysis/xiaoge/backtest" / f"phase4long_{tag}_{slug}.csv"
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        trades.to_csv(out_csv, index=False)
        return summarize(name, trades)

    results: list[dict] = []

    # Individual long subs
    m3 = m3_main_buy_streak(df, n=3)
    m4 = m4_foreign_buy_streak(df, n=3)
    m5 = m5_invest_trust_buy_streak(df, n=3)
    m6 = m6_volatility_rising_strong(df, vol_rise_pp=2.0)
    m7 = m7_break_high(df, lookback=20)
    kd = kd_golden_cross(df, period=9)

    results.append(_run("M3 main_buy_streak3", m3))
    results.append(_run("M4 foreign_buy_streak3", m4))
    results.append(_run("M5 invest_trust_buy_streak3", m5))
    results.append(_run("M6 vol_rising_strong (2pp)", m6))
    results.append(_run("M7 break_20d_high", m7))
    results.append(_run("KD golden_cross", kd))

    # ch13 老師示範組合 (簡化版、跳 M1 真分點): M3 ∩ M6 ∩ KD
    teacher_combo = m3 & m6 & kd
    results.append(_run("ch13 teacher combo: M3 ∩ M6 ∩ KD", teacher_combo))

    # 6-sub combinator at various thresholds
    results.append(_run("combinator score>=2",
                        screener_long(df, n_streak=3, n_high=20,
                                      vol_rise_pp=2.0, kd_period=9,
                                      min_score=2)))
    results.append(_run("combinator score>=3",
                        screener_long(df, n_streak=3, n_high=20,
                                      vol_rise_pp=2.0, kd_period=9,
                                      min_score=3)))
    results.append(_run("combinator score>=4",
                        screener_long(df, n_streak=3, n_high=20,
                                      vol_rise_pp=2.0, kd_period=9,
                                      min_score=4)))

    # Short subs + combinator
    s3 = s3_main_sell_streak(df, n=3)
    s6 = s6_volatility_rising_weak(df, vol_rise_pp=2.0)
    kd_dx = kd_death_cross(df, period=9)
    results.append(_run("S3 main_sell_streak3 (short)", s3, short=True))
    results.append(_run("S6 vol_rising_weak (short)", s6, short=True))
    results.append(_run("KD death_cross (short)", kd_dx, short=True))
    results.append(_run("ch13 short combo: S3 ∩ S6 ∩ KDdx", s3 & s6 & kd_dx, short=True))
    results.append(_run("short combinator score>=3",
                        screener_short(df, n_streak=3, n_high=20,
                                       vol_rise_pp=2.0, kd_period=9,
                                       min_score=3), short=True))

    res_df = pd.DataFrame(results)
    print("\n=== Results ===")
    print(res_df.to_string(index=False))

    verdicts = {r["name"]: robustness_verdict(r) for r in results}
    print("\n=== Verdicts ===")
    for k, v in verdicts.items():
        print(f"  {k}: {v}")

    return results, verdicts


def main():
    universe = _load_teacher_universe()
    print(f"Universe: {len(universe)} teacher tickers")

    # Run two windows in parallel
    res_short, ver_short = run_for_window(
        "2026-05-01", "2026-06-12", universe, "short_sample")
    res_long, ver_long = run_for_window(
        "2024-01-01", "2026-06-12", universe, "long_sample")

    # Compare
    print("\n" + "=" * 72)
    print("Short-sample vs Long-sample comparison")
    print("=" * 72)

    def _idx(rs): return {r["name"]: r for r in rs}
    si, li = _idx(res_short), _idx(res_long)
    names = [r["name"] for r in res_short]

    print(f"\n{'Detector':<50}  {'Short WR':>8} {'Long WR':>8}  {'Δ WR':>6}  {'Short avg':>10} {'Long avg':>10}")
    for name in names:
        s = si.get(name)
        l = li.get(name)
        if not s or not l:
            continue
        s_wr = s.get("win_rate", 0) or 0
        l_wr = l.get("win_rate", 0) or 0
        s_avg = s.get("avg_ret", 0) or 0
        l_avg = l.get("avg_ret", 0) or 0
        dwr = l_wr - s_wr
        print(f"{name:<50}  {s_wr:>7.1f}% {l_wr:>7.1f}% {dwr:>+5.1f}pp  "
              f"{s_avg:>+9.2f}% {l_avg:>+9.2f}%")

    # Write report
    report = "# Phase 4 long-sample — D5 + ch13 teacher combo backtest\n\n"
    report += "> Source: `scripts/xiaoge/backtest_phase4_long.py`\n"
    report += "> Detector: `scripts/xiaoge/entry/flying_stock_screener.py`\n"
    report += "> Date: 2026-06-25\n"
    report += f"> Universe: teacher 99 ({len(universe)} tickers, with 2024 lookahead)\n"
    report += "> Exit: C6 (MA10 trail)\n\n"

    def _table(label: str, rs, vs):
        out = f"\n## {label}\n\n"
        out += "| Detector | n | WR | avg | median | hold | tickers | months | Verdict |\n"
        out += "|---|---|---|---|---|---|---|---|---|\n"
        for r in rs:
            v = vs.get(r["name"], "")
            vshort = v.split(" (")[0]
            out += (f"| {r['name']} | {r['n']} | {r.get('win_rate','-')}% | "
                    f"{r.get('avg_ret','-')}% | {r.get('median_ret','-')}% | "
                    f"{r.get('avg_hold','-')} | {r.get('tickers','-')} | "
                    f"{r.get('months','-')} | {vshort} |\n")
        return out

    report += _table("Short sample (2026-05-01 ~ 2026-06-12, ~30 days)",
                     res_short, ver_short)
    report += _table("Long sample (2024-01-01 ~ 2026-06-12, ~600 days)",
                     res_long, ver_long)

    report += "\n## Short vs Long 對比\n\n"
    report += "| Detector | Short WR | Long WR | Δ WR | Short avg | Long avg |\n"
    report += "|---|---|---|---|---|---|\n"
    for name in names:
        s = si.get(name)
        l = li.get(name)
        if not s or not l:
            continue
        s_wr = s.get("win_rate", 0) or 0
        l_wr = l.get("win_rate", 0) or 0
        s_avg = s.get("avg_ret", 0) or 0
        l_avg = l.get("avg_ret", 0) or 0
        dwr = l_wr - s_wr
        report += (f"| {name} | {s_wr:.1f}% | {l_wr:.1f}% | {dwr:+.1f}pp | "
                   f"{s_avg:+.2f}% | {l_avg:+.2f}% |\n")

    out_path = REPO / "docs/權證小哥/籌碼技術分析/backtest_phase4_long.md"
    out_path.write_text(report)
    print(f"\nReport → {out_path}")


if __name__ == "__main__":
    main()
