"""Test runner — replay a scenario + invoke detectors + log trigger fires.

Usage:
  PYTHONPATH=scripts python -m zhuli.mock.test_runner --scenario 5_22_w_bottom

Output:
  Markdown report to docs/主力大課程/mock_test_results/<scenario>_<date>.md

2026-06-19 audit expansion:
  - 移除 try/except swallow、改成 log error (找出 hidden bug)
  - 新增 R1 首攻 / R11 漲停隔日 / Ch5_3 entry trigger check
  - 擴 SCENARIOS 15+、覆蓋 §7 example stocks
"""
from __future__ import annotations
import argparse
import sys
from datetime import time, datetime
from pathlib import Path

REPO = Path(__file__).parent.parent.parent.parent  # stock-k-bar/
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pandas as pd
from zhuli.mock import DataProvider, MockFubonClient, ReplayEngine
from zhuli.intraday_stage_helper import StageTrigger, _get_prev_levels, _get_ma10, _DB


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIOS — 覆蓋 catalog §7 example stocks + §9 mock server scenarios
# ─────────────────────────────────────────────────────────────────────────────
#
# 每筆 expected_triggers value 為 list[(trigger_name, t_start, t_end)]：
#   - trigger_name: 'R9紅K吞噬' / 'R1首攻' / 'Closing_confirmed' / 'R11警示' / 'Ch5_3_entry'
#   - t_start/t_end: 預期觸發時間窗
#
# 反向 case (expected_triggers={}) = 期望「沒有任何 trigger fire」、若 fire 則 audit
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = {
    # ── 既有 4 個 (catalog §9 對應) ──
    '6_15_red_engulfing': {
        'date': '2026-06-15',
        'tickers': ['1303'],
        'expected_triggers': {
            '1303': [('R9紅K吞噬', time(9, 10), time(12, 0))],
        },
        'description': '6/15 — 1303 6/12 漲停隔日 (+9.9%) → R9 紅K吞噬 watch'
    },
    '6_17_red_engulfing': {
        'date': '2026-06-17',
        'tickers': ['1303'],
        'expected_triggers': {
            '1303': [('R9紅K吞噬', time(9, 10), time(12, 0))],
        },
        'description': '6/17 — 1303 6/16 黑K (-4.6%) 後、R9 setup check (today gap?)'
    },
    '6_12_jump_watch': {
        'date': '2026-06-12',
        'tickers': ['3042', '1303'],
        'expected_triggers': {},
        'description': '6/12 morning dump scenario — 3042/1303 開盤跳空 +3-5%、觀察 gap_down 與 R9'
    },
    '5_22_w_bottom': {
        'date': '2026-05-22',
        'tickers': ['6239'],
        'expected_triggers': {
            '6239': [('R1首攻', time(9, 0), time(13, 30))],
        },
        'description': '5/22 6239 力成 W底起漲 → 早盤一字鎖漲停、R1 應 fire (但鎖漲停沒回踩 5K 多異常)'
    },

    # ── 新增: §7 老師明示案例 ──
    '5_20_small_structure_3481': {
        'date': '2026-05-20',
        'tickers': ['3481'],
        'expected_triggers': {
            '3481': [('R1首攻', time(9, 0), time(13, 30))],
        },
        'description': '3481 群創 5/20 small_structure 觸發 → 5/21 漲停。Mock 重播 5/20 看 R1 早盤'
    },
    '5_22_smallstr_3042': {
        'date': '2026-05-22',
        'tickers': ['3042'],
        'expected_triggers': {
            '3042': [('R1首攻', time(9, 0), time(11, 0))],
        },
        'description': '3042 晶技 5/19 small_structure → 5/22 漲停日。Mock 5/22 看 R1 早盤'
    },
    '6_3_foreign_buy_black_k_2303': {
        'date': '2026-06-03',
        'tickers': ['2303'],
        'expected_triggers': {},
        'description': '2303 聯電 6/3 foreign_buy_on_black_k 案例。daily-level detector、Mock 主要看 intraday 是否出現 R1/Closing'
    },
    '6_5_closing_panel_1605': {
        'date': '2026-06-05',
        'tickers': ['1605'],
        'expected_triggers': {
            '1605': [('Closing_confirmed', time(13, 0), time(13, 25))],
        },
        'description': '6/5 1605 華新 broker tier 1「飆股們的媽媽」、尾盤面板應 confirm'
    },
    '6_11_closing_panel_1303': {
        'date': '2026-06-11',
        'tickers': ['1303'],
        'expected_triggers': {
            '1303': [('Closing_confirmed', time(13, 0), time(13, 25))],
        },
        'description': '6/11 1303 南亞 backtest 期間最佳尾盤進場日 (next day 6/12 漲停)'
    },
    '6_13_locked_limit_up_1303': {
        'date': '2026-06-13',
        'tickers': ['1303'],
        'expected_triggers': {},
        'description': '6/13 1303 漲停隔日 (6/12 已 +9.9%、6/13 又 +? )、R11/紅線 #1 應 skip'
    },
    '6_16_red_engulfing_4958': {
        'date': '2026-06-16',
        'tickers': ['4958'],
        'expected_triggers': {
            '4958': [('R9紅K吞噬', time(9, 10), time(12, 0))],
        },
        'description': '4958 臻鼎 ABF 6/16 升戰略 watchlist 主推、R9 案例 (老師 6/16 教學亮點)'
    },
    '6_15_morning_dump_2404': {
        'date': '2026-06-15',
        'tickers': ['2404'],
        'expected_triggers': {},
        'description': '6/15 2404 漢唐 廠務工程 6/9 → 6/15 隔日拉高賣 +5.3%。預期 09:15-09:45 morning dump、無 R1'
    },
    '6_15_morning_dump_5536': {
        'date': '2026-06-15',
        'tickers': ['5536'],
        'expected_triggers': {},
        'description': '6/15 5536 聖暉 廠務工程隔日拉高賣 +3.4%。預期早盤倒貨'
    },
    '6_5_sell_off_2454': {
        'date': '2026-06-05',
        'tickers': ['2454'],
        'expected_triggers': {},
        'description': '6/5 2454 聯發科 殺盤 -5.4%、預期 gap_down_emergency (early exit) 而非 entry'
    },

    # ── 反向 case (應 skip) ──
    '6_12_skip_2327': {
        'date': '2026-06-12',
        'tickers': ['2327'],
        'expected_triggers': {},
        'description': '反向: 2327 國巨 6/12 漲停 + 隔日跳空 +9.1%、紅線 #1 應全部 skip、無 trigger fire'
    },
    '5_19_8064_warning': {
        'date': '2026-05-19',
        'tickers': ['8064'],
        'expected_triggers': {},
        'description': '反向: 8064 東捷破底股 (Ch2 警示)、預期無 entry trigger fire'
    },
    '5_19_4526_short_swing': {
        'date': '2026-05-19',
        'tickers': ['4526'],
        'expected_triggers': {},
        'description': '反向: 4526 東台雙錨停損案例 (紅線 #7)、預期早盤切入後出場、不該 R1 confirm'
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# TriggerRecorder + replay logic
# ─────────────────────────────────────────────────────────────────────────────

class TriggerRecorder:
    """Capture detector trigger fires + errors per tick."""

    def __init__(self):
        self.events: list[dict] = []
        self.errors: list[dict] = []

    def record(self, t: time, ticker: str, trigger: str, detail: dict):
        self.events.append({
            'time': t.strftime("%H:%M"),
            'ticker': ticker,
            'trigger': trigger,
            'triggered': detail.get('triggered', False),
            'level': detail.get('level', '-'),
            'reason': str(detail.get('reason', ''))[:100],
            'pass_count': detail.get('pass_count', 0),
        })

    def record_error(self, t: time, ticker: str, trigger: str, exc: Exception):
        self.errors.append({
            'time': t.strftime("%H:%M"),
            'ticker': ticker,
            'trigger': trigger,
            'error_type': type(exc).__name__,
            'error_msg': str(exc)[:200],
        })


def build_5k_so_far(day_bars: list[dict], up_to: time) -> pd.DataFrame:
    """Build accumulated 5min K from 1min bars up to up_to time."""
    rows = []
    for b in day_bars:
        bt = datetime.fromisoformat(b['minute']).time()
        if bt > up_to:
            break
        rows.append(b)
    if not rows:
        return pd.DataFrame()
    df1 = pd.DataFrame(rows)
    df1['ts'] = pd.to_datetime(df1['minute'])
    df1 = df1.set_index('ts')
    df5 = df1.resample('5min', origin='start_day', offset='9h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    return df5


def run_scenario(scenario_name: str, output_dir: Path, strict: bool = False):
    """Run a single scenario.

    Args:
        strict: 若 True、不 swallow exception、直接 raise (debug 用)
    """
    cfg = SCENARIOS.get(scenario_name)
    if not cfg:
        print(f"❌ unknown scenario: {scenario_name}")
        return 1

    print(f"▶ Scenario: {scenario_name}")
    print(f"  Date: {cfg['date']}")
    print(f"  Tickers: {cfg['tickers']}")
    print(f"  Description: {cfg['description']}")

    dp = DataProvider()
    client = MockFubonClient(dp, cfg['date'])
    engine = StageTrigger()
    recorder = TriggerRecorder()

    # Pre-load days
    day_data = {}
    for tk in cfg['tickers']:
        d = dp.get_day(tk, cfg['date'])
        if not d:
            print(f"  ⚠️ no data for {tk}")
            continue
        day_data[tk] = d

    if not day_data:
        print("❌ no ticker data available")
        return 1

    # Pre-fetch prev_levels + ma10 once per ticker (不在 tick loop 內反覆查 DB)
    prev_levels_cache: dict[str, dict] = {}
    ma10_cache: dict[str, float | None] = {}
    for tk, day in day_data.items():
        try:
            prev_levels_cache[tk] = _get_prev_levels(tk, _DB)
        except Exception as e:
            print(f"  ⚠️ _get_prev_levels({tk}) error: {e}")
            prev_levels_cache[tk] = {'prev_close': day.prev_close}
        try:
            ma10_cache[tk] = _get_ma10(tk, cfg['date'])
        except Exception as e:
            print(f"  ⚠️ _get_ma10({tk}) error: {e}")
            ma10_cache[tk] = None

    replay = ReplayEngine(client, tick_seconds=300, sleep_ms=0)  # 5min ticks

    def _safe_call(t: time, tk: str, trig_name: str, fn):
        """Run fn() returning dict. Log error or record event."""
        try:
            result = fn()
        except Exception as e:
            recorder.record_error(t, tk, trig_name, e)
            if strict:
                raise
            return None
        return result

    def on_tick(t: time):
        if t < time(9, 5):
            return
        for tk, day in day_data.items():
            k5 = build_5k_so_far(day.bars, t)
            if len(k5) < 1:
                continue
            prev_levels = prev_levels_cache.get(tk, {'prev_close': day.prev_close})
            ma10 = ma10_cache.get(tk)

            # R9 紅 K 吞噬
            r9 = _safe_call(t, tk, 'R9紅K吞噬',
                            lambda: engine.check_red_engulfing(
                                tk, k5, target_date=cfg['date'],
                                _now_override=t.strftime("%H:%M")))
            if r9 and r9.get('triggered'):
                recorder.record(t, tk, 'R9紅K吞噬', r9)

            # R1 首攻 (check_trigger_1)
            if len(k5) >= 5:
                r1 = _safe_call(t, tk, 'R1首攻',
                                lambda: engine.check_trigger_1(
                                    tk, k5, prev_levels.get('prev_high')))
                if r1 and r1.get('triggered'):
                    recorder.record(t, tk, 'R1首攻', r1)

            # Ch5_3 entry (第一根 5K SOP)
            if len(k5) >= 1 and t <= time(9, 30):
                ch = _safe_call(t, tk, 'Ch5_3_entry',
                                lambda: engine.check_ch5_3_entry(
                                    k5, day.prev_close, ma10=ma10,
                                    ticker=tk, target_date=cfg['date']))
                if ch and ch.get('triggered'):
                    recorder.record(t, tk, 'Ch5_3_entry', ch)

            # Closing panel (13:00-13:25)
            if t >= time(13, 0) and t <= time(13, 25):
                cp = _safe_call(t, tk, 'Closing_panel',
                                lambda: engine.check_closing_panel(
                                    tk, k5, ma10=ma10,
                                    target_date=cfg['date'],
                                    _now_override=t.strftime("%H:%M")))
                if cp and cp.get('level') in ('confirmed', 'overheated'):
                    recorder.record(t, tk, f"Closing_{cp['level']}", cp)

    replay.on_tick(on_tick)
    n_ticks = replay.run()
    print(f"  Replayed {n_ticks} ticks")
    print(f"  Events captured: {len(recorder.events)}, errors: {len(recorder.errors)}")

    # Render report
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{scenario_name}_{cfg['date']}.md"
    lines = [
        f"# Mock Test Result — {scenario_name}",
        "",
        f"- **Scenario date**: {cfg['date']}",
        f"- **Tickers**: {', '.join(cfg['tickers'])}",
        f"- **Description**: {cfg['description']}",
        f"- **Total ticks**: {n_ticks}",
        f"- **Trigger events captured**: {len(recorder.events)}",
        f"- **Errors raised**: {len(recorder.errors)}",
        "",
        "## Triggered events",
        "",
        "| Time | Ticker | Trigger | Level | Pass | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for e in recorder.events:
        lines.append(
            f"| {e['time']} | {e['ticker']} | {e['trigger']} | "
            f"{e['level']} | {e['pass_count']} | {e['reason']} |"
        )

    # Expected vs actual
    lines += ["", "## Expected vs Actual", "",
              "| Ticker | Expected trigger | Window | Actual? |",
              "|---|---|---|---|"]
    expected_count = 0
    matched_count = 0
    for tk, expected_list in cfg.get('expected_triggers', {}).items():
        for trig, t_start, t_end in expected_list:
            expected_count += 1
            actual = [e for e in recorder.events if e['ticker'] == tk
                      and e['trigger'] == trig
                      and t_start.strftime("%H:%M") <= e['time'] <= t_end.strftime("%H:%M")]
            mark = "✅ PASS" if actual else "❌ FAIL"
            if actual:
                matched_count += 1
            actual_str = f"{len(actual)} fired" if actual else "no fire"
            lines.append(
                f"| {tk} | {trig} | "
                f"{t_start.strftime('%H:%M')}-{t_end.strftime('%H:%M')} | "
                f"{mark} ({actual_str}) |"
            )

    # 反向 case 提醒
    if not cfg.get('expected_triggers'):
        unwanted = len(recorder.events)
        mark = "✅ PASS (無 fire)" if unwanted == 0 else f"⚠️ AUDIT ({unwanted} fired)"
        lines.append("")
        lines.append(f"### 反向 case 結果: {mark}")

    # Errors section
    if recorder.errors:
        lines += ["", "## Errors raised (應排查)", "",
                  "| Time | Ticker | Trigger | Type | Message |",
                  "|---|---|---|---|---|"]
        for e in recorder.errors[:20]:  # 限制 20 條避免報告爆炸
            lines.append(
                f"| {e['time']} | {e['ticker']} | {e['trigger']} | "
                f"{e['error_type']} | {e['error_msg']} |"
            )
        if len(recorder.errors) > 20:
            lines.append(f"| ... | ... | ... | ... | (+{len(recorder.errors)-20} more) |")

    # Pass/fail meta line (agent parser 用)
    pass_rate = matched_count / expected_count if expected_count else 1.0
    lines += ["", "## Meta",
              f"- expected_triggers: {expected_count}",
              f"- matched: {matched_count}",
              f"- pass_rate: {pass_rate:.2%}",
              f"- errors: {len(recorder.errors)}"]

    out_path.write_text("\n".join(lines))
    print(f"  Report: {out_path}")
    dp.close()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="5_22_w_bottom")
    ap.add_argument("--output-dir", type=Path,
                    default=REPO / "docs" / "主力大課程" / "mock_test_results")
    ap.add_argument("--strict", action="store_true",
                    help="不 swallow exception、直接 raise (debug 用)")
    args = ap.parse_args()
    return run_scenario(args.scenario, args.output_dir, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
