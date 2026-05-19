"""主力意圖判斷 — M 收高開低 / 收低開高 filter (M 策略).

Course source: 主力大全方位操盤教戰守則 (林家洋)
  - strategy-indicators.md §M 主力意圖判斷（Open Price Signal）
  - course_principles.md §15 主力意圖（Ch7-3）

Logic overview:
    Three signal types, all based on the relationship between T-1 close and T open:

    1. bearish_exit（收高開低 — 轉弱出場訊號）
       - T-1：出量實紅K + 收在當日高點附近（收最高）
       - T  ：開平 / 開綠（今日開盤 ≤ 前日收盤）
       - 動作：持有者出場

    2. bullish_entry（收低開高 — 轉強進場訊號）
       - T-1：出量實黑K + 收在當日低點附近（收最低）
       - T  ：開平 / 開紅（今日開盤 ≥ 前日收盤）
       - 動作：視為轉強進場訊號；停損 = T-1 低點

    3. limit_up_flat_warning（漲停隔天開平 — 危險警示）
       - T-1：漲停收盤（close ≈ 漲停價）
       - T  ：開平盤（|today_open − prev_close| / prev_close < 0.005）
       - 動作：警示訊號（非直接進出場，需結合判斷）

    例外：國際利空導致大盤普跌 → bearish_exit 不適用。
    此例外（apply_market_regime_filter）預設 OFF，Phase 2 補。

Output columns:
    ticker              — 股票代號
    signal_date         — 訊號日期（T，今日）
    signal_type         — 'bearish_exit' | 'bullish_entry' | 'limit_up_flat_warning'
    prev_date           — 前日日期（T-1）
    prev_close          — 前日收盤
    prev_high           — 前日最高
    prev_low            — 前日最低
    prev_volume         — 前日成交量
    prev_vol_ma5        — 前日 5MA 量（用於「出量」判斷）
    today_open          — 今日開盤
    today_open_gap_pct  — 今日開盤相對前日收盤漲跌幅（(open - prev_close) / prev_close）
    stop_loss           — 停損參考價（bullish_entry: prev_low；其他: NaN）

課程案例（sanity check 用）：
    3041 揚智  2020/10/21 — 收高 27.20、隔日開平盤後大量下攤（bearish_exit + limit_up_flat_warning）
    2038 海光  2021/06/23 — 收低跌停、隔日轉強開高（bullish_entry）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from zhuli.config import OpenSignalConfig


def detect(
    df: pd.DataFrame,
    cfg: OpenSignalConfig | None = None,
) -> pd.DataFrame:
    """Detect M 主力意圖 entry/exit signals.

    Args:
        df: Features DataFrame after add_features() + add_zhuli_features().
            Required columns: ticker, trade_date, open, high, low, close, volume,
            prev_close, prev_high, prev_low, prev_open (from add_features),
            prev_volume (from add_zhuli_features).
        cfg: OpenSignalConfig. Uses defaults if None.

    Returns:
        DataFrame of signal rows, one row per detected signal.
        Columns: see module docstring.
        Sorted by signal_date desc, then signal_type, then ticker.
    """
    if cfg is None:
        cfg = OpenSignalConfig()

    g = df.groupby("ticker", group_keys=False)

    # === 前日欄位（T-1）===
    # add_features() 已加 prev_close, prev_high, prev_low, prev_open
    # add_zhuli_features() 已加 prev_volume
    # 但 prev_date 需自行 shift
    prev_date = g["trade_date"].shift(1)

    prev_close = df["prev_close"]
    prev_high = df["prev_high"]
    prev_low = df["prev_low"]
    prev_open = df["prev_open"]
    prev_volume = df["prev_volume"]

    # === 前日 5MA 量（出量判斷基準）===
    # rolling(5) 在 shift(1) 後：昨日及其前 4 天的平均成交量 ≈ 前日 5MA
    # min_periods=3 避免資料不足的開頭 rows 變 NaN
    prev_vol_ma5 = (
        g["volume"]
        .shift(1)
        .rolling(5, min_periods=3)
        .mean()
        .reset_index(level=0, drop=True)
    )

    # === 前日 K 棒型態 ===
    prev_is_red = prev_close > prev_open       # 實紅K
    prev_is_black = prev_close < prev_open     # 實黑K（綠K 在台股術語）

    # 收最高：close 在當日 high 的一定比例以上
    # spec: prev.close >= prev.high * bearish_prev_close_position (預設 0.9)
    prev_close_near_high = prev_close >= prev_high * cfg.bearish_prev_close_position

    # 收最低：close 在當日 low 的「容忍幅度」以內
    # bullish_prev_close_position = 0.1 → close ≤ low * 1.1（距低點不超過 10%）
    # Source: strategy-indicators.md §M — 「前一天出量實黑K 收最低（或收相對低點）」
    prev_close_near_low = prev_close <= prev_low * (1 + cfg.bullish_prev_close_position)

    # 前日出量：volume > 5MA volume * multiplier
    prev_vol_burst = prev_volume > prev_vol_ma5 * cfg.prev_volume_multiplier

    # === 今日開盤位置 ===
    today_open = df["open"]
    today_open_gap_pct = (today_open - prev_close) / prev_close.replace(0, np.nan)

    # 開平/開綠（bearish_exit）：today.open <= prev.close
    today_open_flat_or_down = today_open <= prev_close * (1 + cfg.bearish_today_open_max_gain)

    # 開平/開紅（bullish_entry）：today.open >= prev.close
    today_open_flat_or_up = today_open >= prev_close * (1 + cfg.bullish_today_open_min_gain)

    # === 流動性過濾 ===
    if "vol_ma20" in df.columns:
        avg_vol = df["vol_ma20"]
    elif "avg_volume_20" in df.columns:
        avg_vol = df["avg_volume_20"]
    else:
        avg_vol = pd.Series(float("nan"), index=df.index)

    liquid_enough = (
        avg_vol.fillna(0) >= cfg.min_avg_volume_20
    ) & (
        df["close"] >= cfg.min_close
    )

    # === 漲停價估算（台股漲跌停 ±10%）===
    # 台股漲停 = 前日收盤 × 1.10（無條件截到 tick）
    # 這裡用 ≥ 9.5% 作為漲停判定（避免 tick 精度問題）
    LIMIT_UP_THRESHOLD = 0.095   # 前日漲幅 ≥ 9.5% 視為漲停
    prev_prev_close = g["close"].shift(2)
    prev_gain_pct = (prev_close - prev_prev_close) / prev_prev_close.replace(0, np.nan)
    prev_was_limit_up = prev_gain_pct >= LIMIT_UP_THRESHOLD

    # 今日開平：|open - prev_close| / prev_close < flat_threshold
    today_is_flat_open = (
        (today_open - prev_close).abs() / prev_close.replace(0, np.nan)
        < cfg.limit_up_flat_open_threshold
    )

    # === 必要欄位是否存在 ===
    required = ["prev_close", "prev_high", "prev_low", "prev_open", "prev_volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(
            f"open_signal_filter.detect() 缺少欄位: {missing}. "
            "確認已呼叫 add_features() + add_zhuli_features()."
        )

    # ===== Signal masks =====

    # 1. bearish_exit
    bearish_mask = (
        prev_is_red.fillna(False)
        & prev_close_near_high.fillna(False)
        & prev_vol_burst.fillna(False)
        & today_open_flat_or_down.fillna(False)
        & liquid_enough
        & prev_close.notna()
        & prev_high.notna()
        & prev_volume.notna()
    )

    # 2. bullish_entry
    bullish_mask = (
        prev_is_black.fillna(False)
        & prev_close_near_low.fillna(False)
        & prev_vol_burst.fillna(False)
        & today_open_flat_or_up.fillna(False)
        & liquid_enough
        & prev_close.notna()
        & prev_low.notna()
        & prev_volume.notna()
    )

    # 3. limit_up_flat_warning
    warning_mask = (
        prev_was_limit_up.fillna(False)
        & today_is_flat_open.fillna(False)
        & liquid_enough
        & prev_close.notna()
    )

    # ===== Build output rows =====
    frames = []

    for mask, sig_type in [
        (bearish_mask, "bearish_exit"),
        (bullish_mask, "bullish_entry"),
        (warning_mask, "limit_up_flat_warning"),
    ]:
        if not mask.any():
            continue
        hits = df[mask].copy()
        out = pd.DataFrame(
            {
                "ticker": hits["ticker"].values,
                "signal_date": hits["trade_date"].values,
                "signal_type": sig_type,
                "prev_date": prev_date[mask].values,
                "prev_close": prev_close[mask].values,
                "prev_high": prev_high[mask].values,
                "prev_low": prev_low[mask].values,
                "prev_volume": prev_volume[mask].values,
                "prev_vol_ma5": prev_vol_ma5[mask].values,
                "today_open": hits["open"].values,
                "today_open_gap_pct": today_open_gap_pct[mask].round(4).values,
                "stop_loss": (
                    prev_low[mask].values
                    if sig_type == "bullish_entry"
                    else np.full(mask.sum(), np.nan)
                ),
            }
        )
        frames.append(out)

    if not frames:
        return _empty_output()

    result = pd.concat(frames, ignore_index=True)
    return result.sort_values(
        ["signal_date", "signal_type", "ticker"],
        ascending=[False, True, True],
    ).reset_index(drop=True)


def _empty_output() -> pd.DataFrame:
    """Return empty DataFrame with correct output schema."""
    return pd.DataFrame(
        columns=[
            "ticker",
            "signal_date",
            "signal_type",
            "prev_date",
            "prev_close",
            "prev_high",
            "prev_low",
            "prev_volume",
            "prev_vol_ma5",
            "today_open",
            "today_open_gap_pct",
            "stop_loss",
        ]
    )
