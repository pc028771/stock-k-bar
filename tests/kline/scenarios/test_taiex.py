"""Tests for Task 3.S4 — 大盤創紀錄跌點 (TAIEX §30).

Coverage:
  T3S4.1  ContextSnapshot 新增 5 個 taiex 欄位通過 schema 驗證
  T3S4.2  build_context_snapshot 從 fixture taiex DB 填值正確
  T3S4.3  B07 record_decline_rebound playbook 載入正確 (required_context + branches)
  T3S4.4  advisor.analyze 對 fixture 跑 B07 branch 觸發符合預期
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.kline.scenarios._schema import ContextSnapshot
from scripts.kline.scenarios.context import build_context_snapshot, _TaiexContext
from scripts.kline.scenarios import load_playbooks
from scripts.kline.scenarios.condition import evaluate

PLAYBOOKS_DIR = Path("scripts/kline/scenarios/playbooks")

# ---------------------------------------------------------------------------
# T3S4.1 — ContextSnapshot schema 包含 5 個 taiex 欄位
# ---------------------------------------------------------------------------


class TestT3S41Schema:
    """T3S4.1: 5 taiex 欄位 (drop_point / drop_pct / limit_down_count /
    record_any_criterion / no_new_low_next_day) 存在於 ContextSnapshot."""

    def test_taiex_fields_exist_all_none_default(self):
        """ContextSnapshot 預設值全部為 None (optional)."""
        snap = ContextSnapshot()
        assert snap.taiex_record_drop_point is None
        assert snap.taiex_record_drop_pct is None
        assert snap.taiex_record_limit_down_count is None
        assert snap.taiex_record_any_criterion is None
        assert snap.taiex_no_new_low_next_day is None

    def test_taiex_fields_accept_bool_values(self):
        """ContextSnapshot 接受 bool 值的 taiex 欄位."""
        snap = ContextSnapshot(
            taiex_record_drop_point=True,
            taiex_record_drop_pct=False,
            taiex_record_limit_down_count=True,
            taiex_record_any_criterion=True,
            taiex_no_new_low_next_day=True,
        )
        assert snap.taiex_record_drop_point is True
        assert snap.taiex_record_drop_pct is False
        assert snap.taiex_record_limit_down_count is True
        assert snap.taiex_record_any_criterion is True
        assert snap.taiex_no_new_low_next_day is True

    def test_schema_rejects_extra_fields(self):
        """extra='forbid' — 不允許未定義欄位."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ContextSnapshot(unknown_taiex_field=True)


# ---------------------------------------------------------------------------
# Fixtures: in-memory SQLite databases
# ---------------------------------------------------------------------------


def _make_taiex_db(tmp_path: Path) -> Path:
    """Create a minimal taiex_history.sqlite with known data.

    Contains:
    - 2024-08-02: close 21000 → 2024-08-05 close 19200 (drop 1807pt, ~8.6%)
    - 2024-08-05: the historic record drop day
    - 2024-08-06: close 19800 (no new low → low 19100 > 2024-08-05 low 18900)
    """
    db_path = tmp_path / "taiex_history.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE taiex_daily (
            trade_date TEXT PRIMARY KEY,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER
        )
    """)
    rows = [
        # Earlier normal trading days (to establish history)
        ("2024-01-02", 17900.0, 18100.0, 17850.0, 17853.0, 6000000000),
        ("2024-01-03", 17870.0, 17900.0, 17550.0, 17559.0, 6500000000),
        ("2024-07-01", 22000.0, 22200.0, 21900.0, 22000.0, 7000000000),
        ("2024-08-02", 21500.0, 21500.0, 20990.0, 21000.0, 8000000000),  # prev normal
        # 2024-08-05: 歷史最大跌點 (1807pt)
        ("2024-08-05", 20200.0, 20300.0, 18900.0, 19200.0, 12000000000),
        # 2024-08-06: 隔日不再創新低 (low 19100 > 18900)
        ("2024-08-06", 19400.0, 20000.0, 19100.0, 19800.0, 9000000000),
    ]
    conn.executemany(
        "INSERT INTO taiex_daily VALUES (?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return db_path


def _make_limit_down_db(tmp_path: Path) -> Path:
    """Create a minimal limit_down_history.sqlite with known data."""
    db_path = tmp_path / "limit_down_history.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE limit_down_daily (
            trade_date TEXT PRIMARY KEY,
            limit_down_count INTEGER
        )
    """)
    rows = [
        ("2024-01-02", 5),
        ("2024-01-03", 8),
        ("2024-07-01", 3),
        ("2024-08-02", 12),
        ("2024-08-05", 497),  # 歷史最高跌停家數
        ("2024-08-06", 20),
    ]
    conn.executemany(
        "INSERT INTO limit_down_daily VALUES (?,?)", rows
    )
    conn.commit()
    conn.close()
    return db_path


