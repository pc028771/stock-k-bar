# Volume Profile 壓力區 + 攻擊品質分數 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 實作課程定義的壓力區分析（volume profile）與攻擊品質分數，取代現有 OHLCV peak-count 代理。

**Architecture:** 新增 `volume_profile.py` 共用模組處理 VP 計算；FinMind 分K（歷史）與 Fubon 分價量表（即時）透過同一介面輸入；攻擊品質特徵只用突破當下已知資料，權重由回測分析決定。

**Tech Stack:** Python 3.11+, pandas, numpy, fubon_neo SDK, FinMind REST API（現有 `fetch_kbar`）

---

## 檔案異動清單

| 檔案 | 動作 | 說明 |
|------|------|------|
| `scripts/volume_profile.py` | 新增 | VP 計算核心：`build_vp_from_kbar`, `compute_vp_features` |
| `scripts/attack_quality_analysis.py` | 新增 | 回測分析腳本，輸出特徵相關係數表 |
| `stock-analysis-system/clients/fubon_client.py` | 修改 | 新增 `get_intraday_volumes` 方法 |
| `scripts/kline_course_backtest.py` | 修改 | 新增 `higher_low_count`, `gap_open`, `pre_breakout_trend_days` |
| `scripts/breakout_daily_scanner.py` | 修改 | 整合 VP 資料抓取與評分 |

---

## Task 1：`volume_profile.py` — 核心 VP 模組

**Files:**
- Create: `scripts/volume_profile.py`

- [ ] **Step 1：建立 `build_vp_from_kbar`**

建立 `scripts/volume_profile.py`：

```python
from __future__ import annotations

import pandas as pd


def build_vp_from_kbar(kbar: pd.DataFrame, tick_size: float = 0.01) -> pd.DataFrame:
    """把 1分K OHLCV 聚合成分價量表 [price, volume]。

    每根 bar 的 volume 均勻分配到 high-low 之間的 tick 格子。
    tick_size 預設 0.01 元（台股最小跳動單位）。
    """
    if kbar.empty:
        return pd.DataFrame(columns=["price", "volume"])

    buckets: dict[float, float] = {}
    for _, row in kbar.iterrows():
        lo = _snap(float(row["low"]), tick_size)
        hi = _snap(float(row["high"]), tick_size)
        vol = float(row["volume"])
        if lo >= hi:
            buckets[lo] = buckets.get(lo, 0.0) + vol
        else:
            ticks = round((hi - lo) / tick_size) + 1
            vol_per = vol / ticks
            p = lo
            for _ in range(ticks):
                rp = _snap(p, tick_size)
                buckets[rp] = buckets.get(rp, 0.0) + vol_per
                p += tick_size

    return pd.DataFrame(sorted(buckets.items()), columns=["price", "volume"])


def _snap(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 10)
```

- [ ] **Step 2：建立 `compute_vp_features`**

在同一檔案追加：

