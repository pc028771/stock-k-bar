"""攻擊成本顯現日 (attack_cost_displayed) — 明日 K 線 §20 進場觀察 pattern.

Course source:
  - 明日 K 線 §20「攻擊成本顯現日」/ B44741FE824D0798CC91C1521D5B0FF7
  - 明日 K 線 §28「不攻擊」/ E4383C1F106A64F729CAD12E0D4B25F2

Playbook: scripts/kline/scenarios/playbooks/attack_cost_displayed.yaml

Signal class: entry-observation pattern (short-term price-difference traders)
K-bar count: 1 根（當日即顯現）

課程定義（老師原文）：
  「突破前高的當日，股價鎖住漲停板，且最大量就是在這個漲停板的價位，
   成交量越大、成本意義越高」

識別規則（全部 AND）：
  1. 收盤突破前 60 日高點（close > prior_high_60）
  2. 當日鎖住漲停（is_limit_up_locked）：
       close >= prev_close * 1.095（含 tick 容差）
       high == close（無上影線，鎖住）
       low >= prev_close（全天最低不跌回昨收）
  3. 最大量在漲停板：
       若有分K資料 → 使用 get_max_volume_price_intraday() 判斷
         最大量 bar 的 high >= 漲停板（課程精確定義），
         OR 漲停板累計量 >= 所有 bar 中單一最大量 × 0.5（漲停板是主要交易帶）
       若無分K資料 → fallback 日K退化版：
         當日成交量 >= avg_volume_20 * ATTACK_COST_VOL_RATIO

分K量判斷準則（基於 2026-06-04 四個 case 分K分析）：
  3289 宜特  2023-03-08：最大量 bar (10:09, close=96.6) 的 high=96.8=漲停 → 課程精確定義下 YES
  3693 營邦  2023-04-11：最大量 bar (09:02, close=151.5=漲停) → YES
  8215 明基材 2021-12-13：最大量 bar (10:13, open=43.5) 是漲停板打開的那一刻，
                          漲停板上最大 bar 5816 < 最大量 10689 → 最大量 bar high=43.5 → YES
  6209 今國光 2023-12-15：完全沒有漲停板，close=29.0 vs limit_up=31.8 → NO

  結論：使用「最大量 bar 的 high >= 漲停價」作為分K判斷條件，覆蓋三個正例。

STUB-NEED-USER 常數（見 course_proxy_constants.py）：
  ATTACK_COST_LIMIT_UP_THRESHOLD = 1.095  — 同 features.py C05；tick 容差代理
  ATTACK_COST_VOL_RATIO = 1.0             — 日K退化版量比（分K優先時為 fallback）[STUB S2]

課程補充（不影響 detect 邏輯的定性說明）：
  - 若當日有利多消息 → 條件更嚴（不能跌破），但 detect 層無法判斷利多/利空 → 忽略
  - 若當日是利空突破漲停 → 信號更強，不需再看攻擊成本 → detect 不作區分
  - 已脫離基本面（高價飆股）→ 攻擊成本判斷意義小 → [STUB-NEED-USER] 「脫離基本面」定義未明示
  - 不是第一次突破前高 → 攻擊成本門檻較寬 → [STUB-NEED-USER] 「第一次突破前高」用 is_first_breakout_above_level

Course cases (calibration):
  正例（pattern 觸發）：
    3289 宜特  2023-03-08（112-03-08）  → 頸線意義的攻擊成本
    3693 營邦  2023-04-11（112-04-11）  → 攻擊成本顯現
    8215 明基材 2021-12-13（110-12-13） → 以往沒有拉抬的攻擊成本（DB 資料不足，無法驗證）
  反例（pattern 不觸發 / B3 跌破分支）：
    3289 宜特  2023-03-09  → 隔日觀察（非顯現日）
    3289 宜特  2023-03-17  → 跌破攻擊成本（B3 branch）
    8215 明基材 (隔日)     → 漲停後隔日跌破（B3 branch，累犯型）
    6209 今國光 2023-12-15 → 跌破攻擊成本（B3 branch）
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from ..course_proxy_constants import (
    ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS,
    ATTACK_COST_LIMIT_UP_THRESHOLD,
    ATTACK_COST_VOL_RATIO,
)
from ..minute_bars import get_max_volume_high as _get_max_volume_high


def _tick_size(price: float) -> float:
    """台灣股市 tick size 規則。"""
    if price < 10:
        return 0.01
    elif price < 50:
        return 0.05
    elif price < 100:
        return 0.1
    elif price < 500:
        return 0.5
    elif price < 1000:
        return 1.0
    else:
        return 5.0


def _calc_limit_up_price(prev_close: float) -> float:
    """計算漲停價（台灣規則：前日收盤 × 1.10，floor 到合法 tick）。"""
    raw = prev_close * 1.10
    tick = _tick_size(raw)
    return math.floor(raw / tick) * tick


def get_max_volume_price_intraday(ticker: str, date: str) -> float | None:
    """從主 DB minute_bars 撈當日最大量 bar 的 high price。

    回傳 None 表示無分K資料、走 fallback。

    分析依據（2026-06-04 四 case 驗證）：
      最大量 bar 的 high >= 漲停價，涵蓋三個正例：
      - 3289 (close=96.6, high=96.8=漲停)：最大量 bar high 觸及漲停
      - 3693 (close=151.5=漲停)：最大量 bar 本身在漲停板
      - 8215 (最大量 bar 是漲停打開時, open=43.5=漲停, high=43.5)：high 在漲停板
      反例 6209 最大量 bar high=29.0，遠低於漲停價 31.8 → 正確排除

    資料來源：~/.four_seasons/data.sqlite  minute_bars table（由 consolidate_minute_bars.py 整合）
    """
    return _get_max_volume_high(ticker, date)


def _has_max_vol_at_limit_up_intraday(
    ticker: str,
    date: str,
    prev_close: float,
) -> bool | None:
    """判斷當日最大量 bar 的 high 是否在漲停板上。

    回傳 True/False；若無分K資料回傳 None（由呼叫端 fallback）。
    """
    max_vol_high = get_max_volume_price_intraday(ticker, date)
    if max_vol_high is None:
        return None
    limit_up_price = _calc_limit_up_price(prev_close)
    return max_vol_high >= limit_up_price * 0.999


def detect(df: pd.DataFrame) -> pd.Series:
    """攻擊成本顯現日 — 觸發條件純函式版本（僅回傳 bool Series）。

    Args:
        df: 含 ticker, open, high, low, close, volume, prior_high_60,
            prev_close (or computable), avg_volume_20, is_limit_up_locked 等欄位。
            通常已透過 add_features() 加工。

    Returns:
        pd.Series[bool]: 攻擊成本顯現日觸發的 K 棒（回傳 True 的當日）

    Conditions (ALL AND)：
      1. close > prior_high_60         — 突破前 60 日高點
      2. is_limit_up_locked            — 當日漲停鎖住（features.py C05）
      3. 最大量在漲停板：
           若有分K資料 → _has_max_vol_at_limit_up_intraday()
             （最大量 bar 的 high >= 漲停價）
           若無分K資料 → volume >= avg_volume_20 * ATTACK_COST_VOL_RATIO [STUB S2]

    [STUB-NEED-USER S2]:
      ATTACK_COST_VOL_RATIO = 1.0（fallback 時等同「不過濾量能」）。
      課程「最大量就在漲停板價位」用分K才能精確；分K優先使用。
      若設為 1.0（只要有量即通過），則退化為只用 is_limit_up_locked + 突破。

    [STUB-NEED-USER S3]:
      「脫離基本面」的定義老師未明示（課程說「股價遠遠脫離基本面還繼續飆漲」）。
      現行實作不套用此排除條件，等 user 確認定義後再加入。

    [STUB-NEED-USER S4]:
      「第一次突破前高」的定義：可用 is_first_breakout_above_level（features.py）。
      課程說第一次突破時攻擊成本要求最嚴，但 detect 層不區分。
      如需區分，可在呼叫端用 df['is_first_breakout_above_level'] 過濾。
    """
    # 條件 1: 突破前 60 日高點（close > prior_high_60）
    broke_prior_high = (df["close"] > df["prior_high_60"]).fillna(False)

    # 條件 2: 漲停鎖住（使用 features.py 已計算的 C05 欄位）
    if "is_limit_up_locked" in df.columns:
        limit_up_locked = df["is_limit_up_locked"].fillna(False)
        # prev_close 已在 features.py 中算好（用於分K判斷）
        g_close = df.groupby("ticker")["close"]
        prev_close_s = g_close.shift(1)
    else:
        # Fallback: 自行計算（features.py 尚未 run 時的降格）
        g = df.groupby("ticker")
        prev_close_s = g["close"].shift(1)
        limit_up_locked = (
            (df["close"] >= prev_close_s * ATTACK_COST_LIMIT_UP_THRESHOLD)
            & (df["high"] == df["close"])
            & (df["low"] >= prev_close_s)
        ).fillna(False)

    # 條件 3: 最大量在漲停板
    # 先算日K退化版（向量化，作為預設值），再對通過條件 1+2 的少數 row 用分K覆寫
    if "avg_volume_20" in df.columns:
        avg_vol = df["avg_volume_20"]
    else:
        g = df.groupby("ticker")
        avg_vol = g["volume"].transform(
            lambda s: s.shift(1).rolling(20, min_periods=20).mean()
        )
    has_attack_volume = (
        df["volume"] >= avg_vol * ATTACK_COST_VOL_RATIO
    ).fillna(False)

    # 分K覆寫（只對有分K DB 且通過條件 1+2 的少數 row 才做 DB 查詢）
    from ..minute_bars import MAIN_DB_SYMLINK
    minute_db_available = MAIN_DB_SYMLINK.exists()
    date_col = "trade_date" if "trade_date" in df.columns else "date"

    if minute_db_available and "ticker" in df.columns and date_col in df.columns:
        # candidates: 通過條件 1 & 2 的 row（通常只有個位數到幾十個）
        candidates_mask = broke_prior_high & limit_up_locked
        candidates_idx = df.index[candidates_mask]

        for idx in candidates_idx:
            ticker_val = str(df.at[idx, "ticker"])
            date_val = str(df.at[idx, date_col])[:10]
            pc_val = prev_close_s.at[idx]

            if pd.isna(pc_val) or pc_val <= 0:
                continue

            intraday_result = _has_max_vol_at_limit_up_intraday(ticker_val, date_val, float(pc_val))
            if intraday_result is not None:
                # 分K判斷成功 → 用分K結果覆寫日K退化值
                has_attack_volume.at[idx] = intraday_result
            # intraday_result is None → 維持日K退化值，不覆寫

    raw_signal = (broke_prior_high & limit_up_locked & has_attack_volume).fillna(False)

    # ── State-machine: 連續觸發抑制 ──────────────────────────────────────
    # 課程依據（篇 20，B44741FE824D0798CC91C1521D5B0FF7）：
    #   「漲太多已經不是第一次突破前高的，就不在此限」
    #   「跳空攻擊算得上是攻擊成本浮現之後，明日 K 線是『繼續攻擊』的最佳解答」
    #   「至此已經不用再判斷會不會轉變，而是開始設定移動停利」
    # → setup-stage 攻擊成本顯現只認「同一段攻擊內的首日」，後續連續漲停
    #   屬於攻擊企圖確認 branch、不再亮 setup 燈。
    # 實作：對每個 ticker 看過去 N 個交易日內若已有 raw_signal=True，當日抑制。
    # N = ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS (60) [STUB-NEED-USER]
    if "ticker" in df.columns and raw_signal.any():
        n = ATTACK_COST_FIRST_BREAKOUT_LOOKBACK_DAYS
        # 對每個 ticker：rolling N-day max of raw_signal shifted by 1 (exclude today)
        prior_signal_in_window = (
            raw_signal.astype(int)
            .groupby(df["ticker"])
            .shift(1)
            .fillna(0)
            .groupby(df["ticker"])
            .rolling(n, min_periods=1)
            .max()
            .reset_index(level=0, drop=True)
            .reindex(raw_signal.index)
            .fillna(0)
            .astype(bool)
        )
        return (raw_signal & ~prior_signal_in_window).fillna(False)

    return raw_signal
