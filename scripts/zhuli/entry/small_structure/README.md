# small_structure — 小結構整理 Scanner Module

偵測「N字攻擊後的高位整理末端」pattern。

- **狀態**: 已驗證（5/22）
- **結果**: 全市場 77% 上漲率、327 候選、平均 +1.99%
- **老師來源**: 5/20-5/21 群創 N字上攻教學

## 快速開始

```python
from zhuli.entry.small_structure import detect, detect_with_diagnostics, run_watchlist

# 基本偵測
sig = detect(df)  # bool Series

# 含診斷資訊
diag = detect_with_diagnostics(df)  # DataFrame with cond_* columns

# Watchlist 三級分類
wl = run_watchlist(df, universe='all', target_date='2026-05-29')
```

## CLI

```bash
# Detect mode（全市場掃描）
python -m zhuli.entry.small_structure --date 2026-05-29

# Watchlist mode（三級分類）
python -m zhuli.entry.small_structure --date 2026-05-29 --watchlist

# Watchlist + 族群 universe 過濾
python -m zhuli.entry.small_structure --date 2026-05-29 --watchlist --universe sector_all
python -m zhuli.entry.small_structure --date 2026-05-29 --watchlist --universe sector_week

# Validation suite
python -m zhuli.entry.small_structure --validate
python -m zhuli.entry.small_structure --validate --case A B E
```

## 檔案結構

```
small_structure/
├── __init__.py          # 公開 API: detect / detect_with_diagnostics / run_watchlist / run_scan
├── __main__.py          # CLI 入口
├── README.md            # 本文件
├── spec.md              # 偵測邏輯 + 老師原話來源 + 驗證歷史
├── detector.py          # 核心 detect() (6 條件已驗證 spec)
├── helpers.py           # 共用工具（高位判定 / 平台收斂 / 量縮 / 攻擊偵測）
├── watchlist.py         # 三級分類 + 族群 universe 過濾
├── validation.py        # A/B/C/D/E 五個 backtest
└── tests/
    ├── __init__.py
    └── test_detector.py  # 邊界 case 單元測試
```

## Universe 選項（降雜訊）

| Universe | 說明 | 預期候選數 |
|---|---|---|
| `all` | 全市場（預設） | ~327 (5/20 基準) |
| `sector_all` | 老師近 6 月族群（~295 檔去重） | 較少 |
| `sector_week` | 該週主推族群（teacher_sector_timeline.md） | 最少 |

> **Case E validation** 會自動對比三版漲停率，建議在首次部署時跑一次。

## 鐵則

- **不可調整 6 條件 spec** — 已驗證，改動需重跑全市場回測
- **不可混入 kline/ 課程** — 這是主力大課程 (zhuli) 的 module
- **import 向後相容** — `from zhuli.entry.small_structure import detect` 不變