```python
def compute_vp_features(
    vp: pd.DataFrame,
    current_close: float,
    band_pct: float = 0.10,
    dense_quantile: float = 0.80,
) -> dict[str, float | bool]:
    """從分價量表計算壓力區特徵。

    Args:
        vp:             [price, volume] DataFrame
        current_close:  今日收盤價
        band_pct:       觀察帶寬，現價上方 0% ~ band_pct（預設 10%）
        dense_quantile: 密集定義門檻：該帶有 bucket 超過全體第 dense_quantile 分位（預設 80th）

    Returns dict keys:
        vp_overhead_pct           — 現價以上成交量佔全日總量比率（0–1）
        vp_dense_above            — 現價上方 band 內有密集成交區
        vp_supply_vacuum          — 現價上方 band 內無密集區（賣壓中空）
        vp_nearest_resistance_pct — 最近密集成交區距現價距離（%），無則 NaN
    """
    nan_result: dict[str, float | bool] = {
        "vp_overhead_pct": float("nan"),
        "vp_dense_above": False,
        "vp_supply_vacuum": False,
        "vp_nearest_resistance_pct": float("nan"),
    }
    if vp.empty or current_close <= 0:
        return nan_result

    total_vol = float(vp["volume"].sum())
    if total_vol == 0:
        return nan_result

    band_high = current_close * (1 + band_pct)
    above = vp[vp["price"] > current_close]
    in_band = vp[(vp["price"] > current_close) & (vp["price"] <= band_high)]

    vp_overhead_pct = float(above["volume"].sum() / total_vol)

    dense_threshold = float(vp["volume"].quantile(dense_quantile))
    vacuum_threshold = float(vp["volume"].quantile(0.20))

    if in_band.empty:
        vp_dense_above = False
        vp_supply_vacuum = True  # 上方 band 內完全沒成交 = 賣壓中空
    else:
        vp_dense_above = bool((in_band["volume"] >= dense_threshold).any())
        vp_supply_vacuum = bool(float(in_band["volume"].max()) < vacuum_threshold)

    if above.empty:
        vp_nearest_resistance_pct = float("nan")
    else:
        dense_above = above[above["volume"] >= dense_threshold]
        if dense_above.empty:
            vp_nearest_resistance_pct = float("nan")
        else:
            nearest = float(dense_above["price"].min())
            vp_nearest_resistance_pct = round((nearest / current_close - 1) * 100, 2)

    return {
        "vp_overhead_pct": round(vp_overhead_pct, 4),
        "vp_dense_above": vp_dense_above,
        "vp_supply_vacuum": vp_supply_vacuum,
        "vp_nearest_resistance_pct": vp_nearest_resistance_pct,
    }
```

- [ ] **Step 3：內嵌驗證**

在 `scripts/volume_profile.py` 末尾追加，然後執行：

```python
if __name__ == "__main__":
    # 驗證 build_vp_from_kbar
    import pandas as pd
    kbar = pd.DataFrame({
        "open":   [10.0, 10.5],
        "high":   [10.5, 11.0],
        "low":    [10.0, 10.5],
        "close":  [10.4, 10.9],
        "volume": [1000, 2000],
    })
    vp = build_vp_from_kbar(kbar)
    assert not vp.empty, "VP should not be empty"
    assert set(vp.columns) == {"price", "volume"}, "Wrong columns"
    assert abs(vp["volume"].sum() - 3000) < 1, f"Volume sum mismatch: {vp['volume'].sum()}"

    # 驗證 compute_vp_features
    feats = compute_vp_features(vp, current_close=10.4)
    assert "vp_overhead_pct" in feats
    assert 0 <= feats["vp_overhead_pct"] <= 1
    assert isinstance(feats["vp_dense_above"], bool)
    assert isinstance(feats["vp_supply_vacuum"], bool)
    print("volume_profile.py: all assertions passed")
    print(feats)
```

執行：`cd /Users/howard/Repository/stock-k-bar && python scripts/volume_profile.py`

期望輸出：`volume_profile.py: all assertions passed`

- [ ] **Step 4：Commit**

```bash
git add scripts/volume_profile.py
git commit -m "feat(volume-profile): add build_vp_from_kbar and compute_vp_features"
```

---

## Task 2：`fubon_client.py` — 新增 `get_intraday_volumes`

**Files:**
- Modify: `/Users/howard/Repository/stock-analysis-system/clients/fubon_client.py:760`（在 `subscribe_quotes` 前插入）

- [ ] **Step 1：新增方法**

在 `subscribe_quotes` 定義之前插入（約 760 行）：

