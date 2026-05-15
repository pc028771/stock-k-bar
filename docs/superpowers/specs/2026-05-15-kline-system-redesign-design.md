# K-Line 課程系統重新設計 — Spec

**Date:** 2026-05-15
**Branch:** `main`
**Status:** Design

---

## 0. 目標與範圍

完整實作「K線力量判斷入門」（58 篇）課程明確涵蓋的內容，並為兩個尚未實作的子分類預留接口：

- **多空轉折組合K線進階教學**（26 篇）— 補完 reversal-K 結構定義
- **K線行進ing**（40 篇）— 補完 sequential K-line 行為與評分精度

預估完成度：本次設計交付後系統達**入門全覆蓋（~75–80%）**，剩 20–25% 等兩個子分類補完。

**完全乾淨重寫**：新 branch `main`，不與現有 `master` 系統相容。Data migration 另案處理。

---

## 1. 設計原則

| 原則 | 說明 |
|---|---|
| **Pure function + DataFrame in/out** | 每個條件、評分、特徵都是 `(pd.DataFrame, ...) → pd.Series` 或 `→ pd.DataFrame` |
| **Vectorized only** | 禁止 stateful Python loop。所有跨 bar 狀態用 `shift / cummin / expanding / rolling / groupby` 表達 |
| **每檔一條件** | 每個入場、出場、評分條件是獨立檔案；stub 也是獨立檔案 |
| **檔案自足** | 每個條件檔案只依賴 `pandas / numpy`，不 import 同 package 其他檔案，便於外部 repo 直接複製單檔使用 |
| **Stub = drop-in replacement** | 行進ing / 多空轉折補完時，只需替換對應檔案，不動其他 |
| **Course source comment** | 每個函式 docstring 標明課程出處（章節標題）|
| **無 extras 偷渡課程** | 任何非課程邏輯放 `extras/`，預設關閉，需 toggle 啟用 |

---

## 2. 目錄結構

```
scripts/
└── kline/
    ├── __init__.py
    ├── bars.py                       # 資料源（DB → DataFrame）
    ├── features.py                   # 衍生特徵（MA、prior_high、shadow ratio 等）
    │
    ├── entry/
    │   ├── __init__.py               # ENTRY_REGISTRY
    │   ├── breakout.py               # ✅ 入門：突破攻擊（純課程定義）
    │   ├── trend_reversal.py         # ⚪ STUB 入門：底部轉折型買點
    │   └── sunrise.py                # ⚪ STUB 行進ing：日出攻擊
    │
    ├── exit/
    │   ├── __init__.py               # EXIT_REGISTRY + 優先順序定義
    │   ├── simulator.py              # 模擬器：對每筆 entry 找最早觸發的 exit
    │   ├── gap_fill.py               # ✅ 入門：攻擊跳空回補
    │   ├── breakout_low_break.py     # ✅ 入門：突破K低點跌破
    │   ├── neckline_break.py         # ✅ 入門：頸線跌破（prior_low_20 proxy）
    │   ├── trailing_stop.py          # ✅ 入門：移動停利（緩慢推升型）
    │   ├── trend_change.py           # ✅ 入門：趨勢改變（末升低 + MA60 + 趨勢線取較高）
    │   ├── prev_day_low_break.py     # ✅ 入門：短線前一日低點跌破
    │   ├── supply_zone_reach.py      # ⚪ STUB 入門概念：到達賣壓區（需 VP）
    │   ├── ma60_neckline.py          # ⚪ STUB 行進ing：精確頸線（MA60×關鍵K線）
    │   └── reversal_k/
    │       ├── __init__.py           # REVERSAL_K_REGISTRY
    │       ├── dark_double_star.py   # ✅ 入門已定義
    │       ├── bearish_engulfing.py  # ⚪ STUB 多空轉折：空頭吞噬
    │       ├── enemy_at_gate.py      # ⚪ STUB 多空轉折：大敵當前
    │       ├── evening_star.py       # ⚪ STUB 多空轉折：夜星棄嬰
    │       ├── two_crows.py          # ⚪ STUB 多空轉折：雙鴉躍空
    │       └── gap_reversal.py       # ⚪ STUB 多空轉折：跳空反轉
    │
    ├── scoring/
    │   ├── __init__.py               # SCORING_REGISTRY
    │   ├── attack_quality.py         # ✅ 入門：攻擊品質 score
    │   ├── overhead_supply.py        # ✅ 入門：層層套牢 / 賣壓中空（OHLCV proxy）
    │   ├── ma60_rolloff.py           # ✅ 入門：MA60 扣抵壓力
    │   └── shadow_position.py        # ⚪ STUB 行進ing：影線依位置加分
    │
    └── extras/
        ├── __init__.py
        └── strict_breakout.py        # ⚙️ Toggle：close_pos / volume_ratio / red_K 過濾
                                       #   原因：入門明確說 breakout 不需要這些，但我們
                                       #   保留作為可選 filter
scripts/
├── backtest.py                       # 回測進入點：load → features → entry → simulate
└── scanner.py                        # 每日掃描進入點：load → features → entry → score
```

