"""J 投信首買策略 entry signal — 主力大 Ex2-3.

Course source: 主力大全方位操盤教戰守則 (尼克)
  - strategy-indicators.md §J 投信首買策略（Ex2-3）
  - course_principles.md §17 投信跟單加碼

Logic（來源 Ex2-3 投影片 01:23 + 截圖手寫補充）:
    對每個 (ticker, date)：
    1. 該日投信淨買超 (sitc_net) ≥ min_firstbuy_volume（課程：至少 200 張）
    2. 前 no_buy_window_days 個交易日內，所有 sitc_net ≤ 0（前面「完全乾淨」）
       Source: 字幕 01:53「前面都非常乾淨」；截圖 07:24「越長空白越高勝率」
    3. 流動性過濾：20日均量 ≥ min_avg_volume_20 且收盤 ≥ min_close

加分條件（不過濾，只加欄位供排序/標記用）：
    - 價籌背離：當日收黑K（close < open）且 sitc_net > 0
      Source: strategy-indicators.md §J「當日個股收黑K但投信買超 => 價籌背離」
    - 均線多頭排列（ideal_ma_align）
      Source: strategy-indicators.md §J「籌碼+技術面多頭排列 → 勝率加成」

進場提示（課程規則，不在 scanner 判斷，只於 entry_note 標記）：
    「第一天上榜不進場；穩健：等回到十日線附近出量站上十日線；
     積極：用 5 分 K SOP 隔日切入。」
    Source: strategy-indicators.md §I 切入時機（投信首買沿用 Ex2-2 規則）

Output columns:
    ticker              — 股票代號
    signal_date         — 首買日期
    sitc_net            — 當日投信淨買超（張）
    sitc_buy            — 當日投信買進（張）
    sitc_sell           — 當日投信賣出（張）
    no_buy_window_days  — 空白窗口天數（config 值）
    price_divergence    — 是否價籌背離（收黑K + 投信買超）
    close               — 當日收盤
    ma10                — 十日線（出場停損參考）
    ideal_ma_align      — 是否理想多頭排列（5>10>20>60 全上彎）
    entry_note          — 進場提示文字
    stop_loss           — 停損參考（收盤跌破 ma10）
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
from zhuli.config import InstitutionalFirstBuyConfig


# ── 讀取投信資料 ───────────────────────────────────────────────────────────────

def load_institutional(db_path: Path) -> pd.DataFrame:
    """從 DB 讀取 institutional_investors 表。

    Returns DataFrame with columns: ticker, trade_date (datetime64[ns]), sitc_buy, sitc_sell, sitc_net.
    若表格不存在，回傳空 DataFrame。

    ⚠️ 若回傳空 DataFrame，偵測函式會 raise 提醒 user 需先執行 backfill。
    """
    try:
        tmp = Path(tempfile.gettempdir()) / f"inst_snapshot_{os.getpid()}.sqlite"
        shutil.copy2(db_path, tmp)
        conn_path = str(tmp)
    except Exception:
        conn_path = str(db_path)

    try:
        with get_conn(conn_path, timeout=15) as conn:
            # 先確認表存在
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='institutional_investors'"
            )
            if cur.fetchone() is None:
                return pd.DataFrame(columns=["ticker", "trade_date", "sitc_buy", "sitc_sell", "sitc_net"])

            df = pd.read_sql_query(
                "SELECT ticker, trade_date, sitc_buy, sitc_sell, sitc_net FROM institutional_investors",
                conn,
                parse_dates=["trade_date"],
            )
        df["trade_date"] = df["trade_date"].astype("datetime64[ns]")
        return df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("load_institutional failed: %s", exc)
        return pd.DataFrame(columns=["ticker", "trade_date", "sitc_buy", "sitc_sell", "sitc_net"])


# ── 主偵測函式 ────────────────────────────────────────────────────────────────

def detect(
    df: pd.DataFrame,
    cfg: InstitutionalFirstBuyConfig | None = None,
    inst_df: pd.DataFrame | None = None,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Detect J 投信首買 entry signals.

    Args:
        df:       Features DataFrame（來自 add_features() + add_zhuli_features()）。
                  必要欄位：ticker, trade_date, open, close, vol_ma20, ma10,
                             ideal_ma_align。
        cfg:      InstitutionalFirstBuyConfig。None = 使用預設值。
        inst_df:  投信買賣超 DataFrame（ticker, trade_date, sitc_buy, sitc_sell, sitc_net）。
                  None = 從 db_path 自動讀取。
        db_path:  SQLite DB 路徑（inst_df=None 時使用）。

    Returns:
        DataFrame of signal rows, sorted by signal_date desc, then ticker.
        Columns: see module docstring.

    Raises:
        RuntimeError: 若投信資料表不存在（提醒 user 執行 backfill）。
    """
    if cfg is None:
        cfg = InstitutionalFirstBuyConfig()

    # === 載入投信資料 ===
    if inst_df is None:
        if db_path is None:
            from kline.bars import DEFAULT_DB_PATH
            db_path = DEFAULT_DB_PATH
        inst_df = load_institutional(db_path)

    if inst_df.empty:
        raise RuntimeError(
            "投信買賣超資料表（institutional_investors）不存在或為空。\n"
            "請先執行：python scripts/zhuli/backfill_institutional.py\n"
            "或加上 --tickers 參數只撈指定個股（速度較快）。"
        )

    # === 計算「前 N 交易日空白窗口」===
    # 對每個 (ticker, date)，需確認前 no_buy_window_days 筆交易日的 sitc_net 全 ≤ 0。
    # 使用 rolling max 判斷前 N 日最大 sitc_net；若 max ≤ 0 = 全部空白。
    # Source: strategy-indicators.md §J — 「前面至少 2 個月無投信買超」
    inst_sorted = inst_df.sort_values(["ticker", "trade_date"]).copy()
    inst_g = inst_sorted.groupby("ticker", group_keys=False)

    # 前 no_buy_window_days 筆（shift(1) 排除今天自己）的 sitc_net 最大值
    window = cfg.no_buy_window_days
    inst_sorted["prev_window_max_sitc"] = (
        inst_g["sitc_net"]
        .shift(1)
        .rolling(window, min_periods=window)
        .max()
        .reset_index(level=0, drop=True)
    )

    # 「前 window 天全部空白」= prev_window_max_sitc ≤ no_buy_threshold（預設 0）
    inst_sorted["is_clean_window"] = (
        inst_sorted["prev_window_max_sitc"] <= cfg.no_buy_threshold
    )

    # === 篩選首買候選 ===
    # 條件 1：今日 sitc_net ≥ min_firstbuy_volume
    # Source: strategy-indicators.md §J — 「至少 200 張」
    # 條件 2：前 window 天全部空白
    candidate_mask = (
        inst_sorted["sitc_net"] >= cfg.min_firstbuy_volume
    ) & (
        inst_sorted["is_clean_window"].fillna(False)
    )

    candidates = inst_sorted[candidate_mask].copy()
    if candidates.empty:
        return _empty_output()

    # === 合併 bars features ===
    # 只取 candidates 的 (ticker, trade_date) 對應的 bar 資料
    merge_keys = candidates[["ticker", "trade_date"]].copy()
    merged = merge_keys.merge(
        df[["ticker", "trade_date", "open", "close", "vol_ma20", "ma10",
            "ideal_ma_align", "is_red", "is_black"]],
        on=["ticker", "trade_date"],
        how="left",
    )
    merged = merged.merge(
        candidates[["ticker", "trade_date", "sitc_buy", "sitc_sell", "sitc_net"]],
        on=["ticker", "trade_date"],
        how="left",
    )

    # 若 bars 資料裡找不到該 ticker/date（可能不在 standard_daily_bar），就排除
    merged = merged.dropna(subset=["close"])

    # === 流動性過濾 ===
    # Source: 課程中立的操作門檻，非課程條件
    vol_ok = merged["vol_ma20"].fillna(0) >= cfg.min_avg_volume_20
    price_ok = merged["close"] >= cfg.min_close
    liquid_mask = vol_ok & price_ok

    hits = merged[liquid_mask].copy()
    if hits.empty:
        return _empty_output()

    # 若 require_ma_alignment = True，額外過濾
    if cfg.require_ma_alignment:
        ma_ok = hits["ideal_ma_align"].fillna(False)
        hits = hits[ma_ok].copy()
    if hits.empty:
        return _empty_output()

    # === 加分條件：價籌背離 ===
    # 收黑K（close < open）且投信買超 > 0
    # Source: strategy-indicators.md §J「當日個股收黑K但投信買超 => 價籌背離」
    # is_black: close < open（課程定義：收黑K = 綠K/黑K，收盤 < 開盤）
    if "is_black" in hits.columns:
        price_divergence = hits["is_black"].fillna(False) & (hits["sitc_net"] > 0)
    else:
        # 若 is_black 不在 features，直接算
        price_divergence = (hits["close"] < hits["open"]) & (hits["sitc_net"] > 0)

    # === 進場提示 ===
    # Source: strategy-indicators.md §I 切入時機 — 首買沿用 Ex2-2 規則
    # 課程規則：第一天上榜不進場；穩健 = 等回十日線出量站上；積極 = 5分K SOP
    entry_note = (
        "隔日依 5分K SOP 積極進場，或等回十日線附近出量站上（穩健）。"
        "停損：收盤跌破十日線（MA10）。"
    )

    # === 建立輸出 DataFrame ===
    out = pd.DataFrame({
        "ticker":              hits["ticker"].values,
        "signal_date":         hits["trade_date"].values,
        "sitc_net":            hits["sitc_net"].values,
        "sitc_buy":            hits["sitc_buy"].fillna(0).values,
        "sitc_sell":           hits["sitc_sell"].fillna(0).values,
        "no_buy_window_days":  cfg.no_buy_window_days,
        "price_divergence":    price_divergence.values,
        "close":               hits["close"].values,
        "ma10":                hits["ma10"].values,
        "ideal_ma_align":      hits["ideal_ma_align"].fillna(False).values,
        "entry_note":          entry_note,
        "stop_loss":           hits["ma10"].values,  # 跌破十日線停損
    })

    return out.sort_values(
        ["signal_date", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


# ── 空結果模板 ────────────────────────────────────────────────────────────────

def _empty_output() -> pd.DataFrame:
    """Return empty DataFrame with correct output schema."""
    return pd.DataFrame(columns=[
        "ticker",
        "signal_date",
        "sitc_net",
        "sitc_buy",
        "sitc_sell",
        "no_buy_window_days",
        "price_divergence",
        "close",
        "ma10",
        "ideal_ma_align",
        "entry_note",
        "stop_loss",
    ])