```python
    def get_intraday_volumes(self, symbol: str) -> pd.DataFrame:
        """即時分價量表 — GET /intraday/volumes/{symbol}。

        Returns:
            DataFrame with columns [price, volume], sorted by price asc.
            Empty DataFrame on failure — never raises.
        """
        try:
            self._ensure_connected()
            resp = self._reststock.intraday.volumes(symbol=symbol)
            rows = _extract_data(resp)
            if not rows:
                return pd.DataFrame(columns=["price", "volume"])
            df = pd.DataFrame(rows)
            df["price"] = pd.to_numeric(
                df.get("price", pd.Series(dtype=float)), errors="coerce"
            )
            df["volume"] = pd.to_numeric(
                df.get("volume", pd.Series(dtype=float)), errors="coerce"
            )
            return (
                df[["price", "volume"]]
                .dropna()
                .sort_values("price")
                .reset_index(drop=True)
            )
        except Exception as exc:
            logger.warning("FubonClient.get_intraday_volumes(%s) failed: %s", symbol, exc)
            return pd.DataFrame(columns=["price", "volume"])
```

- [ ] **Step 2：盤中手動驗證（需市場開盤）**

盤中執行：

```python
# 快速驗證（在 Python REPL 或 script 裡）
import sys; sys.path.insert(0, "/Users/howard/Repository/stock-analysis-system")
from clients.fubon_client import FubonClient
client = FubonClient()
vp = client.get_intraday_volumes("2330")
print(vp.head())
assert list(vp.columns) == ["price", "volume"]
assert not vp.empty
```

若盤後，`vp` 可能為空 DataFrame——這是正常行為，不報錯即通過。

- [ ] **Step 3：Commit**

```bash
cd /Users/howard/Repository/stock-analysis-system
git add clients/fubon_client.py
git commit -m "feat(fubon-client): add get_intraday_volumes for intraday price-volume table"
```

---

## Task 3：`kline_course_backtest.py` — 攻擊品質特徵

**Files:**
- Modify: `scripts/kline_course_backtest.py`（在 `add_features` 函式末尾，`return df` 之前）

- [ ] **Step 1：新增三個特徵**

在 `add_features` 裡 `return df` 之前插入：

```python
    # --- 攻擊品質特徵（只用突破當下已知資料，不看未來）---

    # higher_low_count：突破前 10 日內，low > 前一日 low 的天數
    def _higher_low_count(s: pd.Series) -> pd.Series:
        is_hl = (s > s.shift(1)).astype(float)
        # shift(1) 使計算不包含今日（突破日本身）
        return is_hl.shift(1).rolling(10, min_periods=1).sum()

    df["higher_low_count"] = (
        df.groupby("ticker", group_keys=False)["low"]
        .transform(_higher_low_count)
    )

    # gap_open：突破日開盤跳空（開盤 > 前收）
    df["gap_open"] = (df["open"] > df["prev_close"]).astype(int)

    # pre_breakout_trend_days：突破前連續收盤在 ma60 上方的天數（最多 20 天）
    def _consec_above_ma60(g: pd.DataFrame) -> pd.Series:
        above = (g["close"] > g["ma60"]).astype(int)
        above_shifted = above.shift(1).fillna(0)  # 不含今日
        result = []
        count = 0
        for v in above_shifted:
            count = (count + 1) * int(v)
            result.append(min(count, 20))
        return pd.Series(result, index=g.index)

    df["pre_breakout_trend_days"] = (
        df.groupby("ticker", group_keys=False)
        .apply(_consec_above_ma60)
        .reset_index(level=0, drop=True)
    )
```

- [ ] **Step 2：驗證新欄位存在且無全 NaN**

```bash
cd /Users/howard/Repository/stock-k-bar
python -c "
from scripts.kline_course_backtest import add_features, load_bars
df = add_features(load_bars())
for col in ['higher_low_count', 'gap_open', 'pre_breakout_trend_days']:
    assert col in df.columns, f'Missing: {col}'
    non_null = df[col].notna().sum()
    assert non_null > 0, f'All NaN: {col}'
    print(f'{col}: {non_null} non-null, range [{df[col].min():.1f}, {df[col].max():.1f}]')
print('attack quality features OK')
"
```

