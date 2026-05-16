"""tweezer_top_breakout_strict entry signal tests.

The strict variant extends tweezer_top_breakout (which requires clean_overhead)
with an additional attack_intensity >= 2 (推升攻擊 or stronger) requirement.
"""
from __future__ import annotations

from kline.entry.tweezer_top_breakout_strict import detect
from kline.features import add_features

from tests.conftest import make_bars


def _tweezer_breakout_rows():
    """Standard tweezer breakout fixture: 60 warm-up + 4 tweezer + 1 breakout."""
    rows = []
    for i in range(60):
        rows.append({"open": 99, "high": 101 + (i % 3) * 0.3, "low": 98,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    for h in [102.0, 102.1, 101.9, 102.0]:
        rows.append({"open": 100, "high": h, "low": 99,
                     "close": 100, "volume": 1000.0, "ma60": 100.0})
    rows.append({"open": 102, "high": 106, "low": 101, "close": 105,
                 "volume": 1000.0, "ma60": 100.0})
    return rows


def test_strict_does_not_fire_when_attack_intensity_zero():
    """Even with valid tweezer + clean overhead + breakout, attack_intensity=0 → no entry.

    The natural add_features result for this fixture is attack_intensity=0 (no push attack).
    Confirms that the base tweezer condition alone is NOT enough for strict variant.
    """
    df = add_features(make_bars(_tweezer_breakout_rows()))
    df.loc[64, "overhead_supply_layer"] = 0
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
    df.loc[64, "is_in_breakdown_pattern"] = False
    # attack_intensity is naturally 0 for this fixture; assert explicitly
    df.loc[64, "attack_intensity"] = 0
    signal = detect(df)
    assert not signal.iloc[64], (
        "attack_intensity=0 must block strict variant even when base tweezer fires"
    )


def test_strict_does_not_fire_when_attack_intensity_one():
    """attack_intensity=1 (波動前進) is below threshold → strict variant must not fire."""
    df = add_features(make_bars(_tweezer_breakout_rows()))
    df.loc[64, "overhead_supply_layer"] = 0
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
    df.loc[64, "is_in_breakdown_pattern"] = False
    df.loc[64, "attack_intensity"] = 1  # 波動前進 — below MIN_ATTACK_INTENSITY=2
    signal = detect(df)
    assert not signal.iloc[64], "attack_intensity=1 (波動前進) must not satisfy strict threshold"


def test_strict_fires_with_attack_intensity_two():
    """Tweezer breakout + clean overhead + attack_intensity=2 (推升攻擊) → fires."""
    df = add_features(make_bars(_tweezer_breakout_rows()))
    df.loc[64, "overhead_supply_layer"] = 0
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
    df.loc[64, "is_in_breakdown_pattern"] = False
    df.loc[64, "attack_intensity"] = 2  # 推升攻擊
    signal = detect(df)
    assert signal.iloc[64], "attack_intensity=2 (推升攻擊) should satisfy strict variant"


def test_strict_fires_with_attack_intensity_three():
    """attack_intensity=3 (跳空攻擊) is above threshold → strict variant fires."""
    df = add_features(make_bars(_tweezer_breakout_rows()))
    df.loc[64, "overhead_supply_layer"] = 0
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
    df.loc[64, "is_in_breakdown_pattern"] = False
    df.loc[64, "attack_intensity"] = 3  # 跳空攻擊
    signal = detect(df)
    assert signal.iloc[64], "attack_intensity=3 (跳空攻擊) should satisfy strict variant"


def test_strict_blocked_by_overhead_supply_even_with_attack():
    """attack_intensity >= 2 but overhead_supply_layer > 0 → base tweezer fails → strict fails."""
    df = add_features(make_bars(_tweezer_breakout_rows()))
    df.loc[64, "overhead_supply_layer"] = 2   # overhead supply present
    df.loc[64, "unfilled_gap_down_count_240d"] = 0
    df.loc[64, "is_in_breakdown_pattern"] = False
    df.loc[64, "attack_intensity"] = 3  # strong attack, but overhead blocks
    signal = detect(df)
    assert not signal.iloc[64], (
        "Overhead supply must block strict variant even with strong attack_intensity"
    )


def test_strict_is_subset_of_base():
    """Every bar where strict fires must also fire for base tweezer.

    This is the fundamental invariant: strict ⊆ base.
    """
    from kline.entry.tweezer_top_breakout import detect as detect_base

    df = add_features(make_bars(_tweezer_breakout_rows()))
    # Force a mix: some bars with attack, some without
    df["attack_intensity"] = df["attack_intensity"].where(
        df.index % 3 != 0, other=2
    )
    base_signal = detect_base(df)
    strict_signal = detect(df)
    # strict must be a strict subset of base (every strict True is also base True)
    assert not (strict_signal & ~base_signal).any(), (
        "strict variant fired where base did not — invariant violated"
    )