**圖示**：
- ✅ 本次實作
- ⚪ STUB（檔名存在，函式回傳全 False/NaN，標 `# STUB: <subcategory>`）
- ⚙️ Toggle（非課程，預設關閉）

---

## 3. 介面契約（DataFrame Schema）

### 3.1 基底 Bar DataFrame（`bars.load_bars()` 輸出）

所有條件接收的 DataFrame **必須**有這些 column，並以 `(ticker, trade_date)` 升序排序：

| Column | dtype | 說明 |
|---|---|---|
| `ticker` | str | 股票代號 |
| `trade_date` | datetime64[ns] | 交易日 |
| `open` `high` `low` `close` | float64 | OHLC |
| `volume` | float64 | 成交量（張或股，與資料源一致） |
| `ma60` | float64 | 季線（可為 NaN） |
| `ma20` `ma240` | float64 | 月線、年線（可為 NaN） |
| `is_usable` | int | 過濾旗標（1 = 可交易） |

### 3.2 衍生 Features DataFrame（`features.add_features()` 輸出）

`add_features(bars)` 在基底之上加入：

| Column | dtype | 計算 |
|---|---|---|
| `prev_close` `prev_open` `prev_high` `prev_low` | float64 | `groupby(ticker).shift(1)` |
| `prior_high_60` `prior_high_20` | float64 | shift(1).rolling(60/20).max |
| `prior_low_60` `prior_low_20` | float64 | shift(1).rolling(60/20).min |
| `range_pct` `body_pct` `body_abs` | float64 | OHLC 派生 |
| `close_pos` | float64 | (close-low)/(high-low) |
| `upper_shadow` `lower_shadow` | float64 | 上下影線長度 |
| `upper_shadow_ratio` `lower_shadow_ratio` | float64 | 影線/實體 |
| `volume_ratio` | float64 | volume / avg_volume_20 |
| `ma60_slope_5d` | float64 | ma60 / ma60.shift(5) - 1 |
| `ma60_rolling_off_close` | float64 | 60 日前的 close（用於扣抵預判） |
| `is_red` `is_black` | bool | close vs open |
| `is_doji` | bool | body_pct ≤ 0.006 且 range_pct ≥ 0.015 |

### 3.3 條件函式介面

**入場條件**：
```python
def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series indexed like df.

    Args:
        df: DataFrame from add_features(), sorted by (ticker, trade_date).

    Returns:
        bool Series, True = entry signal triggered on that bar.
    """
```

**出場條件**（vectorized 標記版）：
```python
def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series, True = exit condition triggered on that bar.

    Args:
        df: DataFrame from add_features(), sorted by (ticker, trade_date).
        entries: Optional entry signal mask. Some exits need to know
                 trade context (e.g., trailing_stop's cummin starts at entry).
                 If None, condition assumes always-on monitoring.

    Returns:
        bool Series.
    """
```