期望每個欄位都有非 NaN 值，`gap_open` 範圍 [0, 1]，`higher_low_count` 範圍 [0, 10]，`pre_breakout_trend_days` 範圍 [0, 20]。

- [ ] **Step 3：Commit**

```bash
git add scripts/kline_course_backtest.py
git commit -m "feat(backtest): add higher_low_count, gap_open, pre_breakout_trend_days features"
```

---

## Task 4：`attack_quality_analysis.py` — 回測分析腳本

**Files:**
- Create: `scripts/attack_quality_analysis.py`
- Output: `docs/K線力量判斷入門/backtests/attack_quality_analysis.md`

- [ ] **Step 1：建立分析腳本**

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

from kline_course_backtest import add_features, add_signals, load_bars

OUT_DIR = Path("data/analysis/kline_course_backtest")
REPORT_PATH = Path("docs/K線力量判斷入門/backtests/attack_quality_analysis.md")

ATTACK_QUALITY_FEATURES = [
    "higher_low_count",
    "gap_open",
    "pre_breakout_trend_days",
    "body_pct",
    "close_pos",
    "volume_ratio",
]


def compute_correlations(df: pd.DataFrame) -> pd.DataFrame:
    """計算各特徵與 ret_10d 的 Spearman 相關係數（只在突破樣本上）。"""
    sample = df[df["breakout_attack"]].dropna(subset=["ret_10d"])
    rows = []
    for feat in ATTACK_QUALITY_FEATURES:
        if feat not in sample.columns:
            continue
        valid = sample[[feat, "ret_10d"]].dropna()
        if len(valid) < 30:
            rows.append({"feature": feat, "n": len(valid), "spearman_r": float("nan"), "p_value": float("nan")})
            continue
        r, p = spearmanr(valid[feat], valid["ret_10d"])
        rows.append({
            "feature": feat,
            "n": int(len(valid)),
            "spearman_r": round(float(r), 4),
            "p_value": round(float(p), 4),
        })
    return pd.DataFrame(rows).sort_values("spearman_r", ascending=False)


def write_report(corr: pd.DataFrame, df: pd.DataFrame) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    n_breakouts = int(df["breakout_attack"].sum())
    sample_start = str(df["trade_date"].min().date())
    sample_end = str(df["trade_date"].max().date())

    def _md_table(rows: pd.DataFrame) -> str:
        cols = list(rows.columns)
        lines = ["| " + " | ".join(cols) + " |",
                 "| " + " | ".join(["---"] * len(cols)) + " |"]
        for row in rows.itertuples(index=False):
            lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
        return "\n".join(lines)

    md = f"""# 攻擊品質特徵相關係數分析

樣本：{sample_start} 至 {sample_end}，突破樣本 {n_breakouts:,} 筆。

目標變數：`ret_10d`（隔日開盤進場，10 交易日後收盤計算報酬）。

所有特徵為**突破當下可知資料**，不含未來資訊。

## Spearman 相關係數

{_md_table(corr)}

## 建議加權方向

依相關係數絕對值排序，正相關特徵加分、負相關扣分。
**請人工審查後確認 `attack_quality_score` 公式，再寫入 `add_signals`。**

| 優先級 | 特徵 | 方向 | 建議權重（初始）|
|--------|------|------|----------------|
"""
    for _, row in corr.head(4).iterrows():
        direction = "加分" if row["spearman_r"] > 0 else "扣分"
        weight = min(15, max(5, int(abs(row["spearman_r"]) * 100)))
        md += f"| - | `{row['feature']}` | {direction} | {weight} |\n"

    REPORT_PATH.write_text(md, encoding="utf-8")
    print(REPORT_PATH)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = add_signals(add_features(load_bars()))
    corr = compute_correlations(df)
    corr.to_csv(OUT_DIR / "attack_quality_correlation.csv", index=False)
    write_report(corr, df)
    print(OUT_DIR / "attack_quality_correlation.csv")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2：執行並確認輸出**

