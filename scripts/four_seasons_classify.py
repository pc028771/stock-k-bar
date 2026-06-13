"""Four-seasons (春/立夏/盛夏/秋/冬) hard classifier for whole market.

Source of truth: docs/四季投資法/course_principles.md §九 量化參數彙整表.
All thresholds traceable to course timestamps. NO non-course conditions.

Output: per ticker on as_of date — classification + matched conditions.
Bucket "未分類" covers (a) matches multiple seasons (ambiguous) and
(b) matches none (transition / not in clear season — course explicitly
allows this: "有些股票四季不明顯").
"""
from __future__ import annotations

from zhuli.db import get_conn

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

DEFAULT_DB = Path("/Users/howard/.four_seasons/data.sqlite")
DEFAULT_OUT = Path("data/analysis/four_seasons/season_classification.csv")


@dataclass
class SeasonConfig:
    """Tunable threshold values. Defaults = 課程示範值 from §9.2.

    Indicators & direction signs are HARD-CODED in evaluators (§9.1 固定).
    These numbers are demonstrations; teacher explicitly says users may tune.
    Load custom via --config path/to/json.
    """
    # 春 (§9.2)
    spring_bb_width_max: float = 10.0           # @ch2 09:09「小於 8、7 都可以」
    spring_ma20_slope_min: float = -1.0         # @ch2 09:07 範圍可調
    spring_ma20_slope_max: float = 1.0
    spring_div_yield_min: float = 5.0           # @ch2 26:33「建議 4% 以上」
    spring_vol_ratio_max: float = 0.8           # 量縮示範
    spring_pb_max: float = 3.0                  # @ch2-1 01:04

    # 立夏 (§9.2)
    lixia_vol_shares_min: float = 500_000       # >500 張 = 500K 股
    lixia_price_pct_min: float = 4.0
    lixia_ma20_slope_max: float = 0.5
    lixia_bb_upper_slope_min: float = 1.0       # 課程基本 (精準版改 3.0)
    lixia_bb_position_min: float = 90.0         # 位階 >8 → DB scale >90
    lixia_dev_ma240_max: float = 30.0

    # 盛夏 (§9.2) — 狀態定義；進場篩選 (vol_ratio/vol) 屬 BacktestConfig
    shengxia_ma20_slope_min: float = 0.5

    # 秋 (§9.2)
    autumn_ma20_slope_min: float = -1.0
    autumn_ma20_slope_max: float = 0.0
    autumn_dev_ma240_min: float = 30.0

    # 冬 (§9.2)
    winter_ma20_slope_max: float = -0.5         # @ch5-2 00:32「-0.6、-0.7 都可以」
    winter_bb_upper_slope_max: float = -0.5
    winter_bb_lower_slope_max: float = -0.5
    winter_vol_ratio_max: float = 0.8


def load_config(path: Path | None) -> SeasonConfig:
    if path is None:
        return SeasonConfig()
    raw = json.loads(path.read_text())
    return SeasonConfig(**raw)


@dataclass
class ConditionResult:
    """One condition evaluation: matched? + value + threshold expression."""
    name: str
    matched: bool
    value: float | None
    threshold: str


def _eval_spring(row: pd.Series, cfg: SeasonConfig) -> list[ConditionResult]:
    return [
        ConditionResult("帶寬窄", row.bb_width_pct < cfg.spring_bb_width_max,
                        row.bb_width_pct, f"<{cfg.spring_bb_width_max}"),
        ConditionResult("月線走平",
                        cfg.spring_ma20_slope_min <= row.ma20_slope <= cfg.spring_ma20_slope_max,
                        row.ma20_slope, f"[{cfg.spring_ma20_slope_min},{cfg.spring_ma20_slope_max}]"),
        ConditionResult("主力5d>0", row.main_force_5d > 0, row.main_force_5d, ">0"),
        ConditionResult("主力10d>0", row.main_force_10d > 0, row.main_force_10d, ">0"),
        ConditionResult("主力20d>0", row.main_force_20d > 0, row.main_force_20d, ">0"),
        ConditionResult("殖利率高", (row.dividend_yield_pct or 0) > cfg.spring_div_yield_min,
                        row.dividend_yield_pct, f">{cfg.spring_div_yield_min}"),
        ConditionResult("量縮", row.vol_ratio_20 < cfg.spring_vol_ratio_max,
                        row.vol_ratio_20, f"<{cfg.spring_vol_ratio_max}"),
        ConditionResult("PB低", (row.pb_ratio or 99) <= cfg.spring_pb_max,
                        row.pb_ratio, f"≤{cfg.spring_pb_max}"),
    ]