**評分因子**：
```python
def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series, score contribution from this factor.

    Magnitude convention: roughly [-50, +50] per factor.
    Final score = base 50 + sum of factors, clipped [0, 100].
    """
```

### 3.4 Trades DataFrame（`simulator.simulate()` 輸出）

每筆交易一列：

| Column | dtype | 說明 |
|---|---|---|
| `ticker` | str | |
| `entry_date` | datetime64 | 訊號日（隔日開盤進場） |
| `entry_open` | float64 | 進場價 |
| `exit_date` | datetime64 | 出場日 |
| `exit_open` | float64 | 出場價（隔日開盤） |
| `exit_reason` | str | 出場條件名稱（e.g. `gap_fill`, `breakout_low_break`） |
| `hold_days` | int | 持有天數 |
| `trade_return` | float64 | 毛報酬 |
| `trade_return_net` | float64 | 淨報酬（扣手續費 + 稅） |

---

## 4. 入場條件設計（入門範圍）

### 4.1 `entry/breakout.py` — 突破攻擊（核心）

**課程依據**：【突破跌破】突破意義的釐清、【買點賣點】股價的買點決策(三)多頭買在攻擊

> 「對於K線圖來說，價格才是最重要的事情，**不需要加上成交量**」
> 「與這一根突破的K線是否**長紅、有沒有上影線都無關**」

**純課程定義**：
```python
def detect(df: pd.DataFrame) -> pd.Series:
    return (
        (df["close"] > df["prior_high_60"])  # 突破前 60 日高點
        & (df["ma60"].notna())                # MA60 有定義
        & (df["close"] > df["ma60"])          # 多頭背景
    )
```

**不包含**：
- ❌ `is_red`（課程明確不需要）
- ❌ `close_pos ≥ 0.7`（課程明確不需要）
- ❌ `volume_ratio ≥ 1.2`（課程明確不需要）

這些移至 `extras/strict_breakout.py` 作為可選 filter。

### 4.2 `entry/trend_reversal.py` — STUB

**課程依據**：【買點賣點】出場點(一)（三大買點之一：底部轉折）

> 需識別「空頭結束、底部完成、轉折發生」三件事，需要 MA60 由下彎轉上揚。

入門未給精確判定方法（只提概念）。STUB 回傳全 False。

### 4.3 `entry/sunrise.py` — STUB（行進ing）

**課程依據**：K線行進ing → 紅K篇(七)日出攻擊

待行進ing 補完。STUB 回傳全 False。

---

## 5. 出場條件設計（入門範圍）

### 5.1 優先順序（同日多條件觸發時）

```python
EXIT_PRIORITY = [
    "reversal_k.dark_double_star",   # E2：明確反轉訊號最優先
    "reversal_k.bearish_engulfing",  # STUB
    "reversal_k.enemy_at_gate",      # STUB
    "reversal_k.evening_star",       # STUB
    "reversal_k.two_crows",          # STUB
    "reversal_k.gap_reversal",       # STUB
    "gap_fill",                       # E1：攻擊缺口回補
    "breakout_low_break",             # E4：突破K低點跌破
    "neckline_break",                 # E3：頸線跌破（隔日確認）
    "prev_day_low_break",             # 短線：前一日低點跌破
    "trailing_stop",                  # 緩慢推升型
    "trend_change",                   # 趨勢改變型
    "supply_zone_reach",              # STUB
]
```

`simulator.simulate()` 對每筆交易：對每個 bar 依優先順序檢查，遇到第一個 True 即出場。

### 5.2 `exit/gap_fill.py` — E1 攻擊跳空回補

**課程依據**：【買點賣點】出場點的各種依據(二)

```python
def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    # 個股跳空 - 大盤跳空 ≥ 2%（excess gap），當日收盤跌破前收 → 回補
    # 大盤跳空需另外傳入或在 features 階段計算
    excess_gap = df["stock_open_ret"] - df["market_open_ret"]
    return (excess_gap >= 0.02) & (df["close"] < df["prev_close"])
```

