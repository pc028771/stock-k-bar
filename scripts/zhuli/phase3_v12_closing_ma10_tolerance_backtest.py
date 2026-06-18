"""Phase 3 v12 — Closing_check cond1 MA10 tolerance backtest.

對比 strict cond1 (close > MA10) vs 候選 A (close > MA10 × 0.99) 的影響.

來源: per memory feedback_closing_panel_ma10_flexibility、6/17 3189 景碩 +9.97% 漲停
被 strict cond1 擋掉的案例觸發本 backtest.

修改 vs v11: 用 daily_watchlist JSON 替代 /tmp/scanner_candidates md (md 已過期)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

from phase3_v11_closing_4cond_backtest import (
    scan_v11_all, TRADING_DATES_FULL, next_trading_day,
    StageTrigger, _DB, _REGIME_EMOJI,
)

WATCHLIST_DIR = Path("/Users/howard/Repository/stock-k-bar/docs/主力大課程/daily_watchlist")


def load_watchlist_json(scan_date: str, priority_min: int = 2) -> list[str]:
    """從 daily_watchlist JSON load tickers (priority >= priority_min)."""
    p = WATCHLIST_DIR / f"{scan_date}.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text())
    out = []
    seen = set()
    for c in d.get('candidates', []):
        t = c.get('ticker')
        if t and t not in seen and c.get('priority', 0) >= priority_min:
            out.append(t)
            seen.add(t)
    return out


def recompute_cond1_with_tolerance(records: list[dict], tolerance: float = 0.01) -> list[dict]:
    out = []
    for r in records:
        new_scores = dict(r.get('scores', {}))
        close = r.get('close')
        ma10 = r.get('ma10')
        if close is not None and ma10 is not None and ma10 > 0:
            new_scores['structure_hold'] = (close > ma10 * (1 - tolerance))
        new_pass = sum(new_scores.values())
        nr = dict(r)
        nr['scores_A'] = new_scores
        nr['pass_count_A'] = new_pass
        nr['cond1_changed'] = (new_scores.get('structure_hold') != r.get('scores', {}).get('structure_hold'))
        out.append(nr)
    return out


def summarize(records: list[dict], use_A: bool = False) -> dict:
    key_pass = 'pass_count_A' if use_A else 'pass_count_v11'
    n_total = len(records)
    n_3of4 = sum(1 for r in records if r[key_pass] == 3)
    n_4of4 = sum(1 for r in records if r[key_pass] == 4)
    confirmed = [r for r in records if r[key_pass] >= 3]
    rets = [r['net_ret_pct'] for r in confirmed if r.get('net_ret_pct') is not None]
    wins = [x for x in rets if x > 0]
    avg = sum(rets) / len(rets) if rets else 0
    wr = len(wins) / len(rets) * 100 if rets else 0
    return {
        'total': n_total,
        'n_3of4': n_3of4,
        'n_4of4': n_4of4,
        'n_confirmed': len(confirmed),
        'wr_confirmed_pct': round(wr, 1),
        'avg_ret_confirmed_pct': round(avg, 3),
    }


def main():
    print("=" * 70)
    print(" Phase 3 v12 — Closing_check cond1 MA10 tolerance backtest")
    print("=" * 70)
    print(" Strict:  cond1 = close > MA10")
    print(" 候選 A:  cond1 = close > MA10 × 0.99 (-1%)")
    print()

    engine = StageTrigger()
    all_records = []
    sample_dates = ['2026-06-01','2026-06-02','2026-06-03','2026-06-04','2026-06-05',
                    '2026-06-08','2026-06-09','2026-06-10','2026-06-11','2026-06-12',
                    '2026-06-15','2026-06-16','2026-06-17']

    for scan_date in sample_dates:
        watchlist = load_watchlist_json(scan_date, priority_min=2)
        if not watchlist:
            print(f"[SKIP] {scan_date} no watchlist JSON")
            continue
        # entry day = scan_date next trading day
        next_date = next_trading_day(scan_date, TRADING_DATES_FULL)
        if not next_date:
            print(f"[SKIP] {scan_date} no next trading day")
            continue
        regime = engine._detect_market_regime(next_date, db_path=_DB)
        print(f"[{scan_date} → {next_date}] wl={len(watchlist)} regime={_REGIME_EMOJI.get(regime, regime)}")
        # 限 50 檔以免 API 過慢
        day_recs = scan_v11_all(engine, next_date, watchlist[:50], regime)
        all_records.extend(day_recs)
        print(f"  → {len(day_recs)} 樣本")

    if not all_records:
        print("無樣本、結束")
        return

    enriched = recompute_cond1_with_tolerance(all_records, tolerance=0.01)
    n_changed = sum(1 for r in enriched if r['cond1_changed'])
    print()
    print(f"Total {len(all_records)} 樣本、cond1 結果變化: {n_changed} 筆")
    print()

    sum_strict = summarize(all_records, use_A=False)
    sum_A = summarize(enriched, use_A=True)
    print(f"{'Metric':<30}{'Strict':<15}{'Candidate A':<15}{'Diff':<10}")
    print("-" * 70)
    for k in ['total','n_3of4','n_4of4','n_confirmed','wr_confirmed_pct','avg_ret_confirmed_pct']:
        s = sum_strict.get(k, 0)
        a = sum_A.get(k, 0)
        try:
            d = a - s
            d_str = f"{d:+}" if isinstance(d, int) else f"{d:+.2f}"
        except Exception:
            d_str = 'n/a'
        print(f"{k:<30}{str(s):<15}{str(a):<15}{d_str:<10}")
    print()
    # Confirmed 新增的 (strict skip, A confirmed)
    new_confirmed = [r for r in enriched if r['cond1_changed'] and r['pass_count_A'] >= 3 and r['pass_count_v11'] < 3]
    new_wr = 0
    if new_confirmed:
        new_rets = [r['net_ret_pct'] for r in new_confirmed if r.get('net_ret_pct') is not None]
        if new_rets:
            new_wr = sum(1 for x in new_rets if x > 0) / len(new_rets) * 100
        print(f"新增進場 (strict skip → A confirmed): {len(new_confirmed)} 筆、WR {new_wr:.1f}%")
        for r in new_confirmed[:10]:
            print(f"  {r['entry_date']} {r['ticker']} close={r['close']:.1f} ma10={r['ma10']:.1f} dist={(r['close']/r['ma10']-1)*100:+.2f}% net_ret={r['net_ret_pct']:+.2f}%")
    print()
    print("=== 結論 ===")
    diff_wr = sum_A['wr_confirmed_pct'] - sum_strict['wr_confirmed_pct']
    if diff_wr >= -3:
        print(f"候選 A WR {sum_A['wr_confirmed_pct']}% vs strict {sum_strict['wr_confirmed_pct']}%、diff {diff_wr:+.1f}%")
        if new_wr >= 70:
            print(f"新增樣本 WR {new_wr:.1f}% 高、候選 A 推薦合併")
        else:
            print(f"新增樣本 WR {new_wr:.1f}% 普通、候選 A 邊緣、user 拍板")
    else:
        print(f"候選 A WR 下降 {diff_wr:.1f}%、不合併")


if __name__ == "__main__":
    main()
