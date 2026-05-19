# zhuli/ — 主力大全方位操盤教戰守則 Scanner Module

Course: 主力大全方位操盤教戰守則（林家洋）  
Phase: 1（Entry signal scanner only; Phase 2 adds backtest engine）

---

## Module Structure

```
scripts/zhuli/
├── __init__.py           # Package root
├── config.py             # SuffocationConfig — all calibratable parameters
├── calibration.py        # Calibration interface stub (Phase 2)
├── features.py           # add_zhuli_features() — zhuli-specific derived columns
├── sanity_check.py       # Verify scanner hits §H instructor cases
├── entry/
│   ├── __init__.py       # ENTRY_REGISTRY = {'suffocation': detect}
│   └── suffocation.py    # H 窒息量 entry signal (情境 A + B)
└── README.md             # This file

scripts/zhuli_scanner.py  # CLI entry point
```

---

## Quick Start

```bash
# Show help
python scripts/zhuli_scanner.py --help

# Scan for today's signals
python scripts/zhuli_scanner.py --signal suffocation

# Scan a specific date
python scripts/zhuli_scanner.py --date 2021-03-10

# Top 50 candidates across all dates
python scripts/zhuli_scanner.py --top-n 50

# Run sanity check against §H instructor cases
python scripts/zhuli_scanner.py --sanity-check --verbose
# or:
python -m zhuli.sanity_check --verbose

# Override config
python scripts/zhuli_scanner.py --config-override max20_volume_ratio=0.12 min_close=15
python scripts/zhuli_scanner.py --config my_overrides.json

# Print effective config
python scripts/zhuli_scanner.py --show-config
```

---

## H 窒息量策略（zhuli_suffocation）

**Course source:** strategy-indicators.md §H + course_principles.md §16

### Entry Logic

1. **前一根 K（窒息量 K）：** `volume < max(vol_20d) * 0.10`
2. **月線必須上彎：** `ma20_slope > 0`（即使價跌破月線，月線斜率 > 0 仍成立）
3. **今日為出量 K：**
   - 成交量 > 前一根窒息量
   - 形態：紅K，或下影線 > 實體長度的綠K
4. **兩種情境：**
   - 情境 A — 收盤 ≥ 月線（主要情境）
   - 情境 B — 收盤 < 月線（月線上彎但價已跌破，潛在反轉）

**停損：** 出量 K 低點

### Output Columns

| 欄位 | 說明 |
|---|---|
| ticker | 股票代號 |
| signal_date | 出量 K 日期（進場參考日）|
| scenario | A（月線上）或 B（月線下）|
| suffocation_date | 窒息量 K 日期 |
| suffocation_vol | 窒息量 K 成交量 |
| suffocation_vol_ratio | 窒息量 / 20日最大量 |
| breakout_close | 出量 K 收盤價 |
| breakout_vol | 出量 K 成交量 |
| breakout_bar_type | red / green_long_lower_shadow |
| ma20 | 月線數值 |
| ma20_slope | 月線斜率 |
| ideal_ma_align | 是否理想多頭排列（5>10>20>60 全上彎）|
| stop_loss | 出量 K 低點（停損參考）|

---

## Calibration Interface

`config.py` 的所有欄位均可透過以下方式覆寫：

```python
# CLI override
python scripts/zhuli_scanner.py --config-override max20_volume_ratio=0.12

# JSON file
python scripts/zhuli_scanner.py --config path/to/overrides.json

# Programmatic
from zhuli.config import SuffocationConfig
cfg = SuffocationConfig(max20_volume_ratio=0.12, min_close=15)
```

`calibration.py` 提供 Phase 2 的更新接口（目前為 stub）：

```python
from zhuli.calibration import calibrate_from_cases
# Phase 2: cfg_updates = calibrate_from_cases("instructor_cases.csv")
```

---

## Sanity Check

**5 個講師案例（§H 驗證）：**

| 代號 | 名稱 | 日期 | 情境 |
|---|---|---|---|
| 3533 | 嘉澤 | 2020-12-30 | A |
| 8150 | 南茂 | 2021-03-10 | A |
| 6284 | 佳邦 | 2021-01-22 | A |
| 2338 | 光罩 | 2021-02-18 | B |
| 1590 | 亞德客-KY | 2020-12-24 | A |

---

## Architecture Notes

- **不動 `kline/`** — zhuli 模組完全獨立，只重用 `kline.bars.load_bars()` 與 `kline.features.add_features()`。
- **Feature layering：** `load_bars()` → `add_features()` → `add_zhuli_features()` → `detect()`。
- **No backtest in Phase 1** — `detect()` 只輸出訊號清單，沒有模擬出場邏輯。
- **Calibration stub** — `calibration.py` 定義接口但不實作，Phase 2 補完。
- **Isolation from K-Line Power course** — 命名前綴 `zhuli_*`，放在獨立目錄，不污染 `kline/`。