def _eval_lixia(row: pd.Series, cfg: SeasonConfig) -> list[ConditionResult]:
    pct_chg = (row.close / row.prev_close - 1) * 100 if row.prev_close else None
    return [
        ConditionResult("成交量大", row.volume > cfg.lixia_vol_shares_min,
                        row.volume, f">{cfg.lixia_vol_shares_min}"),
        ConditionResult("漲幅大", (pct_chg or 0) > cfg.lixia_price_pct_min,
                        pct_chg, f">{cfg.lixia_price_pct_min}%"),
        ConditionResult("月線剛起漲", row.ma20_slope < cfg.lixia_ma20_slope_max,
                        row.ma20_slope, f"<{cfg.lixia_ma20_slope_max}"),
        ConditionResult("上軌向上", row.bb_upper_slope > cfg.lixia_bb_upper_slope_min,
                        row.bb_upper_slope, f">{cfg.lixia_bb_upper_slope_min}"),
        ConditionResult("位階偏上", row.bb_position > cfg.lixia_bb_position_min,
                        row.bb_position, f">{cfg.lixia_bb_position_min}"),
        ConditionResult("乖離未過大", row.dev_ma240_pct < cfg.lixia_dev_ma240_max,
                        row.dev_ma240_pct, f"<{cfg.lixia_dev_ma240_max}%"),
        ConditionResult("主力1d>0", row.main_force_1d > 0, row.main_force_1d, ">0"),
        ConditionResult("主力5d>0", row.main_force_5d > 0, row.main_force_5d, ">0"),
        ConditionResult("主力10d>0", row.main_force_10d > 0, row.main_force_10d, ">0"),
        ConditionResult("主力20d>0", row.main_force_20d > 0, row.main_force_20d, ">0"),
    ]


def _eval_shengxia(row: pd.Series, cfg: SeasonConfig) -> list[ConditionResult]:
    return [
        ConditionResult("月線上升", row.ma20_slope > cfg.shengxia_ma20_slope_min,
                        row.ma20_slope, f">{cfg.shengxia_ma20_slope_min}"),
        ConditionResult("主力5d>0", row.main_force_5d > 0, row.main_force_5d, ">0"),
        ConditionResult("主力10d>0", row.main_force_10d > 0, row.main_force_10d, ">0"),
        ConditionResult("主力20d>0", row.main_force_20d > 0, row.main_force_20d, ">0"),
    ]


def _eval_autumn(row: pd.Series, cfg: SeasonConfig) -> list[ConditionResult]:
    return [
        ConditionResult("月線剛走弱",
                        cfg.autumn_ma20_slope_min <= row.ma20_slope <= cfg.autumn_ma20_slope_max,
                        row.ma20_slope, f"[{cfg.autumn_ma20_slope_min},{cfg.autumn_ma20_slope_max}]"),
        ConditionResult("乖離過大", row.dev_ma240_pct > cfg.autumn_dev_ma240_min,
                        row.dev_ma240_pct, f">{cfg.autumn_dev_ma240_min}%"),
        ConditionResult("主力5d<0", row.main_force_5d < 0, row.main_force_5d, "<0"),
        ConditionResult("主力10d<0", row.main_force_10d < 0, row.main_force_10d, "<0"),
        ConditionResult("主力20d<0", row.main_force_20d < 0, row.main_force_20d, "<0"),
    ]


def _eval_winter(row: pd.Series, cfg: SeasonConfig) -> list[ConditionResult]:
    return [
        ConditionResult("月線下降", row.ma20_slope < cfg.winter_ma20_slope_max,
                        row.ma20_slope, f"<{cfg.winter_ma20_slope_max}"),
        ConditionResult("上軌下彎", row.bb_upper_slope < cfg.winter_bb_upper_slope_max,
                        row.bb_upper_slope, f"<{cfg.winter_bb_upper_slope_max}"),
        ConditionResult("下軌下彎",
                        row.bb_lower_slope is not None and row.bb_lower_slope < cfg.winter_bb_lower_slope_max,
                        row.bb_lower_slope, f"<{cfg.winter_bb_lower_slope_max}"),
        ConditionResult("主力5d<0", row.main_force_5d < 0, row.main_force_5d, "<0"),
        ConditionResult("主力10d<0", row.main_force_10d < 0, row.main_force_10d, "<0"),
        ConditionResult("主力20d<0", row.main_force_20d < 0, row.main_force_20d, "<0"),
        ConditionResult("量縮", row.vol_ratio_20 < cfg.winter_vol_ratio_max,
                        row.vol_ratio_20, f"<{cfg.winter_vol_ratio_max}"),
    ]


