"""xiaoge_flying_stock_screener — 多策略 combinator (9 多頭 + 6 空頭).

Course source: 權證小哥課程 ch12 (飆股口袋名單), ch13 (多策略交叉案例).
Reference: docs/權證小哥/籌碼技術分析/detector_spec.md §5.

課程原話:
> 「越多條件交集的選出來的股票越少，那選出來的股票越少呢，他的精準度會越高。」
>  (ch13 02:03–02:27)
> 「前十大主力買氣強 + 分點主力連續買超 + 波動上升且強勢 + KD 黃金交叉 →
>  超眾、亞光 兩檔後續沿上軌大漲。」 (ch13 案例)

## 設計原則

每條 sub-detector 是獨立 bool Series（True = 命中）。
screen_long() / screen_short() 接受 strategy list，
計算每個 (ticker, date) 行的命中條件數 (score)，
篩出 score ≥ min_score 的列回傳。

## 資料源

- 主力買賣超 (main_force_1d/5d/10d/20d): DB `standard_daily_bar`（機構合計代理）
- 外資 / 投信買超: FinMind `TaiwanStockInstitutionalInvestorsBuySell`
  若 DB 無對應欄位則以 FinMind client 補抓。
- 布林帶 / MA / 波動度 / 20 日新高低: 由本模組計算（依賴 features.py）

## CLI

python -m xiaoge.scoring.screener --side long --strategies M1,M3,M6,M9 \\
    --start 2026-04-01 --end 2026-06-12 --min-score 3

輸出 CSV: data/analysis/xiaoge/screener_{side}_{date}.csv
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date as _date
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Path setup — allow running as __main__ and as a module
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from xiaoge.bars import load_bars, add_squeeze_flag, vol_ma5  # noqa: E402
from xiaoge.features import (  # noqa: E402
    add_volatility,
    add_20d_high_low,
)

# ---------------------------------------------------------------------------
# Helper — build full feature df with all indicators needed
# ---------------------------------------------------------------------------

def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all derived columns needed by sub-detectors."""
    out = df.copy()
    out = add_squeeze_flag(out)           # bb_in_squeeze (uses bb_width_pct)
    out = add_volatility(out)             # volatility_5d, volatility_rising
    out = add_20d_high_low(out)          # high_20d, low_20d, is_20d_high, is_20d_low
    # vol_ma5 for broker-loading checks
    out["_vol_ma5"] = vol_ma5(out)
    # MA5 slope: ma5[t] > ma5[t-1]
    out["_ma5_rising"] = (
        out.groupby("ticker")["ma5"].transform(lambda s: (s > s.shift(1))).fillna(False)
    )
    # close > ma5
    out["_above_ma5"] = (out["close"] > out["ma5"]).fillna(False)
    # bb_upper slope
    out["_bb_upper_rising"] = (
        out.groupby("ticker")["bb_upper"]
        .transform(lambda s: (s > s.shift(1)))
        .fillna(False)
    )
    return out


# ===========================================================================
# 多頭 sub-detectors  M1–M9
# ===========================================================================

def detect_m1_top10_main_buying(df: pd.DataFrame,
                                 min_ratio: float = 1.5,
                                 min_vol_ma5: int = 500) -> pd.Series:
    """M1 — 前 10 大主力買氣強 (xiaoge_top10_main_buying).

    Course source: ch12 多頭策略 #1.
    課程原話: 「分點買張前 10 平均量 / 分點賣張前 10 平均量；附加條件 5 日均量 > 500 張。」

    資料限制: DB 無「個股 × 日 × 分點」粒度，以 main_force_5d / vol_ma5 作代理。
    Proxy rule:
        main_force_5d > 0 (淨買超)
        AND main_force_5d / vol_ma5 ≥ min_ratio%  (買超力道)
        AND vol_ma5 ≥ min_vol_ma5 (課程條件：5 日均量 > 500 張)

    Parameters
    ----------
    min_ratio:
        main_force_5d / vol_ma5 threshold (fraction, 不是 %). Default 1.5 —
        課程僅給「前 10 大買超 / 賣超均量比 ≥ 閾值」方向、具體比值未給；
        1.5 為 conservative 推測（課程僅概念、預設值為 conservative 推測）。
    min_vol_ma5:
        5-day avg volume filter in 張. Default 500 per 課程原話.
    """
    main = df["main_force_5d"].fillna(0)
    vol5 = df["_vol_ma5"].fillna(0)
    ratio = main / vol5.replace(0, pd.NA)
    signal = (
        (main > 0)
        & (ratio >= min_ratio).fillna(False)
        & (vol5 >= min_vol_ma5)
    )
    return signal.fillna(False)


