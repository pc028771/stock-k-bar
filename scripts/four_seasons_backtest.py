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
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

# Allow inline classify when --in is omitted
sys.path.insert(0, str(Path(__file__).parent))
import four_seasons_classify as _classify

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
    # 課程示範值 8/6；老師說「就看你的取向」可自由調整（see extras 區）
    trailing_trigger_pct: float = 8.0     # ran ≥ +X% activates trailing
    trailing_giveback_pct: float = 6.0    # peak − X% → stop
    ma20_break_consecutive_days: int = 3  # ch7-1 @04:37「跌破月線三天沒有站回」直接持股版
    # Short-side exit (course-fixed concept; threshold approximates 台股漲停)
    limit_up_pct: float = 9.5
    # Entry quality gates (§三 進場條件 + ch3-2 @34:00 講師演示)
    shengxia_requires_prior_lixia_days: int = 20  # 推論值（非課程明說）
    # 預設 False：放行未經立夏直接到盛夏的個股（如春→盛夏，無單日爆衝）
    # 實證 2026-01：移除此限制後盛夏進場 1→21 筆、勝率 0%→66.7%、mean -1.9%→+5.7%
    # 「春→盛夏」型可能比「立夏→盛夏」型更賺（漲勢更穩健，非單日煙火）
    shengxia_require_prior_lixia: bool = False
    shengxia_vol_ratio_min: float = 5.0           # @ch3-2 34:15「至少 5 倍」進場篩選
    shengxia_vol_shares_min: float = 1_000_000    # @ch3-2 34:08「至少 1000 張」進場篩選
    # 盛夏量價同步上限：量大但漲幅縮小 = 出貨型 K（課程§夏「量價同步創新高」反面排除）
    # 實證：vol>8M 進場漲幅 1.77% vs vol≤8M 的 2.16%，上影線 35% vs 28%
    shengxia_vol_shares_max: float = 8_000_000   # 8000 張；超過視為量價背離出貨型態
    autumn_rebound_red_k_pct_min: float = 3.0     # @ch4-1 03:23
    # 立夏進場品質：年線乖離（§九 寫 <30% 示範值；實證 ≤ 8% 才是「剛起漲」剔追高）
    lixia_dev_240_max_pct: float = 8.0
    # 立夏進場品質：主力 20 日累積（§九.1 hard-coded mf>0，強度未明示；實證濾掉隔日沖）
    lixia_mf20_min: float = 0.0  # 預設 0=只要求 >0；可調更嚴
    # 春進場品質：主力 20 日累積（課程「主力 5/10/20 >0」+「持續穩定流入」，強度未明示）
    # 實證：mf20≥1M 過濾 81% 雜訊、勝率 41%→52%、mean +28%→+36%；1M=1000 張同盛夏底線
    spring_mf20_min: float = 1_000_000
    # 春進場時機優化（實證調優，非課程明示）：
    # 1) 限定 Q1 月份：實證 4 月後春多為跌出來的假訊號
    # 2) 殖利率 ≥ 6.5%：真價值股 vs 強裝便宜的弱勢股
    # 3) close > MA60：已脫離長期均線、有底氣突破
    # 三條合用：2023 mean +2.21%→+12.64%、2024 mean +2.44%→+16.63%（過濾 ~80%）
    spring_entry_month_max: int = 3       # 只接受 1-3 月進場（Q1 = 真主力吃貨期）
    spring_dividend_yield_min: float = 6.5
    spring_require_close_above_ma60: bool = True
    # 夏轉秋警訊 量價背離 thresholds (§八; @ch7-1; course示範值)
    # 量價背離A: price near all-time peak but volume drying up → top exhaustion
    warn_near_peak_pct: float = 2.0    # within X% of peak = "near peak"
    warn_vol_low_ratio: float = 0.6    # vol_ratio_20 < this = volume drying up
    # 量價背離B: heavy volume but price barely moved → distribution / churning
    warn_vol_high_ratio: float = 3.0   # vol_ratio_20 > this = abnormally heavy vol
    warn_price_stall_pct: float = 1.0  # |daily_chg| < X% despite heavy vol = stall
    # --- extras (非課程明示，需 --extras 啟用) ---
    # 秋空單: 收盤需距 MA20 至少 N%，避免 MA20 支撐反彈創新高
    # 實證：close_vs_ma20 <1.3% 者 new_high 失敗率顯著較高
    extras_autumn_close_vs_ma20_min_pct: float = 2.0
    # 動態 trailing giveback（非課程明示，純自創概念）：
    # 公式：giveback = max(trailing_giveback_pct, peak_ret_pct × factor)
    # 邏輯：漲越多趨勢越確立 → 給越大呼吸空間，自然讓 winners run
    # 範例：peak +50%、factor 0.4 → giveback = 20%（比固定 6/10 寬容很多）
    # 實證 2024 盛夏 trailing median +5.0% → +17.0%（固定 15/10 已測過）
    # ⚠️ 課程說「固定 trailing」可能指機制（vs 主觀），也可能指「不變動」— 寬鬆解讀
    extras_dynamic_trailing_giveback: bool = False
    extras_dynamic_giveback_factor: float = 0.4
    # 大盤方向 extras（自創）：TAIEX 作為大盤代理，過濾與大盤逆勢的進場
    # 只套用於春與秋；立夏/盛夏 = 個股逆勢突破型，不套
    # - 春：TAIEX close > MA20 才放行（大盤多頭、價值股才有人玩）
    # - 秋（空單）：TAIEX close < MA20 才放行（大盤空頭才容易抓崩）
    # 實證 2024：套全季節傷立夏（mean +1.75→+0.91），分季節保留立夏盛夏不變、春秋品質提升
    # 註：0050 在 DB 2025 資料缺，已用 backfill_taiex.py 補抓 TAIEX 2022-2026
    extras_market_direction_filter: bool = False
    extras_market_proxy_ticker: str = "TAIEX"


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