```bash
cd /Users/howard/Repository/stock-k-bar && python scripts/attack_quality_analysis.py
```

期望：輸出兩個檔案路徑，`attack_quality_analysis.md` 裡有 Spearman 係數表。

- [ ] **Step 3：人工審查相關係數，決定 `attack_quality_score` 公式**

讀 `docs/K線力量判斷入門/backtests/attack_quality_analysis.md`，確認：
- 正相關特徵（r > 0）→ 加分
- 負相關特徵（r < 0）→ 扣分
- 係數 < 0.05 的特徵考慮不納入

記錄決定的公式（例如）：
```
attack_quality_score = 0
  + higher_low_count >= 5  → +15
  + gap_open == 1          → +10
  + close_pos >= 0.85      → +10  (已有)
  + pre_breakout_trend_days >= 10 → +10
  clip [0, 100]
```

- [ ] **Step 4：把公式寫入 `add_signals`**

在 `kline_course_backtest.py` 的 `add_signals` 末尾（`return df` 之前）追加：

```python
    # --- attack_quality_score（依 attack_quality_analysis.md 確認的公式）---
    aq = pd.Series(0.0, index=df.index)
    aq += np.where(df["higher_low_count"].fillna(0) >= 5, 15, 0)
    aq += np.where(df["gap_open"].fillna(0) == 1, 10, 0)
    aq += np.where(df["close_pos"].fillna(0) >= 0.85, 10, 0)
    aq += np.where(df["pre_breakout_trend_days"].fillna(0) >= 10, 10, 0)
    df["attack_quality_score"] = aq.clip(0, 100)
```

⚠️ 上方數字是**佔位初始值**，必須先跑 Step 3 查看相關係數後再填入實際權重。

- [ ] **Step 5：Commit**

```bash
git add scripts/attack_quality_analysis.py scripts/kline_course_backtest.py
git commit -m "feat(backtest): add attack quality correlation analysis and score signal"
```

---

## Task 5：`breakout_daily_scanner.py` — 整合 VP

**Files:**
- Modify: `scripts/breakout_daily_scanner.py`

- [ ] **Step 1：新增 FinMind VP 抓取函式**

在 `enrich_intraday` 函式之前插入：

```python
import sys as _sys
_VP_SAS = Path(__file__).parent.parent.parent / "stock-analysis-system"

def _ensure_sas_path() -> None:
    p = str(_VP_SAS.resolve())
    if p not in _sys.path:
        _sys.path.insert(0, p)


def fetch_vp_finmind(
    ticker: str,
    trade_date: str,
    token: str,
    sleep_seconds: float,
) -> pd.DataFrame:
    """從 FinMind TaiwanStockKBar 取分K，聚合成分價量表。

    快取邏輯沿用 finmind_intraday_kline_check.fetch_kbar。
    """
    from finmind_intraday_kline_check import fetch_kbar
    from volume_profile import build_vp_from_kbar

    kbar = fetch_kbar(ticker, trade_date, token, sleep_seconds)
    if kbar.empty:
        return pd.DataFrame(columns=["price", "volume"])

    df = kbar.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["high", "low", "volume"])
    return build_vp_from_kbar(df)


def fetch_vp_fubon(ticker: str) -> pd.DataFrame:
    """從 Fubon 即時分價量表取資料。

    FubonClient 從 stock-analysis-system 載入。
    盤後或連線失敗時回傳空 DataFrame。
    """
    _ensure_sas_path()
    try:
        from clients.fubon_client import FubonClient
        client = FubonClient()
        return client.get_intraday_volumes(ticker)
    except Exception:
        return pd.DataFrame(columns=["price", "volume"])
```

- [ ] **Step 2：修改 `enrich_intraday` 加入 VP 特徵**

在 `enrich_intraday` 函式裡，`rec.update(intraday_features(kbar))` 之後追加：