def _make_bars_df(
    ticker: str = "2330",
    today_date: str = "2024-08-05",
    n_bars: int = 10,
) -> pd.DataFrame:
    """Minimal features-enriched bars DataFrame for build_context_snapshot."""
    dates = pd.bdate_range(end=today_date, periods=n_bars, freq="B")
    df = pd.DataFrame({
        "ticker": ticker,
        "trade_date": dates.strftime("%Y-%m-%d"),
        "close": np.linspace(800.0, 850.0, n_bars),
        "open": np.linspace(799.0, 849.0, n_bars),
        "high": np.linspace(805.0, 855.0, n_bars),
        "low": np.linspace(795.0, 845.0, n_bars),
        "volume": 5_000_000,
        "prev_close": np.linspace(798.0, 848.0, n_bars),
        # Required features.py fields (all stubbed to avoid WARN noise in tests)
        "attack_cost": 830.0,
        "attack_intent_zone_high": 860.0,
        "attack_intent_zone_low": 820.0,
        "defensive_low": 790.0,
        "ma5_will_rise": True,
        "ma10_will_rise": True,
        "ma20_will_rise": False,
        "ma60_will_rise": True,
        "is_just_broke_high": False,
        "is_limit_up_locked": False,
        "is_anomalous_volume": True,
    })
    return df


# ---------------------------------------------------------------------------
# T3S4.2 — build_context_snapshot 填值正確
# ---------------------------------------------------------------------------