### 5.3 `exit/breakout_low_break.py` — E4

**課程依據**：【單一K線】紅色誤解：連續紅K的判斷要點

> 「突破K的低點被跌破 → 攻擊假設失效 → 停損」

```python
def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    # 需要進場 bar 的 low 作為參考。entry_low 在進場日 = bar low，
    # 後續沿用至下次進場前。注意：必須按 ticker 分組做 ffill。
    entry_low_at_signal = df["low"].where(entries)
    entry_low = (
        entry_low_at_signal
        .groupby(df["ticker"])
        .ffill()
    )
    return df["close"] < entry_low
```

> 注意：若同一 ticker 有多次進場，後一次進場會覆寫前一次的 entry_low——這是預期行為（前一筆交易應已先觸發出場）。Simulator 會用 trade_id 確保每筆交易獨立。

### 5.4 `exit/neckline_break.py` — E3

**課程依據**：【買點賣點】多方操作的出場點邏輯

頸線代理 = `prior_low_20`（精確版本待 `ma60_neckline.py` 替換）。
**隔日確認**：今天收破 + 明天收盤仍在頸線下 → 出場。

```python
def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    g = df.groupby("ticker")
    broke_today = df["close"] < df["prior_low_20"]
    broke_tomorrow = g["close"].shift(-1) < df["prior_low_20"]
    # 訊號在「確認日」（即「破的隔天」）標 True，shift(-1) 對齊：
    confirmed = broke_today.shift(1).fillna(False) & broke_today
    return confirmed
```

### 5.5 `exit/trailing_stop.py` — 緩慢推升型

**課程依據**：【買點賣點】出場點的各種依據(二)

> 「前一日低點當作停利點，有過昨高都算攻擊持續」

```python
def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    # 進場後逐日 max(prior_day_low)，跌破即出場。
    # 需 per-ticker 累計 trade_id，確保不同交易區隔開。
    trade_id = entries.groupby(df["ticker"]).cumsum()
    trade_id = trade_id.where(trade_id > 0)
    work = df.assign(_tid=trade_id)
    trailing_low = (
        work.groupby(["ticker", "_tid"])["prev_low"]
            .expanding().max()
            .reset_index(level=[0, 1], drop=True)
    )
    return df["close"] < trailing_low
```

### 5.6 `exit/trend_change.py` — 趨勢改變型

**課程依據**：【買點賣點】出場點的各種依據(一)

> 三者取較高：末升低、上升趨勢線、MA60 下彎

入門未給「末升低」與「上升趨勢線」的精確 detection，本次只實作 MA60 下彎部分：

```python
def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    # MA60 由上升轉下彎（slope 由 + 轉 −）
    slope = df["ma60_slope_5d"]
    prev_slope = df.groupby("ticker")["ma60_slope_5d"].shift(1)
    return (prev_slope >= 0) & (slope < 0)
```

末升低與趨勢線：在檔案內留 `_TODO_last_rally_low()` 與 `_TODO_rising_trendline()` 兩個函式骨架，回傳全 NaN，待後續實作（不是 stub package，因為入門有提但未給精確定義）。

### 5.7 `exit/prev_day_low_break.py` — 短線

**課程依據**：【買點賣點】買點與攻擊研判

```python
def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return df["close"] < df["prev_low"]
```

### 5.8 `exit/supply_zone_reach.py` — STUB

需要 volume profile，留 stub。

### 5.9 `exit/ma60_neckline.py` — STUB（行進ing）

精確頸線需「關鍵K線 × MA60」連結判斷，待行進ing 補完。

### 5.10 `exit/reversal_k/dark_double_star.py` — E2

**課程依據**：暗夜雙星已實作版本

```python
def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return (
        df["is_black"]
        & (df["open"] < df["prev_low"])
        & (df["body_pct"] >= 0.04)
    )
```

### 5.11 `exit/reversal_k/{bearish_engulfing, enemy_at_gate, evening_star, two_crows, gap_reversal}.py`

