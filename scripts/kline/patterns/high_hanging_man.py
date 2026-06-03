"""高檔吊首 — bear, exit (多單出場).

Course source: 第 04 篇《高檔下影線：高檔吊首》(666C90D7BC58F0E0E9629CAD711FD56F)
Cross-course definition: PATTERN_DEFINITIONS.md §2 + PATTERN_INVENTORY P05.

§C06 明日 K 線補充 (INVENTORY §C06, 第 36 篇 — 得利影 6144 範例):

  主力自演場景下「高檔吊首頻發」的處理方式：
    課程第 36 篇明示：「主力自演 / 鎖單拉抬的股票，高檔常常連續出現 T 字線
    或吊首形，是主力刻意製造恐慌的出貨技法，而非真正的多方力竭訊號。」

    「關鍵判斷在於：股價是否不再創新高——若每次吊首後隔日仍創新高，
    表示主力尚未出貨完畢，吊首訊號失效；若股價開始不再創新高，才算確認。」

  實作規範（INVENTORY §C06 明示「不改 detect，加 metadata 標註」）：
    - detect() 邏輯維持不變（bull_exhaustion_context 已涵蓋多方力竭背景）
    - 呼叫方在主力自演股（流通股本小、近期有無量跌停或強制集中趨勢）使用此
      pattern 時，需額外確認「股價已開始不再創新高」才作為真實出場訊號
    - 代理 filter（供 playbook / advisor 注入）：
        `high < g["high"].shift(1).rolling(5).max()` (今日 high 未超越近 5 日高點)
        表示「攻擊轉弱 → 吊首訊號轉為有效」

  Cross-market note:
    主力自演場景的識別需要籌碼資料（主力集中度），屬跨資料源 filter，
    不在本模組實作；本 docstring 僅供 caller 參考。

  Caller note for 主力自演股:
    IMPORTANT: 若 is_speculative_stock == True（流通股本 < N 億、近期漲幅 > X%），
    在 playbook 層加額外條件：「今日 high <= max(high, lookback=5)」
    才觸發此型態的出場訊號。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import bull_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """高檔吊首 — T 字線 (長下影線) + 多方力竭 + 確認日 (日落 OR 開低跳空).

    Conditions (PATTERN_INVENTORY P05):
      1. 多方力竭背景
      2. 前一日為 T 字 / 近 T 字 (下影 >= 2x body, 上影 <= 0.3x body)
      3. 確認：今日為日落 (is_sunset_bar) OR 今日 open < prev_low
      4. 排除：日出攻擊進行中 (attack_intensity == 4)
    """
    g = df.groupby("ticker")
    prev_lower = g["lower_shadow"].shift(1)
    prev_upper = g["upper_shadow"].shift(1)
    prev_body = g["body_abs"].shift(1).replace(0, np.nan)
    prev_low_v = g["low"].shift(1)

    t_line = (prev_lower >= 2 * prev_body) & (prev_upper <= 0.3 * prev_body)

    confirm = df["is_sunset_bar"].fillna(False) | (df["open"] < prev_low_v)

    not_sunrise_attack = df["attack_intensity"].fillna(0) != 4

    exhaust = bull_exhaustion_context(df)

    return (t_line & confirm & not_sunrise_attack & exhaust).fillna(False)