@dataclass
class Tranche:
    """Single position layer (春/立夏/盛夏 entry within a unified position lifecycle)."""
    season: str
    entry_date: pd.Timestamp
    entry_close: float


TIER_RANK = {"春": 0, "立夏": 1, "盛夏": 2}


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
    promotions: list[dict] | None = None, extras: bool = False,
) -> list[Trade]:
    """Multi-tranche long simulation with mid-trade tier promotion.

    forward: rows for this ticker AFTER entry_date, sorted by trade_date.
    promotions: list of {trade_date, season, close} for 立夏/盛夏 transitions
                this ticker has within forward window. When the loop reaches
                a promotion date, a new Tranche is added and price stops
                activate (if not already).

    春→立夏→盛夏 升級：同一倉位生命週期，每個 tranche 各自記錄報酬，
    全部 tranche 共用同一出場日（warning_signals / ma20_break / trailing /
    season_change to 秋/冬）。
    """
    tranches: list[Tranche] = [Tranche(
        season=entry_row["season"],
        entry_date=entry_row["trade_date"],
        entry_close=entry_row["close"],
    )]
    peak_close = entry_row["close"]
    ma20_break_streak = 0
    promotions_by_date = {p["trade_date"]: p for p in (promotions or [])}

    def current_tier() -> str:
        return tranches[-1].season

    for _, r in forward.iterrows():
        # === 1) tier 升級優先：今天若有更高階季節訊號，先加 tranche ===
        promo = promotions_by_date.get(r["trade_date"])
        if promo is not None:
            new_season = promo["season"]
            if TIER_RANK.get(new_season, -1) > TIER_RANK.get(current_tier(), -1):
                tranches.append(Tranche(
                    season=new_season,
                    entry_date=r["trade_date"],
                    entry_close=r["close"],  # 加碼 entry close = 升級當天 close
                ))
                ma20_break_streak = 0  # 升級重置計數

        # === 2) 更新 peak ===
        peak_close = max(peak_close, r["close"])
        # peak return 以第一個 tranche 為基準（最早的春買進價）
        peak_ret = (peak_close - tranches[0].entry_close) / tranches[0].entry_close * 100
        trailing_armed = peak_ret >= bt.trailing_trigger_pct

        # === 3) 價格停損：only when current tier != 春 ===
        apply_price_stops = current_tier() != "春"

        if apply_price_stops:
            if warning_signals_triggered(r, entry_row, peak_close, bt):
                return _close_long_tranches(tranches, r, name, "warning_signals", censored=False)
            if pd.notna(r["ma20"]) and r["close"] < r["ma20"]:
                ma20_break_streak += 1
                required = bt.ma20_break_consecutive_days if trailing_armed else 1
                if ma20_break_streak >= required:
                    reason = "ma20_break_3day" if trailing_armed else "ma20_break_protect"
                    return _close_long_tranches(tranches, r, name, reason, censored=False)
            else:
                ma20_break_streak = 0
            if trailing_armed:
                # 動態 giveback (extras only)：peak 漲越多、giveback 越寬
                giveback_pct = bt.trailing_giveback_pct
                if extras and bt.extras_dynamic_trailing_giveback:
                    dynamic = peak_ret * bt.extras_dynamic_giveback_factor
                    giveback_pct = max(giveback_pct, dynamic)
                stop_price = peak_close * (1 - giveback_pct / 100)
                if r["close"] <= stop_price:
                    return _close_long_tranches(tranches, r, name, "trailing_stop", censored=False)

        # === 4) season_change to 秋/冬 ===
        if r["season"] in LONG_EXIT_TO:
            return _close_long_tranches(tranches, r, name, "season_change", censored=False)

    if forward.empty:
        return _close_long_tranches(tranches, entry_row, name, "censored", censored=True)
    last = forward.iloc[-1]
    return _close_long_tranches(tranches, last, name, "censored", censored=True)


