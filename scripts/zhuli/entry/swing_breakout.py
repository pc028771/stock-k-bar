"""A 大波段選股策略 entry signal — 主力大 Ch3-1, Ch3-2.

Course source: 主力大全方位操盤教戰守則 (尼克)
  - strategy-indicators.md §A 大波段選股策略（Swing Breakout）
  - course_principles.md §7 大波段選股 SOP

Logic（來源 Ch3-1 / Ch3-2 字幕 + 投影片）:

    三面分析必要：族群面 + 籌碼面 + 技術面

    對每個 (ticker, date)：
    1. 籌碼面（必要，擇一）：
       - 外資或投信淨買超 ≥ 當日成交量 × institutional_volume_ratio（預設 1/3）
       - 或  外資或投信淨買超 ≥ institutional_volume_absolute（預設 2 萬張）
       Source: strategy-indicators.md §A — 「外資（或投信）買超 ≥ 1/3 當日成交量，或 ≥ 兩萬張」

    2. 技術面（必要）：
       - ma20_slope > 0（20MA 上彎）
       - ma60_slope > 0（60MA 上彎）
       Source: strategy-indicators.md §A — 「20ma 與 60ma 皆呈現上彎」

    3. 族群面（必要，由 require_sector_density 控制）：
       - 同產業當日籌碼面成立的標的數量 ≥ sector_density_min_count（預設 3）
       Source: strategy-indicators.md §A — 「同產業 ≥ 3 檔出現在買超前列」

    4. 理想距離條件（預設非必要，由 enforce_dist_to_ma20 控制）：
       - 當前股價距 20MA ≤ max_dist_to_ma20_pct（預設 5%）
       Source: strategy-indicators.md §A — 「理想：當前股價離 20MA 在 5% 以內」

    5. 加分：封閉空方缺口（close > prev gap high）
       Source: strategy-indicators.md §A — 「加分：同時封閉空方缺口」

    進場提示（課程規則，不在 scanner 判斷，只於 entry_note 標記）：
       「籌碼大買當日不立即進場，等次日或後續技術面確認。」
       Source: strategy-indicators.md §A — 「籌碼大買後不立即進場，等次日或後續技術面確認」

Output columns:
    ticker              — 股票代號
    name                — 股票名稱
    signal_date         — 訊號日期
    industry            — 產業分類
    foreign_net         — 外資淨買超（張）
    sitc_net            — 投信淨買超（張）
    inst_net            — max(foreign_net, sitc_net)（取主力那側）
    vol_ratio           — inst_net / volume（比例）
    close               — 當日收盤
    ma20                — 20日均線
    ma60                — 60日均線
    ma20_slope          — 20MA 斜率（> 0 = 上彎）
    ma60_slope          — 60MA 斜率（> 0 = 上彎）
    dist_to_ma20_pct    — (close - ma20) / ma20 （正 = 在月線上方，負 = 在月線下方）
    sector_density      — 同產業當日籌碼面成立的標的數量
    sector_peers        — 同產業同日籌碼面成立的其他標的（逗號分隔）
    gap_closed          — 是否封閉空方缺口（加分）
    stop_loss           — 停損參考（= ma20，收盤跌破月線）
    score               — 綜合評分（族群密度×2 + 籌碼絕對門檻 + 距月線理想）
    entry_note          — 進場提示文字
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

# Allow running directly or as submodule
_SCRIPTS_DIR = Path(__file__).parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from zhuli.db import get_conn
from zhuli.config import SwingBreakoutConfig


# ── 資料讀取 ───────────────────────────────────────────────────────────────────

def load_institutional_full(db_path: Path) -> pd.DataFrame:
    """從 DB 讀取 institutional_investors 表（含外資 + 投信欄位）。

    Returns DataFrame with columns:
        ticker, trade_date (datetime64[ns]),
        sitc_buy, sitc_sell, sitc_net,
        foreign_buy, foreign_sell, foreign_net.
    若表格不存在或缺少 foreign_* 欄位，回傳空 DataFrame。
    """
    try:
        tmp = Path(tempfile.gettempdir()) / f"inst_swing_{os.getpid()}.sqlite"
        shutil.copy2(db_path, tmp)
        conn_path = str(tmp)
    except Exception:
        conn_path = str(db_path)

    try:
        with get_conn(conn_path, timeout=15) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='institutional_investors'"
            )
            if cur.fetchone() is None:
                return pd.DataFrame()

            # 確認 foreign_* 欄位存在
            existing_cols = {c[1] for c in conn.execute("PRAGMA table_info(institutional_investors)").fetchall()}
            has_foreign = "foreign_net" in existing_cols

            if has_foreign:
                df = pd.read_sql_query(
                    """SELECT ticker, trade_date,
                              sitc_buy, sitc_sell, sitc_net,
                              foreign_buy, foreign_sell, foreign_net
                         FROM institutional_investors""",
                    conn,
                    parse_dates=["trade_date"],
                )
            else:
                df = pd.read_sql_query(
                    "SELECT ticker, trade_date, sitc_buy, sitc_sell, sitc_net FROM institutional_investors",
                    conn,
                    parse_dates=["trade_date"],
                )
                df["foreign_buy"] = 0.0
                df["foreign_sell"] = 0.0
                df["foreign_net"] = 0.0

        df["trade_date"] = df["trade_date"].astype("datetime64[ns]")
        return df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("load_institutional_full failed: %s", exc)
        return pd.DataFrame()


def load_stock_info(db_path: Path) -> pd.DataFrame:
    """從 DB 讀取 stock_info 表（ticker → industry_category, stock_name）。

    若表不存在，回傳空 DataFrame。
    """
    try:
        tmp = Path(tempfile.gettempdir()) / f"stock_info_{os.getpid()}.sqlite"
        shutil.copy2(db_path, tmp)
        conn_path = str(tmp)
    except Exception:
        conn_path = str(db_path)

    try:
        with get_conn(conn_path, timeout=15) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_info'"
            )
            if cur.fetchone() is None:
                return pd.DataFrame(columns=["ticker", "stock_name", "industry_category"])
            return pd.read_sql_query(
                "SELECT ticker, stock_name, industry_category FROM stock_info",
                conn,
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("load_stock_info failed: %s", exc)
        return pd.DataFrame(columns=["ticker", "stock_name", "industry_category"])


# ── 主偵測函式 ────────────────────────────────────────────────────────────────

def detect(
    df: pd.DataFrame,
    cfg: SwingBreakoutConfig | None = None,
    inst_df: pd.DataFrame | None = None,
    stock_info: pd.DataFrame | None = None,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Detect A 大波段 swing breakout entry signals.

    Args:
        df:         Features DataFrame（來自 add_features() + add_zhuli_features()）。
                    必要欄位：ticker, trade_date, close, volume, vol_ma20,
                               ma20, ma60, ma20_slope（或 ma20_slope_5d）,
                               ma60_slope_5d, high, low（for gap detection）.
        cfg:        SwingBreakoutConfig。None = 使用預設值。
        inst_df:    法人買賣超 DataFrame（ticker, trade_date, foreign_net, sitc_net 等）。
                    None = 從 db_path 自動讀取。
        stock_info: 股票產業分類 DataFrame（ticker, stock_name, industry_category）。
                    None = 從 db_path 自動讀取。
        db_path:    SQLite DB 路徑（inst_df 或 stock_info 為 None 時使用）。

    Returns:
        DataFrame of signal rows, sorted by signal_date desc, score desc, ticker.
        Columns: see module docstring.

    Raises:
        RuntimeError: 若法人資料表不存在（提醒 user 執行 backfill）。
    """
    if cfg is None:
        cfg = SwingBreakoutConfig()

    # === 載入依賴資料 ===
    if db_path is None:
        from kline.bars import DEFAULT_DB_PATH
        db_path = DEFAULT_DB_PATH

    if inst_df is None:
        inst_df = load_institutional_full(db_path)
    if inst_df is None or inst_df.empty:
        raise RuntimeError(
            "法人買賣超資料表（institutional_investors）不存在或為空。\n"
            "請先執行：python scripts/zhuli/backfill_institutional.py\n"
            "（swing_breakout 需要 foreign_net 欄位，請確認已用新版 backfill 重跑）"
        )
    # 確保 foreign_net 欄位存在
    if "foreign_net" not in inst_df.columns:
        inst_df = inst_df.copy()
        inst_df["foreign_net"] = 0.0
    if "foreign_buy" not in inst_df.columns:
        inst_df = inst_df.copy()
        inst_df["foreign_buy"] = 0.0
    if "foreign_sell" not in inst_df.columns:
        inst_df = inst_df.copy()
        inst_df["foreign_sell"] = 0.0

    if stock_info is None:
        stock_info = load_stock_info(db_path)

    # === 合併法人資料 + bars features ===
    # inst_df 可能有多行（per institution），取 date-level dedupe
    inst_daily = (
        inst_df
        .drop_duplicates(subset=["ticker", "trade_date"])
        [["ticker", "trade_date", "sitc_net", "foreign_net", "foreign_buy", "foreign_sell"]]
        .copy()
    )

    # 合併 bars features 與法人資料
    needed_cols = ["ticker", "trade_date", "close", "volume", "vol_ma20",
                   "ma20", "ma60", "ma20_slope"]
    # add ma60_slope（使用 ma60_slope_5d proxy）
    if "ma60_slope" not in df.columns and "ma60_slope_5d" in df.columns:
        df = df.copy()
        df["ma60_slope"] = df["ma60_slope_5d"]
    elif "ma60_slope" not in df.columns:
        df = df.copy()
        df["ma60_slope"] = 0.0

    # === 預計算 ma60_near_bottom 特徵（全市場向量化）===
    # 需要在 merge 之前對全量 df 計算，保留正確的時間序列排序
    if cfg.ma60_near_bottom_enabled and "ma60" in df.columns:
        if not isinstance(df, pd.DataFrame) or "ticker" not in df.columns:
            df = df.copy()
        else:
            df = df.copy()
        g_all = df.sort_values(["ticker", "trade_date"]).groupby("ticker", group_keys=False)

        # 5 日 MA60 最大跌幅：(5日內最大 MA60 - 最小 MA60) / 5日內最大 MA60
        ma60_5d_max = (
            g_all["ma60"]
            .rolling(5, min_periods=5)
            .max()
            .reset_index(level=0, drop=True)
        )
        ma60_5d_min = (
            g_all["ma60"]
            .rolling(5, min_periods=5)
            .min()
            .reset_index(level=0, drop=True)
        )
        df["_ma60_5d_max_drop_pct"] = (
            (ma60_5d_max - ma60_5d_min) / ma60_5d_max.replace(0, float("nan")) * 100
        )

        # MA20 連續 N 天上彎：過去 N 天（包含今天）的 ma20_slope 均 > 0
        n_days = cfg.ma60_near_bottom_ma20_up_days
        ma20_slope_col = "ma20_slope" if "ma20_slope" in df.columns else "ma20_slope_5d"
        df["_ma20_up_nd"] = (
            g_all[ma20_slope_col]
            .rolling(n_days, min_periods=n_days)
            .min()
            .reset_index(level=0, drop=True)
        ) > 0

    # 流動性過濾前先合併，避免不必要的大 merge
    extra_cols = []
    if cfg.ma60_near_bottom_enabled and "_ma60_5d_max_drop_pct" in df.columns:
        extra_cols = ["_ma60_5d_max_drop_pct", "_ma20_up_nd"]
    merged = df[needed_cols + ["ma60_slope", "high", "low", "prev_volume"] + extra_cols].merge(
        inst_daily,
        on=["ticker", "trade_date"],
        how="inner",  # 只保留兩邊都有的資料
    )

    if merged.empty:
        return _empty_output()

    # === 流動性過濾 ===
    # vol_ma20 在 DB 中單位為股（shares），需轉換為張（lots）
    # min_avg_volume_20 = 200 張；vol_ma20 單位 = 股，需 / 1000
    vol_ok = (merged["vol_ma20"].fillna(0) / 1000.0) >= cfg.min_avg_volume_20
    price_ok = merged["close"] >= cfg.min_close
    merged = merged[vol_ok & price_ok].copy()
    if merged.empty:
        return _empty_output()

    # === 籌碼面篩選 ===
    # 取外資與投信中買超較大的一方（inst_net = max(foreign_net, sitc_net)）
    # Source: strategy-indicators.md §A — 「外資（或投信）買超 ≥ 1/3 成交量」
    merged["inst_net"] = merged[["foreign_net", "sitc_net"]].max(axis=1)

    # 成交量單位轉換：
    #   - DB volume 欄位單位：股（shares）；413,940,731 股 = 413,940 張
    #   - institutional_investors sitc_net / foreign_net 單位：張（lots），已由 backfill 除以 1000
    #   - vol_ratio = inst_net（張）/ (volume（股）/ 1000（股/張）)
    volume_lots = merged["volume"] / 1000.0  # 轉換為張
    merged["vol_ratio"] = merged["inst_net"] / volume_lots.replace(0, float("nan"))

    chips_ratio_ok = merged["vol_ratio"] >= cfg.institutional_volume_ratio
    chips_abs_ok = merged["inst_net"] >= cfg.institutional_volume_absolute
    chips_ok = chips_ratio_ok | chips_abs_ok

    candidates = merged[chips_ok].copy()
    if candidates.empty:
        return _empty_output()

    # === 技術面篩選（必要：20MA + 60MA 上彎）===
    # Source: strategy-indicators.md §A — 「20ma 與 60ma 皆呈現上彎」
    ma20_up = candidates["ma20_slope"].fillna(0) > 0
    ma60_up = candidates["ma60_slope"].fillna(0) > 0

    # MA60 放寬條件（ma60_near_bottom）：MA60 幾近平坦且 MA20 已持續上彎
    # 診斷依據：scanner_diagnosis_6449_delay.md — 6449 5/5 miss 原因
    if cfg.ma60_near_bottom_enabled and "_ma60_5d_max_drop_pct" in candidates.columns:
        ma60_slope_neg = candidates["ma60_slope"].fillna(0) < 0
        ma60_flat = candidates["_ma60_5d_max_drop_pct"].fillna(float("inf")) < cfg.ma60_near_bottom_max_drop_pct
        ma20_up_nd = candidates["_ma20_up_nd"].fillna(False)
        ma60_near_bottom = ma60_slope_neg & ma60_flat & ma20_up_nd
        ma60_pass = ma60_up | ma60_near_bottom
    else:
        ma60_near_bottom = pd.Series(False, index=candidates.index)
        ma60_pass = ma60_up

    tech_ok = ma20_up & ma60_pass

    # 記錄哪些行是經由放寬條件通過的
    candidates = candidates.copy()
    candidates["_via_ma60_near_bottom"] = False
    if cfg.ma60_near_bottom_enabled and "_ma60_5d_max_drop_pct" in candidates.columns:
        candidates["_via_ma60_near_bottom"] = (~ma60_up) & ma60_near_bottom & ma20_up

    candidates = candidates[tech_ok].copy()
    if candidates.empty:
        return _empty_output()

    # === 距月線計算（理想條件）===
    # dist_to_ma20_pct = (close - ma20) / ma20
    # 正 = 在月線上方，負 = 在月線下方
    # Source: strategy-indicators.md §A — 「理想：股價離 20MA 在 5% 以內」
    candidates["dist_to_ma20_pct"] = (
        (candidates["close"] - candidates["ma20"]) / candidates["ma20"].replace(0, float("nan"))
    )
    abs_dist = candidates["dist_to_ma20_pct"].abs()
    dist_ideal = abs_dist <= cfg.max_dist_to_ma20_pct

    if cfg.enforce_dist_to_ma20:
        candidates = candidates[dist_ideal].copy()
        if candidates.empty:
            return _empty_output()

    # === 族群密度計算 ===
    # 對每個 (date, industry) 計算同日同產業籌碼面成立的標的數
    # Source: strategy-indicators.md §A — 「同產業 ≥ 3 檔出現在買超前列」
    if not stock_info.empty:
        candidates = candidates.merge(
            stock_info[["ticker", "stock_name", "industry_category"]].rename(
                columns={"industry_category": "industry"}
            ),
            on="ticker",
            how="left",
        )
    else:
        candidates["stock_name"] = ""
        candidates["industry"] = ""

    # 計算每個 (date, industry) 的族群密度
    # 對空產業（NaN / ""）不計入族群密度
    has_industry = candidates["industry"].notna() & (candidates["industry"] != "")
    candidates_with_industry = candidates[has_industry].copy()

    if not candidates_with_industry.empty:
        density = (
            candidates_with_industry.groupby(["trade_date", "industry"])["ticker"]
            .transform("count")
        )
        peers_map = (
            candidates_with_industry.groupby(["trade_date", "industry"])["ticker"]
            .transform(lambda x: ",".join(sorted(x.astype(str).tolist())))
        )
        candidates.loc[has_industry, "sector_density"] = density.values
        candidates.loc[has_industry, "sector_peers_all"] = peers_map.values
    else:
        candidates["sector_density"] = 0
        candidates["sector_peers_all"] = ""

    candidates["sector_density"] = candidates["sector_density"].fillna(1).astype(int)
    candidates["sector_peers_all"] = candidates["sector_peers_all"].fillna("")

    # sector_peers = 同族群中排除自己的其他標的
    def _peers_without_self(row: pd.Series) -> str:
        all_peers = [t for t in row["sector_peers_all"].split(",") if t and t != row["ticker"]]
        return ",".join(all_peers)

    candidates["sector_peers"] = candidates.apply(_peers_without_self, axis=1)

    # === 族群密度過濾（必要，若 require_sector_density = True）===
    if cfg.require_sector_density:
        density_ok = candidates["sector_density"] >= cfg.sector_density_min_count
        candidates = candidates[density_ok].copy()
        if candidates.empty:
            return _empty_output()

    # === 加分：封閉空方缺口 ===
    # 空方缺口：前一日高點 > 前前日低點（真空 = gap_high > prev_prev_low）
    # 封閉缺口：當日收盤站上缺口高點（close > prev gap high）
    # Source: strategy-indicators.md §K — 「收盤站上缺口高點（封閉缺口）→ 進場」
    # 此為 A 策略的「加分」條件，不做必要過濾
    # 簡化實作：前日有向下跳空（prev high < prev_prev high 的缺口），當日收盤補上
    # 此處以 「prev_volume 存在且 high > prev_high」作為簡化近似
    # 注意：精確缺口需要兩根前資料，此處暫以 NaN 補充（gap_closed = False 預設）
    candidates["gap_closed"] = False  # placeholder，後續可擴充精確邏輯

    # === 評分系統 ===
    # 族群面：density ≥ 3 → +2 分，每多 1 檔 +0.5
    # 籌碼面：達絕對門檻 ≥ 2 萬張 → +2 分；達比例 1/3 → +1 分
    # 技術面：距月線 ≤ 5% → +1 分
    # 加分：封閉缺口 → +1 分
    def _score(row: pd.Series) -> float:
        s = 0.0
        # 族群面
        d = int(row.get("sector_density", 0))
        if d >= cfg.sector_density_min_count:
            s += 2.0 + max(0, d - cfg.sector_density_min_count) * 0.5
        # 籌碼面
        if row.get("inst_net", 0) >= cfg.institutional_volume_absolute:
            s += 2.0
        elif row.get("vol_ratio", 0) >= cfg.institutional_volume_ratio:
            s += 1.0
        # 技術面距月線
        if abs(row.get("dist_to_ma20_pct", 1.0)) <= cfg.max_dist_to_ma20_pct:
            s += 1.0
        # 加分
        if row.get("gap_closed", False):
            s += 1.0
        return s

    candidates["score"] = candidates.apply(_score, axis=1)

    # === 進場提示 ===
    # Source: strategy-indicators.md §A — 「籌碼大買後不立即進場，等次日或後續技術面確認」
    entry_note = (
        "籌碼大買日不立即進場。"
        "等次日技術面確認（月線附近、量縮後出量站上）再切入。"
        "停損：收盤跌破月線（MA20）或大量黑K 跌破前一根紅K 低點。"
    )

    # === 建立輸出 DataFrame ===
    out = pd.DataFrame({
        "ticker":               candidates["ticker"].values,
        "name":                 candidates.get("stock_name", pd.Series("", index=candidates.index)).values,
        "signal_date":          candidates["trade_date"].values,
        "industry":             candidates.get("industry", pd.Series("", index=candidates.index)).values,
        "foreign_net":          candidates["foreign_net"].fillna(0).values,
        "sitc_net":             candidates["sitc_net"].fillna(0).values,
        "inst_net":             candidates["inst_net"].values,
        "vol_ratio":            candidates["vol_ratio"].fillna(0).round(4).values,
        "close":                candidates["close"].values,
        "ma20":                 candidates["ma20"].values,
        "ma60":                 candidates["ma60"].values,
        "ma20_slope":           candidates["ma20_slope"].values,
        "ma60_slope":           candidates["ma60_slope"].values,
        "dist_to_ma20_pct":     candidates["dist_to_ma20_pct"].fillna(0).round(4).values,
        "sector_density":       candidates["sector_density"].values,
        "sector_peers":         candidates["sector_peers"].values,
        "gap_closed":           candidates["gap_closed"].values,
        "stop_loss":            candidates["ma20"].values,  # 收盤跌破月線停損
        "score":                candidates["score"].values,
        "entry_note":           entry_note,
        "ma60_near_bottom":     candidates.get("_via_ma60_near_bottom", pd.Series(False, index=candidates.index)).values,
    })

    return out.sort_values(
        ["signal_date", "score", "sector_density", "ticker"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)


# ── 空結果模板 ────────────────────────────────────────────────────────────────

def _empty_output() -> pd.DataFrame:
    """Return empty DataFrame with correct output schema."""
    return pd.DataFrame(columns=[
        "ticker", "name", "signal_date", "industry",
        "foreign_net", "sitc_net", "inst_net", "vol_ratio",
        "close", "ma20", "ma60", "ma20_slope", "ma60_slope",
        "dist_to_ma20_pct", "sector_density", "sector_peers",
        "gap_closed", "stop_loss", "score", "entry_note",
        "ma60_near_bottom",
    ])
