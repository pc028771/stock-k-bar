"""Unit tests for small_structure detector - boundary cases."""
from __future__ import annotations

import numpy as np
import pandas as pd
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent.parent.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.entry.small_structure.detector import detect, detect_with_diagnostics

COND_COLS = [
    'cond_prior_attack', 'cond_sideways', 'cond_vol_contracted',
    'cond_ma5_close', 'cond_above_ma10', 'cond_high_holding',
]


def _make_df(
    attack: bool = True,
    sideways: bool = True,
    vol_contracted: bool = True,
    ma5_close: bool = True,
    above_ma10: bool = True,
    high_holding: bool = True,
) -> pd.DataFrame:
    """Synthetic DataFrame for testing.

    Structure (n=55 bars):
      idx 0-34 : flat low phase (20.0)
      idx 35-44: attack phase (20 -> 33.5, +67%)
      idx 45-54: high sideways (~33.0)

    At idx 54: rolling(20).min().shift(5) covers idx 30-49,
    including low phase -> prior_low~20, ratio~1.65 > 1.10 (pass).
    MA5 matches close in plateau -> ratio > 0.93 (pass).
    """
    base_n = 55

    low_phase    = [20.0] * 35
    attack_phase = [20.0 + i * 1.5 for i in range(10)]   # 20 -> 33.5
    side_phase   = [33.0 + (i % 3 - 1) * 0.1 for i in range(10)]
    close_vals   = (low_phase + attack_phase + side_phase)[:base_n]

    if not attack:
        close_vals = [20.0 + i * 0.006 for i in range(base_n)]   # only +3%

    if not sideways:
        for i in range(base_n - 5, base_n):
            close_vals[i] += (i % 2) * 4.0   # large oscillation -> range > 10%

    close = pd.Series(close_vals, dtype=float)
    high  = close * 1.01
    low_px = close * 0.99

    ma5_val  = close.rolling(5).mean().fillna(close)
    ma10_val = close.rolling(10).mean().fillna(close)

    if not ma5_close:
        ma5_val = close * 0.80   # MA5 far below close

    if not above_ma10:
        ma10_val = close * 1.10  # close below MA10

    if not high_holding:
        high = high.copy()
        for i in range(base_n - 10, base_n):
            high.iloc[i] = close.iloc[i] * 1.25   # recent extreme high

    if vol_contracted:
        vol_ratio = pd.Series([1.2] * base_n, dtype=float)
        for i in range(base_n - 3, base_n):
            vol_ratio.iloc[i] = 0.7   # declining
    else:
        vol_ratio = pd.Series([2.5] * base_n, dtype=float)   # high volume

    df = pd.DataFrame({
        'date':       [f'2026-01-{i+1:04d}'[:10] for i in range(base_n)],
        'trade_date': [f'2026-01-{i+1:04d}'[:10] for i in range(base_n)],
        'open':       close * 0.99,
        'high':       high,
        'low':        low_px,
        'close':      close,
        'volume':     pd.Series([10000.0] * base_n),
        'vol_ratio_20': vol_ratio,
        'ma5':        ma5_val,
        'ma10':       ma10_val,
        'ma20':       close.rolling(20).mean().fillna(close),
        'ma60':       close.rolling(60).mean().fillna(close),
    })
    return df


class TestDetect:
    def test_all_conditions_pass(self):
        """All 6 conditions met -> detect() should trigger."""
        df = _make_df()
        sig = detect(df)
        assert sig.iloc[-1] == True, "All 6 conditions met should trigger"

    def test_missing_attack_fails(self):
        """Insufficient prior attack -> should not trigger."""
        df = _make_df(attack=False)
        sig = detect(df)
        assert sig.iloc[-1] == False, "Insufficient prior attack should not trigger"

    def test_not_sideways_fails(self):
        """High oscillation (not sideways) -> should not trigger."""
        df = _make_df(sideways=False)
        sig = detect(df)
        assert sig.iloc[-1] == False, "High oscillation should not trigger"

    def test_vol_not_contracted_fails(self):
        """Volume not contracted -> should not trigger."""
        df = _make_df(vol_contracted=False)
        sig = detect(df)
        assert sig.iloc[-1] == False, "High volume should not trigger"

    def test_ma5_too_far_fails(self):
        """MA5 far below close -> should not trigger."""
        df = _make_df(ma5_close=False)
        sig = detect(df)
        assert sig.iloc[-1] == False, "MA5 far below close should not trigger"

    def test_below_ma10_fails(self):
        """Close below MA10 -> should not trigger."""
        df = _make_df(above_ma10=False)
        sig = detect(df)
        assert sig.iloc[-1] == False, "Close below MA10 should not trigger"

    def test_high_not_held_fails(self):
        """High position not maintained -> should not trigger."""
        df = _make_df(high_holding=False)
        sig = detect(df)
        assert sig.iloc[-1] == False, "High not held should not trigger"

    def test_returns_bool_series(self):
        """detect() should return a bool-compatible Series."""
        df = _make_df()
        sig = detect(df)
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(df)

    def test_empty_df_returns_empty_series(self):
        """Empty DataFrame should return empty Series without crashing."""
        df = pd.DataFrame(columns=['date', 'close', 'high', 'low', 'vol_ratio_20', 'ma5', 'ma10'])
        sig = detect(df)
        assert len(sig) == 0

    def test_short_df_no_signal(self):
        """DataFrame with < 25 rows should not trigger (rolling window too short)."""
        df = _make_df()
        df_short = df.iloc[:20].copy().reset_index(drop=True)
        sig = detect(df_short)
        assert sig.iloc[-1] == False, "Short data should not trigger"


class TestDetectWithDiagnostics:
    def test_returns_dataframe_with_all_cond_cols(self):
        """detect_with_diagnostics should include all 6 cond_ columns."""
        df = _make_df()
        result = detect_with_diagnostics(df)
        for col in COND_COLS:
            assert col in result.columns, f"Missing column: {col}"

    def test_all_pass_matches_detect(self):
        """all_pass column should match detect() output."""
        df = _make_df()
        sig = detect(df)
        diag = detect_with_diagnostics(df)
        pd.testing.assert_series_equal(
            sig.reset_index(drop=True).iloc[-10:],
            diag['all_pass'].reset_index(drop=True).iloc[-10:],
            check_names=False,
        )

    def test_hit_count_correct_when_all_pass(self):
        """When all 6 conditions pass, hit count should be 6."""
        df = _make_df()
        diag = detect_with_diagnostics(df)
        last = diag.iloc[-1]
        hit = sum(bool(last[c]) for c in COND_COLS)
        assert last['all_pass'] == True, f"Expected all_pass=True, got {dict(last[COND_COLS])}"
        assert hit == 6, f"Expected 6 hits, got {hit}: {dict(last[COND_COLS])}"

    def test_hit_count_5_when_one_fails(self):
        """When one condition fails (attack=False), hit count should be 5."""
        df = _make_df(attack=False)
        diag = detect_with_diagnostics(df)
        last = diag.iloc[-1]
        hit = sum(bool(last[c]) for c in COND_COLS)
        assert hit == 5, f"Expected 5 hits, got {hit}"
        assert last['cond_prior_attack'] == False
