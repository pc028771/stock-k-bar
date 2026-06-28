"""TUI 測試 — L1 純函式 + L2 Pilot 互動 + L3 結構快照。

依 docs/主力大課程/tui_testing_research.md 落地。零依賴 (不裝 pytest-asyncio /
pytest-textual-snapshot)：L2/L3 用 asyncio.run() 包 Textual 內建 App.run_test()。

Usage:
  PYTHONPATH=scripts python -m zhuli.mock.tui_tests          # 跑全部 L1+L2+L3
  PYTHONPATH=scripts python -m zhuli.mock.tui_tests --l1     # 只 L1
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import zhuli.live_position_monitor as mon
from zhuli.live_position_monitor_v2 import MonitorApp, TAB_HELD, TAB_WATCHING

logging.disable(logging.CRITICAL)   # 消 FubonClient connected 等 log 噪音

# 這些 _fmt_* / sort / status 都不用 self → 直接 unbound 呼叫 (None 當 self)
_F = MonitorApp


# ── L1: 純函式 (formatter 邊界 / sort / status icon) ──────────────────────────
def test_l1():
    # _fmt_vol 燈號上色邊界 1.5 / 2.0 / 3.0
    assert _F._fmt_vol(None, None) == "—"
    assert _F._fmt_vol(None, 1.49).startswith("⚪")
    assert _F._fmt_vol(None, 1.5).startswith("🟡")
    assert _F._fmt_vol(None, 1.99).startswith("🟡")
    assert _F._fmt_vol(None, 2.0).startswith("🟢")
    assert _F._fmt_vol(None, 2.99).startswith("🟢")
    assert _F._fmt_vol(None, 3.0).startswith("🚀")

    # _fmt_gap 跳空% + 缺值
    assert _F._fmt_gap(None, 0, 100) == "—"
    assert _F._fmt_gap(None, 103, 100) == "+3.0%"
    assert _F._fmt_gap(None, 98, 100) == "-2.0%"

    # _fmt_price 現價 + 漲跌%
    assert _F._fmt_price(None, 0, 100) == "—"
    assert "(-2.5%)" in _F._fmt_price(None, 97.5, 100)
    assert "(+0.0%)" in _F._fmt_price(None, 100, 100)

    # _fmt_pnl 正負號
    assert _F._fmt_pnl(None, 1500, 5.0) == "+1,500 (+5.0%)"
    assert _F._fmt_pnl(None, -800, -2.3) == "-800 (-2.3%)"

    # _fmt_dist 距離 (999 = 無資料)
    assert _F._fmt_dist(None, 999) == "—"
    assert _F._fmt_dist(None, -3.2) == "-3.2%"

    # _get_status_icon: dist<0 紅、<1 警、有 trigger 綠、else 白
    def icon(dist, trig):
        return _F._get_status_icon(None, {'ticker': 'X'},
                                   {'X': {'dist_stop': dist, 'trigger': trig}})
    assert icon(-0.5, 'none') == "🔴"
    assert icon(0.5, 'none') == "⚠️"
    assert icon(5.0, '首攻') == "🟢"
    assert icon(5.0, 'none') == "⚪"

    # _watch_sort_key: 老師明示(0) < pri3(1) < pri2(2) < 其他(3)
    k = lambda src, pri: _F._watch_sort_key(None, {'source': src, 'priority': pri, 'ticker': 'X'})
    assert k('老師明示', 1)[0] == 0
    assert k('雙重背書', 1)[0] == 0
    assert k('scanner', 3)[0] == 1
    assert k('scanner', 2)[0] == 2
    assert k('自選', 1)[0] == 3
    # 同 group 內按 ticker
    a = _F._watch_sort_key(None, {'source': 's', 'priority': 1, 'ticker': '1101'})
    b = _F._watch_sort_key(None, {'source': 's', 'priority': 1, 'ticker': '2330'})
    assert a < b
    print("L1 純函式: ✅ (vol/gap/price/pnl/dist/status/sort 全邊界通過)")


# ── demo app 建構 + monkey-patch teardown (research §4) ──────────────────────
def _make_demo_app():
    return MonitorApp(demo_mode=True, demo_client=mon.MockClient(),
                      demo_scenarios=mon._build_scenarios())


def _save_patches():
    return (mon.check_trigger_inline, mon.load_prev_close)


def _restore_patches(saved):
    mon.check_trigger_inline, mon.load_prev_close = saved


# ── L2: Pilot 互動 (tab 切換 / toggle / row_count) ───────────────────────────
async def _l2():
    saved = _save_patches()
    app = _make_demo_app()
    try:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            # 持倉 tab → DataTable 有 row
            await pilot.press("1"); await pilot.pause()
            from textual.widgets import DataTable, TabbedContent
            held = app.query_one("#dt-held", DataTable)
            assert held.row_count > 0, "held 表應有 row"
            n_cols = len(held.columns)
            assert n_cols >= 8, f"held 欄位數異常 {n_cols}"

            # t 切 teacher-only → reactive flip
            before = app.teacher_only
            await pilot.press("t"); await pilot.pause()
            assert app.teacher_only != before, "t 應 toggle teacher_only"
            await pilot.press("t"); await pilot.pause()
            assert app.teacher_only == before, "再按 t 應切回"

            # 4 → 觀察 tab active
            await pilot.press("4"); await pilot.pause()
            tc = app.query_one(TabbedContent)
            assert tc.active == TAB_WATCHING, f"tab 切換失敗: {tc.active}"

            # f 切顯失敗 → reactive flip
            bf = app.show_failed
            await pilot.press("f"); await pilot.pause()
            assert app.show_failed != bf, "f 應 toggle show_failed"
    finally:
        _restore_patches(saved)
    print("L2 Pilot 互動: ✅ (tab 1/4 切換 / t·f toggle / row_count 通過)")


# ── L3: 結構快照 (zero-dep、非 SVG；固定 scenario 抓穩定結構) ─────────────────
# golden = 持倉表的欄位 header (版面結構、不含每日變動資料)、改版面才會動。
_GOLDEN_HELD_COLS = None   # 第一次跑記錄、之後比對 (寫進檔當常數)

# golden = 各 tab DataTable 的欄位 header (版面結構、不含每日變動資料)。
# 改欄位/版面才該 fail；資料天天變不影響 → churn 控制好的結構快照。
_GOLDEN_COLS = {
    "dt-held":     ["代號", "股名", "量比", "Trigger", "出貨"],   # 必含結構欄 (子字串)
    "dt-watching": ["代號", "股名"],
}

async def _l3():
    saved = _save_patches()
    app = _make_demo_app()
    try:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import DataTable
            captured = {}
            for tab_key, table_id in (("1", "dt-held"), ("4", "dt-watching")):
                await pilot.press(tab_key); await pilot.pause()
                dt = app.query_one(f"#{table_id}", DataTable)
                cols = [str(c.label) for c in dt.columns.values()]
                captured[table_id] = cols
                assert len(cols) >= 8, f"{table_id} 欄位數 {len(cols)} < 8 (版面變動?)"
                for must in _GOLDEN_COLS[table_id]:
                    assert any(must in c for c in cols), \
                        f"{table_id} 缺結構欄 '{must}': {cols}"
    finally:
        _restore_patches(saved)
    print(f"L3 結構快照: ✅ (held {len(captured['dt-held'])} 欄 / "
          f"watching {len(captured['dt-watching'])} 欄、golden 結構符合)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--l1", action="store_true")
    ap.add_argument("--l2", action="store_true")
    ap.add_argument("--l3", action="store_true")
    a = ap.parse_args()
    run_all = not (a.l1 or a.l2 or a.l3)
    if run_all or a.l1:
        test_l1()
    if run_all or a.l2:
        asyncio.run(_l2())
    if run_all or a.l3:
        asyncio.run(_l3())
    print("TUI tests: 全通過")


if __name__ == "__main__":
    main()