def detect_m2_max_broker_loading(df: pd.DataFrame,
                                  min_pct: float = 0.20,
                                  min_volume: int = 1000) -> pd.Series:
    """M2 — 最大主力狂進貨 (xiaoge_max_broker_loading).

    Course source: ch12 多頭策略 #2.
    課程原話: 「最大買超分點買超量 ≥ 成交量 20%、當日成交量 > 1000 張。
               記得避開短線客（隔日沖）。」

    資料限制: DB 無個別分點資料；以 main_force_1d / volume 作代理。
    Proxy rule:
        main_force_1d / volume ≥ min_pct (單日主力淨買佔成交量)
        AND volume ≥ min_volume

    課程原話「排除隔日沖分點」= 無分點資料時此條件不可精確判斷；
    以 NotImplementedError 標記缺資料部分、但仍以代理計算回傳結果。

    Parameters
    ----------
    min_pct:
        main_force_1d / volume threshold. Default 0.20 per 課程原話「≥ 20%」.
    min_volume:
        Single-day volume floor in 張. Default 1000 per 課程原話.
    """
    main1d = df["main_force_1d"].fillna(0)
    vol    = df["volume"].fillna(0)
    ratio  = main1d / vol.replace(0, pd.NA)
    # NOTE: 課程「排除隔日沖慣性分點」需分點層級資料 — 此處無法精確執行，以代理為主
    signal = (
        (main1d > 0)
        & (ratio >= min_pct).fillna(False)
        & (vol >= min_volume)
    )
    return signal.fillna(False)


def detect_m3_main_buy_streak_n(df: pd.DataFrame, n: int = 5) -> pd.Series:
    """M3 — 分點主力連續買超 N 天 (xiaoge_main_buy_streak_N).

    Course source: ch12 多頭策略 #3.
    課程原話: 「分點主力連續買超 N 天（找長期佈局；年底/年初可挑董監改選股）。」

    Uses main_force_1d as daily proxy for 主力買賣超.

    Parameters
    ----------
    n:
        Consecutive days of buying required. Default 5.
        課程給「N 可調 3/5/10/20」、預設 5。
    """
    is_buy = (df["main_force_1d"].fillna(0) > 0).astype(int)
    streak = (
        is_buy.groupby(df["ticker"])
        .transform(lambda s: s.rolling(n, min_periods=n).sum())
    )
    return (streak >= n).fillna(False)


def detect_m4_foreign_buy_streak_n(df: pd.DataFrame, n: int = 5) -> pd.Series:
    """M4 — 外資連續買超 N 天 (xiaoge_foreign_buy_streak_N).

    Course source: ch12 多頭策略 #4.
    課程原話: 「外資連續買超 N 天，但容易買在頭部，須交叉看關鍵分點是否在賣。」

    資料依賴: DB `standard_daily_bar` 無 foreign 欄位；需 FinMind
    `TaiwanStockInstitutionalInvestorsBuySell`。若 df 含 `foreign_net_1d` 欄位則直接用；
    否則此 detector 回傳全 False 並記錄。

    「交叉看關鍵分點是否在賣」= 需分點資料，目前無法精確判斷（標記為 NotImplementedError 方向）。

    Parameters
    ----------
    n:
        Consecutive days of foreign buying required. Default 5.
        課程給「N 可調 3/5/10/20」。
    """
    if "foreign_net_1d" not in df.columns:
        # 課程要求、資料源待補 — 現有 DB 無外資欄位
        return pd.Series(False, index=df.index)

    is_buy = (df["foreign_net_1d"].fillna(0) > 0).astype(int)
    streak = (
        is_buy.groupby(df["ticker"])
        .transform(lambda s: s.rolling(n, min_periods=n).sum())
    )
    return (streak >= n).fillna(False)


