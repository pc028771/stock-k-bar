"""
xiaoge vs kline_course detector 同期對比分析（Phase 4）。

僅做分析、不寫 detector code。

對齊邏輯
- xiaoge: phase3_chip_tight 的 (ticker, signal_date) 是 detector trigger 日，entry_date = signal_date + 1
- kline:  kline backtest_trades.csv 的 entry_date 為進場日（signal 隱含 = entry_date - 1）
- 為了對齊兩邊，統一以「entry_date」當 key、視同 detector trigger 後隔日進場

期間
- xiaoge entry_date 2026-05-05 ~ 2026-05-25
- 取交集區間 2026-05-01 ~ 2026-06-12 做篩選（兩邊都覆蓋到的子集）
"""

from __future__ import annotations

import pandas as pd
from pathlib import Path

ROOT = Path('/Users/howard/Repository/stock-k-bar')
XG_FILE = ROOT / 'data/analysis/xiaoge/backtest/phase3_chip_tight.csv'
KL_FILE = ROOT / 'data/analysis/kline/backtest_trades.csv'
# Fresh re-run (2026-06-14) extending to end-of-period for proper alignment.
# Merged = union of tweezer_top_breakout + combined_pattern_or_tweezer detectors.
KL_FRESH = Path('/tmp/kline_bt_merged.csv')
KL_FRESH_SINGLE = Path('/tmp/kline_bt_fresh.csv')
BB_FILE = ROOT / 'data/analysis/xiaoge/backtest/bb_squeeze_trades.csv'

PERIOD_START = pd.Timestamp('2026-05-01')
PERIOD_END = pd.Timestamp('2026-06-12')


def load_xiaoge() -> pd.DataFrame:
    df = pd.read_csv(XG_FILE)
    df['ticker'] = df['ticker'].astype(str)
    df['entry_date'] = pd.to_datetime(df['entry_date'])
    df['signal_date'] = pd.to_datetime(df['signal_date'])
    mask = (df['entry_date'] >= PERIOD_START) & (df['entry_date'] <= PERIOD_END)
    df = df[mask].copy()
    df['source'] = 'xiaoge_chip_tight'
    return df


def load_xiaoge_bb() -> pd.DataFrame:
    df = pd.read_csv(BB_FILE)
    df['ticker'] = df['ticker'].astype(str)
    df['entry_date'] = pd.to_datetime(df['entry_date'])
    df['signal_date'] = pd.to_datetime(df['signal_date'])
    mask = (df['entry_date'] >= PERIOD_START) & (df['entry_date'] <= PERIOD_END)
    df = df[mask].copy()
    df['source'] = 'xiaoge_bb_squeeze'
    return df


def load_kline() -> pd.DataFrame:
    src = KL_FRESH if KL_FRESH.exists() else KL_FILE
    df = pd.read_csv(src)
    df['ticker'] = df['ticker'].astype(str)
    df['entry_date'] = pd.to_datetime(df['entry_date'])
    mask = (df['entry_date'] >= PERIOD_START) & (df['entry_date'] <= PERIOD_END)
    df = df[mask].copy()
    # 統一 column 命名
    df = df.rename(columns={'trade_return': 'ret_pct_raw'})
    df['ret_pct'] = df['ret_pct_raw'] * 100.0  # convert to percentage
    df['source'] = 'kline_course'
    return df


def basic_summary(df: pd.DataFrame, name: str) -> dict:
    if len(df) == 0:
        return {'set': name, 'n': 0, 'unique_ticker': 0, 'avg_ret': None, 'win_rate': None,
                'med_ret': None, 'max_ret': None, 'min_ret': None}
    return {
        'set': name,
        'n': len(df),
        'unique_ticker': df['ticker'].nunique(),
        'avg_ret': round(df['ret_pct'].mean(), 2),
        'med_ret': round(df['ret_pct'].median(), 2),
        'win_rate': round((df['ret_pct'] > 0).mean() * 100, 1),
        'max_ret': round(df['ret_pct'].max(), 2),
        'min_ret': round(df['ret_pct'].min(), 2),
    }


