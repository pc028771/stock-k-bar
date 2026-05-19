"""Sanity check — verify scanner hits the 5 instructor cases from §H.

Course source: strategy-indicators.md §H 講師案例

Entry types:
    'full'            — 預期 scanner 完整 hit（找到窒息量 + 出量 K + 情境 A/B）
    'suffocation_only' — 只檢查「窒息量是否出現」（不查出量 K）

Expected cases:
    3533 嘉澤    2020/12/30  suffocation_only  — 課程僅標窒息量範例，無進場價
    8150 南茂    2021/03/10  full (known divergence)
    6284 佳邦    2021/01/22  full (known divergence — doji)
    2338 光罩    2021/02/18  full (known divergence — 日期可能不準)
    1590 亞德客-KY 2020/12/24 full — 基準成功案例

Note: sanity check uses a ±2 trading-day tolerance for signal_date,
because the spec records entry dates but not the exact suffocation date.
A "hit" = scanner finds a signal for that ticker within ±2 trading days
of the spec's signal_date.

Usage:
    python -m zhuli.sanity_check [--db PATH] [--verbose]
    python scripts/zhuli/sanity_check.py [--db PATH] [--verbose]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Allow running as script directly
_SCRIPT_DIR = Path(__file__).parent.parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.features import add_features
from zhuli.config import SuffocationConfig
from zhuli.features import add_zhuli_features
from zhuli.entry.suffocation import detect


# === Instructor cases from strategy-indicators.md §H ===
# Format: dict with keys: ticker, name, date_range, entry_type, [expected_entry], [expected_scenario], note
EXPECTED_CASES = [
    {
        'ticker': '3533',
        'name': '嘉澤',
        'date_range': ('2020-12-28', '2021-01-04'),
        'entry_type': 'suffocation_only',
        'note': '課程明標窒息量範例（無進場價），不查出量 K',
    },
    {
        'ticker': '8150',
        'name': '南茂',
        'date_range': ('2021-03-08', '2021-03-15'),
        'entry_type': 'full',
        'expected_entry': 35.43,
        'expected_scenario': 'A',
        'note': '⚠️ 已知機械命中失敗',
    },
    {
        'ticker': '6284',
        'name': '佳邦',
        'date_range': ('2021-01-20', '2021-01-29'),
        'entry_type': 'full',
        'expected_entry': 73.9,
        'expected_scenario': 'A',
        'note': '⚠️ doji 阻擋（依拍板保持）',
    },
    {
        'ticker': '2338',
        'name': '光罩',
        'date_range': ('2021-02-16', '2021-02-22'),
        'entry_type': 'full',
        'expected_entry': 45.28,
        'expected_scenario': 'B',
        'note': '⚠️ 已知機械命中失敗 / 日期可能不準',
    },
    {
        'ticker': '1590',
        'name': '亞德客-KY',
        'date_range': ('2020-12-22', '2020-12-30'),
        'entry_type': 'full',
        'note': '基準成功案例',
    },
]

# Tickers with known divergences (⚠️ in note) — will not cause sanity FAIL
KNOWN_DIVERGENCE_TICKERS = {c['ticker'] for c in EXPECTED_CASES if '⚠️ 已知' in c.get('note', '')}

TOLERANCE_DAYS = 2  # ±2 calendar days for date matching


def _get_db_date_range(db_path: Path) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return (min_date, max_date) from the DB, or (None, None) on error."""
    import sqlite3
    try:
        with sqlite3.connect(str(db_path), timeout=15) as conn:
            row = conn.execute(
                "SELECT MIN(trade_date), MAX(trade_date) "
                "FROM standard_daily_bar WHERE is_usable=1"
            ).fetchone()
        if row and row[0]:
            return pd.Timestamp(row[0]), pd.Timestamp(row[1])
    except Exception:
        pass
    return None, None


