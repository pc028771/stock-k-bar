"""層 2: Classifier regression tests.

針對 MonitorApp._classify_watch 的完整 trigger 分類邏輯進行 regression test。
不需要啟動 Textual UI，直接用 MagicMock 包 self 後呼叫 method。
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


def _get_classify_watch():
    """取得 MonitorApp._classify_watch unbound method。

    避免在 module level import 觸發 Textual / DB 初始化。
    只 import 必要的 module-level 常數 set。
    """
    # 直接從 v2 module 取 method，用 MagicMock self 呼叫
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(
        "live_position_monitor_v2_cls",
        Path(_REPO) / "scripts" / "zhuli" / "live_position_monitor_v2.py",
    )
    assert spec and spec.loader
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod.MonitorApp._classify_watch, mod


def _classify(trig_key: str, priority: int = 3) -> str:
    """Helper: 呼叫 _classify_watch(item, d) → 'confirmed' / 'watching' / 'excluded'。"""
    classify_fn, _ = _get_classify_watch()
    mock_self = MagicMock()
    item = {"priority": priority}
    d = {"trigger": trig_key}
    return classify_fn(mock_self, item, d)


# ── Confirmed Triggers ────────────────────────────────────────────────────────

class TestClassifierConfirmed:
    """已觸發進場訊號應分到 'confirmed'。"""

    def test_首攻_classified_confirmed(self):
        assert _classify("首攻") == "confirmed"

    def test_Ch5_3_alias_classified_confirmed(self):
        """英文 alias Ch5-3 應與首攻等效。"""
        assert _classify("Ch5-3") == "confirmed"

    def test_續攻_classified_confirmed(self):
        assert _classify("續攻") == "confirmed"

    def test_T1_alias_classified_confirmed(self):
        assert _classify("T1") == "confirmed"

    def test_反彈_classified_confirmed(self):
        assert _classify("反彈") == "confirmed"

    def test_T2_alias_classified_confirmed(self):
        assert _classify("T2") == "confirmed"

    def test_尾盤_confirmed_classified_confirmed(self):
        assert _classify("尾盤_confirmed") == "confirmed"

    def test_Closing_confirmed_alias_classified_confirmed(self):
        """英文 alias Closing_confirmed 應分到 confirmed。"""
        assert _classify("Closing_confirmed") == "confirmed"


# ── Excluded Triggers ─────────────────────────────────────────────────────────

class TestClassifierExcluded:
    """破底訊號應分到 'excluded'。"""

    def test_破底_classified_excluded(self):
        assert _classify("破底") == "excluded"

    def test_TC_alias_classified_excluded(self):
        assert _classify("TC") == "excluded"

    def test_none_low_priority_excluded(self):
        """無訊號 + priority=1 → excluded。"""
        assert _classify("none", priority=1) == "excluded"

    def test_unknown_trigger_low_priority_excluded(self):
        """未知 trigger key + priority=1 → excluded。"""
        assert _classify("some_unknown_trigger", priority=1) == "excluded"


# ── Watching Triggers ─────────────────────────────────────────────────────────

class TestClassifierWatching:
    """觀察中 (watch/signal/pullback) 應分到 'watching'。"""

    def test_T1_watch_classified_watching(self):
        assert _classify("T1_watch") == "watching"

    def test_T2_watch_classified_watching(self):
        assert _classify("T2_watch") == "watching"

    def test_續攻_watch_classified_watching(self):
        assert _classify("續攻_watch") == "watching"

    def test_反彈_watch_classified_watching(self):
        assert _classify("反彈_watch") == "watching"

    def test_首攻_pullback_classified_watching(self):
        assert _classify("首攻_pullback") == "watching"

    def test_首攻_signal_classified_watching(self):
        assert _classify("首攻_signal") == "watching"

    def test_Ch5_3_pullback_classified_watching(self):
        assert _classify("Ch5-3_pullback") == "watching"

    def test_Ch5_3_signal_classified_watching(self):
        assert _classify("Ch5-3_signal") == "watching"


# ── Priority-based fallback ───────────────────────────────────────────────────

class TestClassifierPriorityFallback:
    """無已知 trigger 時，依 priority 分類。"""

    def test_none_trigger_priority_3_is_watching(self):
        """priority ≥ 2 + none trigger → watching。"""
        assert _classify("none", priority=3) == "watching"

    def test_none_trigger_priority_2_is_watching(self):
        """priority=2 → watching。"""
        assert _classify("none", priority=2) == "watching"

    def test_none_trigger_priority_1_is_excluded(self):
        """priority=1 → excluded。"""
        assert _classify("none", priority=1) == "excluded"

    def test_none_trigger_priority_0_is_excluded(self):
        """priority=0 → excluded。"""
        assert _classify("none", priority=0) == "excluded"

    def test_確認集_優先於_priority(self):
        """即使 priority=1，若 trigger 在 confirmed set → confirmed。"""
        assert _classify("首攻", priority=1) == "confirmed"

    def test_排除集_優先於_priority(self):
        """即使 priority=5，若 trigger 在 excluded set → excluded。"""
        assert _classify("破底", priority=5) == "excluded"

    def test_尾盤_過熱_not_confirmed(self):
        """尾盤_過熱 不在 confirmed set → priority=3 → watching。"""
        result = _classify("尾盤_過熱", priority=3)
        assert result != "confirmed"

    def test_尾盤_skip_not_confirmed(self):
        """尾盤_skip 不在 confirmed/excluded/watching sets → priority=3 → watching。"""
        result = _classify("尾盤_skip", priority=3)
        assert result != "confirmed"