def compare_sets(xg: pd.DataFrame, kl: pd.DataFrame, window_days: int = 0):
    """同 ticker × 同 entry_date (window_days=0) 或 ±N 日 (window_days>0)。"""
    if window_days == 0:
        xg_key = set(zip(xg['ticker'], xg['entry_date']))
        kl_key = set(zip(kl['ticker'], kl['entry_date']))
        cross_keys = xg_key & kl_key
        xg_only = xg_key - kl_key
        kl_only = kl_key - xg_key
        return cross_keys, xg_only, kl_only
    else:
        # ticker 重疊、entry_date 差 <= window
        kl_idx = {}
        for _, r in kl.iterrows():
            kl_idx.setdefault(r['ticker'], []).append(r['entry_date'])
        cross = []
        xg_only = []
        for _, r in xg.iterrows():
            t = r['ticker']
            d = r['entry_date']
            matched = False
            for kd in kl_idx.get(t, []):
                if abs((kd - d).days) <= window_days:
                    matched = True
                    cross.append((t, d, kd))
                    break
            if not matched:
                xg_only.append((t, d))
        # kl_only: ticker 在 kl 出現、xg 找不到 window 內配對
        xg_idx = {}
        for _, r in xg.iterrows():
            xg_idx.setdefault(r['ticker'], []).append(r['entry_date'])
        kl_only = []
        for _, r in kl.iterrows():
            t = r['ticker']
            d = r['entry_date']
            matched = any(abs((xd - d).days) <= window_days for xd in xg_idx.get(t, []))
            if not matched:
                kl_only.append((t, d))
        return cross, xg_only, kl_only


def subset_by_keys(df: pd.DataFrame, keys: set) -> pd.DataFrame:
    """keys = set of (ticker, entry_date) tuples."""
    df_keys = list(zip(df['ticker'], df['entry_date']))
    mask = [k in keys for k in df_keys]
    return df[mask].copy()