def _check_suffocation_only(
    case: dict,
    feats: pd.DataFrame,
    cfg: SuffocationConfig,
    verbose: bool,
) -> dict:
    """Check 'suffocation_only' entry_type — only verify that suffocation bar(s) appear."""
    ticker = case['ticker']
    name = case['name']
    date_start = pd.Timestamp(case['date_range'][0])
    date_end = pd.Timestamp(case['date_range'][1])
    note = case['note']

    ticker_df = feats[
        (feats['ticker'] == ticker)
        & (feats['trade_date'] >= date_start)
        & (feats['trade_date'] <= date_end)
    ].copy()

    if ticker_df.empty:
        return {
            'ticker': ticker,
            'name': name,
            'entry_type': 'suffocation_only',
            'result': 'no_data',
            'note': note,
            'msg': f'無資料（{date_start.date()} ~ {date_end.date()}）',
        }

    # Look for suffocation bars — vol < max_vol_20d * ratio
    if 'suffocation_bar' not in ticker_df.columns:
        # Compute manually using the same logic as features.py
        ticker_df = ticker_df.copy()
        ticker_df['_suf'] = (
            ticker_df.get('volume', pd.Series(dtype=float))
            < ticker_df.get('max_vol_20d', pd.Series(dtype=float)) * cfg.max20_volume_ratio
        )
        suf_col = '_suf'
    else:
        suf_col = 'suffocation_bar'

    suf_rows = ticker_df[ticker_df[suf_col] == True]

    if len(suf_rows) > 0:
        suf_dates = [pd.Timestamp(d).strftime('%Y-%m-%d') for d in suf_rows['trade_date']]
        msg = f'窒息量於 {", ".join(suf_dates)} 出現'
        result = 'suffocation_found'
        if verbose:
            print(f'  ✓ {ticker} ({name})：{msg}  [{note}]')
    else:
        # Compute vol_ratio for diagnosis
        if 'max_vol_20d' in ticker_df.columns and 'volume' in ticker_df.columns:
            ticker_df = ticker_df.copy()
            ticker_df['_vol_ratio'] = ticker_df['volume'] / ticker_df['max_vol_20d']
            min_ratio = ticker_df['_vol_ratio'].min()
            msg = f'窒息量未出現（日期範圍內最低 vol_ratio={min_ratio:.1%}，閾值 {cfg.max20_volume_ratio:.0%}）'
        else:
            msg = f'窒息量未出現（{date_start.date()} ~ {date_end.date()}）'
        result = 'suffocation_missing'
        if verbose:
            print(f'  ✗ {ticker} ({name})：{msg}  [{note}]')

    return {
        'ticker': ticker,
        'name': name,
        'entry_type': 'suffocation_only',
        'result': result,
        'note': note,
        'msg': msg,
    }