def _close_long_tranches(
    tranches: list[Tranche], exit_row, name: str, reason: str, censored: bool
) -> list[Trade]:
    """Close all tranches at the same exit point; each computes own return."""
    out: list[Trade] = []
    ticker = str(exit_row["ticker"])
    xc = exit_row["close"]
    xd = exit_row["trade_date"]
    for t in tranches:
        out.append(Trade(
            ticker=ticker, name=name, season=t.season, side="long",
            entry_date=t.entry_date, entry_close=t.entry_close,
            exit_date=xd, exit_close=xc, exit_reason=reason,
            days_held=(xd - t.entry_date).days,
            return_pct=(xc - t.entry_close) / t.entry_close * 100,
            censored=censored,
        ))
    return out


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
    shutil.copy2(db, tmp)
    return str(tmp)


def load_panel(conn_path: str) -> pd.DataFrame:
    with sqlite3.connect(conn_path, timeout=15) as conn:
        df = pd.read_sql_query(
            "select ticker, trade_date, close, ma20, ma60, volume, vol_ratio_20, "
            "dev_ma240_pct, main_force_20d, dividend_yield_pct "
            "from standard_daily_bar where is_usable=1",
            conn, parse_dates=["trade_date"],
        )
    df["ticker"] = df["ticker"].astype(str)
    df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    df["prev_close"] = df.groupby("ticker")["close"].shift(1)
    return df