class TestT3S42ContextBuild:
    """T3S4.2: build_context_snapshot 從 fixture DB 填 taiex 欄位正確."""

    def _patch_taiex_context(self, taiex_db: Path, ld_db: Path):
        """Patch _TaiexContext to use fixture DBs instead of production paths."""
        import scripts.kline.scenarios.context as ctx_mod
        # Reset class state
        _TaiexContext._loaded = False
        _TaiexContext._taiex_df = None
        _TaiexContext._ld_df = None
        # Patch paths
        ctx_mod._TAIEX_DB = taiex_db
        ctx_mod._LIMIT_DOWN_DB = ld_db

    def _restore_taiex_context(self):
        import scripts.kline.scenarios.context as ctx_mod
        from pathlib import Path as _Path
        _wt = _Path(__file__).resolve().parents[4]
        ctx_mod._TAIEX_DB = _wt / "data/analysis/kline_patterns/taiex_history.sqlite"
        ctx_mod._LIMIT_DOWN_DB = _wt / "data/analysis/kline_patterns/limit_down_history.sqlite"
        _TaiexContext._loaded = False
        _TaiexContext._taiex_df = None
        _TaiexContext._ld_df = None

    def test_record_drop_day_all_true(self, tmp_path):
        """2024-08-05 應: drop_point=True, drop_pct=True, limit_down_count=True, any=True."""
        taiex_db = _make_taiex_db(tmp_path)
        ld_db = _make_limit_down_db(tmp_path)
        self._patch_taiex_context(taiex_db, ld_db)
        try:
            bars = _make_bars_df(today_date="2024-08-05")
            overrides = {
                "broker_tier1_buy": None,
                "teacher_tier": None,
                "broker_concentration": None,
                "ch2_warning_score": None,
                "sector_consensus_direction": None,
            }
            snap, warns = build_context_snapshot(bars, "2024-08-05", "2330", overrides=overrides)
            assert snap.taiex_record_drop_point is True, (
                f"Expected drop_point=True, got {snap.taiex_record_drop_point}"
            )
            assert snap.taiex_record_drop_pct is True, (
                f"Expected drop_pct=True, got {snap.taiex_record_drop_pct}"
            )
            assert snap.taiex_record_limit_down_count is True, (
                f"Expected limit_down_count=True, got {snap.taiex_record_limit_down_count}"
            )
            assert snap.taiex_record_any_criterion is True, (
                "taiex_record_any_criterion should be True when any sub-flag is True"
            )
            # 2024-08-06 low (19100) > 2024-08-05 low (18900) → no_new_low=True
            assert snap.taiex_no_new_low_next_day is True, (
                f"Expected no_new_low_next_day=True, got {snap.taiex_no_new_low_next_day}"
            )
        finally:
            self._restore_taiex_context()

    def test_normal_day_drop_point_not_record(self, tmp_path):
        """2024-08-02: drop < 2024-08-05 record → drop_point=False after 2024-08-05 added."""
        taiex_db = _make_taiex_db(tmp_path)
        ld_db = _make_limit_down_db(tmp_path)
        self._patch_taiex_context(taiex_db, ld_db)
        try:
            # Use 2024-08-06 (the day AFTER the record drop) — drop was small
            # 2024-08-06 close=19800, prev (2024-08-05) close=19200 → rose, drop_point = negative
            # so taiex_record_drop_point should be False (not a record drop)
            bars = _make_bars_df(today_date="2024-08-06")
            overrides = {
                "broker_tier1_buy": None, "teacher_tier": None,
                "broker_concentration": None, "ch2_warning_score": None,
                "sector_consensus_direction": None,
            }
            snap, _ = build_context_snapshot(bars, "2024-08-06", "2330", overrides=overrides)
            # 2024-08-06: close > prev_close (market bounced) → drop_point negative → False
            assert snap.taiex_record_drop_point is False, (
                f"2024-08-06 is a rebound day, drop_point should be False, got {snap.taiex_record_drop_point}"
            )
            # limit_down=20, historical max=497 → False
            assert snap.taiex_record_limit_down_count is False, (
                f"limit_down=20 should not be record vs 497, got {snap.taiex_record_limit_down_count}"
            )
        finally:
            self._restore_taiex_context()

    def test_overrides_win_over_db(self, tmp_path):
        """overrides 優先於 DB 計算結果."""
        taiex_db = _make_taiex_db(tmp_path)
        ld_db = _make_limit_down_db(tmp_path)
        self._patch_taiex_context(taiex_db, ld_db)
        try:
            bars = _make_bars_df(today_date="2024-08-05")
            overrides = {
                "taiex_record_drop_point": False,   # override: force False despite DB=True
                "taiex_record_drop_pct": False,
                "taiex_record_limit_down_count": False,
                "taiex_record_any_criterion": False,
                "taiex_no_new_low_next_day": False,
            }
            snap, _ = build_context_snapshot(bars, "2024-08-05", "2330", overrides=overrides)
            assert snap.taiex_record_drop_point is False
            assert snap.taiex_record_any_criterion is False
        finally:
            self._restore_taiex_context()

    def test_missing_db_returns_none_with_warn(self, tmp_path):
        """DB 不存在 → taiex 欄位為 None + warn 訊息."""
        import scripts.kline.scenarios.context as ctx_mod
        _TaiexContext._loaded = False
        _TaiexContext._taiex_df = None
        _TaiexContext._ld_df = None
        ctx_mod._TAIEX_DB = tmp_path / "nonexistent_taiex.sqlite"
        ctx_mod._LIMIT_DOWN_DB = tmp_path / "nonexistent_ld.sqlite"
        try:
            bars = _make_bars_df(today_date="2024-08-05")
            snap, warns = build_context_snapshot(bars, "2024-08-05", "2330")
            assert snap.taiex_record_drop_point is None
            assert snap.taiex_record_any_criterion is None
            assert snap.taiex_no_new_low_next_day is None
            # Should have warns for missing taiex fields
            taiex_warns = [w for w in warns if "taiex" in w.lower()]
            assert len(taiex_warns) >= 1, f"Expected taiex warns, got: {warns}"
        finally:
            self._restore_taiex_context()


