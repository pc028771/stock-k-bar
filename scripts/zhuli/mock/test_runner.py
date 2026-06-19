"""Test runner — replay a scenario + invoke detectors + log trigger fires.

Usage:
  python -m zhuli.mock.test_runner --scenario 6_12_red_engulfing --ticker 3042

Output:
  Markdown report to docs/主力大課程/mock_test_results/<scenario>_<date>.md
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
from zhuli.intraday_stage_helper import StageTrigger, _get_prev_levels, _DB


# Scenarios from catalog §9
SCENARIOS = {
    '6_15_red_engulfing': {
        'date': '2026-06-15',
        'tickers': ['1303'],  # 1303 6/12 漲停、6/15 是隔日、R9 應 fire
        'expected_triggers': {
            '1303': [('R9紅K吞噬', time(9, 0), time(13, 30))],
        },
        'description': '6/15 — 1303 6/12 漲停隔日、R9 紅K吞噬 watch'
    },
    '6_17_red_engulfing': {
        'date': '2026-06-17',
        'tickers': ['1303'],  # 1303 6/16 ? -1.7%、6/17 漲停日、應該 R9 不 fire (today 漲停 = setup fail)
        'expected_triggers': {
            '1303': [('R9紅K吞噬', time(9, 0), time(13, 30))],
        },
        'description': '6/17 — 1303 6/16 黑K、6/17 漲停、R9 setup check'
    },
    '6_12_jump_watch': {
        'date': '2026-06-12',
        'tickers': ['3042', '1303'],
        'expected_triggers': {},
        'description': '6/12 morning dump scenario — 3042 open +3.6% / 1303 open +4.75% 漲停'
    },
    '5_22_w_bottom': {
        'date': '2026-05-22',
        'tickers': ['6239'],
        'expected_triggers': {
            '6239': [('R1首攻', time(9, 0), time(13, 30))],
        },
        'description': '5/22 6239 力成 W底起漲 + 漲停日'
    },
}


class TriggerRecorder:
    """Capture detector trigger fires per tick."""

    def __init__(self):
        self.events: list[dict] = []

    def record(self, t: time, ticker: str, trigger: str, detail: dict):
        self.events.append({
            'time': t.strftime("%H:%M"),
            'ticker': ticker,
            'trigger': trigger,
            'triggered': detail.get('triggered', False),
            'level': detail.get('level', '-'),
            'reason': detail.get('reason', '')[:80],
            'pass_count': detail.get('pass_count', 0),
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


def run_scenario(scenario_name: str, output_dir: Path):
    cfg = SCENARIOS.get(scenario_name)
    if not cfg:
        print(f"❌ unknown scenario: {scenario_name}")
        return 1

    print(f"▶ Scenario: {scenario_name}")
    print(f"  Date: {cfg['date']}")
    print(f"  Tickers: {cfg['tickers']}")
    print(f"  Description: {cfg['description']}")
    print()

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

    replay = ReplayEngine(client, tick_seconds=300, sleep_ms=0)  # 5min ticks

    def on_tick(t: time):
        if t < time(9, 5):
            return
        for tk, day in day_data.items():
            k5 = build_5k_so_far(day.bars, t)
            if len(k5) < 1:
                continue
            try:
                prev_levels = _get_prev_levels(tk, _DB)
            except Exception:
                prev_levels = {'prev_close': day.prev_close}

            # R9 紅K吞噬 (positional: ticker, k5)
            try:
                r9 = engine.check_red_engulfing(tk, k5, target_date=cfg['date'],
                                                _now_override=t.strftime("%H:%M"))
                if r9.get('triggered'):
                    recorder.record(t, tk, 'R9紅K吞噬', r9)
            except Exception as e:
                pass

            # Closing panel (only after 13:00)
            if t >= time(13, 0):
                try:
                    from zhuli.intraday_stage_helper import _get_ma10 as get_ma10
                    ma10 = get_ma10(tk, cfg['date'])
                    cp = engine.check_closing_panel(k5, ma10 or 0, ticker=tk,
                                                    _now_override=t.strftime("%H:%M"))
                    if cp.get('level') in ('confirmed', 'overheated'):
                        recorder.record(t, tk, f"Closing_{cp['level']}", cp)
                except Exception as e:
                    pass

    replay.on_tick(on_tick)
    n_ticks = replay.run()
    print(f"  Replayed {n_ticks} ticks")
    print(f"  Events captured: {len(recorder.events)}")

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
        "",
        "## Triggered events",
        "",
        "| Time | Ticker | Trigger | Level | Pass | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for e in recorder.events:
        lines.append(f"| {e['time']} | {e['ticker']} | {e['trigger']} | {e['level']} | {e['pass_count']} | {e['reason']} |")

    # Expected vs actual
    lines.append("")
    lines.append("## Expected vs Actual")
    lines.append("")
    lines.append("| Ticker | Expected trigger | Expected window | Actual? |")
    lines.append("|---|---|---|---|")
    for tk, expected_list in cfg.get('expected_triggers', {}).items():
        for trig, t_start, t_end in expected_list:
            actual = [e for e in recorder.events if e['ticker'] == tk
                      and t_start.strftime("%H:%M") <= e['time'] <= t_end.strftime("%H:%M")]
            mark = "✅" if actual else "❌"
            actual_str = f"{len(actual)} fired" if actual else "no fire"
            lines.append(f"| {tk} | {trig} | {t_start.strftime('%H:%M')}-{t_end.strftime('%H:%M')} | {mark} {actual_str} |")

    out_path.write_text("\n".join(lines))
    print(f"  Report: {out_path}")
    dp.close()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="6_12_red_engulfing")
    ap.add_argument("--output-dir", type=Path,
                    default=REPO / "docs" / "主力大課程" / "mock_test_results")
    args = ap.parse_args()
    return run_scenario(args.scenario, args.output_dir)


if __name__ == "__main__":
    sys.exit(main())
