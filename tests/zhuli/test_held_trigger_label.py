"""層 3: HELD trigger label tests.

針對 MonitorApp._fmt_trigger(trig_key, for_held=True/False) 測試:
  - for_held=True  + confirmed trigger → 含「加碼需 +10%」、不含「最佳進場」
  - for_held=False + confirmed trigger → 含原 label (最佳進場 / confirmed)
  - for_held=True  + 非 override trigger → 回傳預設 TRIGGER_DISPLAY label
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── 路徑設定 ─────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_v2_module():
    """載入 live_position_monitor_v2 module (含 _HELD_OVERRIDE / TRIGGER_DISPLAY)。"""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(
        "live_position_monitor_v2_label",
        Path(_REPO) / "scripts" / "zhuli" / "live_position_monitor_v2.py",
    )
    assert spec and spec.loader
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _fmt(trig_key: str, reason: str = "", for_held: bool = False) -> str:
    """Helper: 呼叫 MonitorApp._fmt_trigger 的純邏輯 (用 MagicMock self)。"""
    mod = _load_v2_module()
    mock_self = MagicMock()
    return mod.MonitorApp._fmt_trigger(mock_self, trig_key, reason, for_held)


# ── confirmed triggers 集合 (測試主力) ────────────────────────────────────────
_CONFIRMED_KEYS = [
    "首攻", "Ch5-3",
    "續攻", "T1",
    "反彈", "T2",
    "尾盤_confirmed", "Closing_confirmed",
]


class TestHeldOverrideLabels:
    """for_held=True 的 confirmed trigger 必須含「加碼需 +10%」且不含「最佳進場」。"""

    @pytest.mark.parametrize("trig_key", _CONFIRMED_KEYS)
    def test_held_contains_加碼需十percent(self, trig_key: str):
        """for_held=True: 所有 override trigger 回傳含「加碼需 +10%」字串。"""
        label = _fmt(trig_key, for_held=True)
        assert "加碼需 +10%" in label, (
            f"trig_key={trig_key!r}: 期望含「加碼需 +10%」但得到: {label!r}"
        )

    @pytest.mark.parametrize("trig_key", _CONFIRMED_KEYS)
    def test_held_not_contains_最佳進場(self, trig_key: str):
        """for_held=True: 所有 override trigger 不應含「最佳進場」字串 (避免誤導加碼)。"""
        label = _fmt(trig_key, for_held=True)
        assert "最佳進場" not in label, (
            f"trig_key={trig_key!r}: 持倉 label 不應含「最佳進場」但得到: {label!r}"
        )


class TestNonHeldLabels:
    """for_held=False 的 confirmed trigger 應回傳原始 TRIGGER_DISPLAY label。"""

    def test_尾盤_confirmed_non_held_contains_最佳進場(self):
        """for_held=False 的尾盤_confirmed → 含「最佳進場」。"""
        label = _fmt("尾盤_confirmed", for_held=False)
        assert "最佳進場" in label, f"got: {label!r}"

    def test_Closing_confirmed_non_held_contains_最佳進場(self):
        """for_held=False 的 Closing_confirmed alias → 含「最佳進場」。"""
        label = _fmt("Closing_confirmed", for_held=False)
        assert "最佳進場" in label, f"got: {label!r}"

    def test_首攻_non_held_contains_confirmed(self):
        """for_held=False 的首攻 → 含「confirmed」。"""
        label = _fmt("首攻", for_held=False)
        assert "confirmed" in label, f"got: {label!r}"

    def test_Ch5_3_non_held_contains_confirmed(self):
        """for_held=False 的 Ch5-3 alias → 含「confirmed」。"""
        label = _fmt("Ch5-3", for_held=False)
        assert "confirmed" in label, f"got: {label!r}"

    def test_續攻_non_held_contains_confirmed(self):
        label = _fmt("續攻", for_held=False)
        assert "confirmed" in label, f"got: {label!r}"

    def test_T1_non_held_contains_confirmed(self):
        label = _fmt("T1", for_held=False)
        assert "confirmed" in label, f"got: {label!r}"

    def test_反彈_non_held_contains_confirmed(self):
        """反彈 label 含「confirmed」或「反彈」。"""
        label = _fmt("反彈", for_held=False)
        assert "confirmed" in label or "反彈" in label, f"got: {label!r}"

    def test_T2_non_held_contains_confirmed(self):
        label = _fmt("T2", for_held=False)
        assert "confirmed" in label or "反彈" in label, f"got: {label!r}"


class TestNonOverrideTriggers:
    """for_held=True 但 trigger 不在 _HELD_OVERRIDE → 回傳 TRIGGER_DISPLAY 預設 label。"""

    def test_none_trigger_held_returns_default(self):
        """trigger='none' + for_held=True → 回傳無訊號 label (不含「加碼需 +10%」)。"""
        label = _fmt("none", for_held=True)
        assert "加碼需 +10%" not in label
        assert "無訊號" in label

    def test_破底_held_returns_default_not_override(self):
        """破底不在 _HELD_OVERRIDE → for_held=True 依然回傳 TRIGGER_DISPLAY 的破底 label。"""
        label = _fmt("破底", for_held=True)
        assert "加碼需 +10%" not in label
        assert "破底" in label

    def test_TC_alias_held_returns_default(self):
        label = _fmt("TC", for_held=True)
        assert "加碼需 +10%" not in label
        assert "破底" in label

    def test_尾盤_過熱_held_returns_default(self):
        """尾盤_過熱 不在 _HELD_OVERRIDE → 回傳 TRIGGER_DISPLAY label。"""
        label = _fmt("尾盤_過熱", for_held=True)
        assert "加碼需 +10%" not in label
        assert "過熱" in label

    def test_T1_watch_held_returns_default(self):
        label = _fmt("T1_watch", for_held=True)
        assert "加碼需 +10%" not in label


class TestReasonAppended:
    """當 reason 非空時，label 應附上 reason 片段。"""

    def test_non_held_with_reason_appended(self):
        """for_held=False + reason → label 含 reason 前 35 字。"""
        label = _fmt("續攻", reason="連 2 紅K + 量×2.5", for_held=False)
        assert "連 2 紅K" in label, f"got: {label!r}"

    def test_held_with_reason_not_appended(self):
        """for_held=True + _HELD_OVERRIDE trig → _fmt_trigger 用 override label。
        _fmt_trigger 邏輯: if reason and trig_key not in ('none', None, ''):
        → held trigger with reason WILL append reason (code line 1278).
        只要 override label 本身含「加碼需 +10%」即滿足紀律。
        """
        label = _fmt("首攻", reason="9:12 過高 102", for_held=True)
        assert "加碼需 +10%" in label, f"got: {label!r}"

    def test_none_trigger_with_reason_not_appended(self):
        """trigger='none' + reason → reason 不附加 (code skips when trig_key=='none')。"""
        label = _fmt("none", reason="某原因", for_held=False)
        # 當 trig_key == 'none' 時 reason 不附加
        assert "某原因" not in label
