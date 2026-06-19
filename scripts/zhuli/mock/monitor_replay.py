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

import pandas as pd
import zhuli.live_position_monitor as mon
import zhuli.live_position_monitor_v2 as monv2
import zhuli.intraday_stage_helper as helper
import zhuli.intraday_indicators.data_provider as idp
from zhuli.exit.detectors import (check_umbrella_exit, check_high_long_black,
                                  check_profit_milestone, check_gap_down_emergency)
from zhuli.mock import DataProvider
from zhuli.mock.test_runner import SCENARIOS, build_5k_so_far
from zhuli.live_position_monitor_v2 import _overnight_status_text


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


def _run_dump(tk, day, clk_t, date, tracker, out):
    """拉高出貨 dump signals — 每步餵 price+cum_volume、評估警示 (HELD 視角)。"""
    from zhuli.dump_signals import evaluate_dump_signals
    k5 = build_5k_so_far(day.bars, clk_t)
    if k5 is None or k5.empty:
        return
    now = datetime.combine(_Date.fromisoformat(date), clk_t)
    price = float(k5["close"].iloc[-1])
    cum_vol = int(k5["volume"].sum())
    tracker.update_tick(tk, price=price, cum_volume=cum_vol, now=now)
    item = {"stop": day.prev_close * 0.93, "shares": 1000, "cost": day.prev_close}
    warns = evaluate_dump_signals(
        tk, tracker.get_state(tk), item, {}, current_close=price,
        volume_spike=tracker.get_volume_spike(tk), now=now,
        yesterday_close_override=day.prev_close)
    seen = {w[1] for w in out}
    for w in warns:
        if w not in seen:
            out.append((clk_t.strftime("%H:%M"), w[:80]))


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


class _FakeApp:
    """最小 self、餵 _classify_watch 用 (只實作它呼叫的 2 個 method)。"""
    def __init__(self, dp, date):
        self._dp, self._date = dp, date

    def _yesterday_change_pct(self, tk):
        r = self._dp._conn().execute(
            "SELECT close FROM standard_daily_bar WHERE ticker=? AND trade_date<? "
            "ORDER BY trade_date DESC LIMIT 2", (tk, self._date)).fetchall()
        return (r[0][0] / r[1][0] - 1) * 100 if len(r) == 2 and r[1][0] else 0.0

    def _is_weak_regime(self):
        r = self._dp._conn().execute(
            "SELECT close FROM standard_daily_bar WHERE ticker='TAIEX' AND trade_date<? "
            "ORDER BY trade_date DESC LIMIT 6", (self._date,)).fetchall()
        return len(r) == 6 and r[5][0] and (r[0][0] / r[5][0] - 1) * 100 <= -1.0


def evaluate_overnight(tk, day, dp, date):
    """隔日沖 overnight 評估 (4 條件)、static asof=replay日、snap=當日 EOD。"""
    from zhuli.precompute_overnight_static import (compute_features_for_ticker,
                                                   compute_market_features)
    con = dp._conn()
    static = compute_features_for_ticker(tk, con, asof_date=date)
    if static.get("error"):
        return {"error": static["error"]}
    k5 = build_5k_so_far(day.bars, time(13, 30))
    if k5 is None or k5.empty:
        return {"error": "no_5k"}
    snap = {"close": float(k5["close"].iloc[-1]), "open": float(k5["open"].iloc[0]),
            "total_volume": int(k5["volume"].sum()), "ts": f"{date} 13:30:00"}
    mkt = compute_market_features(con, asof_date=date)
    tx = dp.get_daily_bar("TAIEX", date) or {}
    market_snap = {"close": tx.get("close", 0), "open": tx.get("open", 0), "total_volume": 0}
    return monv2._evaluate_overnight_live(tk, static, snap, mkt.get("TAIEX", {}), market_snap)


def classify_watch_at_close(tk, day, trig, dp, date):
    """13:25 決策點的 WATCH 分類 (confirmed/watching/excluded)。"""
    k5 = build_5k_so_far(day.bars, time(13, 25))
    if k5 is None or k5.empty:
        return "?"
    m10 = helper._get_ma10(tk, date) or 0
    cl = float(k5["close"].iloc[-1])
    d = {'trigger': trig, 'open': float(k5["open"].iloc[0]), 'close': cl,
         'prev_close': day.prev_close,
         'dist_ma10': (cl - m10) / m10 * 100 if m10 else None, 'ticker': tk}
    return monv2.MonitorApp._classify_watch(_FakeApp(dp, date), {'ticker': tk, 'priority': 3}, d)


