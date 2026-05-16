"""EXTRA: Force exit after N bars held (NOT in course).

## 課程立場
**課程沒有時間型的失效條件。** 課程的出場全部基於價格／K線型態
（收盤跌破、攻擊跳空被回補、大黑K反包等）。CLAUDE.md 也明文禁止
「連續 N 天」這類時間條件，除非課程明說。

## 為什麼放這裡
回測觀察：
- `breakout_price_break` 佔 tweezer 44% 出場，且勝率僅 17%——這些 trade
  通常 1-2 天就死
- 反過來，課程式 exits 沒觸發時，trade 會一直拖到資料末端，最後
  fallback 用 `exit_reason="open"` 平倉
- 部分長期不出場的 trade 拖累 mean return

時間上限可作為**安全網**（safety net），不取代課程出場邏輯——只在
所有課程 exit 都沒觸發時，才強制平倉。

## 實作位置
這是一個 exit condition（接到 simulator 的 priority 末端）。
放在末端 = 優先讓課程 exits 觸發；只有當課程都沒觸發到第 N 天時才生效。

## 參數
`--extras hold_days_cap=N` （default N=20）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_CAP_DAYS = 20


def make_mark(arg: str | None) -> callable:
    """Returns mark(df, entries) -> bool Series.

    Bar fires when, for the most recent entry on this ticker, the held-day
    count has reached `cap_days`.
    """
    cap_days = int(arg) if arg else DEFAULT_CAP_DAYS

    def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
        # df is sorted by (ticker, trade_date), so per-ticker positional
        # indices are contiguous. Mark the bar at cap_days after each entry,
        # bounded by the same ticker's last bar.
        work = df.reset_index(drop=True)
        ent = entries.reset_index(drop=True).fillna(False).astype(bool)
        out = pd.Series(False, index=work.index)

        for _ticker, grp in work.groupby("ticker", sort=False):
            idx = grp.index.to_numpy()
            ticker_last = idx[-1]
            ent_pos = idx[ent.iloc[idx].to_numpy()]
            for ep in ent_pos:
                target = ep + cap_days
                if target <= ticker_last:
                    out.iloc[target] = True
        return out

    mark.__name__ = f"hold_days_cap_{cap_days}"
    mark.cap_days = cap_days
    return mark