全部 STUB，多空轉折補完前回傳全 False。每個檔案結構：
```python
"""STUB: 多空轉折組合K線 — <pattern name>

Course source: <article title placeholder>
Replace this stub with actual structural definition after reading
multi-side-bear-side combination subcategory.
"""
def mark(df, entries=None):
    return pd.Series(False, index=df.index)
```

---

## 6. 評分因子設計（入門範圍）

### 6.1 `scoring/attack_quality.py`

直接搬移目前 `kline_course_backtest.py` 的 attack_quality_score 邏輯（base 50 + 4 個 factor）。

### 6.2 `scoring/overhead_supply.py`

層層套牢 / 賣壓中空（OHLCV proxy 版本，搬移自現有實作）。

### 6.3 `scoring/ma60_rolloff.py`

MA60 扣抵壓力（已在 `master` 有實作）。

### 6.4 `scoring/shadow_position.py` — STUB（行進ing）

依位置（新高 / 遇壓 / 整理）區分上影線意義，待行進ing 補完。

---

## 7. Registry 機制

每個子 package 的 `__init__.py` 集中註冊：

```python
# entry/__init__.py
from .breakout import detect as breakout_attack
from .trend_reversal import detect as trend_reversal  # STUB
from .sunrise import detect as sunrise_attack         # STUB (行進ing)

ENTRY_REGISTRY = {
    "breakout_attack": breakout_attack,
    "trend_reversal": trend_reversal,
    "sunrise_attack": sunrise_attack,
}
```

```python
# exit/__init__.py
from . import gap_fill, breakout_low_break, neckline_break, trailing_stop
from . import trend_change, prev_day_low_break, supply_zone_reach, ma60_neckline
from .reversal_k import REVERSAL_K_REGISTRY

EXIT_REGISTRY = {
    "gap_fill": gap_fill.mark,
    "breakout_low_break": breakout_low_break.mark,
    "neckline_break": neckline_break.mark,
    "trailing_stop": trailing_stop.mark,
    "trend_change": trend_change.mark,
    "prev_day_low_break": prev_day_low_break.mark,
    "supply_zone_reach": supply_zone_reach.mark,  # STUB
    "ma60_neckline": ma60_neckline.mark,           # STUB
    **{f"reversal_k.{k}": v for k, v in REVERSAL_K_REGISTRY.items()},
}

EXIT_PRIORITY = [...]  # 見 §5.1
```

外部 repo 只需 `from kline.exit.gap_fill import mark` 即可單獨使用某個條件，**不需要載入 registry**。

---

## 8. Simulator 設計

```python
# kline/exit/simulator.py
def simulate(
    df: pd.DataFrame,                       # 含 features 的 bars
    entries: pd.Series,                     # bool, 進場訊號
    exit_priority: list[str] | None = None, # 預設用 EXIT_PRIORITY
    exit_registry: dict | None = None,      # 預設用 EXIT_REGISTRY
    cost: float = 0.00585,                  # 手續費 + 稅
) -> pd.DataFrame:
    """
    1. 對每個 exit condition 跑 mark(df, entries)，產生 bool column。
    2. 對每筆 entry：
       - 取進場後（含當日）所有 bar 中，依優先順序找最早 True。
       - 出場日的 next_open 作為 exit_open。
    3. 組裝 trades DataFrame（schema §3.4）。
    """
```

**Vectorized 實作**：
- 先把所有 exit columns 合併成 `exit_triggers` DataFrame（shape: n_bars × n_conditions）
- 對每筆 entry，slice 進場後的列，用 `idxmax`（依優先順序）找最早觸發。

---

## 9. Stub 設計規範

### 9.1 命名
- 檔案名稱即條件名稱（snake_case）
- 函式名稱 `detect`（entry）/ `mark`（exit）/ `score`（scoring）

### 9.2 內容
```python
"""STUB: <subcategory> — <pattern name>

Course source: <章節標題 placeholder>

Replace this file with actual implementation when <subcategory>
content is read and structural definition is finalized.
"""
from __future__ import annotations
import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index)
```