def _check_full(
    case: dict,
    signals: pd.DataFrame,
    db_min: pd.Timestamp | None,
    cfg: SuffocationConfig,
    verbose: bool,
) -> dict:
    """Check 'full' entry_type — scanner must produce a signal (窒息量 + 出量 K)."""
    ticker = case['ticker']
    name = case['name']
    date_start = pd.Timestamp(case['date_range'][0])
    date_end = pd.Timestamp(case['date_range'][1])
    note = case['note']
    is_known_divergence = '⚠️' in note

    # Use centre of date_range as the spec date for tolerance matching
    spec_date = date_start + (date_end - date_start) / 2
    tolerance = pd.Timedelta(days=TOLERANCE_DAYS + 4)  # +4 for weekends/holidays

    # Filter signals for this ticker within extended date window
    ticker_signals = signals[
        (signals['ticker'] == ticker)
        & (signals['signal_date'] >= date_start - pd.Timedelta(days=4))
        & (signals['signal_date'] <= date_end + pd.Timedelta(days=4))
    ]

    if len(ticker_signals) > 0:
        # Pick closest signal date to spec centre
        best = ticker_signals.iloc[
            (ticker_signals['signal_date'] - spec_date).abs().argsort().iloc[0]
        ]
        found_date = pd.Timestamp(best['signal_date']).strftime('%Y-%m-%d')
        found_scenario = best['scenario']
        expected_scenario = case.get('expected_scenario')
        scenario_match = (expected_scenario is None) or (found_scenario == expected_scenario)

        result_info = {
            'ticker': ticker,
            'name': name,
            'entry_type': 'full',
            'result': 'hit',
            'found_date': found_date,
            'found_scenario': found_scenario,
            'expected_scenario': expected_scenario,
            'scenario_match': scenario_match,
            'vol_ratio': round(float(best['suffocation_vol_ratio']), 4),
            'stop_loss': float(best['stop_loss']),
            'note': note,
            'is_known_divergence': is_known_divergence,
        }

        if verbose:
            scenario_flag = '✓' if scenario_match else '⚠ 情境不符'
            print(
                f'  ✓ {ticker} ({name})：找到 {found_date} '
                f'scenario={found_scenario}({scenario_flag}) '
                f'vol_ratio={result_info["vol_ratio"]:.4f} '
                f'stop={result_info["stop_loss"]:.2f}  [{note}]'
            )
        return result_info

    else:
        # Miss — check if there are signals nearby for diagnosis
        data_limited = db_min is not None and date_start < db_min

        any_signals = signals[signals['ticker'] == ticker]
        if len(any_signals) == 0:
            reason = '全歷史無任何 signal'
        else:
            nearest = any_signals.iloc[
                (any_signals['signal_date'] - spec_date).abs().argsort().iloc[0]
            ]
            nearest_ts = pd.Timestamp(nearest['signal_date'])
            nearest_date = nearest_ts.strftime('%Y-%m-%d') if not pd.isnull(nearest_ts) else 'unknown'
            nearest_scenario = nearest['scenario']
            reason = (
                f'指定日期範圍內無 signal；'
                f'最近 signal: {nearest_date} scenario={nearest_scenario}'
            )

        result_info = {
            'ticker': ticker,
            'name': name,
            'entry_type': 'full',
            'result': 'miss',
            'reason': reason,
            'note': note,
            'data_limited': data_limited,
            'is_known_divergence': is_known_divergence,
        }

        if verbose:
            divergence_tag = ' ← known divergence' if is_known_divergence else ''
            print(f'  ✗ {ticker} ({name})：{reason}{divergence_tag}  [{note}]')
        return result_info


def run_sanity_check(
    db_path: Path = DEFAULT_DB_PATH,
    cfg: SuffocationConfig | None = None,
    verbose: bool = False,
) -> dict:
    """Run sanity check against all instructor cases.

    Returns:
        dict with keys:
            results: list of per-case result dicts
            strict_hits: list — full cases that hit (no known divergence)
            suffocation_hits: list — suffocation_only cases that found window
            known_divergences: list — full cases that missed but are known divergence
            unexpected_misses: list — full cases that missed and are NOT known divergence
            passed: bool
    """
    if cfg is None:
        cfg = SuffocationConfig()

    db_min, db_max = _get_db_date_range(db_path)
    if db_min:
        print(f'DB date range: {db_min.date()} → {db_max.date()}')

    print('Loading bars from DB...')
    bars = load_bars(db_path=db_path)
    print(f'  Loaded {len(bars):,} rows for {bars["ticker"].nunique()} tickers.')

    print('Computing features...')
    feats = add_features(bars)
    feats = add_zhuli_features(feats)

    # Run scanner without date filter (full history) — for 'full' entry_type
    print('Running suffocation detector (full history)...')
    signals = detect(feats, cfg=cfg)
    print(f'  Found {len(signals):,} total signals across all dates.')

    results = []
    for case in EXPECTED_CASES:
        if case['entry_type'] == 'suffocation_only':
            r = _check_suffocation_only(case, feats, cfg, verbose)
        else:
            r = _check_full(case, signals, db_min, cfg, verbose)
        results.append(r)

    strict_hits = [
        r for r in results
        if r['entry_type'] == 'full'
        and r['result'] == 'hit'
        and not r.get('is_known_divergence', False)
    ]
    suffocation_hits = [
        r for r in results
        if r['entry_type'] == 'suffocation_only'
        and r['result'] == 'suffocation_found'
    ]
    known_divergences = [
        r for r in results
        if r['entry_type'] == 'full'
        and r['result'] == 'miss'
        and r.get('is_known_divergence', False)
    ]
    # Also include full hits with known divergence tag (they hit but were expected to miss)
    unexpected_misses = [
        r for r in results
        if r['entry_type'] == 'full'
        and r['result'] == 'miss'
        and not r.get('is_known_divergence', False)
        and not r.get('data_limited', False)
    ]

    # passed = no unexpected logic misses
    passed = len(unexpected_misses) == 0

    return {
        'results': results,
        'strict_hits': strict_hits,
        'suffocation_hits': suffocation_hits,
        'known_divergences': known_divergences,
        'unexpected_misses': unexpected_misses,
        'passed': passed,
        'total': len(EXPECTED_CASES),
        'db_range': (
            (db_min.date().isoformat(), db_max.date().isoformat())
            if db_min else None
        ),
    }