def main():
    xg = load_xiaoge()
    bb = load_xiaoge_bb()
    kl = load_kline()

    print("=" * 70)
    print(f"期間: {PERIOD_START.date()} ~ {PERIOD_END.date()}")
    print(f"xiaoge_chip_tight: {len(xg)} trades, {xg.ticker.nunique()} unique ticker")
    print(f"  signal_date range: {xg.signal_date.min().date()} ~ {xg.signal_date.max().date()}")
    print(f"xiaoge_bb_squeeze: {len(bb)} trades, {bb.ticker.nunique()} unique ticker")
    print(f"kline_course:      {len(kl)} trades, {kl.ticker.nunique()} unique ticker")
    print(f"  entry_date range: {kl.entry_date.min().date()} ~ {kl.entry_date.max().date()}")
    print()

    # === 對齊區間 ===
    # 兩邊都有的「最緊」共同區間（xiaoge entry 截到 2026-05-25）
    xg_max = xg.entry_date.max()
    common_end = min(xg_max, PERIOD_END)
    print(f"兩邊都覆蓋的對齊區間: {PERIOD_START.date()} ~ {common_end.date()}")
    xg_c = xg[xg['entry_date'] <= common_end]
    kl_c = kl[kl['entry_date'] <= common_end]
    print(f"對齊後 xiaoge: {len(xg_c)} trades / kline: {len(kl_c)} trades")
    print()

    # === 1. 完全重疊 (ticker × entry_date) ===
    print("=" * 70)
    print("1. 嚴格重疊 (ticker × entry_date 完全相同)")
    cross, xg_only, kl_only = compare_sets(xg_c, kl_c, window_days=0)
    print(f"  ∩ cross:    {len(cross)} (ticker, date) pairs")
    print(f"  xiaoge only: {len(xg_only)}")
    print(f"  kline only:  {len(kl_only)}")
    print()

    cross_xg = subset_by_keys(xg_c, cross)
    cross_kl = subset_by_keys(kl_c, cross)
    xg_only_df = subset_by_keys(xg_c, xg_only)
    kl_only_df = subset_by_keys(kl_c, kl_only)

    summary_rows = []
    summary_rows.append(basic_summary(cross_xg, 'cross (xiaoge perf)'))
    summary_rows.append(basic_summary(cross_kl, 'cross (kline perf)'))
    summary_rows.append(basic_summary(xg_only_df, 'xiaoge only'))
    summary_rows.append(basic_summary(kl_only_df, 'kline only'))
    summary_rows.append(basic_summary(xg_c, 'xiaoge total'))
    summary_rows.append(basic_summary(kl_c, 'kline total'))
    print(pd.DataFrame(summary_rows).to_string(index=False))
    print()

    # === 2. 寬鬆對齊 ±5 日 ===
    print("=" * 70)
    print("2. 寬鬆重疊 (ticker × entry_date ±5 日)")
    cross5, xg_only5, kl_only5 = compare_sets(xg_c, kl_c, window_days=5)
    print(f"  ∩ cross (±5d): {len(cross5)} pairs")
    print(f"  xiaoge only:   {len(xg_only5)}")
    print(f"  kline only:    {len(kl_only5)}")
    # cross5 perf
    cross5_xg_keys = {(item[0], item[1]) for item in cross5}
    cross5_kl_keys = {(item[0], item[2]) for item in cross5}
    # 但同 ticker 可能多筆 -> use multi-key
    cross5_xg = xg_c[xg_c.apply(lambda r: (r['ticker'], r['entry_date']) in cross5_xg_keys, axis=1)]
    cross5_kl = kl_c[kl_c.apply(lambda r: (r['ticker'], r['entry_date']) in cross5_kl_keys, axis=1)]
    print()
    print("  cross ±5d 績效對比:")
    s5 = [basic_summary(cross5_xg, 'cross±5d (xiaoge side)'),
          basic_summary(cross5_kl, 'cross±5d (kline side)')]
    print(pd.DataFrame(s5).to_string(index=False))
    print()

    # === 3. Top winners 重疊 ===
    print("=" * 70)
    print("3. xiaoge Top 20 winners — kline 是否也抓到？")
    xg_sorted = xg_c.sort_values('ret_pct', ascending=False).head(20)
    kl_ticker_dates = {(t, d) for t, d in zip(kl_c['ticker'], kl_c['entry_date'])}
    kl_tickers_in_period = set(kl_c['ticker'].unique())

    rows = []
    for _, r in xg_sorted.iterrows():
        t, d, ret = r['ticker'], r['entry_date'], r['ret_pct']
        exact = (t, d) in kl_ticker_dates
        ticker_in_kline = t in kl_tickers_in_period
        # check ±5d
        kl_dates_for_t = kl_c[kl_c['ticker'] == t]['entry_date'].tolist()
        within5 = any(abs((kd - d).days) <= 5 for kd in kl_dates_for_t)
        rows.append({
            'ticker': t,
            'xg_entry_date': d.date(),
            'xg_ret_pct': round(ret, 2),
            'kline_exact_hit': exact,
            'kline_within_5d': within5,
            'kline_any_in_period': ticker_in_kline,
        })
    top_df = pd.DataFrame(rows)
    print(top_df.to_string(index=False))
    print()
    n_exact = top_df['kline_exact_hit'].sum()
    n_5d = top_df['kline_within_5d'].sum()
    n_any = top_df['kline_any_in_period'].sum()
    print(f"  Top20 xiaoge 大贏家中: exact 對到 {n_exact}/20, ±5d {n_5d}/20, 任意期間 {n_any}/20")
    print()

    # === 4. kline Top winners — xiaoge 是否也抓到？ ===
    print("=" * 70)
    print("4. kline Top 20 winners — xiaoge 是否也抓到？")
    kl_sorted = kl_c.sort_values('ret_pct', ascending=False).head(20)
    xg_ticker_dates = {(t, d) for t, d in zip(xg_c['ticker'], xg_c['entry_date'])}
    xg_tickers_in_period = set(xg_c['ticker'].unique())
    rows = []
    for _, r in kl_sorted.iterrows():
        t, d, ret = r['ticker'], r['entry_date'], r['ret_pct']
        exact = (t, d) in xg_ticker_dates
        xg_dates_for_t = xg_c[xg_c['ticker'] == t]['entry_date'].tolist()
        within5 = any(abs((xd - d).days) <= 5 for xd in xg_dates_for_t)
        ticker_in_xg = t in xg_tickers_in_period
        rows.append({
            'ticker': t,
            'kl_entry_date': d.date(),
            'kl_ret_pct': round(ret, 2),
            'xiaoge_exact_hit': exact,
            'xiaoge_within_5d': within5,
            'xiaoge_any_in_period': ticker_in_xg,
        })
    top_kl = pd.DataFrame(rows)
    print(top_kl.to_string(index=False))
    print()
    n_exact = top_kl['xiaoge_exact_hit'].sum()
    n_5d = top_kl['xiaoge_within_5d'].sum()
    n_any = top_kl['xiaoge_any_in_period'].sum()
    print(f"  Top20 kline 大贏家中: exact 對到 {n_exact}/20, ±5d {n_5d}/20, 任意期間 {n_any}/20")
    print()

    # === 5. xiaoge 漏掉的 winner（在 kline 抓到、但 xiaoge entire 期間 ticker 沒出現）===
    print("=" * 70)
    print("5. kline 抓到的好股、xiaoge 完全沒抓 (ret >= 5%、ticker 不在 xiaoge 期間)")
    big_winners_kl = kl_c[kl_c['ret_pct'] >= 5.0]
    missed = big_winners_kl[~big_winners_kl['ticker'].isin(xg_tickers_in_period)]
    print(missed[['ticker', 'entry_date', 'ret_pct']].sort_values('ret_pct', ascending=False).to_string(index=False))
    print()

    print("=" * 70)
    print("6. xiaoge 抓到的好股、kline 完全沒抓 (ret >= 20%、ticker 不在 kline 期間)")
    big_winners_xg = xg_c[xg_c['ret_pct'] >= 20.0]
    missed_kl = big_winners_xg[~big_winners_xg['ticker'].isin(kl_tickers_in_period)]
    print(missed_kl[['ticker', 'entry_date', 'ret_pct']].sort_values('ret_pct', ascending=False).head(30).to_string(index=False))
    print(f"\n  (xiaoge 大贏家 ret>=20%, kline 完全沒在期間掃到的 ticker 共 {len(missed_kl)} 筆)")
    print()

    # === 7. cross signals 報酬 vs 單獨 ===
    print("=" * 70)
    print("7. 結論統計")
    if len(cross_xg) > 0:
        improve_xg = cross_xg['ret_pct'].mean() - xg_c['ret_pct'].mean()
        improve_kl = cross_kl['ret_pct'].mean() - kl_c['ret_pct'].mean()
        print(f"  cross signal (xiaoge perf {cross_xg['ret_pct'].mean():.2f}%) vs xiaoge total ({xg_c['ret_pct'].mean():.2f}%) → Δ {improve_xg:+.2f}%")
        print(f"  cross signal (kline perf  {cross_kl['ret_pct'].mean():.2f}%) vs kline total  ({kl_c['ret_pct'].mean():.2f}%) → Δ {improve_kl:+.2f}%")
        # win rate
        wr_cross_xg = (cross_xg['ret_pct'] > 0).mean() * 100
        wr_xg = (xg_c['ret_pct'] > 0).mean() * 100
        print(f"  win rate: cross(xg) {wr_cross_xg:.1f}% vs xg total {wr_xg:.1f}%")
    else:
        print("  cross signals = 0、無法做 lift 統計")
    print()

    # 5d cross
    if len(cross5_xg) > 0:
        improve5_xg = cross5_xg['ret_pct'].mean() - xg_c['ret_pct'].mean()
        improve5_kl = cross5_kl['ret_pct'].mean() - kl_c['ret_pct'].mean()
        wr5_xg = (cross5_xg['ret_pct'] > 0).mean() * 100
        wr5_kl = (cross5_kl['ret_pct'] > 0).mean() * 100
        print(f"  cross±5d (xiaoge side) avg {cross5_xg['ret_pct'].mean():.2f}% / wr {wr5_xg:.1f}% (n={len(cross5_xg)}) vs xg total {xg_c['ret_pct'].mean():.2f}% / {(xg_c['ret_pct']>0).mean()*100:.1f}%")
        print(f"  cross±5d (kline side)  avg {cross5_kl['ret_pct'].mean():.2f}% / wr {wr5_kl:.1f}% (n={len(cross5_kl)}) vs kl total {kl_c['ret_pct'].mean():.2f}% / {(kl_c['ret_pct']>0).mean()*100:.1f}%")


if __name__ == '__main__':
    main()
