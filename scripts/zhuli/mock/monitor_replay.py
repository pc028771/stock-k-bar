"""Wire the mock feed into the REAL monitor evaluation (check_trigger_inline).

vs test_runner.py (calls individual check_* detectors), this drives the exact
path the live monitor runs each cycle — composite_check cascade + 紅線 discipline
filter — with mock-replayed 5K, over a frozen replay clock. Output = per-ticker
燈號 timeline for agent analysis.

Usage:
  PYTHONPATH=scripts python -m zhuli.mock.monitor_replay --scenario 6_15_red_engulfing
  PYTHONPATH=scripts python -m zhuli.mock.monitor_replay --all
  PYTHONPATH=scripts python -m zhuli.mock.monitor_replay --selftest
"""
from __future__ import annotations
import argparse
import sys
from datetime import date as _Date, datetime, time
from pathlib import Path

REPO = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import zhuli.live_position_monitor as mon
import zhuli.intraday_stage_helper as helper
from zhuli.mock import DataProvider
from zhuli.mock.test_runner import SCENARIOS, build_5k_so_far


def _fake_clock(target_date: str, clk: list):
    """FakeDT/FakeDate whose now()/today() read the replay clock (clk[0]=time)."""
    d = _Date.fromisoformat(target_date)

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(d, clk[0])

    class FakeDate(_Date):
        @classmethod
        def today(cls):
            return d

    return FakeDT, FakeDate


def replay_scenario(name: str, cfg: dict, dp: DataProvider) -> dict:
    """Step the monitor's check_trigger_inline over a day; collect 燈號 changes."""
    clk = [time(9, 5)]                       # mutable replay clock
    FakeDT, FakeDate = _fake_clock(cfg['date'], clk)
    days = {t: dp.get_day(t, cfg['date']) for t in cfg['tickers']}
    days = {t: d for t, d in days.items() if d}

    # Patch the monitor's injected globals to read mock data + frozen clock.
    # _get_fubon→None forces _detect_market_regime to its DB-TAIEX fallback (no live API).
    orig = (mon._fetch_5min, mon._get_prev, mon.datetime,
            helper.datetime, helper.date, helper._get_fubon)

    def mock_fetch_5min(ticker, _date):
        d = days.get(ticker)
        return build_5k_so_far(d.bars, clk[0]) if d else None

    def mock_get_prev(ticker, _db):
        d = days.get(ticker)
        if not d:
            return {}
        # prev_high/low from the 5 daily bars before the replay date (no today() dep)
        rows = dp._conn().execute(
            "SELECT high, low FROM standard_daily_bar WHERE ticker=? AND trade_date<? "
            "ORDER BY trade_date DESC LIMIT 5", (ticker, cfg['date'])).fetchall()
        highs = [r[0] for r in rows if r[0] is not None]
        lows = [r[1] for r in rows if r[1] is not None]
        return {'prev_close': d.prev_close,
                'prev_high': max(highs) if highs else d.prev_close * 1.02,
                'prev_low': min(lows) if lows else d.prev_close * 0.98}

    mon._fetch_5min = mock_fetch_5min
    mon._get_prev = mock_get_prev
    mon.datetime = FakeDT
    helper.datetime = FakeDT
    helper.date = FakeDate
    helper._get_fubon = lambda: None    # → regime uses DB TAIEX fallback

    timeline = {t: [] for t in days}         # ticker -> [(time, trig_key, reason)]
    try:
        t = time(9, 5)
        while t <= time(13, 30):
            clk[0] = t
            for tk in days:
                trig, reason = mon.check_trigger_inline(tk, tactic='核心')
                last = timeline[tk][-1][1] if timeline[tk] else None
                if trig != last:               # record only transitions
                    timeline[tk].append((t.strftime("%H:%M"), trig, reason[:70]))
            # advance 5 min
            t = (datetime.combine(_Date(2000, 1, 1), t).replace(
                minute=(t.minute + 5) % 60,
                hour=t.hour + (t.minute + 5) // 60)).time()
    finally:
        (mon._fetch_5min, mon._get_prev, mon.datetime,
         helper.datetime, helper.date, helper._get_fubon) = orig

    return timeline


def render(name: str, cfg: dict, timeline: dict) -> str:
    out = [f"# Monitor Replay — {name}", "",
           f"- date: {cfg['date']}  |  tickers: {', '.join(cfg['tickers'])}",
           f"- desc: {cfg['description']}",
           f"- path: check_trigger_inline (composite_check + 紅線、真實 monitor cycle)", ""]
    for tk, changes in timeline.items():
        fired = [c for c in changes if c[1] != 'none']
        out.append(f"## {tk} — {len(fired)} 個非 none 燈號")
        out.append("| time | trigger | reason |")
        out.append("|---|---|---|")
        for tm, trig, reason in changes:
            out.append(f"| {tm} | {trig} | {reason} |")
        out.append("")
    # expected vs actual
    exp = cfg.get('expected_triggers', {})
    if exp:
        out += ["## Expected vs Actual", "| ticker | expected | window | hit |", "|---|---|---|---|"]
        for tk, lst in exp.items():
            for trig, s, e in lst:
                hit = any(s.strftime("%H:%M") <= c[0] <= e.strftime("%H:%M") and c[1] != 'none'
                          for c in timeline.get(tk, []))
                out.append(f"| {tk} | {trig} | {s.strftime('%H:%M')}-{e.strftime('%H:%M')} | "
                           f"{'✅' if hit else '❌'} |")
    return "\n".join(out)


def run(names: list[str], outdir: Path):
    dp = DataProvider()
    outdir.mkdir(parents=True, exist_ok=True)
    for name in names:
        cfg = SCENARIOS[name]
        tl = replay_scenario(name, cfg, dp)
        total = sum(len([c for c in v if c[1] != 'none']) for v in tl.values())
        (outdir / f"monitor_{name}.md").write_text(render(name, cfg, tl))
        print(f"  {name}: {total} 燈號 fire → monitor_{name}.md")
    dp.close()


def selftest():
    """Frozen-clock + mock-feed sanity: a known漲停-隔日 ticker yields a non-none燈號 timeline without crashing."""
    dp = DataProvider()
    tl = replay_scenario('6_15_red_engulfing', SCENARIOS['6_15_red_engulfing'], dp)
    dp.close()
    assert '1303' in tl, "ticker missing from timeline"
    assert all(len(c) == 3 for v in tl.values() for c in v), "malformed timeline row"
    print("selftest ok:", {k: len(v) for k, v in tl.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--outdir", type=Path,
                    default=REPO / "docs" / "主力大課程" / "mock_test_results")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    names = list(SCENARIOS) if a.all else [a.scenario or "6_15_red_engulfing"]
    run(names, a.outdir)


if __name__ == "__main__":
    main()
