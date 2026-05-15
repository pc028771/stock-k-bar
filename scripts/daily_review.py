"""每日大盤模式監測 + 自動 config 更新。

使用方式：
    python scripts/daily_review.py              # 檢查模式是否改變
    python scripts/daily_review.py --force      # 強制重跑回測更新 config
    python scripts/daily_review.py --n-sweep    # 回測各 n 值（模式改變時自動執行）

流程：
    收盤後執行 → 偵測今日模式 → 與 config 比較
    → 無變化：印出目前參數，結束
    → 有變化：自動跑 n-sweep → 更新 config → 通知使用者
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

CONFIG_PATH = Path("data/analysis/kline_course_backtest/portfolio_config.json")
TAIEX_PATH  = Path("data/analysis/kline_course_backtest/taiex_daily.csv")
OUT_DIR     = Path("data/analysis/kline_course_backtest")


# ---------------------------------------------------------------------------
# 1. 大盤模式偵測
# ---------------------------------------------------------------------------

def detect_today_regime(crash_threshold: float = -0.08) -> str:
    """偵測最新交易日的大盤模式。

    回傳：'bull' / 'range' / 'crash' / 'bear'
    """
    from kline_course_backtest import add_features, load_bars
    from false_breakdown_strategy_check import add_market_regime
    import warnings; warnings.filterwarnings("ignore")

    df = add_market_regime(add_features(load_bars()))

    # 取最新交易日的 market_regime
    latest = df.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    today_regime = str(latest["market_regime"].iloc[-1])

    # 疊加 TAIEX 急跌判斷
    if TAIEX_PATH.exists():
        taiex = pd.read_csv(TAIEX_PATH, parse_dates=["date"]).sort_values("date")
        taiex["ret_10d"] = taiex["close"].pct_change(10)
        latest_taiex = taiex.dropna(subset=["ret_10d"]).iloc[-1]
        if float(latest_taiex["ret_10d"]) < crash_threshold:
            return "crash"

    return today_regime


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"找不到 config: {CONFIG_PATH}")
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    cfg["last_updated"] = str(date.today())
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 2. N-sweep：找當前模式最佳持倉數
# ---------------------------------------------------------------------------

def run_n_sweep(regime: str, cfg: dict) -> int:
    """跑 n=3~20 的回測，回傳最佳 max_positions。"""
    from kline_course_backtest import add_features, add_signals, load_bars
    from false_breakdown_strategy_check import add_market_regime
    from exit_simulation import simulate_exits
    from portfolio_simulator import (
        simulate_portfolio, load_market_cap, load_excluded_sectors,
        build_rank_lookup, detect_daily_regime,
    )
    import warnings; warnings.filterwarnings("ignore")

    playbook = cfg["playbook"][regime]
    top_n    = playbook["market_cap_top_n"]
    price_c  = playbook.get("price_ceiling")
    sizing   = playbook["sizing_mode"]

    df    = add_market_regime(add_signals(add_features(load_bars())))
    trades = simulate_exits(df)
    mc_data  = load_market_cap()
    excluded = load_excluded_sectors()
    rank_set = build_rank_lookup(mc_data, top_n=top_n, excluded_tickers=excluded)

    taiex = pd.read_csv(TAIEX_PATH, parse_dates=["date"]) if TAIEX_PATH.exists() else pd.DataFrame()
    market_daily = (df[["trade_date","market_regime"]]
                    .drop_duplicates("trade_date")
                    .set_index("trade_date")["market_regime"])
    market_daily.index = pd.to_datetime(market_daily.index)

    results = []
    for n in [3, 5, 8, 10, 15, 20]:
        executed, _ = simulate_portfolio(
            trades, df,
            strategy_name="top100_attack",
            max_price_per_share=price_c,
            sizing_mode=sizing,
            max_positions=n,
            rank_set=rank_set,
        )
        if executed.empty:
            continue
        final = executed["actual_pnl_twd"].sum() + 3_000_000
        ret   = (final - 3_000_000) / 3_000_000
        n_trades = len(executed)
        results.append({"n": n, "ret": ret, "trades": n_trades, "final": final})

    if not results:
        return cfg["playbook"][regime]["max_positions"]

    df_r = pd.DataFrame(results)
    print(f"\n  N-sweep 結果（模式：{regime}）：")
    print(f"  {'n':>4}  {'報酬':>8}  {'筆數':>6}  {'最終資金':>12}")
    for _, row in df_r.iterrows():
        print(f"  {int(row['n']):>4}  {row['ret']*100:>7.1f}%  {int(row['trades']):>6}  {row['final']:>12,.0f}")

    best_n = int(df_r.loc[df_r["ret"].idxmax(), "n"])
    print(f"\n  ★ 最佳 n = {best_n}（報酬最高）")
    df_r.to_csv(OUT_DIR / f"n_sweep_{regime}.csv", index=False)
    return best_n


# ---------------------------------------------------------------------------
# 3. 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force",   action="store_true", help="強制重跑回測更新 config")
    parser.add_argument("--n-sweep", action="store_true", help="只跑 n-sweep，不更新 config")
    args = parser.parse_args()

    cfg = load_config()
    crash_threshold = cfg["regime_detection"]["crash_threshold_10d"]

    print("偵測今日大盤模式...")
    today_regime = detect_today_regime(crash_threshold=crash_threshold)
    prev_regime  = cfg["current_regime"]

    print(f"  上次模式：{prev_regime}")
    print(f"  今日模式：{today_regime}")

    regime_changed = today_regime != prev_regime

    if not regime_changed and not args.force and not args.n_sweep:
        print("\n✓ 模式未改變，沿用現有參數：")
        _print_active(cfg)
        return

    if args.n_sweep:
        run_n_sweep(today_regime, cfg)
        return

    # 模式改變 or --force：重新回測最佳 n
    if regime_changed:
        print(f"\n⚠ 模式改變：{prev_regime} → {today_regime}，執行 n-sweep 更新參數...")
    else:
        print("\n強制重跑 n-sweep...")

    best_n = run_n_sweep(today_regime, cfg)

    # 更新 config
    cfg["current_regime"]  = today_regime
    cfg["active_params"]   = {
        **cfg["playbook"][today_regime],
        "max_positions": best_n,
    }
    save_config(cfg)

    print(f"\n✓ Config 已更新：")
    _print_active(cfg)
    print(f"\n  儲存至：{CONFIG_PATH}")


def _print_active(cfg: dict) -> None:
    p = cfg["active_params"]
    playbook_desc = cfg["playbook"].get(cfg["current_regime"], {}).get("description", "")
    print(f"  模式     ：{cfg['current_regime']} — {playbook_desc}")
    print(f"  最大持倉  ：{p['max_positions']} 檔")
    print(f"  規模策略  ：{p['sizing_mode']}")
    print(f"  股價上限  ：{p.get('price_ceiling') or '無限制'}")
    print(f"  市值篩選  ：前 {p['market_cap_top_n']} 大")
    print(f"  更新日期  ：{cfg['last_updated']}")


if __name__ == "__main__":
    main()