def detect_m5_invest_trust_buy_streak_n(df: pd.DataFrame, n: int = 5) -> pd.Series:
    """M5 — 投信連續買超 N 天 (xiaoge_invest_trust_buy_streak_N).

    Course source: ch12 多頭策略 #5.
    課程原話: 「投信連續買超 N 天，投信有研究團隊，會帶動波段漲勢。」

    資料依賴: 同 M4 — 需 `invest_trust_net_1d` 欄位，若缺回傳全 False。

    Parameters
    ----------
    n:
        Consecutive days of trust buying required. Default 5.
    """
    if "invest_trust_net_1d" not in df.columns:
        # 課程要求、資料源待補 — 現有 DB 無投信欄位
        return pd.Series(False, index=df.index)

    is_buy = (df["invest_trust_net_1d"].fillna(0) > 0).astype(int)
    streak = (
        is_buy.groupby(df["ticker"])
        .transform(lambda s: s.rolling(n, min_periods=n).sum())
    )
    return (streak >= n).fillna(False)


def detect_m6_volatility_rising_strong(df: pd.DataFrame) -> pd.Series:
    """M6 — 波動上升且強勢 (xiaoge_volatility_rising_strong).

    Course source: ch12 多頭策略 #6.
    課程原話: 「短期波動度上升 2%↑ + 5MA 上揚 + 站上 5MA」
              「買權證最怕盤整、買有波動的。」

    Requires features built by add_volatility() + _build_features():
        volatility_rising, _ma5_rising, _above_ma5
    """
    return (
        df["volatility_rising"].fillna(False)
        & df["_ma5_rising"].fillna(False)
        & df["_above_ma5"].fillna(False)
    )


def detect_m7_break_20d_high(df: pd.DataFrame) -> pd.Series:
    """M7 — 突破平台整理區 / 創 20 日新高 (xiaoge_break_20d_high).

    Course source: ch12 多頭策略 #7.
    課程原話: 「突破平台整理區…創 20 日高價（這 20 天買的人都賺錢）。」

    Requires add_20d_high_low(): is_20d_high column.
    """
    return df["is_20d_high"].fillna(False)


def detect_m8_bb_open(df: pd.DataFrame) -> pd.Series:
    """M8 — 布林軌道打開 (xiaoge_bb_open).

    Course source: ch12 多頭策略 #8.
    課程原話: 「布林軌道打開，上通道打開，短期整理完往上攻；壓縮越久、之後漲勢越驚人。」

    Condition: bb_upper斜率正 (bb_upper today > bb_upper yesterday).
    Requires _build_features(): _bb_upper_rising column.
    """
    return df["_bb_upper_rising"].fillna(False)


def detect_m9_bb_squeeze(df: pd.DataFrame,
                          squeeze_threshold: float = 10.0) -> pd.Series:
    """M9 — 布林軌道壓縮 (xiaoge_bb_squeeze).

    Course source: ch12 多頭策略 #9.
    課程原話: 「布林軌道壓縮，找尚未表態的股票。」

    Uses bb_width_pct (DB precomputed) or bb_in_squeeze from add_squeeze_flag().
    Threshold: < 10 per 老師原話「10 算正常、< 10 算收斂」.

    Parameters
    ----------
    squeeze_threshold:
        bb_width_pct ≤ this counts as compressed. Default 10.0 per 課程.
    """
    if "bb_in_squeeze" in df.columns:
        return df["bb_in_squeeze"].fillna(False)
    return (df["bb_width_pct"] <= squeeze_threshold).fillna(False)


# ===========================================================================
# 空頭 sub-detectors  S1–S6
# ===========================================================================

