"""inst_direction_score — 法人方向分組加分（User-created, NOT course-defined）。

## 課程立場

課程（K線力量判斷入門）未曾說明「比較外資與投信 5 日淨買超方向」作為進場依據。
外資 vs 投信方向分析（對做／同向）是 **user 自行設計的過濾與評分層**，
用於在 shakeout_strong 命中後進一步區分強弱。

## 為什麼放這裡

- 「用法人 5 日方向加分」是回測導出的規則，非課程明示條件。
- CLAUDE.md 明訂：「任何課程外條件必須放在 extras/，預設 OFF。」
- 與 shakeout_strong.py 配合使用；兩者皆屬 user-created 策略層。

## 觀察證據（回測，非保證）

進場前 5d 外資 / 投信方向分組（n=65 筆有法人資料，out of 157 total）：

| 分組               | n  | 20d net %  | hit    | PF    |
|--------------------|-----|------------|--------|-------|
| A 外賣投買（對做） | 7   | +25.76%    | 71.4%  | 14.90 |
| B 外買投賣（對做） | 10  | +3.17%     | 50.0%  | 1.44  |
| C 同向買           | 22  | +12.97%    | 68.2%  | 2.98  |
| D 同向賣           | 4   | +29.96%    | 100%   | 99    |
| E 微小             | 22  | +22.38%    | 63.6%  | 6.75  |

加分邏輯來自回測 EV 排序：A > D > C > E > B，
加分值設計以「不主導、只輔助」為原則，僅作 tiebreaker 用途。
"""
from __future__ import annotations

import pandas as pd

# 判斷「顯著」的最低門檻（張數）。低於此視為微小（E 類）。
_MIN_LOTS = 100


def classify_direction(foreign_5d: float, sitc_5d: float) -> str:
    """根據外資與投信 5 日淨買超方向，回傳分組標籤。

    Parameters
    ----------
    foreign_5d : float
        進場前 5 交易日外資累計淨買超（萬股，正=買、負=賣）。
    sitc_5d : float
        進場前 5 交易日投信累計淨買超（張，正=買、負=賣）。

    Returns
    -------
    str
        'A 外賣投買' / 'B 外買投賣' / 'C 同向買' / 'D 同向賣' / 'E 微小'
    """
    import math

    def _is_significant(val: float) -> bool:
        return not math.isnan(val) and abs(val) >= _MIN_LOTS

    f_sig = _is_significant(foreign_5d)
    s_sig = _is_significant(sitc_5d)

    if not f_sig and not s_sig:
        return "E 微小"

    f_buy = (not math.isnan(foreign_5d)) and foreign_5d > 0
    s_buy = (not math.isnan(sitc_5d)) and sitc_5d > 0

    if f_sig and s_sig:
        if not f_buy and s_buy:
            return "A 外賣投買"
        if f_buy and not s_buy:
            return "B 外買投賣"
        if f_buy and s_buy:
            return "C 同向買"
        return "D 同向賣"

    # 只有一方顯著
    if f_sig:
        return "C 同向買" if f_buy else "D 同向賣"
    return "C 同向買" if s_buy else "D 同向賣"


# 分組加分對照（回測 EV 正相關強弱排序）
_GROUP_SCORE: dict[str, float] = {
    "A 外賣投買": 3.0,  # 最強，PF 14.90
    "B 外買投賣": 0.0,  # 最弱，PF 1.44，不加分
    "C 同向買":   2.0,
    "D 同向賣":   2.0,  # 樣本少（n=4）但 PF 99，給同等加分
    "E 微小":     0.0,
}


def score(foreign_5d: pd.Series, sitc_5d: pd.Series) -> pd.Series:
    """依法人方向分類計算加分，回傳 float Series。

    加分邏輯：A=+3, C=+2, D=+2, B=0, E=0（僅作 tiebreaker，不主導排序）。

    Parameters
    ----------
    foreign_5d : pd.Series
        外資 5 日累計淨買超（萬股）。
    sitc_5d : pd.Series
        投信 5 日累計淨買超（張）。

    Returns
    -------
    pd.Series[float]
        index 對齊輸入，值為 0.0–3.0。
    """
    import math

    def _row_score(f, s) -> float:
        fv = float(f) if not pd.isna(f) else math.nan
        sv = float(s) if not pd.isna(s) else math.nan
        grp = classify_direction(fv, sv)
        return _GROUP_SCORE.get(grp, 0.0)

    result = pd.Series(
        [_row_score(f, s) for f, s in zip(foreign_5d, sitc_5d)],
        index=foreign_5d.index,
        dtype=float,
    )
    return result
