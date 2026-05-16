"""EXTRA: Require attack_intensity ≥ threshold at entry (NOT in course).

## 課程立場
課程把攻擊型態分四級（日出 4 / 跳空 3 / 推升 2 / 波動前進 1），
並指出較高級別的可信度通常較高。**但課程從未說「至少哪一級才能進場」。**

## 為什麼放這裡
分析 `docs/analysis/2026-05-16-tweezer-vs-pattern.md` 觀察：
- pattern entries 74% 落在 intensity ≥ 1，tweezer 只有 25%
- pattern 勝率明顯高
- intensity 2 / 3 是觀察到的 "sweet spot"

→ 把 intensity ≥ N 當 entry 硬過濾可能改善 tweezer。但這是**回測導出**的閾值
選擇，課程沒講，所以放 extras。

## 參數
`--extras intensity_floor=N` （default N=2）
"""
from __future__ import annotations

import pandas as pd

DEFAULT_THRESHOLD = 2


def make_filter(arg: str | None) -> callable:
    """Returns a function(df, entries) -> entries with intensity floor applied."""
    threshold = int(arg) if arg else DEFAULT_THRESHOLD

    def apply(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
        if "attack_intensity" not in df.columns:
            raise KeyError(
                "extras.intensity_floor requires 'attack_intensity' column. "
                "Ensure features.add_features() has been applied."
            )
        passes = df["attack_intensity"].fillna(0) >= threshold
        return (entries & passes).fillna(False)

    apply.__name__ = f"intensity_floor_{threshold}"
    apply.threshold = threshold
    return apply
