"""Calibration interface — update default config values from data.

Currently stub. Future: feed POC #2 large_volume_ratios.csv or sanity-check
case data to suggest refined parameter defaults.

Course source: 主力大全方位操盤教戰守則 (林家洋)
Status: Phase 1 stub — to be implemented after backtest sanity check (Phase 2).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def calibrate_from_cases(case_csv_path: str | Path) -> dict[str, Any]:
    """Read 講師案例 CSV, return suggested config updates.

    Expected CSV columns:
        ticker, signal_date, suffocation_date, breakout_date,
        vol_ratio, ma20_slope, scenario

    Example future use: run after each new spec audit to refresh defaults.
    After Phase 2 backtest is available, this function will:
      1. Load known-good instructor cases.
      2. Compute empirical vol_ratio distribution across cases.
      3. Suggest max20_volume_ratio that captures ≥ 95% of known cases.
      4. Suggest breakout_volume_multiplier from case breakout bars.

    Returns:
        dict with suggested override values, e.g.:
        {"max20_volume_ratio": 0.12, "breakout_volume_multiplier": 1.2}
    """
    raise NotImplementedError(
        "Phase 1 stub — to be implemented after backtest sanity check (Phase 2). "
        "See docs/主力大課程/phase1_scanner_proposal.md §3 for roadmap."
    )


def calibrate_from_backtest_results(
    backtest_csv_path: str | Path,
    target_win_rate: float = 0.55,
) -> dict[str, Any]:
    """Suggest config updates that maximise win rate on backtest output.

    Phase 2 implementation will:
      1. Load backtest result CSV (entries, exits, P&L).
      2. Walk-forward grid-search over soft margin parameters.
      3. Return the parameter set achieving >= target_win_rate in-sample.

    Args:
        backtest_csv_path: Path to backtest result CSV.
        target_win_rate: Minimum acceptable win rate (default 0.55).

    Returns:
        dict with suggested override values.
    """
    raise NotImplementedError(
        "Phase 2 stub — requires backtest engine from Phase 2."
    )