def detect_s1_top10_main_selling(df: pd.DataFrame,
                                  min_ratio: float = 1.5,
                                  min_vol_ma5: int = 500) -> pd.Series:
    """S1 — 前 10 大主力賣壓重 (xiaoge_top10_main_selling).

    Course source: ch12 空頭策略 #1.
    課程原話: 「前 10 大主力賣壓重。」 Mirror of M1.

    Proxy: main_force_5d < 0 AND abs(main_force_5d) / vol_ma5 ≥ min_ratio.
    """
    main = df["main_force_5d"].fillna(0)
    vol5 = df["_vol_ma5"].fillna(0)
    ratio = (-main) / vol5.replace(0, pd.NA)
    signal = (
        (main < 0)
        & (ratio >= min_ratio).fillna(False)
        & (vol5 >= min_vol_ma5)
    )
    return signal.fillna(False)


def detect_s2_max_broker_dumping(df: pd.DataFrame,
                                  min_pct: float = 0.20,
                                  min_volume: int = 1000) -> pd.Series:
    """S2 — 最大主力狂倒貨 (xiaoge_max_broker_dumping).

    Course source: ch12 空頭策略 #2.
    課程原話: 「最大賣超分點佔成交量 20%↑、成交量 > 1000 張。」 Mirror of M2.

    Proxy: main_force_1d < 0 AND abs(main_force_1d) / volume ≥ min_pct.
    """
    main1d = df["main_force_1d"].fillna(0)
    vol    = df["volume"].fillna(0)
    ratio  = (-main1d) / vol.replace(0, pd.NA)
    signal = (
        (main1d < 0)
        & (ratio >= min_pct).fillna(False)
        & (vol >= min_volume)
    )
    return signal.fillna(False)


def detect_s3_main_sell_streak_n(df: pd.DataFrame, n: int = 5) -> pd.Series:
    """S3 — 分點主力連續賣超 N 天 (xiaoge_main_sell_streak_N).

    Course source: ch12 空頭策略 #3. Mirror of M3.
    """
    is_sell = (df["main_force_1d"].fillna(0) < 0).astype(int)
    streak  = (
        is_sell.groupby(df["ticker"])
        .transform(lambda s: s.rolling(n, min_periods=n).sum())
    )
    return (streak >= n).fillna(False)


def detect_s4_foreign_sell_streak_n(df: pd.DataFrame, n: int = 5) -> pd.Series:
    """S4 — 外資連續賣超 N 天 (xiaoge_foreign_sell_streak_N).

    Course source: ch12 空頭策略 #4.
    課程原話: 「外資連續賣超 N 天（要交叉看關鍵分點是否在大買，避免空在低點）。」

    資料依賴: 需 `foreign_net_1d` 欄位，若缺回傳全 False。
    """
    if "foreign_net_1d" not in df.columns:
        return pd.Series(False, index=df.index)

    is_sell = (df["foreign_net_1d"].fillna(0) < 0).astype(int)
    streak  = (
        is_sell.groupby(df["ticker"])
        .transform(lambda s: s.rolling(n, min_periods=n).sum())
    )
    return (streak >= n).fillna(False)


def detect_s5_invest_trust_sell_streak_n(df: pd.DataFrame, n: int = 5) -> pd.Series:
    """S5 — 投信連續賣超 N 天 (xiaoge_invest_trust_sell_streak_N).

    Course source: ch12 空頭策略 #5. Mirror of M5.

    資料依賴: 需 `invest_trust_net_1d`，若缺回傳全 False。
    """
    if "invest_trust_net_1d" not in df.columns:
        return pd.Series(False, index=df.index)

    is_sell = (df["invest_trust_net_1d"].fillna(0) < 0).astype(int)
    streak  = (
        is_sell.groupby(df["ticker"])
        .transform(lambda s: s.rolling(n, min_periods=n).sum())
    )
    return (streak >= n).fillna(False)