SEASON_EVALUATORS = {
    "春": _eval_spring,
    "立夏": _eval_lixia,
    "盛夏": _eval_shengxia,
    "秋": _eval_autumn,
    "冬": _eval_winter,
}


def classify(matches: dict[str, bool]) -> str:
    """Tie-break logic: given which seasons fully matched, return final label.

    TODO (Howard): decide policy when a row matches 0 or 2+ seasons.

    Args:
        matches: e.g. {"春": False, "立夏": True, "盛夏": False, "秋": False, "冬": False}

    Returns:
        One of: "春", "立夏", "盛夏", "秋", "冬", "未分類"

    Design choices to consider:
      Strict (recommended baseline):
          1 match → that season; 0 or 2+ → "未分類"
      Spring/Lixia overlap policy:
          If 春 + 立夏 both match — they describe different phases of the same
          uptrend transition. Course never says how to disambiguate.
      Autumn/Winter overlap policy:
          If 秋 + 冬 both match — ma20_slope ∈ [-1, -0.5] is shared. Possibly
          prefer 冬 (more advanced down phase) since 冬 also requires both
          bb_upper_slope<-0.5 AND bb_lower_slope<-0.5 (stricter band collapse).
    """
    hits = [s for s, m in matches.items() if m]
    return hits[0] if len(hits) == 1 else "未分類"


def evaluate_row(row: pd.Series, cfg: SeasonConfig) -> dict:
    """Run all 5 season evaluators on one row, return classification + details."""
    season_results = {
        season: evaluator(row, cfg) for season, evaluator in SEASON_EVALUATORS.items()
    }
    matches = {season: all(c.matched for c in results)
               for season, results in season_results.items()}
    label = classify(matches)
    return {
        "ticker": row.ticker,
        "trade_date": row.trade_date,
        "close": row.close,
        "season": label,
        **{f"match_{s}": m for s, m in matches.items()},
        **{f"detail_{s}": "; ".join(
            f"{c.name}={'✓' if c.matched else '✗'}({c.value:.3g})" if c.value is not None
            else f"{c.name}={'✓' if c.matched else '✗'}(NA)"
            for c in season_results[s]
        ) for s in SEASON_EVALUATORS},
    }


SLOPE_LOOKBACK_DAYS = 5  # DB convention: slope = (v_today - v_5d) / v_5d * 100
LOAD_DAYS = SLOPE_LOOKBACK_DAYS + 2  # +1 for prev_close, +1 buffer


def _compute_bb_lower_slope(group: pd.DataFrame) -> float | None:
    """Reverse-engineered DB formula: (latest - lookback_ago) / lookback_ago * 100."""
    g = group.sort_values("trade_date").reset_index(drop=True)
    if len(g) < SLOPE_LOOKBACK_DAYS + 1:
        return None
    latest = g["bb_lower"].iloc[-1]
    past = g["bb_lower"].iloc[-(SLOPE_LOOKBACK_DAYS + 1)]
    if past is None or pd.isna(past) or past == 0 or pd.isna(latest):
        return None
    return (latest - past) / past * 100


def _snapshot_db(db_path: Path) -> str:
    try:
        tmp = Path(tempfile.gettempdir()) / f"fs_classify_snapshot_{os.getpid()}.sqlite"
        shutil.copy2(db_path, tmp)
        return str(tmp)
    except Exception:
        return str(db_path)


def _load_stock_names(conn_path: str) -> dict[str, str]:
    with get_conn(conn_path, timeout=15) as conn:
        df = pd.read_sql_query("select ticker, name from stock_name", conn)
    return dict(zip(df.ticker.astype(str), df.name))


def _list_trade_dates(conn_path: str, start: str, end: str) -> list[pd.Timestamp]:
    with get_conn(conn_path, timeout=15) as conn:
        df = pd.read_sql_query(
            "select distinct trade_date from standard_daily_bar "
            "where is_usable=1 and trade_date between ? and ? order by trade_date",
            conn, params=(start, end), parse_dates=["trade_date"],
        )
    return df["trade_date"].tolist()