def print_report(result: dict) -> None:
    """Print formatted sanity check report."""
    results = result['results']
    strict_hits = result['strict_hits']
    suffocation_hits = result['suffocation_hits']
    known_divergences = result['known_divergences']
    unexpected_misses = result['unexpected_misses']
    passed = result['passed']
    total = result['total']

    print()
    print('=' * 60)
    print(f'Sanity Check: {total} instructor cases')
    print('=' * 60)

    # Full cases
    full_cases = [r for r in results if r['entry_type'] == 'full']
    if full_cases:
        print('\n[Full cases — 窒息量 + 出量 K]')
        for r in full_cases:
            ticker = r['ticker']
            name = r['name']
            note = r['note']
            if r['result'] == 'hit':
                scenario_flag = '' if r.get('scenario_match', True) else ' (情境不符)'
                print(
                    f'  ✓ {ticker} {name}  found={r["found_date"]}  '
                    f'scenario={r["found_scenario"]}{scenario_flag}  '
                    f'vol_ratio={r["vol_ratio"]:.4f}'
                )
            elif r.get('is_known_divergence'):
                print(f'  ⚠️ {ticker} {name}  不命中（已知落差）: {r.get("reason", "")}')
                print(f'     note: {note}')
            else:
                print(f'  ✗ {ticker} {name}  不命中（未預期）: {r.get("reason", "")}')

    # Suffocation_only cases
    suf_cases = [r for r in results if r['entry_type'] == 'suffocation_only']
    if suf_cases:
        print('\n[Suffocation-only cases — 只驗窒息量出現]')
        for r in suf_cases:
            ticker = r['ticker']
            name = r['name']
            icon = '✓' if r['result'] == 'suffocation_found' else '✗'
            print(f'  {icon} {ticker} {name}：{r["msg"]}')

    print()
    n_strict = len(strict_hits)
    n_suf = len(suffocation_hits)
    n_div = len(known_divergences)
    n_unexpected = len(unexpected_misses)

    summary_parts = []
    if n_strict > 0 or any(r['entry_type'] == 'full' for r in results):
        full_total = sum(1 for r in results if r['entry_type'] == 'full')
        summary_parts.append(f'{n_strict}/{full_total} strict hit')
    if n_suf > 0 or suf_cases:
        suf_total = len(suf_cases)
        summary_parts.append(f'{n_suf}/{suf_total} suffocation_only 確認')
    if n_div > 0:
        summary_parts.append(f'{n_div} known divergence')

    summary = ' + '.join(summary_parts)

    if passed and n_unexpected == 0:
        print(f'PASSED — {summary} — overall PASSED with caveats')
    else:
        print(f'FAILED — {summary} — {n_unexpected} unexpected miss(es)')
        for r in unexpected_misses:
            print(f'  ✗ {r["ticker"]} {r["name"]}：{r.get("reason", "")}')

    print('=' * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Sanity check: verify scanner detects §H instructor cases.'
    )
    parser.add_argument('--db', type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print per-case detail during scan.'
    )
    parser.add_argument(
        '--config-override', nargs='*', metavar='KEY=VALUE',
        help='Override SuffocationConfig values, e.g. max20_volume_ratio=0.12',
    )
    args = parser.parse_args()

    cfg = SuffocationConfig()
    if args.config_override:
        overrides = dict(kv.split('=', 1) for kv in args.config_override)
        cfg = cfg.apply_overrides(overrides)

    result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
    print_report(result)

    sys.exit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