def detect_s6_volatility_rising_weak(df: pd.DataFrame) -> pd.Series:
    """S6 — 波動上升且弱勢 + 跌破平台整理區 (xiaoge_volatility_rising_weak).

    Course source: ch12 空頭策略 #6.
    課程原話: 「波動上升且弱勢、跌破平台整理區（創 20 日低）。」

    Conditions (ALL):
        volatility_rising (波動度上升)
        AND _ma5_rising is False (5MA 下彎)
        AND close < ma5 (跌破 5MA)
        AND is_20d_low (創 20 日低)
    """
    close    = df["close"]
    ma5      = df["ma5"]
    below_ma5  = (close < ma5).fillna(False)
    ma5_down   = ~df["_ma5_rising"].fillna(True)  # NOT rising = down

    return (
        df["volatility_rising"].fillna(False)
        & ma5_down
        & below_ma5
        & df["is_20d_low"].fillna(False)
    )


# ===========================================================================
# Strategy registry
# ===========================================================================

_LONG_DETECTORS: dict[str, object] = {
    "M1": detect_m1_top10_main_buying,
    "M2": detect_m2_max_broker_loading,
    "M3": detect_m3_main_buy_streak_n,
    "M4": detect_m4_foreign_buy_streak_n,
    "M5": detect_m5_invest_trust_buy_streak_n,
    "M6": detect_m6_volatility_rising_strong,
    "M7": detect_m7_break_20d_high,
    "M8": detect_m8_bb_open,
    "M9": detect_m9_bb_squeeze,
}

_SHORT_DETECTORS: dict[str, object] = {
    "S1": detect_s1_top10_main_selling,
    "S2": detect_s2_max_broker_dumping,
    "S3": detect_s3_main_sell_streak_n,
    "S4": detect_s4_foreign_sell_streak_n,
    "S5": detect_s5_invest_trust_sell_streak_n,
    "S6": detect_s6_volatility_rising_weak,
}


# ===========================================================================
# Combinator
# ===========================================================================

def screen_long(
    df: pd.DataFrame,
    strategies: list[str],
    min_score: int = 1,
) -> pd.DataFrame:
    """組合多頭策略 (M1–M9) 回傳命中 rows.

    Parameters
    ----------
    df:
        Full feature DataFrame (output of _build_features(); must include
        ticker, trade_date, close, volume, main_force_1d/5d, ma5,
        bb_upper, bb_width_pct, volatility_rising, is_20d_high/low, …).
    strategies:
        List of strategy codes from ['M1','M2',...,'M9'].
        E.g. ['M1', 'M3', 'M6', 'M9'].
    min_score:
        Minimum number of strategies that must hit (≥ min_score). Default 1.

    Returns
    -------
    pd.DataFrame with columns:
        ticker, trade_date, score, hit_strategies (list as str)
    """
    unknown = set(strategies) - set(_LONG_DETECTORS)
    if unknown:
        raise ValueError(f"Unknown long strategies: {unknown}. Valid: {list(_LONG_DETECTORS)}")

    if "is_20d_high" not in df.columns or "volatility_rising" not in df.columns:
        df = _build_features(df)

    hits: dict[str, pd.Series] = {}
    for code in strategies:
        fn = _LONG_DETECTORS[code]
        hits[code] = fn(df)  # type: ignore[call-arg]

    return _combine(df, hits, min_score)


def screen_short(
    df: pd.DataFrame,
    strategies: list[str],
    min_score: int = 1,
) -> pd.DataFrame:
    """組合空頭策略 (S1–S6) 回傳命中 rows.

    Parameters
    ----------
    df:
        Full feature DataFrame (output of _build_features()).
    strategies:
        List of strategy codes from ['S1','S2',...,'S6'].
    min_score:
        Minimum number of strategies that must hit. Default 1.

    Returns
    -------
    pd.DataFrame with columns:
        ticker, trade_date, score, hit_strategies (list as str)
    """
    unknown = set(strategies) - set(_SHORT_DETECTORS)
    if unknown:
        raise ValueError(f"Unknown short strategies: {unknown}. Valid: {list(_SHORT_DETECTORS)}")

    if "is_20d_low" not in df.columns or "volatility_rising" not in df.columns:
        df = _build_features(df)

    hits: dict[str, pd.Series] = {}
    for code in strategies:
        fn = _SHORT_DETECTORS[code]
        hits[code] = fn(df)  # type: ignore[call-arg]

    return _combine(df, hits, min_score)