def load_bars_as_of(
    conn_path: str,
    as_of: pd.Timestamp | None,
    tickers: list[str] | None = None,
) -> pd.DataFrame:
    """Load LOAD_DAYS rows per ticker ending at `as_of` (None = market latest).

    Returns only the as_of row, with prev_close + recomputed bb_lower_slope.
    """
    where_ticker = ""
    params: tuple = ()
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        where_ticker = f" and ticker in ({placeholders})"
        params = tuple(tickers)

    where_date = ""
    if as_of is not None:
        where_date = " and trade_date <= ?"
        params = params + (as_of.strftime("%Y-%m-%d"),)

    query = f"""
        with ranked as (
            select *,
                   row_number() over (partition by ticker order by trade_date desc) as rn
            from standard_daily_bar
            where is_usable=1
              and ma20_slope is not null
              and bb_width_pct is not null
              and bb_position is not null
              and bb_upper_slope is not null
              and dev_ma240_pct is not null
              and vol_ratio_20 is not null
              and main_force_1d is not null
              and main_force_5d is not null
              and main_force_10d is not null
              and main_force_20d is not null
              {where_ticker}
              {where_date}
        )
        select * from ranked where rn <= ?
    """
    params = params + (LOAD_DAYS,)
    with get_conn(conn_path, timeout=15) as conn:
        df = pd.read_sql_query(query, conn, params=params, parse_dates=["trade_date"])

    if df.empty:
        return df

    df = df.sort_values(["ticker", "trade_date"])
    df["prev_close"] = df.groupby("ticker")["close"].shift(1)
    recomputed = df.groupby("ticker", group_keys=False).apply(
        lambda g: pd.Series({"bb_lower_slope_recomputed": _compute_bb_lower_slope(g)})
    )
    latest = df[df["rn"] == 1].drop(columns=["rn"]).merge(
        recomputed, left_on="ticker", right_index=True, how="left"
    )
    latest["bb_lower_slope"] = latest["bb_lower_slope_recomputed"]
    return latest.drop(columns=["bb_lower_slope_recomputed"])


def classify_one_date(
    conn_path: str,
    as_of: pd.Timestamp | None,
    tickers: list[str] | None,
    names: dict[str, str],
    cfg: SeasonConfig,
) -> pd.DataFrame:
    df = load_bars_as_of(conn_path, as_of, tickers)
    if df.empty:
        return pd.DataFrame()
    out = pd.DataFrame([evaluate_row(r, cfg) for _, r in df.iterrows()])
    out.insert(1, "name", out["ticker"].astype(str).map(names).fillna(""))
    return out


def run(
    db_path: Path,
    out_path: Path,
    tickers: list[str] | None = None,
    as_of: pd.Timestamp | None = None,
    date_range: tuple[str, str] | None = None,
    season_filter: str | None = None,
    cfg: SeasonConfig | None = None,
) -> pd.DataFrame:
    cfg = cfg or SeasonConfig()
    conn_path = _snapshot_db(db_path)
    names = _load_stock_names(conn_path)

    if date_range is not None:
        dates = _list_trade_dates(conn_path, *date_range)
        frames = [classify_one_date(conn_path, d, tickers, names, cfg) for d in dates]
        out = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    else:
        out = classify_one_date(conn_path, as_of, tickers, names, cfg)

    if out.empty:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(out_path, index=False)
        return out

    if season_filter:
        out = out[out["season"] == season_filter].copy()

    out = out.sort_values(["trade_date", "season", "ticker"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--tickers", nargs="*", help="Limit to these tickers.")
    p.add_argument("--date", help="Single trade date YYYY-MM-DD (default: latest).")
    p.add_argument("--range", nargs=2, metavar=("START", "END"),
                   help="Iterate every trade date in [START, END] (YYYY-MM-DD).")
    p.add_argument("--season", choices=list(SEASON_EVALUATORS) + ["未分類"],
                   help="Filter output to only this season.")
    p.add_argument("--config", type=Path,
                   help="JSON file with tunable thresholds (overrides §9.2 defaults).")
    p.add_argument("--dump-config", action="store_true",
                   help="Print default config as JSON and exit.")
    args = p.parse_args()

    if args.dump_config:
        print(json.dumps(asdict(SeasonConfig()), indent=2))
        return 0

    cfg = load_config(args.config)
    as_of = pd.Timestamp(args.date) if args.date else None
    date_range = tuple(args.range) if args.range else None
    out = run(args.db, args.out, args.tickers, as_of, date_range, args.season, cfg)
    print(f"Wrote {len(out)} rows → {args.out}")
    print(out["season"].value_counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
