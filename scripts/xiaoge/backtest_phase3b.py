"""Backtest xiaoge_main_chip_holder v2 (真三軸) vs v1 (機構代理).

Output: detector 2 v1 vs v2 comparison, plus Phase 4 starter (kline subset).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.xiaoge.bars import load_bars, add_squeeze_flag
from scripts.xiaoge.backtest_phase3 import simulate_trades, summarize
from scripts.xiaoge.entry.main_chip_holder import detect as detect_v1
from scripts.xiaoge.entry.main_chip_holder_v2 import detect as detect_v2


REPO = Path(__file__).resolve().parents[2]


def main():
    start, end = "2026-05-01", "2026-06-12"
    df = load_bars(start, end)
    df = add_squeeze_flag(df, lookback=10, threshold=15.0)
    in_window = df["trade_date"] >= pd.Timestamp(start)

    # v1: 機構 only (10% ratio)
    v1_sig = detect_v1(df, min_chip_ratio=0.10) & in_window
    v1_trades = simulate_trades(df, v1_sig)
    v1_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3b_v1.csv", index=False)

    # v2: 真三軸
    v2_sig = detect_v2(df, min_chip_ratio=0.10) & in_window
    v2_trades = simulate_trades(df, v2_sig)
    v2_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3b_v2.csv", index=False)

    # v2 with relaxed chip ratio (5% — let more signals through, see if quality holds)
    v2_5pct_sig = detect_v2(df, min_chip_ratio=0.05) & in_window
    v2_5pct_trades = simulate_trades(df, v2_5pct_sig)
    v2_5pct_trades.to_csv(REPO / "data/analysis/xiaoge/backtest/phase3b_v2_5pct.csv", index=False)

    # v2 三軸 no chip filter (純大戶+集保戶+月線、不要求機構 ratio)
    # — to isolate the shareholding axes' effect
    # Skipping for brevity; can add later if needed.

    results = [
        summarize("v1: chip 10% (機構 only)", v1_trades),
        summarize("v2: 真三軸 10% (機構+大戶+集保戶↓+月線)", v2_trades),
        summarize("v2 寬鬆: 真三軸 5%", v2_5pct_trades),
    ]
    res_df = pd.DataFrame(results)
    print(res_df.to_string(index=False))

    # Spot check: which winners did v2 catch that v1 missed (or vice versa)?
    v1_set = set(zip(v1_trades["ticker"], v1_trades["signal_date"]))
    v2_set = set(zip(v2_trades["ticker"], v2_trades["signal_date"]))
    only_v2 = v2_set - v1_set
    only_v1 = v1_set - v2_set
    both = v1_set & v2_set
    print(f"\nv1∩v2: {len(both)}")
    print(f"only v1: {len(only_v1)}")
    print(f"only v2: {len(only_v2)}")

    # Top winners by version
    print("\n=== v2 top 10 winners (真三軸 10%) ===")
    print(v2_trades.nlargest(10, "ret_pct")[["ticker", "signal_date", "entry_price", "exit_price", "hold_days", "ret_pct"]].to_string(index=False))

    report = f"""# Phase 3b — main_chip_holder v2 backtest (真三軸)

> Source: `scripts/xiaoge/backtest_phase3b.py`
> Date: 2026-06-14
> 樣本：2026-05-01 ~ 2026-06-12 (30 trading days)
> 新增資料：`TaiwanStockHoldingSharesPer` (週粒度集保戶 + 大戶/散戶分級)

## 結果對比

| Detector | n | avg_ret | median | win_rate | avg_hold | max | min |
|---|---|---|---|---|---|---|---|
| v1: chip 10% (機構 only) | {results[0]['n']} | {results[0]['avg_ret']}% | {results[0].get('median_ret','-')}% | {results[0]['win_rate']}% | {results[0]['avg_hold']} | {results[0].get('max_ret','-')}% | {results[0].get('min_ret','-')}% |
| **v2: 真三軸 10%** | **{results[1]['n']}** | **{results[1]['avg_ret']}%** | {results[1].get('median_ret','-')}% | **{results[1]['win_rate']}%** | {results[1]['avg_hold']} | {results[1].get('max_ret','-')}% | {results[1].get('min_ret','-')}% |
| v2 寬鬆: 真三軸 5% | {results[2]['n']} | {results[2]['avg_ret']}% | {results[2].get('median_ret','-')}% | {results[2]['win_rate']}% | {results[2]['avg_hold']} | {results[2].get('max_ret','-')}% | {results[2].get('min_ret','-')}% |

## 訊號集合分析

- v1 ∩ v2: {len(both)} 同訊號
- 只 v1: {len(only_v1)} 訊號（v2 因加大戶/集保戶條件被濾掉）
- 只 v2: {len(only_v2)} 訊號（理論上 0、v2 是 v1 子集；若有 → bug）

## 解讀

- v2 把 v1 的 {len(v1_set)} 訊號收斂到 {len(v2_set)} 個，是 {(len(v2_set)/max(len(v1_set),1)*100):.1f}% 留下率。
- 老師三軸論的篩選效應 → 訊號減少、品質變化看 win_rate / avg_ret 比較。

## 已知限制

1. 樣本期太短 (30 trading days)、訊號數較 v1 大幅減少後統計可信度更低
2. shareholding 週粒度 → 訊號生效時可能 staleness 達 5 個交易日
3. 真分點 detector (key_broker_signal) 還沒做、留 Phase 3c

## 後續

- 若 v2 比 v1 好 → v2 上線、v1 deprecate
- 若 v2 沒明顯改善 → 三軸論在 30 日窗口可能不顯著、需更長 backtest 確認
- detector 4 (key_broker_signal 真分點) 待 Phase 3c
"""
    (REPO / "docs/權證小哥/籌碼技術分析/backtest_phase3b.md").write_text(report)
    print(f"\nReport → docs/權證小哥/籌碼技術分析/backtest_phase3b.md")


if __name__ == "__main__":
    main()