def _combine(
    df: pd.DataFrame,
    hits: dict[str, pd.Series],
    min_score: int,
) -> pd.DataFrame:
    """Internal: combine hit series, compute score, filter."""
    scores = pd.DataFrame(hits)
    score_col = scores.sum(axis=1)

    # hit_strategies as comma-separated string
    def _hit_list(row: pd.Series) -> str:
        return ",".join(code for code, val in row.items() if val)

    hit_strats = scores.apply(_hit_list, axis=1)

    mask = score_col >= min_score
    result = pd.DataFrame({
        "ticker":         df["ticker"][mask].values,
        "trade_date":     df["trade_date"][mask].values,
        "score":          score_col[mask].values,
        "hit_strategies": hit_strats[mask].values,
    })
    return result.reset_index(drop=True)


# ===========================================================================
# CLI
# ===========================================================================

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="xiaoge flying_stock_screener — 多策略組合篩股",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m xiaoge.scoring.screener --side long --strategies M7,M9 \\
      --start 2026-06-01 --end 2026-06-12 --min-score 1

  python -m xiaoge.scoring.screener --side short --strategies S1,S3,S6 \\
      --start 2026-04-01 --end 2026-06-12 --min-score 2

課程來源: ch12 飆股口袋名單 + ch13 多策略交叉案例
""",
    )
    p.add_argument("--side", choices=["long", "short"], required=True,
                   help="多頭 (long) 或空頭 (short)")
    p.add_argument("--strategies", required=True,
                   help="策略代碼，逗號分隔。多頭: M1-M9；空頭: S1-S6")
    p.add_argument("--start", required=True, help="開始日期 YYYY-MM-DD")
    p.add_argument("--end",   required=True, help="結束日期 YYYY-MM-DD")
    p.add_argument("--min-score", type=int, default=1,
                   help="最少命中策略數 (預設: 1)")
    p.add_argument("--tickers", default=None,
                   help="限定 ticker 清單（逗號分隔）；預設全市場")
    p.add_argument("--db", default=None,
                   help="SQLite DB 路徑（預設: ~/.four_seasons/data.sqlite）")
    p.add_argument("--out-dir", default=None,
                   help="輸出 CSV 目錄（預設: data/analysis/xiaoge/）")
    p.add_argument("--no-csv", action="store_true",
                   help="不輸出 CSV，只印到 stdout")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    strategies = [s.strip().upper() for s in args.strategies.split(",") if s.strip()]
    tickers    = [t.strip() for t in args.tickers.split(",")] if args.tickers else None

    load_kwargs: dict = dict(start_date=args.start, end_date=args.end)
    if args.db:
        from pathlib import Path as _Path
        load_kwargs["db_path"] = _Path(args.db)
    if tickers:
        load_kwargs["tickers"] = tickers

    print(f"Loading bars {args.start} ~ {args.end} …", file=sys.stderr)
    df = load_bars(**load_kwargs)
    print(f"  Loaded {len(df):,} rows × {df['ticker'].nunique()} tickers", file=sys.stderr)

    print("Building features …", file=sys.stderr)
    df = _build_features(df)

    # Trim warm-up rows
    df = df[df["trade_date"] >= pd.Timestamp(args.start)].copy()

    print(f"Running {args.side} screen with strategies {strategies}, min_score={args.min_score} …",
          file=sys.stderr)

    if args.side == "long":
        result = screen_long(df, strategies, args.min_score)
    else:
        result = screen_short(df, strategies, args.min_score)

    print(f"Result: {len(result):,} rows", file=sys.stderr)
    if len(result) == 0:
        print("(no hits)", file=sys.stderr)

    # Print to stdout
    print(result.to_string(index=False))

    # Save CSV
    if not args.no_csv:
        out_dir = Path(args.out_dir) if args.out_dir else (
            Path(__file__).resolve().parent.parent.parent.parent
            / "data" / "analysis" / "xiaoge"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        today = _date.today().isoformat()
        fname = out_dir / f"screener_{args.side}_{today}.csv"
        result.to_csv(fname, index=False, encoding="utf-8-sig")
        print(f"\nCSV saved: {fname}", file=sys.stderr)


if __name__ == "__main__":
    main()
