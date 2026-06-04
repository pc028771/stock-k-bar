# minute_bars Consolidation Report

Generated: 2026-06-04 12:05:34

## Backup
- Path: `/tmp/data.sqlite.backup_20260604_120518`

## Source Row Counts
| 來源 | 嘗試插入 |
|---|---|
| Source 1 — CSV cache (`finmind_kbar_cache/*.csv`) | 84,653 |
| Source 2 — JSON cache (`.cache/finmind/kbar/`) | 864 |
| Source 3 — Small SQLite (`attack_cost_minute_data.sqlite`) | 864 |
| **Total attempted** | **86,381** |

Note: `INSERT OR IGNORE` — duplicates across sources are silently dropped.

## Main DB minute_bars Table (Final)
- Total rows: **85,517**
- Unique tickers: 248
- Unique dates: 34
- Date span: 2021-12-13 ~ 2026-05-14
- NULL ohlcv rows: 0

## Schema Deviations / Data Quality
- CSV Source: columns `date,minute,stock_id,open,high,low,close,volume` — normalized to `(ticker, trade_date, ts, open, high, low, close, volume)`
- JSON Source: list of `{minute, open, high, low, close, volume}` — ticker/date from path
- SQLite Source: already matches target schema exactly

## detector helper 改動
- `scripts/kline/patterns/attack_cost_displayed.py`
  - `_MINUTE_BAR_DB` removed
  - `get_max_volume_price_intraday()` now calls `get_minute_bars()` from `scripts/kline/minute_bars.py`
  - New helper `scripts/kline/minute_bars.py` — copies main DB to /tmp before reading

## detector 9-case 結果（與前次一致）
| ticker | date | max_vol_high | 判斷 |
|---|---|---|---|
| 3289 宜特 | 2023-03-08 | 96.8 | 漲停 ✓ |
| 3693 營邦 | 2023-04-11 | 151.5 | 漲停 ✓ |
| 3693 營邦 | 2023-04-12 | 160.5 | 有資料 |
| 8215 明基材 | 2021-12-13 | 43.5 | 漲停 ✓ |
| 6209 今國光 | 2023-12-15 | 29.0 | 非漲停 ✓ (反例正確排除) |

## pytest 結果
- `uv run pytest tests/kline/ -q` → **554 passed**

## Files to Consider Deleting (user confirm)
- `data/analysis/kline_patterns/attack_cost_minute_data.sqlite` — already integrated into main DB **請 user 確認再刪**
- `~/.four_seasons/finmind_kbar_cache/*.csv` — raw source, keep for reference
- `~/.cache/finmind/kbar/*.json` — used by FinMind client, keep

## 備註
- Source 2 (JSON, 864 rows) 與 Source 3 (SQLite, 864 rows) 資料完全重疊（同一批 attack_cost case）
  → `INSERT OR IGNORE` 去重後最終 85,517 rows（並非 86,381）
