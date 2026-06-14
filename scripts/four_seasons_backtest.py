"""Course-aligned backtest for four-seasons classifier.

Entry: first day a ticker enters a tradeable season.
Holding period: VARIABLE — determined by course-defined exit rules only.

Long side (春 / 立夏 / 盛夏 — 直接持股；本 backtest 不含 CB):
  EXIT priority order (first match wins):
    1. warning_signals       — 夏轉秋量價背離 (§八 / ch7-1)
    2. ma20_break (動態):
       - trailing 未活化 (peak_ret < trigger): 1 天即出 (capital protection)
         未獲利的部位無 trailing 安全墊，破月線多半是假突破
       - trailing 已活化 (peak_ret ≥ trigger): 3 天確認 (ch7-1 @04:37
         「跌破月線三天沒有站回」直接持股版)
       (注：CB 的 1 天即停規則 ch3-3 與此無關；CB 不在本 backtest 範圍)
    3. trailing_stop         — ran ≥ +8% from entry, then close ≤ peak*0.94 (@ch10-1 26:18)
    4. season_change         — classifier moved ticker to 秋/冬 ONLY
                               未分類 不退場（分類臨界游移，給持股機會走到盛夏）

Short side (秋):
  EXIT:
    1. new_high   — close > running_max since entry (§三 秋季操作 停損: 創新高)
    2. limit_up   — daily change ≥ +9.5% (§三 秋季操作 停損: 漲停板)
    3. season_change — moved to 春/立夏/盛夏/未分類

Notes:
  - 春多停損課程未量化（「基本面惡化」非價格規則）→ 沿用多單 3 條退場規則.
  - 冬季：「零操作」（§三 冬季操作）→ 不回測.
  - 仍未出場（censored）樣本獨立統計.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

# Allow inline classify when --in is omitted
sys.path.insert(0, str(Path(__file__).parent))
import four_seasons_classify as _classify

from zhuli.db import get_conn
DEFAULT_DB = Path("/Users/howard/.four_seasons/data.sqlite")
DEFAULT_OUT_TRADES = Path("data/analysis/four_seasons/backtest_trades.csv")
DEFAULT_OUT_REPORT = Path("data/analysis/four_seasons/backtest_report.md")

LONG_SEASONS = {"春", "立夏", "盛夏"}
SHORT_SEASONS = {"秋"}
# 多單僅在「明確進入秋/冬」時退場；「未分類」屬於分類臨界游移，給持股機會走到盛夏 / 拿到 trailing / ma20
LONG_EXIT_TO = {"秋", "冬"}
# 短空（秋）退場含「未分類」：秋天空方走完，分類由明確轉模糊代表空方動能消退，可主動回補
SHORT_EXIT_TO = {"春", "立夏", "盛夏", "未分類"}

@dataclass
class BacktestConfig:
    """Tunable backtest thresholds. Defaults = course示範值.

    Course-fixed mechanism (not in config):
      - 多單: state_change exit, ma20_break stop, trailing stop *concept*
      - 短空: state_change, new_high stop, limit_up stop *concepts*
      - 春多不套用價格停損 (§三 春季操作 停損: 基本面非價格)

    All numeric thresholds below are course示範值 (§9.2) — tunable via --config.
    """
    # Long-side exits (@ch10-1 25:57「就看你的取向」)
    trailing_trigger_pct: float = 8.0     # ran ≥ +8% activates trailing
    trailing_giveback_pct: float = 6.0    # peak − 6% → stop
    ma20_break_consecutive_days: int = 3  # ch7-1 @04:37「跌破月線三天沒有站回」直接持股版
    # Short-side exit (course-fixed concept; threshold approximates 台股漲停)
    limit_up_pct: float = 9.5
    # Entry quality gates (§三 進場條件 + ch3-2 @34:00 講師演示)
    shengxia_requires_prior_lixia_days: int = 20  # 推論值
    shengxia_vol_ratio_min: float = 5.0           # @ch3-2 34:15「至少 5 倍」進場篩選
    shengxia_vol_shares_min: float = 1_000_000    # @ch3-2 34:08「至少 1000 張」進場篩選
    autumn_rebound_red_k_pct_min: float = 3.0     # @ch4-1 03:23
    # 立夏進場品質：年線乖離（§九 寫 <30% 示範值；實證 ≤ 8% 才是「剛起漲」剔追高）
    lixia_dev_240_max_pct: float = 8.0
    # 立夏進場品質：主力 20 日累積（§九.1 hard-coded mf>0，強度未明示；實證濾掉隔日沖）
    lixia_mf20_min: float = 0.0  # 預設 0=只要求 >0；可調更嚴
    # 夏轉秋警訊 量價背離 thresholds (§八; @ch7-1; course示範值)
    # 量價背離A: price near all-time peak but volume drying up → top exhaustion
    warn_near_peak_pct: float = 2.0    # within X% of peak = "near peak"
    warn_vol_low_ratio: float = 0.6    # vol_ratio_20 < this = volume drying up
    # 量價背離B: heavy volume but price barely moved → distribution / churning
    warn_vol_high_ratio: float = 3.0   # vol_ratio_20 > this = abnormally heavy vol
    warn_price_stall_pct: float = 1.0  # |daily_chg| < X% despite heavy vol = stall
    # Exit mode: "standard" = 課程全部規則; "trailing_only" = 只保留 trailing_stop
    # （for testing whether 立夏/盛夏 trailing-only 子集的 backtest 結果可以推廣）
    exit_mode: str = "standard"


def load_bt_config(path: Path | None) -> BacktestConfig:
    if path is None:
        return BacktestConfig()
    raw = json.loads(path.read_text())
    return BacktestConfig(**raw)


@dataclass
class Trade:
    ticker: str
    name: str
    season: str
    side: str             # "long" | "short"
    entry_date: pd.Timestamp
    entry_close: float
    exit_date: pd.Timestamp
    exit_close: float
    exit_reason: str
    days_held: int
    return_pct: float
    censored: bool


def warning_signals_triggered(
    row: pd.Series, entry_row: pd.Series, peak_close: float, bt: BacktestConfig
) -> bool:
    """夏轉秋警訊 (§八 / @ch7-1). Fires before ma20_break in priority order.

    Implemented (with available daily data):
      A. 量價背離 — price at all-time high since entry but vol_ratio_20 very low
         → top-out: buyers exhausted, distribution beginning
      B. 量價背離 — abnormally heavy volume but price barely moved (churning)
         → distribution: sellers absorbing every buy

    Not implemented (require cross-ticker or sentiment data):
      - 領頭羊力竭: need sector membership + peer prices
      - 情緒極度樂觀: no retail-sentiment data available
      - 月線兩次跌破: first break already handled by ma20_break exit;
        implementing "two breaks" would require changing exit priority architecture
    """
    vol_ratio = row.get("vol_ratio_20")
    if pd.isna(vol_ratio):
        return False

    close = row["close"]

    # A: near all-time peak since entry but volume drying up
    if close >= peak_close * (1 - bt.warn_near_peak_pct / 100):
        if vol_ratio < bt.warn_vol_low_ratio:
            return True

    # B: heavy distribution volume but price stalled
    prev = row.get("prev_close")
    if not pd.isna(prev) and prev > 0 and vol_ratio > bt.warn_vol_high_ratio:
        daily_chg_pct = abs(close - prev) / prev * 100
        if daily_chg_pct < bt.warn_price_stall_pct:
            return True

    return False


def simulate_long(
    entry_row: pd.Series, forward: pd.DataFrame, name: str, bt: BacktestConfig,
) -> Trade:
    """forward: rows for this ticker AFTER entry_date, sorted by trade_date.

    Iterates each future day, checks exit rules in priority order.
    春多單僅允許 state-change 退場（§三 春季操作：停損是「基本面惡化」非價格規則）.
    """
    entry_close = entry_row["close"]
    peak_close = entry_close
    trailing_only = getattr(bt, "exit_mode", "standard") == "trailing_only"
    # 春多原本「不套用價格停損」(§三 春季 停損=基本面)；trailing_only 模式統一用 trailing.
    apply_price_stops = trailing_only or entry_row["season"] != "春"
    ma20_break_streak = 0  # consecutive days closing below ma20

    for _, r in forward.iterrows():
        peak_close = max(peak_close, r["close"])
        peak_ret = (peak_close - entry_close) / entry_close * 100
        trailing_armed = peak_ret >= bt.trailing_trigger_pct

        if apply_price_stops:
            # standard mode: warning + ma20 break exits
            if not trailing_only:
                if warning_signals_triggered(r, entry_row, peak_close, bt):
                    return _close_long(entry_row, r, name, "warning_signals", censored=False)
                # 動態 ma20 break：未獲利 1 天即出（capital protection）；獲利後 3 天確認（ch7-1 @04:37）
                if pd.notna(r["ma20"]) and r["close"] < r["ma20"]:
                    ma20_break_streak += 1
                    required = bt.ma20_break_consecutive_days if trailing_armed else 1
                    if ma20_break_streak >= required:
                        reason = "ma20_break_3day" if trailing_armed else "ma20_break_protect"
                        return _close_long(entry_row, r, name, reason, censored=False)
                else:
                    ma20_break_streak = 0  # 站回月線，計數歸零
            # trailing stop: 兩種 mode 都認 (trailing_only 模式下是唯一價格 exit)
            if trailing_armed:
                stop_price = peak_close * (1 - bt.trailing_giveback_pct / 100)
                if r["close"] <= stop_price:
                    return _close_long(entry_row, r, name, "trailing_stop", censored=False)
        # season_change exit 只在 standard mode 觸發
        if not trailing_only and r["season"] in LONG_EXIT_TO:
            return _close_long(entry_row, r, name, "season_change", censored=False)

    if forward.empty:
        return _close_long(entry_row, entry_row, name, "censored", censored=True)
    last = forward.iloc[-1]
    return _close_long(entry_row, last, name, "censored", censored=True)


def simulate_short(
    entry_row: pd.Series, forward: pd.DataFrame, name: str, bt: BacktestConfig,
) -> Trade:
    entry_close = entry_row["close"]
    running_max = entry_close

    for _, r in forward.iterrows():
        if r["close"] > running_max:
            return _close_short(entry_row, r, name, "new_high", censored=False)
        if pd.notna(r["prev_close"]) and r["prev_close"] > 0:
            pct_chg = (r["close"] - r["prev_close"]) / r["prev_close"] * 100
            if pct_chg >= bt.limit_up_pct:
                return _close_short(entry_row, r, name, "limit_up", censored=False)
        if r["season"] in SHORT_EXIT_TO:
            return _close_short(entry_row, r, name, "season_change", censored=False)
        running_max = max(running_max, r["close"])

    if forward.empty:
        return _close_short(entry_row, entry_row, name, "censored", censored=True)
    last = forward.iloc[-1]
    return _close_short(entry_row, last, name, "censored", censored=True)


def _close_long(entry_row, exit_row, name, reason, censored) -> Trade:
    ec, xc = entry_row["close"], exit_row["close"]
    return Trade(
        ticker=str(entry_row["ticker"]), name=name, season=entry_row["season"], side="long",
        entry_date=entry_row["trade_date"], entry_close=ec,
        exit_date=exit_row["trade_date"], exit_close=xc, exit_reason=reason,
        days_held=(exit_row["trade_date"] - entry_row["trade_date"]).days,
        return_pct=(xc - ec) / ec * 100, censored=censored,
    )


def _close_short(entry_row, exit_row, name, reason, censored) -> Trade:
    ec, xc = entry_row["close"], exit_row["close"]
    return Trade(
        ticker=str(entry_row["ticker"]), name=name, season=entry_row["season"], side="short",
        entry_date=entry_row["trade_date"], entry_close=ec,
        exit_date=exit_row["trade_date"], exit_close=xc, exit_reason=reason,
        days_held=(exit_row["trade_date"] - entry_row["trade_date"]).days,
        return_pct=(ec - xc) / ec * 100, censored=censored,
    )


def _snapshot(db: Path) -> str:
    tmp = Path(tempfile.gettempdir()) / f"fs_bt_{os.getpid()}.sqlite"
    db = Path(db).resolve()  # follow symlink → real file
    shutil.copy2(db, tmp)
    for ext in ("-wal", "-shm"):
        src = db.with_name(db.name + ext)
        if src.exists():
            shutil.copy2(src, str(tmp) + ext)
    return str(tmp)


def load_panel(conn_path: str) -> pd.DataFrame:
    with get_conn(conn_path, timeout=15) as conn:
        df = pd.read_sql_query(
            "select ticker, trade_date, close, ma20, volume, vol_ratio_20, "
            "dev_ma240_pct, main_force_20d "
            "from standard_daily_bar where is_usable=1",
            conn, parse_dates=["trade_date"],
        )
    df["ticker"] = df["ticker"].astype(str)
    df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    df["prev_close"] = df.groupby("ticker")["close"].shift(1)
    return df


def load_names(conn_path: str) -> dict[str, str]:
    with get_conn(conn_path, timeout=15) as conn:
        df = pd.read_sql_query("select ticker, name from stock_name", conn)
    return dict(zip(df.ticker.astype(str), df.name))


def find_first_entries(classifications: pd.DataFrame) -> pd.DataFrame:
    df = classifications.copy()
    df["ticker"] = df["ticker"].astype(str)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    df["prev_season"] = df.groupby("ticker")["season"].shift(1)
    return df[df["season"] != df["prev_season"]].drop(columns=["prev_season"])


def _had_recent_lixia(
    cls: pd.DataFrame, ticker: str, entry_date: pd.Timestamp, days: int
) -> bool:
    """Did this ticker classify as 立夏 in the past `days` trading days before entry_date?"""
    g = cls[(cls["ticker"] == ticker) & (cls["trade_date"] < entry_date)]
    g = g.sort_values("trade_date").tail(days)
    return (g["season"] == "立夏").any()


def _is_rebound_red_k(panel_row: pd.Series, threshold_pct: float) -> bool:
    """Today close > prev_close and pct change > threshold_pct."""
    pc = panel_row.get("prev_close")
    if pd.isna(pc) or pc is None or pc <= 0:
        return False
    pct = (panel_row["close"] - pc) / pc * 100
    return pct > threshold_pct


def run_backtest(
    classifications: pd.DataFrame, panel: pd.DataFrame, names: dict[str, str],
    bt: BacktestConfig,
) -> list[Trade]:
    # Merge season into panel so we can read season per (ticker, trade_date)
    cls = classifications[["ticker", "trade_date", "season"]].copy()
    cls["ticker"] = cls["ticker"].astype(str)
    cls["trade_date"] = pd.to_datetime(cls["trade_date"])
    panel = panel.merge(cls, on=["ticker", "trade_date"], how="left")
    panel["season"] = panel["season"].fillna("未分類")
    panel_by_ticker = {tkr: g.reset_index(drop=True) for tkr, g in panel.groupby("ticker")}

    entries = find_first_entries(classifications)
    entries = entries[entries["season"].isin(LONG_SEASONS | SHORT_SEASONS)]

    cls_sorted = cls.sort_values(["ticker", "trade_date"]).reset_index(drop=True)

    trades: list[Trade] = []
    for _, e in entries.iterrows():
        tkr = str(e["ticker"])
        if tkr not in panel_by_ticker:
            continue
        g = panel_by_ticker[tkr]
        entry_panel = g[g["trade_date"] == e["trade_date"]]
        if entry_panel.empty:
            continue
        entry_row = entry_panel.iloc[0].copy()
        if not entry_row["close"] or entry_row["close"] <= 0:
            continue
        entry_row["season"] = e["season"]

        # Quality gates (§三 進場條件 + ch3-2 @34:00 講師演示 + 實證調優)
        if e["season"] == "立夏":
            dev = entry_row.get("dev_ma240_pct")
            if pd.isna(dev) or dev is None or dev > bt.lixia_dev_240_max_pct:
                continue
            mf20 = entry_row.get("main_force_20d")
            if pd.isna(mf20) or mf20 is None or mf20 < bt.lixia_mf20_min:
                continue
        if e["season"] == "盛夏":
            if not _had_recent_lixia(cls_sorted, tkr, e["trade_date"],
                                      bt.shengxia_requires_prior_lixia_days):
                continue
            vr = entry_row.get("vol_ratio_20")
            vol = entry_row.get("volume")
            if pd.isna(vr) or vr is None or vr < bt.shengxia_vol_ratio_min:
                continue
            if pd.isna(vol) or vol is None or vol < bt.shengxia_vol_shares_min:
                continue
        if e["season"] == "秋":
            if not _is_rebound_red_k(entry_row, bt.autumn_rebound_red_k_pct_min):
                continue

        forward = g[g["trade_date"] > e["trade_date"]].reset_index(drop=True)
        name = names.get(tkr, "")
        if e["season"] in LONG_SEASONS:
            trades.append(simulate_long(entry_row, forward, name, bt))
        else:
            trades.append(simulate_short(entry_row, forward, name, bt))
    return trades


def trades_to_df(trades: list[Trade]) -> pd.DataFrame:
    return pd.DataFrame([t.__dict__ for t in trades])


def build_report(trades_df: pd.DataFrame) -> str:
    lines = ["# Four-Seasons Course-Aligned Backtest Report", ""]
    if trades_df.empty:
        return "\n".join(lines + ["No trades."])

    closed = trades_df[~trades_df["censored"]]
    censored = trades_df[trades_df["censored"]]

    lines += [
        f"- Total entries: **{len(trades_df)}** (closed: {len(closed)}, censored: {len(censored)})",
        "",
        "## Closed trades — by season",
        "",
        "| 季節 | side | n | win% | median ret% | mean ret% | median 天 |",
        "|---|---|---|---|---|---|---|",
    ]
    for (season, side), g in closed.groupby(["season", "side"]):
        lines.append(
            f"| {season} | {side} | {len(g)} | {(g.return_pct > 0).mean()*100:.1f}% | "
            f"{g.return_pct.median():+.2f}% | {g.return_pct.mean():+.2f}% | "
            f"{g.days_held.median():.0f} |"
        )

    lines += ["", "## Closed trades — by season × exit_reason", "",
              "| 季節 | side | exit_reason | n | win% | median ret% | median 天 |",
              "|---|---|---|---|---|---|---|"]
    for (season, side, reason), g in closed.groupby(["season", "side", "exit_reason"]):
        lines.append(
            f"| {season} | {side} | {reason} | {len(g)} | "
            f"{(g.return_pct > 0).mean()*100:.1f}% | "
            f"{g.return_pct.median():+.2f}% | {g.days_held.median():.0f} |"
        )

    if not censored.empty:
        lines += ["", "## Censored cohort (仍在場上)", "",
                  "| 季節 | side | n | median MTM ret% | median 天 |",
                  "|---|---|---|---|---|"]
        for (season, side), g in censored.groupby(["season", "side"]):
            lines.append(
                f"| {season} | {side} | {len(g)} | "
                f"{g.return_pct.median():+.2f}% | {g.days_held.median():.0f} |"
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--in", dest="inp", type=Path, default=None,
                   help="Pre-computed classification CSV. Omit to run classify inline.")
    p.add_argument("--range", nargs=2, metavar=("START", "END"),
                   help="Date range for inline classify (YYYY-MM-DD). Required when --in is omitted.")
    p.add_argument("--classify-config", type=Path, default=None,
                   help="JSON file with SeasonConfig thresholds for inline classify.")
    p.add_argument("--out-trades", type=Path, default=DEFAULT_OUT_TRADES)
    p.add_argument("--out-report", type=Path, default=DEFAULT_OUT_REPORT)
    p.add_argument("--config", type=Path,
                   help="JSON file with tunable backtest thresholds.")
    p.add_argument("--dump-config", action="store_true",
                   help="Print default BacktestConfig as JSON and exit.")
    p.add_argument("--dump-classify-config", action="store_true",
                   help="Print default SeasonConfig as JSON and exit.")
    p.add_argument("--exit-mode", choices=["standard", "trailing_only"], default="standard",
                   help="standard = course-full exits (default); "
                        "trailing_only = 只認 trailing_stop、忽略 warning/ma20_break/season_change "
                        "(用來驗證 trailing-only 子集 backtest 的可推廣性)")
    args = p.parse_args()

    if args.dump_config:
        print(json.dumps(asdict(BacktestConfig()), indent=2))
        return 0
    if args.dump_classify_config:
        print(json.dumps(asdict(_classify.SeasonConfig()), indent=2))
        return 0

    bt = load_bt_config(args.config)
    bt.exit_mode = args.exit_mode
    print(f"[exit_mode] {bt.exit_mode}")
    conn_path = _snapshot(args.db)

    if args.inp is not None:
        classifications = pd.read_csv(args.inp)
    else:
        if not args.range:
            p.error("--range START END is required when --in is omitted")
        season_cfg = _classify.load_config(args.classify_config)
        print(f"[classify] running inline for {args.range[0]} → {args.range[1]} …")
        # Write to a temp path so classify can satisfy its out_path requirement
        _tmp_csv = Path(tempfile.mktemp(suffix=".csv"))
        classifications = _classify.run(
            db_path=args.db,
            out_path=_tmp_csv,
            date_range=(args.range[0], args.range[1]),
            cfg=season_cfg,
        )
        _tmp_csv.unlink(missing_ok=True)
        print(f"[classify] {len(classifications)} rows, seasons: {classifications['season'].value_counts().to_dict()}")

    panel = load_panel(conn_path)
    names = load_names(conn_path)
    trades = run_backtest(classifications, panel, names, bt)
    df = trades_to_df(trades)

    args.out_trades.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out_trades, index=False)
    report = build_report(df)
    args.out_report.write_text(report)
    print(report)
    print(f"\nTrades CSV: {args.out_trades}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
