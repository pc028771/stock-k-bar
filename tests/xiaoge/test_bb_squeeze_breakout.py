"""Tests for xiaoge/entry/bb_squeeze_breakout.py — detect().

Course source: 權證小哥課程 ch06-ch08, ch12 飆股口袋名單做多策略 #8 #9.
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §1.

課程原話 (verbatim):
> 「布林昇龍拳…先沿下軌洗清浮額…連續二根紅K或三根紅K，從下通道一下就打到上通道，
>   這種是多頭表態。」(ch07 00:21–01:16)
> 「布林軌道打開…短期有整理完畢往上攻擊的態勢，那這種呢通常壓縮的越久，
>   之後的漲勢拉就越驚人。」(ch12 06:44–07:08)

Detector conditions (spec §1):
  1. Squeeze precondition: past 10 bars all bandwidth ≤ 12 (bb_in_squeeze)
  2a. 升龍拳: 2+ consecutive red K's, prev close ≤ bb_mid, today cross above bb_upper
  2b. 開布林: single red K + vol ≥ 1.5× MA5 vol + cross upper
  3. Trend filter: 5MA up-sloping AND close > 5MA
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xiaoge.entry.bb_squeeze_breakout import detect


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _build_breakout_df(
    n_warmup: int = 20,
    fire_row_close: float = 108.0,
    fire_row_open: float = 99.0,
    prev_close: float = 97.0,
    prev_open: float = 96.0,
    bb_in_squeeze_val: bool = True,
    prev_bb_upper: float = 105.0,
    today_bb_upper: float = 105.0,
    prev_bb_mid: float = 102.0,
    ma5_rising: bool = True,
    close_above_ma5: bool = True,
    vol: float = 2000.0,
    ticker: str = "A001",
) -> pd.DataFrame:
    """Build a minimal DataFrame with a squeezed history + 2-row breakout."""
    # Build warm-up period (in squeeze, close around 100)
    n = n_warmup + 2
    dates = pd.bdate_range("2026-01-05", periods=n)
    close_arr = np.full(n, 100.0)
    open_arr  = np.full(n, 99.0)
    close_arr[-2] = prev_close
    close_arr[-1] = fire_row_close
    open_arr[-2]  = prev_open
    open_arr[-1]  = fire_row_open

    bb_in_sq = np.ones(n, dtype=bool)
    bb_in_sq[-1] = bb_in_squeeze_val   # squeeze precondition = yesterday was squeezed

    bb_upper_arr = np.full(n, 106.0)
    bb_upper_arr[-2] = prev_bb_upper
    bb_upper_arr[-1] = today_bb_upper

    bb_mid_arr = np.full(n, 102.0)
    bb_mid_arr[-2] = prev_bb_mid

    # ma5 construction: use constant so slope is determined by last entry
    ma5_base = 98.0
    ma5_arr  = np.full(n, ma5_base)
    if ma5_rising:
        ma5_arr[-1] = ma5_base + 0.5   # today > yesterday → ma5 rising
    else:
        ma5_arr[-1] = ma5_base - 0.5

    if close_above_ma5:
        close_arr[-1] = max(close_arr[-1], ma5_arr[-1] + 1)
    else:
        close_arr[-1] = ma5_arr[-1] - 1  # below ma5

    vol_arr = np.full(n, 1000.0)
    vol_arr[-1] = vol

    df = pd.DataFrame({
        "ticker":       ticker,
        "trade_date":   dates,
        "open":         open_arr,
        "high":         close_arr * 1.02,
        "low":          open_arr  * 0.98,
        "close":        close_arr,
        "volume":       vol_arr,
        "bb_upper":     bb_upper_arr,
        "bb_mid":       bb_mid_arr,
        "bb_lower":     np.full(n, 94.0),
        "bb_bandwidth": np.full(n, 8.0),
        "bb_in_squeeze": bb_in_sq,
        "ma5":          ma5_arr,
    })
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Positive (fire) tests
# ---------------------------------------------------------------------------

class TestBBSqueezeBreakoutFire:
    def test_shenglongquan_fires(self):
        """ch07 升龍拳: squeeze + 2 consecutive red K + prev near mid + cross upper → True."""
        df = _build_breakout_df(
            fire_row_close=110.0,
            fire_row_open=98.0,      # red K today
            prev_close=97.0,         # prev close ≤ bb_mid (102)
            prev_open=96.0,          # red K yesterday
            prev_bb_mid=102.0,
            today_bb_upper=105.0,    # 110 > 105 → cross upper
            bb_in_squeeze_val=True,  # was squeezed yesterday
        )
        sig = detect(df, breakout_mode="shenglongquan")
        assert sig.iloc[-1], (
            "ch07 升龍拳: squeeze + 2紅K + prev_near_mid + cross_upper 應觸發"
        )

    def test_open_breakout_fires(self):
        """ch12 開布林: squeeze + single red K + high volume → True."""
        # Volume today = 2000, vol_ma5 will be near 1000 → vol_ratio ≥ 1.5 OK
        df = _build_breakout_df(
            fire_row_close=110.0,
            fire_row_open=98.0,
            vol=2500.0,
            bb_in_squeeze_val=True,
            today_bb_upper=105.0,
        )
        sig = detect(df, breakout_mode="open_breakout", vol_multiple=1.5)
        assert sig.iloc[-1], "ch12 開布林: squeeze + 紅K + 放量應觸發"

    def test_any_mode_fires_when_shenglongquan(self):
        """breakout_mode='any' should fire when 升龍拳 condition met."""
        df = _build_breakout_df(
            fire_row_close=110.0, fire_row_open=98.0,
            prev_close=97.0, prev_open=96.0,
            today_bb_upper=105.0,
        )
        sig = detect(df, breakout_mode="any")
        assert sig.iloc[-1], "any mode: 升龍拳 命中應觸發"


# ---------------------------------------------------------------------------
# Negative (no-fire) tests
# ---------------------------------------------------------------------------

class TestBBSqueezeBreakoutNoFire:
    def test_no_fire_when_not_squeezed(self):
        """Without squeeze precondition, detector should not fire.

        The detector checks was_squeezed = shift(1) of bb_in_squeeze.
        To block the signal, YESTERDAY's bb_in_squeeze must also be False.
        """
        df = _build_breakout_df(bb_in_squeeze_val=False)
        # was_squeezed = yesterday's bb_in_squeeze; the helper sets bb_in_squeeze
        # for the last row only. We must also set the row before last to False.
        df.loc[df.index[-2], "bb_in_squeeze"] = False
        sig = detect(df, breakout_mode="shenglongquan")
        assert not sig.iloc[-1], "沒有 squeeze 前置條件不應觸發 (ch12: 壓縮才有驚人漲勢)"

    def test_no_fire_when_not_cross_upper(self):
        """close below bb_upper → no breakout."""
        df = _build_breakout_df(
            fire_row_close=103.0,    # close < bb_upper (105)
            today_bb_upper=105.0,
        )
        sig = detect(df, breakout_mode="shenglongquan")
        assert not sig.iloc[-1], "收盤未穿越上軌不應觸發"

    def test_no_fire_when_ma5_falling(self):
        """Trend filter: ma5 not rising → no fire."""
        df = _build_breakout_df(
            fire_row_close=110.0, fire_row_open=98.0,
            prev_close=97.0, prev_open=96.0,
            today_bb_upper=105.0,
            ma5_rising=False,
        )
        sig = detect(df, breakout_mode="shenglongquan")
        assert not sig.iloc[-1], "ch12 #6: 5MA 下彎時不應觸發 (trend filter)"

    def test_no_fire_when_close_below_ma5(self):
        """Trend filter: close below ma5 → no fire."""
        df = _build_breakout_df(
            fire_row_close=110.0, fire_row_open=98.0,
            prev_close=97.0, prev_open=96.0,
            today_bb_upper=105.0,
            close_above_ma5=False,
        )
        sig = detect(df, breakout_mode="shenglongquan")
        assert not sig.iloc[-1], "ch12 #6: 收盤低於 5MA 不應觸發 (trend filter)"


# ---------------------------------------------------------------------------
# Parameter tests
# ---------------------------------------------------------------------------

class TestBBSqueezeBreakoutParameters:
    def test_vol_multiple_changes_open_breakout(self):
        """Higher vol_multiple threshold should prevent firing when volume is borderline.

        vol_ma5 is computed as rolling(5) including today, so:
        - If previous 4 bars have vol=1000 and today=vol, vol_ma5 = mean([1000,1000,1000,1000,vol])
        - We want ratio = vol / vol_ma5 to be in range (1.5, 2.5) so:
          with vol=2000: vol_ma5 = (4000+2000)/5 = 1200, ratio = 2000/1200 = 1.67 ≥ 1.5 → fires
          with vol_multiple=2.0: 1.67 < 2.0 → should NOT fire
        """
        df = _build_breakout_df(
            fire_row_close=110.0, fire_row_open=98.0,
            today_bb_upper=105.0, vol=2000.0
        )
        # vol_ma5 ≈ 1200 (rolling mean with 4 prior bars at 1000 + today 2000)
        # ratio = 2000/1200 ≈ 1.67
        # vol_multiple=2.0 → 1.67 < 2.0 → should NOT fire
        sig_strict = detect(df, breakout_mode="open_breakout", vol_multiple=2.0)
        # vol_multiple=1.5 → 1.67 ≥ 1.5 → should fire
        sig_loose  = detect(df, breakout_mode="open_breakout", vol_multiple=1.5)
        assert not sig_strict.iloc[-1], "vol_multiple=2.0 時量不足應不觸發"
        assert sig_loose.iloc[-1], "vol_multiple=1.5 時量足夠應觸發"


# ---------------------------------------------------------------------------
# NaN / missing column tolerance tests
# ---------------------------------------------------------------------------

class TestBBSqueezeBreakoutNanTolerance:
    def test_nan_bb_columns_return_false(self):
        """NaN in bb columns should result in False (not crash)."""
        df = _build_breakout_df()
        df.loc[df.index[-1], "bb_upper"] = float("nan")
        df.loc[df.index[-1], "bb_mid"]   = float("nan")
        sig = detect(df, breakout_mode="any")
        assert not sig.iloc[-1], "bb 欄位 NaN 時不應觸發 (graceful False)"

    def test_missing_ma5_falls_back_gracefully(self):
        """When ma5 column absent, detector computes it from close (no crash)."""
        df = _build_breakout_df()
        df_no_ma5 = df.drop(columns=["ma5"])
        # Should not raise; result may be all False but no exception
        try:
            sig = detect(df_no_ma5, breakout_mode="any")
            assert isinstance(sig, pd.Series)
        except KeyError:
            pytest.fail("缺 ma5 欄位不應 raise KeyError，應 gracefully 降級")

    def test_result_is_bool_series(self):
        """detect() must return a bool Series indexed identically to input."""
        df = _build_breakout_df()
        sig = detect(df)
        assert isinstance(sig, pd.Series), "detect 必須回傳 pd.Series"
        assert sig.dtype == bool, "dtype 必須是 bool"
        assert len(sig) == len(df), "長度必須與 df 相同"
