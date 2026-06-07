"""類外側三黑 (outside_three_black_like) — bear, exit / context.

Course source:
  - 明日 K 線 第 43 篇 / 3995DDF008E3E1B600A9D920E6FFC07C（補充說明段）
  - INVENTORY §A02 outside_three_black_like
  - INVENTORY §C01 — outside_three_black.py 擴充為 N=3..M

與既有 outside_three_black.py 的差異（§A02 明示）:
  - 既有（P15）：固定 N=3 連續黑 K
  - 此 pattern：N ∈ [3, M]，老師明示 N=4、N=9（「外側九黑」）都成立
  - 最終觸發條件相同：第 N 根黑 K close < 最近一根創新高紅 K 的 low
  - 本檔 detect() 為擴充版；既有 outside_three_black.detect() 不動

識別規則（老師明示，INVENTORY §A02）:
  1. 前面有明確多方拉抬：最近一根創新高紅 K（close > prior_high_60 AND is_red）
  2. 最近一根創新高紅 K 之後，連續 N 根黑 K（N ≥ 3）
  3. 第 N 根黑 K close 跌破該創新高紅 K 的低點

老師範例：
  - 外側三黑（N=3）：課程第 14 篇原始定義（P15）
  - 外側四黑（N=4）：第 43 篇明示
  - 外側九黑（N=9）：第 43 篇明示，「也可以叫類外側三黑」

不確定（INVENTORY §A02 標記）:
  連續黑 K 之間是否可容忍小紅 K？老師範例皆連續黑 → 預設「全黑」

[STUB-NEED-USER] N 上限 M (INVENTORY §A02 §C01 S7):
  課程明示「沒有上限」，工程代理 M=20。超過 20 根視為非結構性下跌，
  通常已有其他出場訊號。需 user 確認 M 是否合適。

Cross-course: 是（明日 K 線 + 多空轉折篇均適用）
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import HIGH_LONG_BLACK_BODY_PCT_MIN


# [STUB-NEED-USER] 連續黑 K 上限 M（課程說「沒有上限」，工程代理 M=20）
OUTSIDE_THREE_BLACK_LIKE_MAX_N: int = 20


def detect(df: pd.DataFrame, max_n: int = OUTSIDE_THREE_BLACK_LIKE_MAX_N) -> pd.Series:
    """類外側三黑 — 最近一根創新高紅 K 後，連續 N ∈ [3, max_n] 根黑 K 跌破紅 K 低點。

    Args:
        df:    含 ticker, open, high, low, close, prior_high_60, body_pct 等欄位
        max_n: 連續黑 K 最大回看窗口（[STUB-NEED-USER] 預設 20）

    Returns:
        pd.Series[bool]: 類外側三黑觸發的 K 棒（今日為第 N 根黑 K）

    Algorithm:
      對於每個 ticker 的每一根 K 棒，往前回看 3..max_n 天，尋找：
        - 在 [3..max_n] 範圍內最近一根創新高紅 K（index = -(n+1) 相對今日）
        - 該 K 後到今日之間全部為黑 K（共 n 根）
        - 今日 close < 該創新高紅 K 的 low

      由於 groupby + 向量化困難，採「固定 N 迴圈 OR」策略：
        對 N = 3, 4, ..., max_n 分別向量化計算，結果取 OR。

    Conditions per N (INVENTORY §A02):
      1. D-(N): 創新高紅 K（close > prior_high_60 AND close > open）
      2. D-(N-1) .. D-0: 全黑 K（close < open）
      3. D-0 close < D-(N).low（跌破創新高紅 K 低點）
      4. D-0 body_pct >= HIGH_LONG_BLACK_BODY_PCT_MIN（最終確認黑 K 力道，沿用 P15）

    NOTE: 條件 4 沿用 outside_three_black.py 一致規範（唯一保留 body 門檻場合）。
    """
    g = df.groupby("ticker")
    result = pd.Series(False, index=df.index)

    # D-0 body 條件（沿用 P15）
    d0_body_pct = (df["open"] - df["close"]).abs() / df["open"].replace(0, float("nan"))
    d0_high_long_black = d0_body_pct >= HIGH_LONG_BLACK_BODY_PCT_MIN
    d0_black = df["close"] < df["open"]

    # Pre-compute per-ticker consecutive-black streak ending at today.
    # "D-(n-1)..D-0 全黑" ≡ black_streak[today] >= n. Avoids the inner
    # for-k loop that was running O(n) groupby.shift ops per outer n
    # (the dominant cost of this detector).
    is_black_int = d0_black.astype(int)
    def _streak(s: pd.Series) -> pd.Series:
        grp = (s != s.shift(1)).cumsum()
        return s.groupby(grp).cumsum() * s
    black_streak = is_black_int.groupby(df["ticker"]).transform(_streak)

    for n in range(3, max_n + 1):
        # D-(n): 最近一根創新高紅 K（在今日前第 n 根）
        close_dn = g["close"].shift(n)
        open_dn = g["open"].shift(n)
        low_dn = g["low"].shift(n)
        prior_high_60_dn = g["prior_high_60"].shift(n)

        dn_red_new_high = (close_dn > open_dn) & (close_dn > prior_high_60_dn)

        # D-(n-1) .. D-0: 連續 n 根黑 K（含今日）
        all_n_black = black_streak >= n

        # D-0 跌破 D-n 低點
        breaks_dn_low = df["close"] < low_dn

        trigger_n = (
            dn_red_new_high
            & all_n_black
            & breaks_dn_low
            & d0_high_long_black
        ).fillna(False)

        result = result | trigger_n

    return result
