"""比較 scanner 在「老師指定族群」universe 內的篩選價值.

Universe 限縮: teacher_sector_tickers.json (293 檔)

對照組（全部在老師族群 universe 內）:
  1. W底起漲 (scanner 篩) → MA5 trail
  2. Shakeout (scanner 篩) → MA5 trail
  3. 小結構 (scanner 篩) → 守整理底
  4. Baseline MA5: 老師族群每日隨機進場 → MA5 trail（衡量「不篩」的水準）
  5. Baseline 守底: 老師族群每日隨機進場 → 守整理底

Exit rules:
  - ma5_trail: 進場後每日檢查 close < ma5 → 隔日 open 出場
  - structural_low: 跌破訊號日前 5 根最低收盤 → 隔日 open 出場
  - max_hold = 60 天強制出場

Entry: signal_date + 1 day open (含 0.3% 滑價)
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.extras.shakeout_strong import detect as detect_shakeout  # noqa
from zhuli.entry.small_structure import detect as detect_small_structure  # noqa
from zhuli.entry.w_bottom_launch import detect as detect_wbottom  # noqa

_DB = MAIN_DB
_REPO_DIR = Path(__file__).parent.parent.parent

START_DATE = "2026-01-01"
END_DATE = "2026-05-22"
MAX_HOLD = 60
SLIPPAGE = 0.003

VOL_RATIO_MIN = {
    'w_bottom_launch': 2.0,
    'small_structure': 1.0,
    'shakeout_strong': 2.0,
}

# 大盤狀態 lookup（0050 收盤是否 >= MA20），trade_date → bool
TAIEX_MA20_BULL: dict[str, bool] = {}


def load_market_regime(con) -> None:
    rows = con.execute(
        "SELECT trade_date, close, ma20 FROM standard_daily_bar WHERE ticker='0050'"
    ).fetchall()
    for d, c, m in rows:
        if c is not None and m is not None and m > 0:
            TAIEX_MA20_BULL[d] = float(c) >= float(m)
    print(f"大盤 0050 regime 載入 {len(TAIEX_MA20_BULL)} 天")


def load_teacher_tickers() -> set[str]:
    p = _REPO_DIR / "docs" / "主力大課程" / "teacher_sector_tickers.json"
    data = json.loads(p.read_text())
    s: set[str] = set()
    for tickers in data.values():
        s.update(tickers)
    return s


def simulate_trade(after_df: pd.DataFrame, exit_rule: str, struct_low: float,
                   post_exit_df: pd.DataFrame | None = None) -> dict | None:
    """模擬從 after_df (signal_day+1 起的 bars) 進場到出場.

    exit_rule:
      - 'ma5_trail': close < ma5 → 隔日 open 出場
      - 'structural_low': close < struct_low → 隔日 open 出場

    post_exit_df: 出場後 10 天的 bars (用於 post-exit return 追蹤)
    """
    if len(after_df) < 2:
        return None

    entry_row = after_df.iloc[0]
    entry_open = float(entry_row['open'])
    if entry_open <= 0:
        return None
    entry_price = entry_open * (1 + SLIPPAGE)
    entry_date = entry_row['trade_date']

    bars = after_df.head(MAX_HOLD + 1)
    prev_break_ma5 = False  # for ma5_buffer_2d

    for i in range(len(bars)):
        row = bars.iloc[i]
        close = float(row['close'])
        triggered = False
        ma5 = float(row['ma5']) if pd.notna(row['ma5']) else None
        ma10 = float(row['ma10']) if pd.notna(row['ma10']) else None

        if exit_rule == 'ma5_trail':
            if ma5 is not None and close < ma5:
                triggered = True
        elif exit_rule == 'ma5_buffer_2d':
            # 連續 2 天收盤 < MA5 才出
            cur_break = ma5 is not None and close < ma5
            if cur_break and prev_break_ma5:
                triggered = True
            prev_break_ma5 = cur_break
        elif exit_rule == 'ma10_trail':
            if ma10 is not None and close < ma10:
                triggered = True
        elif exit_rule == 'regime_adaptive':
            # 大盤站 MA20 → MA10 trail（放寬，吃多段）；跌破 → MA5 trail（快出）
            is_bull = TAIEX_MA20_BULL.get(row['trade_date'], True)
            ref_ma = ma10 if is_bull else ma5
            if ref_ma is not None and close < ref_ma:
                triggered = True
        elif exit_rule == 'structural_low':
            if close < struct_low:
                triggered = True

        if triggered:
            if i + 1 < len(bars):
                exit_row = bars.iloc[i + 1]
                exit_price = float(exit_row['open']) * (1 - SLIPPAGE)
                exit_date = exit_row['trade_date']
                exit_reason = 'rule_exit'
                exit_idx_in_bars = i + 1
            else:
                exit_price = close * (1 - SLIPPAGE)
                exit_date = row['trade_date']
                exit_reason = 'rule_eod'
                exit_idx_in_bars = i
            hold_days = i + 1
            ret = (exit_price - entry_price) / entry_price
            tr = {
                'entry_date': entry_date, 'exit_date': exit_date,
                'entry_price': entry_price, 'exit_price': exit_price,
                'hold_days': hold_days, 'return_pct': ret * 100,
                'exit_reason': exit_reason,
            }
            # post-exit follow-up: 出場後 5/10 天股價變化
            post = bars.iloc[exit_idx_in_bars + 1:exit_idx_in_bars + 11]
            if len(post) >= 5:
                tr['post5_pct'] = (float(post.iloc[4]['close']) - exit_price) / exit_price * 100
            if len(post) >= 10:
                tr['post10_pct'] = (float(post.iloc[9]['close']) - exit_price) / exit_price * 100
            return tr

    last_row = bars.iloc[-1]
    exit_price = float(last_row['close']) * (1 - SLIPPAGE)
    ret = (exit_price - entry_price) / entry_price
    return {
        'entry_date': entry_date, 'exit_date': last_row['trade_date'],
        'entry_price': entry_price, 'exit_price': exit_price,
        'hold_days': len(bars), 'return_pct': ret * 100,
        'exit_reason': 'max_hold',
    }


def run() -> dict:
    teacher_set = load_teacher_tickers()
    print(f"老師族群 ticker: {len(teacher_set)}")

    con = get_conn(_DB, timeout=15)
    db_tickers = set(r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM standard_daily_bar WHERE is_usable=1"
    ).fetchall())
    universe = sorted(teacher_set & db_tickers)
    print(f"DB 內老師族群 universe: {len(universe)}")

    load_market_regime(con)

    scanners = {
        'w_bottom_launch': detect_wbottom,
        'small_structure': detect_small_structure,
        'shakeout_strong': detect_shakeout,
    }
    EXITS = ['ma5_trail', 'ma5_buffer_2d', 'ma10_trail', 'regime_adaptive']

    trades: dict[str, list[dict]] = {}
    for sname in list(scanners) + ['baseline']:
        for ex in EXITS:
            trades[f"{sname}__{ex}"] = []
    all_tickers = universe

    for i, t in enumerate(all_tickers):
        if i % 200 == 0:
            print(f"  進度 {i}/{len(all_tickers)}")
        df = pd.read_sql("""
            SELECT trade_date, open, high, low, close, volume,
                   vol_ratio_20, ma5, ma10, ma20, ma60, vol_ma20,
                   bb_upper, bb_lower, bb_mid, ma20_slope, ma20_slope_proxy
            FROM standard_daily_bar
            WHERE ticker=? AND is_usable=1 AND trade_date BETWEEN date(?, '-300 days') AND date(?, '+90 days')
            ORDER BY trade_date
        """, con, params=(t, START_DATE, END_DATE))
        if len(df) < 100:
            continue

        df['prev_close'] = df['close'].shift(1)
        df['prev_open'] = df['open'].shift(1)
        df['prev_high'] = df['high'].shift(1)
        df['prev_low'] = df['low'].shift(1)
        df['ma5_slope_5d'] = df['ma5'].diff(5)
        df['volume_ratio'] = df['vol_ratio_20']

        # shakeout_strong 所需衍生欄位
        df['prior_high_60'] = df['high'].shift(1).rolling(60, min_periods=60).max()
        df['breakout_strength_pct'] = (df['close'] / df['prior_high_60'] - 1) * 100
        # 隔日開低（次日 open < 今日 close） — 次日確認，最後一根為 NaN
        df['breakout_next_low_open'] = df['open'].shift(-1) < df['close']
        # overhead_supply_layer: 過去 240 天內 5-bar 局部高點高於今日 close 的個數
        high_arr = df['high'].to_numpy()
        close_arr = df['close'].to_numpy()
        n = len(df)
        peak_count = np.zeros(n)
        high_s = pd.Series(high_arr)
        for lag in range(1, 241):
            past_high = high_s.shift(lag).to_numpy()
            past_max5 = high_s.shift(lag).rolling(5, min_periods=5).max().to_numpy()
            is_peak = (past_high == past_max5) & ~np.isnan(past_max5)
            peak_count += ((past_high > close_arr) & is_peak).astype(float)
        df['overhead_supply_layer'] = np.where(np.arange(n) >= 20, peak_count, np.nan)

        for sname, fn in scanners.items():
            try:
                sig = fn(df)
            except Exception:
                continue
            if not hasattr(sig, 'iloc'):
                continue
            hit_idx = df.index[sig.fillna(False).astype(bool)].tolist()
            if not hit_idx:
                continue

            for idx in hit_idx:
                if idx < 5 or idx >= len(df) - 2:
                    continue
                sig_date = df.iloc[idx]['trade_date']
                if not (START_DATE <= sig_date <= END_DATE):
                    continue
                vr = df.iloc[idx]['vol_ratio_20']
                if pd.isna(vr) or float(vr) < VOL_RATIO_MIN[sname]:
                    continue

                struct_low = float(df.iloc[idx - 5:idx]['close'].min())
                after = df.iloc[idx + 1:].reset_index(drop=True)
                # 訊號日特徵 (進場時可觀察)
                sig_row = df.iloc[idx]
                feat = {'sig_vol_ratio': round(float(vr), 2)}
                if pd.notna(sig_row.get('ma20')) and sig_row['ma20'] > 0:
                    feat['sig_close_vs_ma20_pct'] = round((float(sig_row['close']) - float(sig_row['ma20'])) / float(sig_row['ma20']) * 100, 2)
                if pd.notna(sig_row.get('ma5')) and idx >= 5 and pd.notna(df.iloc[idx-5].get('ma5')) and df.iloc[idx-5]['ma5'] > 0:
                    feat['sig_ma5_slope_5d_pct'] = round((float(sig_row['ma5']) - float(df.iloc[idx-5]['ma5'])) / float(df.iloc[idx-5]['ma5']) * 100, 2)
                if pd.notna(sig_row.get('prior_high_60')) and sig_row['prior_high_60'] > 0:
                    feat['sig_dist_from_high60_pct'] = round((float(sig_row['close']) - float(sig_row['prior_high_60'])) / float(sig_row['prior_high_60']) * 100, 2)
                if pd.notna(sig_row.get('ma60')) and sig_row['ma60'] > 0:
                    feat['sig_close_vs_ma60_pct'] = round((float(sig_row['close']) - float(sig_row['ma60'])) / float(sig_row['ma60']) * 100, 2)
                for ex_rule in EXITS:
                    tr = simulate_trade(after, ex_rule, struct_low)
                    if tr is None:
                        continue
                    tr['ticker'] = t
                    tr['signal_date'] = sig_date
                    tr.update(feat)
                    trades[f"{sname}__{ex_rule}"].append(tr)

        # Baseline: 每隔 20 個交易日進場一次
        for idx in range(20, len(df) - 2, 20):
            sig_date = df.iloc[idx]['trade_date']
            if not (START_DATE <= sig_date <= END_DATE):
                continue
            struct_low = float(df.iloc[idx - 5:idx]['close'].min())
            after = df.iloc[idx + 1:].reset_index(drop=True)
            for ex_rule in EXITS:
                tr = simulate_trade(after, ex_rule, struct_low)
                if tr is None:
                    continue
                tr['ticker'] = t
                tr['signal_date'] = sig_date
                trades[f"baseline__{ex_rule}"].append(tr)

    con.close()

    summary = {}
    for name, lst in trades.items():
        if not lst:
            summary[name] = {'n': 0}
            continue
        df = pd.DataFrame(lst)
        n = len(df)
        win = (df['return_pct'] > 0).sum()
        avg_ret = df['return_pct'].mean()
        med_ret = df['return_pct'].median()
        avg_hold = df['hold_days'].mean()
        daily = avg_ret / avg_hold if avg_hold else 0
        # post-exit: 出場後續漲幅（負值=出場時機好；正值=出場太早）
        post5 = df['post5_pct'].dropna() if 'post5_pct' in df.columns else pd.Series(dtype=float)
        post10 = df['post10_pct'].dropna() if 'post10_pct' in df.columns else pd.Series(dtype=float)
        summary[name] = {
            'n': n,
            'win_rate': win / n * 100,
            'avg_return_pct': avg_ret,
            'median_return_pct': med_ret,
            'avg_hold_days': avg_hold,
            'daily_return_pct': daily,
            'post5_avg': float(post5.mean()) if len(post5) else None,
            'post10_avg': float(post10.mean()) if len(post10) else None,
            'post5_rose_pct': float((post5 > 0).mean() * 100) if len(post5) else None,
        }
    return {'summary': summary, 'trades': trades}


def analyze_post_exit_features(trades: dict) -> None:
    """分析出場後續漲（出場太早）vs 續跌（出場時機準）的特徵差異."""
    print("\n" + "=" * 100)
    print("出場後 5 天續漲特徵分析（找出「應該續抱」的訊號特徵）")
    print("=" * 100)
    for name in ['w_bottom_launch', 'shakeout_strong', 'small_structure']:
        lst = trades.get(name, [])
        if not lst:
            continue
        df = pd.DataFrame(lst)
        if 'post5_pct' not in df.columns:
            continue
        df = df.dropna(subset=['post5_pct'])
        if len(df) < 10:
            continue
        # 分群：出場後 5 天續漲 >2% (出場太早) vs <-2% (出場準)
        good_exit = df[df['post5_pct'] < -2]      # 真的轉弱
        bad_exit = df[df['post5_pct'] > 2]        # 出場太早、後續續漲
        print(f"\n--- {name} (n={len(df)}) ---")
        print(f"  出場準 (後 5d <-2%): {len(good_exit)} 筆 ({len(good_exit)/len(df)*100:.1f}%)")
        print(f"  出場早 (後 5d >+2%): {len(bad_exit)} 筆 ({len(bad_exit)/len(df)*100:.1f}%)")
        feat_cols = ['sig_vol_ratio', 'sig_close_vs_ma20_pct',
                     'sig_ma5_slope_5d_pct', 'sig_dist_from_high60_pct',
                     'return_pct', 'hold_days']
        rows = []
        for label, sub in [('出場準', good_exit), ('出場早', bad_exit)]:
            for col in feat_cols:
                if col in sub.columns:
                    rows.append((label, col, sub[col].dropna().mean()))
        if rows:
            cmp_df = pd.DataFrame(rows, columns=['group', 'feature', 'mean'])
            print(cmp_df.pivot(index='feature', columns='group', values='mean').round(2).to_string())


def print_report(summary: dict):
    scanners = ['w_bottom_launch', 'small_structure', 'shakeout_strong', 'baseline']
    exits = ['ma5_trail', 'ma5_buffer_2d', 'ma10_trail', 'regime_adaptive']
    scanner_labels = {
        'w_bottom_launch': 'W底起漲',
        'small_structure': '小結構',
        'shakeout_strong': 'Shakeout',
        'baseline':        'Baseline隨機',
    }
    exit_labels = {
        'ma5_trail':       'MA5純',
        'ma5_buffer_2d':   'MA5(2d緩衝)',
        'ma10_trail':      'MA10純',
        'regime_adaptive': '大盤適應',
    }

    print()
    print("=" * 110)
    print(f"Scanner × Exit Rule 矩陣（{START_DATE} ~ {END_DATE}, 老師族群 universe）")
    print("=" * 110)

    for metric, fmt, label in [
        ('avg_return_pct', '{:>8.2f}%', '平均報酬%'),
        ('win_rate',       '{:>8.1f}%', '上漲率%'),
        ('daily_return_pct','{:>8.2f}%', '日均報酬% (效率)'),
        ('avg_hold_days',  '{:>8.1f}天', '平均持有'),
        ('n',              '{:>8d} ',   '樣本'),
    ]:
        print(f"\n【{label}】")
        header = f"{'':<14}" + "".join(f"{exit_labels[e]:>12}" for e in exits)
        print(header)
        for s in scanners:
            row = f"{scanner_labels[s]:<14}"
            for e in exits:
                key = f"{s}__{e}"
                v = summary.get(key, {}).get(metric)
                if v is None or (isinstance(v, (int, float)) and v == 0 and metric != 'n'):
                    row += f"{'—':>12}"
                else:
                    row += "  " + fmt.format(v)
            print(row)
    print()


if __name__ == "__main__":
    r = run()
    print_report(r['summary'])
