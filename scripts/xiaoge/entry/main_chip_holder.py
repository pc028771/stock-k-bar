"""xiaoge_main_chip_holder — 主力買超 + 月線多頭 detector.

Course source: 權證小哥課程 ch11 (主力買賣超與集保戶數變化), ch14 (籌碼 K 線分析).
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §2.

Course quotes:
> 「多頭是主力買超，散戶賣超，集保戶數下降。」 (ch11 00:14–00:25)
> 「主力數字…0 到 10 算小買，10 到 20 算中買，20 以上算大買。」 (ch11 02:34–02:39)
> 「大戶持股的比率持續性的上升…散戶呢 100 張以下的這持股比率持續性的下降。」 (ch14 02:55–03:11)

## 資料限制 (2026-06-14 audit)

DB schema `standard_daily_bar` 有：
- `main_force_1d/5d/10d/20d` — 在股 (NOT 張)、為機構買賣超 proxy（不是真正的「分點主力」）
- `custody_accounts` — **目前全部 None、資料尚未匯入**

所以本 detector v0.1 採三軸的子集：
1. ✅ 主力買超（用 `main_force_5d` 機構代理）
2. ⚠️ 散戶賣超（無資料、暫缺）
3. ❌ 集保戶數下降（無資料、暫缺、待 FinMind 補）
4. ✅ 月線（20MA）上揚 + 收盤站上月線

## 主力數字門檻換算

老師說「20 張」是真正的分點主力。但 DB 的 `main_force_1d` 是機構合計、
單位股、規模差很多。本 detector 用「相對量比」門檻：
    main_force_5d > 0 AND main_force_5d / volume_5d_total ≥ 5%
換算合理性：5% 持續 5 天 → 機構淨買壓占成交量 5%、屬於明顯買超。
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame, min_chip_ratio: float = 0.05) -> pd.Series:
    """Return bool Series; True = xiaoge_main_chip_holder long signal.

    Required df columns: ticker, trade_date, close, volume, ma20,
        main_force_5d. Sorted by (ticker, trade_date).

    Parameters
    ----------
    min_chip_ratio:
        Minimum main_force_5d / sum(volume_last_5d) ratio. Default 5%.
    """
    close = df["close"]
    ma20 = df["ma20"]
    main_5d = df["main_force_5d"]

    # 5-day rolling volume sum (must be positive)
    vol_5d_sum = df.groupby("ticker")["volume"].transform(
        lambda s: s.rolling(5, min_periods=5).sum()
    )

    # 1. 主力買超：main_force_5d > 0 AND ratio ≥ min_chip_ratio
    chip_ratio = main_5d / vol_5d_sum.replace(0, pd.NA)
    chip_strong = (main_5d > 0) & (chip_ratio >= min_chip_ratio).fillna(False)

    # 2. 月線上揚（20MA today > 20MA yesterday）
    ma20_prev = ma20.groupby(df["ticker"]).shift(1)
    ma20_rising = (ma20 > ma20_prev).fillna(False)

    # 3. 收盤 ≥ 月線
    above_ma20 = (close >= ma20).fillna(False)

    return (chip_strong & ma20_rising & above_ma20).fillna(False)