```python
        # VP 壓力區特徵
        from volume_profile import compute_vp_features
        trade_date_str = pd.Timestamp(row.trade_date).strftime("%Y-%m-%d")
        vp = fetch_vp_finmind(str(row.ticker), trade_date_str, token, sleep_seconds)
        rec.update(compute_vp_features(vp, current_close=float(row.close)))
```

- [ ] **Step 3：在 `_init_intraday_cols` 加入 VP 欄位**

修改 `_init_intraday_cols`，在 `return rows` 之前追加：

```python
    rows["vp_overhead_pct"] = np.nan
    rows["vp_dense_above"] = np.nan
    rows["vp_supply_vacuum"] = np.nan
    rows["vp_nearest_resistance_pct"] = np.nan
```

- [ ] **Step 4：把 VP 欄位加入 `intraday_cols` 清單**

在 `build_scanner` 裡，`intraday_cols` list 追加：

```python
    intraday_cols = [
        "intraday_rows",
        "intraday_strong_attack",
        "below_open_after_1130",
        "intraday_attack_failure",
        "intraday_close_pos",
        "intraday_return_pct",
        "vp_overhead_pct",       # 新增
        "vp_dense_above",        # 新增
        "vp_supply_vacuum",      # 新增
        "vp_nearest_resistance_pct",  # 新增
    ]
```

- [ ] **Step 5：把 VP 特徵加入 `score_rows`**

在 `score_rows` 裡 `rows["scanner_score"] = rows["pre_rank_score"]` 之後追加：

```python
    # VP 壓力區評分（初始值，待 VP 回測驗證後調整）
    has_vp = rows["vp_overhead_pct"].notna()
    rows["scanner_score"] += np.where(has_vp & rows["vp_supply_vacuum"].eq(True), 10, 0)
    rows["scanner_score"] += np.where(has_vp & rows["vp_dense_above"].eq(True), -10, 0)
    rows["scanner_score"] += np.where(has_vp & (rows["vp_overhead_pct"].fillna(1) < 0.15), 5, 0)
    rows["scanner_score"] += np.where(has_vp & (rows["vp_overhead_pct"].fillna(0) > 0.40), -5, 0)
```

- [ ] **Step 6：在 report 的最新交易日候選表加入 VP 欄位**

在 `write_report` 裡 `_latest_cols_base` list 追加（現有清單末尾）：

```python
        "vp_supply_vacuum",
        "vp_dense_above",
        "vp_overhead_pct",
        "vp_nearest_resistance_pct",
```

- [ ] **Step 7：驗證 scanner 執行不報錯**

```bash
cd /Users/howard/Repository/stock-k-bar
python scripts/breakout_daily_scanner.py --strict-filter-profile off --max-intraday-per-date 3 --no-shakeout
```

期望：正常產生 report，VP 欄位出現在輸出表格中（歷史 date 的候選應有 vp 值；今日若無 FinMind 資料則為 NaN）。

- [ ] **Step 8：Commit**

```bash
git add scripts/breakout_daily_scanner.py
git commit -m "feat(scanner): integrate volume profile features from FinMind kbar and Fubon intraday"
```

---

## Self-Review Checklist

- [x] `build_vp_from_kbar` 與 `compute_vp_features` 的 DataFrame 欄位名稱在所有 task 中一致（`price`, `volume`）
- [x] `fetch_vp_finmind` 重用現有 `fetch_kbar` 快取，不重複抓取
- [x] `get_intraday_volumes` 失敗回傳空 DataFrame，不 raise，呼叫方以 `vp.empty` 判斷
- [x] `attack_quality_score` 的權重標注為「初始值，待 Task 4 Step 3 確認」
- [x] VP 欄位初始化在 `_init_intraday_cols`，避免 merge 時缺欄位報錯
- [x] `scipy` 在 Task 4 中引入——確認環境已安裝（若未安裝：`pip install scipy`）