# ---------------------------------------------------------------------------
# T3S4.3 — B07 playbook 載入正確
# ---------------------------------------------------------------------------


class TestT3S43PlaybookLoad:
    """T3S4.3: record_decline_rebound.yaml 載入正確."""

    def test_b07_loads_without_error(self):
        """B07 playbook 載入無 exception."""
        result = load_playbooks([PLAYBOOKS_DIR])
        assert "record_decline_rebound" in result

    def test_b07_required_context_is_taiex_record_any_criterion(self):
        """required_context 使用 taiex_record_any_criterion（三項 OR 複合旗標）."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        assert "taiex_record_any_criterion" in pb.setup.required_context

    def test_b07_has_three_branches(self):
        """B07 有 B1_taiex_no_new_low / B2_taiex_new_low / B3_hold_watch 三個 branch."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        branch_ids = [b.id for b in pb.branches]
        assert "B1_taiex_no_new_low" in branch_ids
        assert "B2_taiex_new_low" in branch_ids
        assert "B3_hold_watch" in branch_ids

    def test_b07_b1_is_entry_signal(self):
        """B1_taiex_no_new_low action type = entry_signal."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        b1 = next(b for b in pb.branches if b.id == "B1_taiex_no_new_low")
        assert b1.action.type == "entry_signal"

    def test_b07_b2_is_exhaust_invalid(self):
        """B2_taiex_new_low action type = exhaust_invalid."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        b2 = next(b for b in pb.branches if b.id == "B2_taiex_new_low")
        assert b2.action.type == "exhaust_invalid"

    def test_b07_b1_when_uses_context_taiex_no_new_low(self):
        """B1 when condition 引用 context.taiex_no_new_low_next_day: true."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        b1 = next(b for b in pb.branches if b.id == "B1_taiex_no_new_low")
        assert "context.taiex_no_new_low_next_day" in b1.when
        assert b1.when["context.taiex_no_new_low_next_day"] is True

    def test_b07_b2_when_uses_context_taiex_no_new_low_false(self):
        """B2 when condition 引用 context.taiex_no_new_low_next_day: false."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        b2 = next(b for b in pb.branches if b.id == "B2_taiex_new_low")
        assert "context.taiex_no_new_low_next_day" in b2.when
        assert b2.when["context.taiex_no_new_low_next_day"] is False

    def test_b07_course_sources_reference_article_77DC(self):
        """course_sources 引用 77DC434EC71DB04553752A44C9354680."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        article_ids = [cs.article_id for cs in pb.course_sources if cs.article_id]
        assert "77DC434EC71DB04553752A44C9354680" in article_ids

    def test_b07_b1_stub_documented(self):
        """B1 notes 記錄 STUB-NEED-USER S4."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        b1 = next(b for b in pb.branches if b.id == "B1_taiex_no_new_low")
        notes_text = " ".join(b1.action.notes)
        assert "STUB" in notes_text or "S4" in notes_text


# ---------------------------------------------------------------------------
# T3S4.4 — condition.evaluate 對 taiex 欄位行為正確
# ---------------------------------------------------------------------------