### 9.3 Grep 統一標記
所有 stub 檔案第一行 docstring 開頭必為 `"""STUB:`，方便 `grep -rn '"""STUB:' scripts/kline/` 列出所有待補。

---

## 10. 已知限制

| 限制 | 影響 | 處理 |
|---|---|---|
| 兩段操作（異常體質型）路徑相依 | Vectorized 不支援「先 A 後 B」的條件啟動 | 入門只提概念未給判定，先不做。未來若需要，改用「對每筆交易跑 stage1/stage2 二次 simulate」 |
| 末升低、上升趨勢線 | 需 swing-low detection 與多點擬合，入門未給精確法 | `trend_change.py` 內留函式骨架，回 NaN，後續實作 |
| 攻擊跳空精確判定 | 入門僅用 `gap_open` 粗代理；精確版本需要「左側無交易」判斷 | E1 用 excess gap 2% 代理，留 `ma60_neckline.py` 但**這個條件本身**精確版本待行進ing |
| MA60 頸線精確版 | 需「關鍵K線 × MA60」連結 | 入門用 `prior_low_20`，行進ing 補完 |
| Supply zone exit | 需 volume profile，入門明確但需 VP 資料 | STUB，VP 系統就緒後實作 |
| Reversal-K 5 個 pattern | 入門只列名稱無結構定義 | STUB，多空轉折補完 |

---

## 11. Migration / Compatibility

**完全不相容**舊系統。Data migration 另案處理：

- 新系統的 trades DataFrame schema 與舊 `exit_simulation_trades.csv` 不同
- 評分系統重置（base 50 + factor 加總，clip [0, 100]）
- 舊系統的 `breakout_attack`（含 red K / vol / close_pos）改名為 `extra_strict_breakout`，**不會**自動套用

---

## 12. 實作分工建議（多 model）

當進入 implementation plan 階段，task 拆分建議：

| Task 類型 | 建議 model | 理由 |
|---|---|---|
| 目錄骨架 / `__init__.py` / stub 檔案產生 | Haiku | 機械性、模板化 |
| Pure function 條件實作（每個檔案 30-80 行） | Sonnet | 邏輯不複雜，平行多 worker |
| Simulator vectorized 邏輯 | Sonnet | 需要 pandas 細節，但範圍明確 |
| Features pipeline 設計 | Sonnet | 需考慮 NaN handling、groupby pitfalls |
| 整體 review / 課程合規檢查 | Opus | 跨檔案邏輯一致性、課程出處驗證 |
| 回測結果 sanity check | Sonnet | 跑數據 + 對 master 結果差異分析 |

---

## 13. 測試策略

每個條件檔案附 inline doctest 或同目錄 `_test.py`：

- Entry：建構 minimal DataFrame（5–10 bar）驗證 detect 對特定情境回傳預期 bool
- Exit：建構進場 + 後續 bar 驗證 mark 在預期日標 True
- Scoring：邊界值（base 50、極端 factor）

外部 repo 只需 `pip install pandas numpy pytest` 即可跑單檔測試。

---

## 14. 交付清單

完成定義：

- [ ] 所有目錄與 `__init__.py` 建立
- [ ] 入門範圍 14 個檔案實作（entry × 1 + exit × 7 + reversal_k × 1 + scoring × 3 + bars + features = 14）
- [ ] STUB 檔案 10 個（entry × 2 + exit × 2 + reversal_k × 5 + scoring × 1 = 10）
- [ ] `extras/strict_breakout.py` toggle
- [ ] `backtest.py` 與 `scanner.py` 進入點
- [ ] 每個檔案 inline test 或同目錄測試
- [ ] `scripts/kline/README.md`：使用方式 + 外部整合範例
- [ ] `grep -rn '"""STUB:'` 能列出所有 STUB 檔案

---

## 15. Open Questions

無——所有設計決策都已在 brainstorming 階段確認。
