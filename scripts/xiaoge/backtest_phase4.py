"""Phase 4 — D5 flying_stock_screener sub-detector + combinator backtest.

8 個 sub-detector individually (M3-M7 long + S3-S7 short) + combinator at
min_score=2/3 thresholds. Exit = C6 (MA10 trail).

Universe: teacher 99 (老師 picks ∪ sectors ∩ bb/chip 候選).
Sample window: 2026-05-01 ~ 2026-06-12 (30 trading days).

進場 = 訊號日隔日開盤、單位 1 張。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.xiaoge.bars import load_bars
from scripts.xiaoge.entry.flying_stock_screener import (
    attach_institutional,
    m3_main_buy_streak, m4_foreign_buy_streak, m5_invest_trust_buy_streak,
    m7_break_high,
    s3_main_sell_streak, s4_foreign_sell_streak, s5_invest_trust_sell_streak,
    s7_break_low,
    long_score, short_score, screener_long, screener_short,
)
from scripts.xiaoge.backtest_phase3c import (
    simulate_trades_c6, simulate_trades_short_c6,
    summarize, robustness_verdict,
)


REPO = Path(__file__).resolve().parents[2]


def _load_teacher_universe() -> list[str]:
    p = Path("/tmp/teacher_xiaoge_universe.txt")
    if not p.exists():
        raise FileNotFoundError(
            "/tmp/teacher_xiaoge_universe.txt missing; rebuild via "
            "earlier script or pass --universe arg")
    return sorted({t.strip() for t in p.read_text().splitlines() if t.strip()})


def main():
    start, end = "2026-05-01", "2026-06-12"
    universe = _load_teacher_universe()
    print(f"Universe: {len(universe)} teacher tickers")

    df = load_bars(start, end, tickers=universe)
    df = attach_institutional(df)
    in_window = df["trade_date"] >= pd.Timestamp(start)
    print(f"Bars loaded: {len(df):,} rows, {df['ticker'].nunique()} tickers, "
          f"{df['trade_date'].nunique()} dates "
          f"(in-window: {in_window.sum():,})")

    # ── Individual sub-detectors (long) ────────────────────────────────────
    def _run(name: str, sig: pd.Series, short: bool = False) -> dict:
        s = sig & in_window
        sim = simulate_trades_short_c6 if short else simulate_trades_c6
        trades = sim(df, s)
        slug = name.replace(" ", "_").replace("/", "_").replace(":", "")
        out_csv = REPO / "data/analysis/xiaoge/backtest" / f"phase4_{slug}.csv"
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        trades.to_csv(out_csv, index=False)
        return summarize(name, trades)

    results: list[dict] = []
    results.append(_run("M3 main_buy_streak3 (long)",
                        m3_main_buy_streak(df, n=3)))
    results.append(_run("M4 foreign_buy_streak3 (long)",
                        m4_foreign_buy_streak(df, n=3)))
    results.append(_run("M5 invest_trust_buy_streak3 (long)",
                        m5_invest_trust_buy_streak(df, n=3)))
    results.append(_run("M7 break_20d_high (long)",
                        m7_break_high(df, lookback=20)))

    # combinator long: min_score 2, 3
    results.append(_run("combinator long: score>=2",
                        screener_long(df, n_streak=3, n_high=20, min_score=2)))
    results.append(_run("combinator long: score>=3",
                        screener_long(df, n_streak=3, n_high=20, min_score=3)))

    # ── Short mirrors ──────────────────────────────────────────────────────
    results.append(_run("S3 main_sell_streak3 (short)",
                        s3_main_sell_streak(df, n=3), short=True))
    results.append(_run("S4 foreign_sell_streak3 (short)",
                        s4_foreign_sell_streak(df, n=3), short=True))
    results.append(_run("S5 invest_trust_sell_streak3 (short)",
                        s5_invest_trust_sell_streak(df, n=3), short=True))
    results.append(_run("S7 break_20d_low (short)",
                        s7_break_low(df, lookback=20), short=True))
    results.append(_run("combinator short: score>=2",
                        screener_short(df, n_streak=3, n_high=20, min_score=2),
                        short=True))

    res_df = pd.DataFrame(results)
    print("\n=== Results ===")
    print(res_df.to_string(index=False))

    verdicts = {r["name"]: robustness_verdict(r) for r in results}
    print("\n=== Robustness Verdicts ===")
    for k, v in verdicts.items():
        print(f"  {k}: {v}")

    # ── Write report ───────────────────────────────────────────────────────
    def _row(r: dict) -> str:
        return (f"| {r['name']} | {r['n']} | {r['avg_ret']}% | "
                f"{r.get('median_ret', '-')}% | {r['win_rate']}% | "
                f"{r['avg_hold']} | {r['tickers']} | {r['months']} | "
                f"{r.get('max_ret', '-')}% | {r.get('min_ret', '-')}% |\n")

    report = f"""# Phase 4 — D5 flying_stock_screener backtest

> Source: `scripts/xiaoge/backtest_phase4.py`
> Detector: `scripts/xiaoge/entry/flying_stock_screener.py`
> Date: 2026-06-19
> Universe: teacher 99 ({len(universe)} tickers — 老師 picks_2026 ∪ teacher_sector_tickers ∩ bb/chip 候選)
> Sample: 2026-05-01 ~ 2026-06-12 (30 trading days)
> 進場閾值: streak n=3, 新高 lookback=20
> 出場規則: **C6** (MA10 容忍 + 量比 + 連 2 天容忍 → 隔日開盤出)

## 結果

| Detector | n | avg_ret | median | win_rate | avg_hold | tickers | months | max | min |
|---|---|---|---|---|---|---|---|---|---|
"""
    for r in results:
        report += _row(r)

    report += """

## Robustness Verdicts

> 跨股 ≥ 5 + 跨月 ≥ 2 + win_rate ≥ 65% = actionable
> 50-65% = watch-only
> ≤ 35% = 反向訊號 skip 清單

"""
    for k, v in verdicts.items():
        report += f"- **{k}**: {v}\n"

    out_path = REPO / "docs/權證小哥/籌碼技術分析/backtest_phase4.md"
    out_path.write_text(report)
    print(f"\nReport → {out_path}")


if __name__ == "__main__":
    main()
