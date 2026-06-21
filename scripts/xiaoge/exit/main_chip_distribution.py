"""xiaoge_main_chip_distribution — 曲終人散出場警告 (空頭三軸 exit detector).

Course source: 權證小哥 ch07 (曲終人散), ch11.

> 「在高檔的時候主力在這邊大幅地賣超，散戶大幅地買超，集保戶數大幅地增加…
>  很容易第一根出現之後後面就崩跌了。」(ch07 09:13–09:35)

## 量化條件（完全照 spec、不自行增減）

1. **高檔**：close >= MA60 × 1.15（個股在 60 日均線相對高檔）
2. **主力大賣**：main_force_5d <= -20,000 股（= -20 張、課程「大賣」門檻）
3. **集保戶數環比增加**：total_people 本週 > 上週（集保戶大增 = 散戶大買接盤）
   - 若 shareholding_path 缺、此條件跳過；但其他 4 條全過仍亮燈（信心降一級）
4. **布林帶寬寬**：bb_width_pct >= 20（課程：高檔震盪帶寬展開）
5. **第一根明顯黑 K 觸發**：close < open AND (open - close)/open >= 0.03（振幅 ≥ 3%）

## 用途

**這是 exit / warn detector，不是進場 detector。**
持倉警示：五條件全部成立時，出現第一根明顯黑 K 是老師說的「崩跌前兆」。

## 輸出

pd.Series[bool]：True = 當日為「曲終人散」警告訊號。

## 欄位需求

df 必須含：ticker, trade_date, close, open, ma60, bb_width_pct, main_force_5d
shareholding 透過 shareholding_path as-of join（可選）

## 備註

- shareholding 是週粒度，detector 用 merge_asof backward join 拿最新快照。
- 若 shareholding_path=None 或檔案不存在：集保戶條件跳過，亮燈信心降一級
  （docstring 明示、其他 4 條全過仍回傳 True）。
- 「主力大賣 -20 張」絕對門檻 = ch11 02:35「20 以上大買」鏡像版。流動性中立的比例化版見
  `scripts/xiaoge/scoring/screener.py::detect_s2_max_broker_dumping`（ch12 08:42 課程明示）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
DEFAULT_SHAREHOLDING_PATH = (
    REPO / "data/analysis/xiaoge/shareholding/2026-04-01_2026-06-12.parquet"
)


def _attach_shareholding(df: pd.DataFrame, shareholding_path: Path) -> pd.DataFrame:
    """As-of join shareholding (weekly) onto daily bars.

    Computes week-over-week change to check whether total_people increased
    (集保戶數大增 = 散戶大買接盤、空頭訊號).
    """
    if not shareholding_path.exists():
        raise FileNotFoundError(
            f"Shareholding parquet missing: {shareholding_path}. "
            f"Run `python3 -m scripts.xiaoge.fetch_shareholding` first."
        )
    sh = pd.read_parquet(shareholding_path)
    sh = sh.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Week-over-week: total_people 增加 = 集保戶大增（空頭訊號、散戶接盤）
    g = sh.groupby("ticker")
    sh["total_people_prev"] = g["total_people"].shift(1)
    # total_down=False 的鏡像：total_up = 集保戶增加
    sh["total_up"] = (sh["total_people"] > sh["total_people_prev"]).fillna(False)

    df = df.copy()
    df["_orig_idx"] = df.index

    df_sorted = df.sort_values("trade_date").reset_index(drop=True)
    sh_sorted = sh.sort_values("date").reset_index(drop=True)

    out = pd.merge_asof(
        df_sorted,
        sh_sorted[["ticker", "date", "total_up", "total_people"]],
        left_on="trade_date",
        right_on="date",
        by="ticker",
        direction="backward",
    )
    # Restore original row order
    out = out.sort_values("_orig_idx").reset_index(drop=True)
    out = out.drop(columns=["_orig_idx"])
    return out


def detect(
    df: pd.DataFrame,
    min_chip_sell_shares: int = -20_000,    # 課程: 大賣門檻 = -20 張 = -20,000 股
    min_high_zone_ratio: float = 1.15,      # 課程: 高檔 = close >= MA60 × 1.15
    min_bandwidth: float = 20.0,            # 課程: 布林帶寬寬 ≥ 20
    min_black_k_amplitude: float = 0.03,    # 課程: 振幅 ≥ 3%（明顯黑 K 觸發）
    shareholding_path: Path | None = DEFAULT_SHAREHOLDING_PATH,
) -> pd.Series:
    """xiaoge_main_chip_distribution — 曲終人散出場警告.

    Parameters
    ----------
    df:
        日 K DataFrame。必要欄位：ticker, trade_date, close, open,
        ma60, bb_width_pct, main_force_5d。
    min_chip_sell_shares:
        主力賣超門檻（股數）。課程明示「大賣 -20 張」，預設 -20,000。
        注意符號：main_force_5d 賣超時為負數，門檻也是負數。
    min_high_zone_ratio:
        高檔判定：close >= MA60 × ratio。課程「60 日 / 120 日相對高檔」，
        預設 1.15。
    min_bandwidth:
        布林帶寬門檻（%）。課程「高檔震盪帶寬展開 ≥ 20」，預設 20.0。
    min_black_k_amplitude:
        明顯黑 K 振幅門檻（小數）。課程「振幅 ≥ 3%」，預設 0.03。
    shareholding_path:
        集保戶 parquet 路徑。None 或檔案不存在 → 集保戶條件跳過（信心降一級）。

    Returns
    -------
    pd.Series[bool]
        True = 當日觸發「曲終人散」出場警告。
        所有 5 條件通過（or 無 shareholding 時前 4 條通過）才回傳 True。
    """
    close = df["close"]
    open_ = df["open"]
    ma60 = df["ma60"]
    bb_width_pct = df["bb_width_pct"]
    main_5d = df["main_force_5d"]

    # Condition 1: 高檔（close >= MA60 × 1.15）
    in_high_zone = (close >= ma60 * min_high_zone_ratio).fillna(False)

    # Condition 2: 主力大賣（main_force_5d <= -20,000）
    main_selling = (main_5d <= min_chip_sell_shares).fillna(False)

    # Condition 4: 布林帶寬寬（bb_width_pct >= 20）
    wide_bandwidth = (bb_width_pct >= min_bandwidth).fillna(False)

    # Condition 5: 第一根明顯黑 K（close < open AND 振幅 ≥ 3%）
    is_black_k = (close < open_).fillna(False)
    amplitude = ((open_ - close) / open_.replace(0, pd.NA)).fillna(0.0)
    is_significant_black_k = is_black_k & (amplitude >= min_black_k_amplitude)

    # Condition 3: 集保戶數環比增加（as-of join shareholding，可選）
    use_shareholding = False
    total_up: pd.Series = pd.Series(False, index=df.index)

    if shareholding_path is not None:
        spath = Path(shareholding_path)
        if spath.exists():
            df2 = _attach_shareholding(df, spath)
            total_up = df2["total_up"].fillna(False).reindex(df.index).fillna(False).astype(bool)
            use_shareholding = True

    # Combine conditions
    if use_shareholding:
        # 全 5 條都要過
        sig = (
            in_high_zone
            & main_selling
            & total_up
            & wide_bandwidth
            & is_significant_black_k
        )
    else:
        # 集保戶條件跳過，其他 4 條全過仍亮燈（信心降一級、docstring 已說明）
        sig = (
            in_high_zone
            & main_selling
            & wide_bandwidth
            & is_significant_black_k
        )

    return sig.fillna(False).astype(bool)