def _make_row(**kwargs) -> pd.Series:
    defaults = {
        "open": 100.0, "high": 105.0, "low": 95.0, "close": 103.0,
        "volume": 1_000_000,
        "prev_open": 99.0, "prev_high": 104.0, "prev_low": 94.0, "prev_close": 101.0,
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


def _make_ctx(**kwargs) -> ContextSnapshot:
    defaults = {
        "broker_tier1_buy": None, "teacher_tier": None,
        "ch2_warning_score": None, "sector_consensus_direction": None,
        "ma5_will_rise": None, "ma10_will_rise": None,
        "ma20_will_rise": None, "ma60_will_rise": None,
        "attack_cost": None, "defensive_low": None,
        "attack_intent_zone_high": None, "attack_intent_zone_low": None,
        "is_just_broke_high": None, "is_limit_up_locked": None, "is_anomalous_volume": None,
    }
    defaults.update(kwargs)
    return ContextSnapshot(**defaults)


class TestT3S44AdvisorBranchTrigger:
    """T3S4.4: condition.evaluate 對 B07 branch when 條件行為正確."""

    def test_b1_no_new_low_true_triggers(self):
        """context.taiex_no_new_low_next_day=True → B1 when 評估 True."""
        b1_when = {"context.taiex_no_new_low_next_day": True}
        row = _make_row()
        ctx = _make_ctx(taiex_no_new_low_next_day=True)
        result = evaluate(b1_when, row, ctx)
        assert result is True, f"Expected True, got {result}"

    def test_b1_no_new_low_false_does_not_trigger(self):
        """context.taiex_no_new_low_next_day=False → B1 when 評估 False."""
        b1_when = {"context.taiex_no_new_low_next_day": True}
        row = _make_row()
        ctx = _make_ctx(taiex_no_new_low_next_day=False)
        result = evaluate(b1_when, row, ctx)
        assert result is False, f"Expected False, got {result}"

    def test_b1_no_new_low_none_is_pending(self):
        """context.taiex_no_new_low_next_day=None → B1 when 評估 None (pending)."""
        b1_when = {"context.taiex_no_new_low_next_day": True}
        row = _make_row()
        ctx = _make_ctx(taiex_no_new_low_next_day=None)
        result = evaluate(b1_when, row, ctx)
        assert result is None, f"Expected None (pending), got {result}"

    def test_b2_new_low_fires_when_no_new_low_false(self):
        """context.taiex_no_new_low_next_day=False → B2 when (false) 評估 True."""
        b2_when = {"context.taiex_no_new_low_next_day": False}
        row = _make_row()
        ctx = _make_ctx(taiex_no_new_low_next_day=False)
        result = evaluate(b2_when, row, ctx)
        assert result is True, f"Expected True for B2 (signal invalid), got {result}"

    def test_record_any_criterion_true_fires(self):
        """context.taiex_record_any_criterion=True 條件能正常評估."""
        when = {"context.taiex_record_any_criterion": True}
        row = _make_row()
        ctx = _make_ctx(taiex_record_any_criterion=True)
        result = evaluate(when, row, ctx)
        assert result is True

    def test_record_any_criterion_none_is_pending(self):
        """context.taiex_record_any_criterion=None → pending."""
        when = {"context.taiex_record_any_criterion": True}
        row = _make_row()
        ctx = _make_ctx(taiex_record_any_criterion=None)
        result = evaluate(when, row, ctx)
        assert result is None

    def test_b07_playbook_branch_b1_fires_when_context_set(self):
        """B07 B1 完整流程：從 playbook 載入 branch + evaluate = True."""
        result = load_playbooks([PLAYBOOKS_DIR])
        pb = result["record_decline_rebound"][0]
        b1 = next(b for b in pb.branches if b.id == "B1_taiex_no_new_low")

        row = _make_row()
        ctx = _make_ctx(
            taiex_record_any_criterion=True,
            taiex_no_new_low_next_day=True,
        )
        outcome = evaluate(b1.when, row, ctx)
        assert outcome is True, f"B1 should fire when no_new_low=True, got {outcome}"

    def test_b07_playbook_branch_b1_skipped_when_context_missing(self):
        """B07 required_context=taiex_record_any_criterion: None → advisor 跳過 playbook."""
        from scripts.kline.scenarios import load_playbooks as lp
        from scripts.kline.scenarios.advisor import _build_scenarios

        result = lp([PLAYBOOKS_DIR])
        hit_mock = type("H", (), {"pattern": "record_decline_rebound", "fired_at": "2024-08-05", "confidence": None})()
        row = _make_row()
        ctx = _make_ctx(taiex_record_any_criterion=None)  # required_context is None
        notes: list[str] = []
        scenarios = _build_scenarios([hit_mock], result, row, ctx, notes)

        # With required_context = None → playbook skipped → scenarios empty
        assert len(scenarios) == 0, f"Expected 0 scenarios (playbook skipped), got {len(scenarios)}"
        # Should have a warn about skipped playbook
        skip_warns = [n for n in notes if "taiex_record_any_criterion" in n]
        assert len(skip_warns) >= 1, f"Expected warn about taiex_record_any_criterion, got: {notes}"
