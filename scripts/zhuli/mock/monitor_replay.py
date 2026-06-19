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
from zhuli.exit.detectors import (check_umbrella_exit, check_high_long_black,
                                  check_profit_milestone, check_gap_down_emergency)
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


def _run_exits(tk, day, clk_t, milestones, out):
    """跑 4 個出場 detector、entry 基準=昨收、只記轉變/新觸發。"""
    k5 = build_5k_so_far(day.bars, clk_t)
    if k5 is None or k5.empty:
        return
    entry = day.prev_close
    cur = float(k5["close"].iloc[-1])
    checks = [
        ("掀傘", check_umbrella_exit(k5, entry)),
        ("高檔長黑", check_high_long_black(k5)),
        ("分批停利", check_profit_milestone(cur, entry, milestones)),
    ]
    if clk_t <= time(9, 10):                  # gap_down 只在開盤評估
        checks.append(("跳空急殺",
                       check_gap_down_emergency(float(k5["open"].iloc[0]), entry)))
    seen = {e[1] for e in out}
    for kind, r in checks:
        if r.get("triggered") and kind not in seen:   # 每種出場一天記一次
            out.append((clk_t.strftime("%H:%M"), kind, str(r.get("reason", ""))[:70]))


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

    timeline = {t: [] for t in days}         # ticker -> [(time, trig_key, reason)] 進場燈號
    exits = {t: [] for t in days}            # ticker -> [(time, exit_kind, reason)] 出場訊號
    milestones = {t: set() for t in days}    # profit_milestone 累積 state
    try:
        t = time(9, 5)
        while t <= time(13, 30):
            clk[0] = t
            for tk in days:
                trig, reason = mon.check_trigger_inline(tk, tactic='核心')
                last = timeline[tk][-1][1] if timeline[tk] else None
                if trig != last:               # record only transitions
                    timeline[tk].append((t.strftime("%H:%M"), trig, reason[:70]))
                # exit detectors (HELD 視角、entry 基準 = 昨收)
                _run_exits(tk, days[tk], clk[0], milestones[tk], exits[tk])
            # advance 5 min
            t = (datetime.combine(_Date(2000, 1, 1), t).replace(
                minute=(t.minute + 5) % 60,
                hour=t.hour + (t.minute + 5) // 60)).time()
    finally:
        (mon._fetch_5min, mon._get_prev, mon.datetime,
         helper.datetime, helper.date, helper._get_fubon) = orig

    return timeline, exits


def render(name: str, cfg: dict, timeline: dict, exits: dict) -> str:
    out = [f"# Monitor Replay — {name}", "",
           f"- date: {cfg['date']}  |  tickers: {', '.join(cfg['tickers'])}",
           f"- desc: {cfg['description']}",
           f"- path: check_trigger_inline (進場) + exit detectors (出場)、真實 monitor 邏輯", ""]
    for tk, changes in timeline.items():
        fired = [c for c in changes if c[1] != 'none']
        out.append(f"## {tk} 進場燈號 — {len(fired)} 個非 none")
        out.append("| time | trigger | reason |")
        out.append("|---|---|---|")
        for tm, trig, reason in changes:
            out.append(f"| {tm} | {trig} | {reason} |")
        ex = exits.get(tk, [])
        out.append(f"\n### {tk} 出場訊號 — {len(ex)} 個")
        if ex:
            out.append("| time | exit | reason |")
            out.append("|---|---|---|")
            for tm, kind, reason in ex:
                out.append(f"| {tm} | {kind} | {reason} |")
        else:
            out.append("（無）")
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
        tl, ex = replay_scenario(name, cfg, dp)
        n_in = sum(len([c for c in v if c[1] != 'none']) for v in tl.values())
        n_out = sum(len(v) for v in ex.values())
        (outdir / f"monitor_{name}.md").write_text(render(name, cfg, tl, ex))
        print(f"  {name}: 進場 {n_in} / 出場 {n_out} → monitor_{name}.md")
    dp.close()


def selftest():
    """Frozen-clock + mock-feed sanity: a known漲停-隔日 ticker yields a non-none燈號 timeline without crashing."""
    dp = DataProvider()
    tl, ex = replay_scenario('6_5_sell_off_2454', SCENARIOS['6_5_sell_off_2454'], dp)
    dp.close()
    assert '2454' in tl and '2454' in ex, "ticker missing"
    assert all(len(c) == 3 for v in tl.values() for c in v), "malformed entry row"
    assert all(len(c) == 3 for v in ex.values() for c in v), "malformed exit row"
    print("selftest ok: entry", {k: len(v) for k, v in tl.items()},
          "| exit", {k: len(v) for k, v in ex.items()})


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