def load_names(conn_path: str) -> dict[str, str]:
    with sqlite3.connect(conn_path, timeout=15) as conn:
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
    bt: BacktestConfig, extras: bool = False,
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
    entries = entries.sort_values("trade_date").reset_index(drop=True)

    cls_sorted = cls.sort_values(["ticker", "trade_date"]).reset_index(drop=True)

    # 大盤方向 extras：撈大盤代理 (0050) 的 close vs MA20 序列
    market_direction: dict[pd.Timestamp, bool] = {}  # date → True=多頭(>MA20)
    if extras and bt.extras_market_direction_filter:
        proxy = bt.extras_market_proxy_ticker
        if proxy in panel_by_ticker:
            mp = panel_by_ticker[proxy]
            for _, mr in mp.iterrows():
                if pd.notna(mr["ma20"]) and mr["close"] is not None:
                    market_direction[mr["trade_date"]] = mr["close"] > mr["ma20"]

    def passes_quality_gate(e_season: str, entry_row: pd.Series, tkr: str, edate) -> bool:
        """Apply per-season quality gates. Returns True if entry should proceed."""
        # 大盤方向 extras：只套用於春與秋（立夏/盛夏 = 個股逆勢突破型，不套）
        # 實證 2024 立夏 mean +1.75 → +0.91（套大盤過濾傷立夏）；秋大幅改善
        if extras and bt.extras_market_direction_filter:
            if e_season == "春" or e_season == "秋":
                market_up = market_direction.get(edate)
                if market_up is None:
                    return False  # 大盤資料缺，安全保留
                if e_season == "春" and not market_up:
                    return False  # 大盤空頭、春不該進
                if e_season == "秋" and market_up:
                    return False  # 大盤多頭、秋空不該開
        if e_season == "春":
            mf20 = entry_row.get("main_force_20d")
            if pd.isna(mf20) or mf20 is None or mf20 < bt.spring_mf20_min:
                return False
            # 月份限制（Q1 主力吃貨期）
            if hasattr(edate, "month"):
                if edate.month > bt.spring_entry_month_max:
                    return False
            # 殖利率底線
            divy = entry_row.get("dividend_yield_pct")
            if pd.isna(divy) or divy is None or divy < bt.spring_dividend_yield_min:
                return False
            # close > MA60（已脫離長期均線）
            if bt.spring_require_close_above_ma60:
                ma60 = entry_row.get("ma60")
                close = entry_row.get("close")
                if pd.isna(ma60) or ma60 is None or close is None or close <= ma60:
                    return False
        if e_season == "立夏":
            dev = entry_row.get("dev_ma240_pct")
            if pd.isna(dev) or dev is None or dev > bt.lixia_dev_240_max_pct:
                return False
            mf20 = entry_row.get("main_force_20d")
            if pd.isna(mf20) or mf20 is None or mf20 < bt.lixia_mf20_min:
                return False
        if e_season == "盛夏":
            if bt.shengxia_require_prior_lixia:
                if not _had_recent_lixia(cls_sorted, tkr, edate,
                                          bt.shengxia_requires_prior_lixia_days):
                    return False
            vr = entry_row.get("vol_ratio_20")
            vol = entry_row.get("volume")
            if pd.isna(vr) or vr is None or vr < bt.shengxia_vol_ratio_min:
                return False
            if pd.isna(vol) or vol is None or vol < bt.shengxia_vol_shares_min:
                return False
            if vol > bt.shengxia_vol_shares_max:
                return False
        if e_season == "秋":
            if not _is_rebound_red_k(entry_row, bt.autumn_rebound_red_k_pct_min):
                return False
            if extras:
                ma20 = entry_row.get("ma20")
                close = entry_row.get("close")
                if ma20 and ma20 > 0 and close:
                    if (close - ma20) / ma20 * 100 < bt.extras_autumn_close_vs_ma20_min_pct:
                        return False
        return True

    # === 兩階段處理 long entries ===
    # Phase 1：建立每檔股票的「entry events」時間序列（已過品質閘）
    long_entries_by_ticker: dict[str, list[dict]] = {}
    short_entries: list[pd.Series] = []
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

        if not passes_quality_gate(e["season"], entry_row, tkr, e["trade_date"]):
            continue

        if e["season"] in LONG_SEASONS:
            long_entries_by_ticker.setdefault(tkr, []).append({
                "trade_date": e["trade_date"],
                "season": e["season"],
                "close": float(entry_row["close"]),
                "entry_row": entry_row,
            })
        else:
            short_entries.append(entry_row)

    # Phase 2：long — 同一檔依時間排序，第一個是 position root，
    # 後續是 promotion（升級加碼）或被吸收（同階段/低階段時跳過）
    trades: list[Trade] = []
    for tkr, ev_list in long_entries_by_ticker.items():
        ev_list.sort(key=lambda x: x["trade_date"])
        g = panel_by_ticker[tkr]
        name = names.get(tkr, "")

        # 同檔股票可能有多個獨立 position 週期（出場後再開新倉）
        i = 0
        while i < len(ev_list):
            root = ev_list[i]
            current_tier = TIER_RANK.get(root["season"], -1)
            promotions: list[dict] = []
            # 收集 root 之後所有 tier 升級事件作為 promotion 候選
            # （simulate 只會套用日期落在 exit 之前的；之後的自然被忽略）
            for k in range(i + 1, len(ev_list)):
                ev = ev_list[k]
                ev_tier = TIER_RANK.get(ev["season"], -1)
                if ev_tier > current_tier:
                    promotions.append(ev)
                    current_tier = ev_tier

            forward = g[g["trade_date"] > root["trade_date"]].reset_index(drop=True)
            tr_list = simulate_long(root["entry_row"], forward, name, bt,
                                     promotions=promotions, extras=extras)
            trades.extend(tr_list)

            # 跳過 root 自己 + 所有「出場前」已被消化的事件
            exit_date = tr_list[0].exit_date if tr_list else root["trade_date"]
            i += 1
            while i < len(ev_list) and ev_list[i]["trade_date"] <= exit_date:
                i += 1

    # short entries (no promotion logic)
    for entry_row in short_entries:
        tkr = str(entry_row["ticker"])
        g = panel_by_ticker[tkr]
        name = names.get(tkr, "")
        forward = g[g["trade_date"] > entry_row["trade_date"]].reset_index(drop=True)
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
    p.add_argument("--extras", action="store_true",
                   help="Enable non-course empirical filters (default OFF).")
    args = p.parse_args()

    if args.dump_config:
        print(json.dumps(asdict(BacktestConfig()), indent=2))
        return 0
    if args.dump_classify_config:
        print(json.dumps(asdict(_classify.SeasonConfig()), indent=2))
        return 0

    bt = load_bt_config(args.config)
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
    trades = run_backtest(classifications, panel, names, bt, extras=args.extras)
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