def replay_scenario(name: str, cfg: dict, dp: DataProvider) -> dict:
    """Step the monitor's check_trigger_inline over a day; collect 燈號 changes."""
    clk = [time(9, 5)]                       # mutable replay clock
    FakeDT, FakeDate = _fake_clock(cfg['date'], clk)
    days = {t: dp.get_day(t, cfg['date']) for t in cfg['tickers']}
    days = {t: d for t, d in days.items() if d}

    # Patch the monitor's injected globals to read mock data + frozen clock.
    # _get_fubon→None forces _detect_market_regime to its DB-TAIEX fallback (no live API).
    orig = (mon._fetch_5min, mon._get_prev, mon.datetime,
            helper.datetime, helper.date, helper._get_fubon, idp.get_k1m_today)

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
    # (b) Ch5 當沖 indicator 的 1分K 也走 clk-windowed mock (compose_trigger 用)
    idp.get_k1m_today = lambda ticker, target_date=None: (
        build_5k_so_far(days[ticker].bars, clk[0]) if ticker in days else pd.DataFrame())

    timeline = {t: [] for t in days}         # ticker -> [(time, trig_key, reason)] 進場燈號
    exits = {t: [] for t in days}            # ticker -> [(time, exit_kind, reason)] 出場訊號
    dumps = {t: [] for t in days}            # ticker -> [(time, warn)] 拉高出貨警示
    milestones = {t: set() for t in days}    # profit_milestone 累積 state
    from zhuli.dump_signals import DumpStateTracker
    dump_tracker = DumpStateTracker(tickers=list(days))
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
                # 拉高出貨 dump signals (tick-volume 警示)
                _run_dump(tk, days[tk], clk[0], cfg['date'], dump_tracker, dumps[tk])
            # advance 5 min
            t = (datetime.combine(_Date(2000, 1, 1), t).replace(
                minute=(t.minute + 5) % 60,
                hour=t.hour + (t.minute + 5) // 60)).time()
    finally:
        (mon._fetch_5min, mon._get_prev, mon.datetime,
         helper.datetime, helper.date, helper._get_fubon, idp.get_k1m_today) = orig

    # WATCH 分類 + 隔日沖 overnight + 出場時點預警 @ EOD (patch 已還原)
    from zhuli.live_position_monitor import check_strategy_exit_alert
    watch, overnight, exit_alert = {}, {}, {}
    for tk in days:
        last_trig = next((c[1] for c in reversed(timeline[tk])
                          if c[0] <= "13:25"), "none")
        watch[tk] = classify_watch_at_close(tk, days[tk], last_trig, dp, cfg['date'])
        overnight[tk] = evaluate_overnight(tk, days[tk], dp, cfg['date'])
        # 出場時點預警: 13:25 (當沖預警)、用 intraday mode item
        _now = datetime.combine(_Date.fromisoformat(cfg['date']), time(13, 25))
        exit_alert[tk] = check_strategy_exit_alert(
            {'ticker': tk, 'strategy_mode': 'intraday'}, now=_now) or "—"
    return timeline, exits, dumps, watch, overnight, exit_alert


def render(name: str, cfg: dict, timeline: dict, exits: dict, dumps: dict, watch: dict, overnight: dict, exit_alert: dict) -> str:
    out = [f"# Monitor Replay — {name}", "",
           f"- date: {cfg['date']}  |  tickers: {', '.join(cfg['tickers'])}",
           f"- desc: {cfg['description']}",
           f"- path: 進場 + 出場 + 拉高出貨(dump) + WATCH + 隔日沖 + 出場預警(strategy_exit_alert)", ""]
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
        out.append(f"\n### {tk} WATCH 分類@13:25 → **{watch.get(tk,'?')}**")
        ov = overnight.get(tk, {})
        ov_txt = ov.get('error') or f"{_overnight_status_text(ov)} (pass {ov.get('pass_count','?')}/4)"
        out.append(f"\n### {tk} 隔日沖@EOD → **{ov_txt}**")
        dl = dumps.get(tk, [])
        out.append(f"\n### {tk} 拉高出貨 — {len(dl)} 個警示")
        if dl:
            out.append("| time | warn |"); out.append("|---|---|")
            for tm, w in dl: out.append(f"| {tm} | {w} |")
        else:
            out.append("（無）")
        out.append(f"\n### {tk} 出場時點預警@13:25 → **{exit_alert.get(tk,'—')}**\n")
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
        tl, ex, dm, wt, ov, ea = replay_scenario(name, cfg, dp)
        n_in = sum(len([c for c in v if c[1] != 'none']) for v in tl.values())
        n_out = sum(len(v) for v in ex.values())
        (outdir / f"monitor_{name}.md").write_text(render(name, cfg, tl, ex, dm, wt, ov, ea))
        buckets = '/'.join(f'{k}:{v}' for k,v in wt.items())
        n_dump = sum(len(v) for v in dm.values())
        ovs = "/".join(f"{k}:{(v.get('error') or str(v.get('pass_count','?'))+'/4')}" for k,v in ov.items())
        print(f"  {name}: 進場 {n_in} / 出場 {n_out} / 出貨 {n_dump} / WATCH {buckets} / 隔日沖 {ovs} → monitor_{name}.md")
    dp.close()


def selftest():
    """Frozen-clock + mock-feed sanity: a known漲停-隔日 ticker yields a non-none燈號 timeline without crashing."""
    dp = DataProvider()
    tl, ex, dm, wt, ov, ea = replay_scenario('6_5_sell_off_2454', SCENARIOS['6_5_sell_off_2454'], dp)
    dp.close()
    assert all('2454' in x for x in (tl,ex,dm,wt,ov,ea)), "ticker missing"
    assert isinstance(dm['2454'], list) and len(dm['2454']) >= 1, "dump 應在殺盤日 fire"
    assert ea['2454'] and ea['2454'] != '—', "出場時點預警應產出"
    assert wt['2454'] in ('confirmed','watching','excluded','?'), "bad bucket"
    assert all(len(c) == 3 for v in tl.values() for c in v), "malformed entry row"
    assert all(len(c) == 3 for v in ex.values() for c in v), "malformed exit row"
    # 隔日沖量單位 fix 回歸守門: 教科書突破日 (張單位) 必 4/4 + kbar True
    static = {'bb_upper': 100.0, 'bandwidth_prev': 0.05, 'prev_close': 100.0,
              'prev_volume': 5_000_000, 'ma20': 95.0, 'ma20_slope_5d': 0.01}
    snap = {'close': 105.0, 'open': 101.0, 'total_volume': 8000, 'ts': '2026-06-19 13:30:00'}
    r = monv2._evaluate_overnight_live('TEST', static, snap,
                                       {'prev_close': 18000, 'prev_open': 17900,
                                        'prev_volume': 100, 'ma5': 17800},
                                       {'close': 18200, 'open': 18000, 'total_volume': 200})
    assert r['kbar'] and r['pass_count'] == 4, f"overnight 量單位 regression: {r}"
    # 當沖 Ch5 indicator 邏輯守門 (合成 canonical shape、daily replay 結構性難觸發、故合成驗證):
    import numpy as _np
    from zhuli.intraday_indicators.ch5_complement import (
        check_b5_1_stop_profit, check_ma_divergence, check_b5_3_quarterly_ma_short_filter)
    # B5-1: 真實歷史檔 3296 勝德 6/18 09:00 單根 5K +7.2% (window 到 09:04 隔離 spike bar)
    _dp1 = DataProvider()
    _b1day = _dp1.get_day('3296', '2026-06-18')
    _dp1.close()
    _b1 = build_5k_so_far(_b1day.bars, time(9, 4)) if _b1day else pd.DataFrame()
    assert check_b5_1_stop_profit(_b1).get('triggered'), "B5-1 大紅棒停利 regression (3296 6/18)"
    _p = list(_np.linspace(100, 140, 20))
    _b2 = pd.DataFrame({'open': _p, 'high': _p, 'low': _p, 'close': _p, 'volume': [50] * 20})
    assert check_ma_divergence(_b2).get('triggered'), "ma_divergence regression"
    assert check_b5_3_quarterly_ma_short_filter(
        pd.Series(_np.linspace(50, 100, 70))).get('triggered'), "B5-3 季線濾空 regression"
    # 日線均線發散 當沖提醒 (純資訊): 格式 + 台積電應算得出 (tight)
    _div = mon.daily_ma_divergence('2330')
    assert '發散' in _div and '%' in _div, f"daily_ma_divergence format regression: {_div}"
    print("selftest ok: entry", {k: len(v) for k, v in tl.items()},
          "| exit", {k: len(v) for k, v in ex.items()}, "| watch", wt, "| overnight", {k:(v.get("error") or v.get("pass_count")) for k,v in ov.items()})


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
