# Shared Data Layer Design — `stock-data-core`

> Status: draft for review
> Date: 2026-05-27
> Owner: Howard

## Context

四個本機 Python 專案各自抓重複的市場資料：

| Repo | 主要外部呼叫 | 儲存 |
|---|---|---|
| `stock-analysis-system` | FinMind（自家 throttle）、Fubon | NDJSON cache + `data/journal.db` |
| `four-seasons-investment` | FinMind、Fubon、CSV import | `~/.four_seasons/data.sqlite`（25 張表） |
| `stock-research` | 9 家 ETF 提供商爬蟲 | per-provider CSV |
| `stock-k-bar` | 不抓，讀 four-seasons sqlite | local Parquet/CSV 分析輸出 |

問題：

1. **API key 只有一把** — FinMind sponsor token / Fubon SDK login。多個進程各自跑 token bucket，token 用量加總會超量、有觸發 IP ban 的紀錄
2. **同一份 OHLCV / 三大法人被抓兩次**（stock-analysis-system + four-seasons）
3. **SQLite 多 session lock** — `~/.four_seasons/data.sqlite` 並行讀寫常 lock
4. **無 single source of truth** — 一個 repo 跑完分析、另一個 repo 不知道；ETF holdings 沒有 schema 對齊
5. **未來搬 AWS RDS** — 需要 Postgres/MySQL 相容

目標：建立 `stock-data-core` 為共享資料層，集中 API 呼叫與 rate limiter，三個分析 repo 直連同一份 Postgres。

---

## Architecture

```
┌───────────────────────────┐
│  fetcher worker (daemon)  │   API key 只在這
│  ─ FinMind / Fubon client │   token bucket 集中
│  ─ scheduler (cron-like)  │
│  ─ queue listener         │
└─────────────┬─────────────┘
              │ writes
              ▼
     ┌──────────────────┐
     │   PostgreSQL     │   canonical store
     │ (docker → RDS)   │
     └────────┬─────────┘
              │ reads (+ fetch_request inserts)
   ┌──────────┼──────────┬────────────────┐
   ▼          ▼          ▼                ▼
stock-k-bar  four-seasons  stock-analysis  stock-research
             investment    -system
```

**核心原則**：
- API 呼叫只發生在 worker 一個進程內 → token bucket 物理上不可能被繞過
- 三個分析 repo 不持 API key、不直接呼叫 FinMind/Fubon
- 缺資料時走 `fetch_request` queue table，worker 排隊抓

---

## Repo Layout — `stock-data-core` (new)

```
stock-data-core/
├── pyproject.toml
├── docker-compose.yml          # local Postgres 17 + worker
├── alembic.ini
├── migrations/                 # Alembic schema versions
│   └── versions/
├── src/
│   ├── stock_data_core/
│   │   ├── __init__.py
│   │   ├── config.py           # DB URL, API keys (from env)
│   │   ├── sdk/                # 三個 repo 用的 client
│   │   │   ├── client.py       # StockDataClient
│   │   │   ├── ohlcv.py        # get_ohlcv(ticker, start, end)
│   │   │   ├── institutional.py
│   │   │   ├── broker.py
│   │   │   ├── etf.py
│   │   │   ├── calendar.py
│   │   │   └── fetch.py        # request_fetch(...) → enqueue
│   │   ├── models/             # SQLAlchemy ORM
│   │   ├── worker/
│   │   │   ├── daemon.py       # main loop
│   │   │   ├── scheduler.py    # 排程：每日盤後抓
│   │   │   ├── queue.py        # poll fetch_request
│   │   │   ├── ratelimit.py    # token bucket（FinMind / Fubon）
│   │   │   ├── clients/        # 從 stock-analysis-system 移過來
│   │   │   │   ├── finmind.py
│   │   │   │   ├── fubon.py
│   │   │   │   └── etf_crawlers/  # 從 stock-research 移過來
│   │   │   └── enrich.py       # MA backfill, market_calendar update
│   │   └── migrate_legacy.py   # 一次性遷移腳本（four-seasons sqlite → PG）
└── tests/
```

---

## Canonical Tables (Phase 1)

### Raw datasets

#### `ohlcv_daily`
```sql
CREATE TABLE ohlcv_daily (
  ticker        VARCHAR(10) NOT NULL,
  trade_date    DATE        NOT NULL,
  open          NUMERIC(10,2),
  high          NUMERIC(10,2),
  low           NUMERIC(10,2),
  close         NUMERIC(10,2),
  volume        BIGINT,
  -- 衍生：worker enrich 後填回（通用 MA，跨專案共用）
  ma5           NUMERIC(10,3),
  ma10          NUMERIC(10,3),
  ma20          NUMERIC(10,3),
  ma60          NUMERIC(10,3),
  ma240         NUMERIC(10,3),
  source_id     SMALLINT NOT NULL,
  ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, trade_date)
);
CREATE INDEX idx_ohlcv_date ON ohlcv_daily (trade_date);
```

#### `institutional_daily`
```sql
CREATE TABLE institutional_daily (
  ticker         VARCHAR(10) NOT NULL,
  trade_date     DATE NOT NULL,
  investor_type  VARCHAR(20) NOT NULL,  -- foreign / trust / dealer_self / dealer_hedge
  buy_shares     BIGINT,
  sell_shares    BIGINT,
  net_shares     BIGINT,
  source_id      SMALLINT NOT NULL,
  ingested_at    TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (ticker, trade_date, investor_type)
);
```

#### `broker_activity_daily`（最大宗，可 partition by month）
```sql
CREATE TABLE broker_activity_daily (
  ticker        VARCHAR(10) NOT NULL,
  trade_date    DATE NOT NULL,
  broker_id     VARCHAR(20) NOT NULL,  -- e.g. "9217" Fubon
  branch_id     VARCHAR(20),           -- 分點代碼
  buy_shares    BIGINT,
  sell_shares   BIGINT,
  net_shares    BIGINT,
  source_id     SMALLINT NOT NULL,
  ingested_at   TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (ticker, trade_date, broker_id, branch_id)
) PARTITION BY RANGE (trade_date);
-- 預建 5 年 monthly partitions
```

#### `etf_holdings_snapshot`
```sql
CREATE TABLE etf_holdings_snapshot (
  fund_id        VARCHAR(10) NOT NULL,   -- e.g. "00982A"
  snapshot_date  DATE NOT NULL,
  ticker         VARCHAR(10) NOT NULL,
  shares         BIGINT,
  weight_pct     NUMERIC(7,4),
  provider       VARCHAR(20) NOT NULL,   -- capital / nomura / unimind / ...
  ingested_at    TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (fund_id, snapshot_date, ticker)
);
```

#### `disposition_period` / `attention_period`
```sql
CREATE TABLE disposition_period (
  ticker        VARCHAR(10) NOT NULL,
  start_date    DATE NOT NULL,
  end_date      DATE,
  category      VARCHAR(20),  -- 處置 / 注意 / 警示
  reason        TEXT,
  PRIMARY KEY (ticker, start_date, category)
);
CREATE TABLE attention_period (LIKE disposition_period INCLUDING ALL);
```

#### `market_calendar`
```sql
CREATE TABLE market_calendar (
  trade_date  DATE PRIMARY KEY,
  is_open     BOOLEAN NOT NULL,
  reason      TEXT  -- 國定假日 / 颱風 / 補班
);
```

### Plumbing tables

#### `fetch_request`（queue）
```sql
CREATE TABLE fetch_request (
  id              BIGSERIAL PRIMARY KEY,
  dataset         VARCHAR(40) NOT NULL,   -- ohlcv / institutional / broker / etf / disposition
  ticker          VARCHAR(10),            -- NULL = 全市場
  start_date      DATE NOT NULL,
  end_date        DATE NOT NULL,
  requested_by    VARCHAR(40),            -- repo 名稱，方便 audit
  status          VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / running / done / failed
  attempts        SMALLINT NOT NULL DEFAULT 0,
  error           TEXT,
  created_at      TIMESTAMPTZ DEFAULT now(),
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ
);
CREATE INDEX idx_fetch_pending ON fetch_request (status, created_at) WHERE status = 'pending';
```

Worker 用 `LISTEN/NOTIFY` + 5s poll fallback。SDK 提供 `client.request_fetch(...)` 同步等待（poll 至 status = done）或 fire-and-forget 兩種模式。

#### `raw_data_batch`（audit log）
```sql
CREATE TABLE raw_data_batch (
  id            BIGSERIAL PRIMARY KEY,
  request_id    BIGINT REFERENCES fetch_request(id),
  source        VARCHAR(20) NOT NULL,   -- finmind / fubon / etf_<provider>
  dataset       VARCHAR(40) NOT NULL,
  symbol_count  INTEGER,
  row_count     INTEGER,
  api_calls     INTEGER,                -- 給 rate limit 對帳
  started_at    TIMESTAMPTZ NOT NULL,
  finished_at   TIMESTAMPTZ NOT NULL,
  success       BOOLEAN NOT NULL,
  error         TEXT
);
```

#### `data_source` (registry)
```sql
CREATE TABLE data_source (
  id            SMALLINT PRIMARY KEY,
  name          VARCHAR(40) UNIQUE,     -- finmind / fubon / etf_capital / ...
  priority      SMALLINT,               -- 衝突時優先序
  is_active     BOOLEAN DEFAULT TRUE
);
```

---

## Rate Limiter（集中）

Worker daemon 內單一 token bucket，per source：

| Source | Quota | 實作 |
|---|---|---|
| FinMind sponsor | 4500 req/hr | `asyncio.Semaphore` + leak rate |
| Fubon REST | 300 req/min | 同上 |
| Fubon intraday | 60 req/min | 同上 |
| ETF crawlers | 1 req/3s per provider | per-domain queue |

`worker/ratelimit.py` 提供 `async def acquire(source, weight=1)`。
所有 `clients/*.py` 必須走這層才能發 request。

由於 API key 環境變數只給 worker 容器讀，**三個分析 repo 拿不到 key，物理上不可能繞過**。

---

## SDK API（三個分析 repo 用）

```python
from stock_data_core import StockDataClient

client = StockDataClient()  # 從 env 讀 DB URL

# 讀 OHLCV（含 MA）
df = client.ohlcv.get(ticker="2330", start="2025-01-01", end="2026-05-27")

# 缺資料時觸發 fetch
result = client.fetch.request(
    dataset="ohlcv",
    ticker="2330",
    start="2026-05-20",
    end="2026-05-27",
    wait=True,  # 阻塞直到 worker 完成
    timeout=60,
)

# 三大法人
inst = client.institutional.get(ticker="2330", start="...", end="...")

# 主力分點
brokers = client.broker.get(ticker="2330", trade_date="2026-05-26")

# ETF holdings
holdings = client.etf.holdings(fund_id="00982A", date="2026-05-26")

# Calendar
is_trading_day = client.calendar.is_open("2026-05-27")
```

底層 read 路徑：直接走 SQLAlchemy → Postgres，**沒有 HTTP service hop**（穩定性 = Postgres 穩定性）。

---

## Migration Plan

採三階段保守切換 — worker 跟新 DB 自證穩定後才讓 repo 切過去。Postgres **本機 docker 起步**，上雲 deferred。

### Step 1 — Worker + Postgres 起來確保運作正常
1. 新 repo `stock-data-core`，docker-compose（Postgres 17 + 1 worker container），**只在本機**
2. Alembic migrations 跑全部 schema
3. Worker daemon 排程：每交易日 14:00 抓 OHLCV + 三大法人；19:00 抓主力分點；週末 ETF holdings；月初 calendar
4. **僅寫入 Postgres**，三個 repo 此時完全不知道 Postgres 存在
5. 連跑 5 個交易日，自我驗證：
   - `raw_data_batch` 全綠
   - rate limiter 沒爆量（`api_calls` 加總對得起 FinMind dashboard）
   - 隨機抽 100 ticker × 60 days 數值 vs 舊 `~/.four_seasons/data.sqlite` 一致
   - Queue 模擬故障演練

### Step 2 — Worker 雙寫（Postgres + 舊 sqlite）
6. Worker 加 dual-write mode（env flag `DUAL_WRITE_SQLITE=1`）：
   - 主寫 Postgres
   - 同步寫 `~/.four_seasons/data.sqlite`（保留 four-seasons 原 schema）
   - 任一邊寫失敗 → 整筆 rollback、記 `raw_data_batch.error`
7. 三個 repo 維持現狀，繼續用 sqlite（**完全無感**）
8. 連跑 10 個交易日，每日盤後跑 parity check script：對拍兩邊每張表 row count + checksum
9. 期間發現 schema 對應問題、命名衝突等都在此階段修

### Step 3 — Repo 切換到 shared DB
10. Parity 連 10 天無差異 → 把 `stock-data-core` SDK merge / `pip install -e` 到三個 repo
11. 一次切一個 repo：先 stock-k-bar（讀為主，風險最低）→ stock-research → stock-analysis-system → four-seasons-investment
12. 每切一個跑該 repo 既有 smoke test + 一個交易日觀察
13. 全切完後 worker 關掉 dual-write，舊 sqlite 進入唯讀凍結期一週
14. 一週無回頭 issue → 移除舊 sqlite 路徑、清掉各 repo 內 FinMind/Fubon client 死碼

### Step 4 — AWS RDS（**deferred，後續再評估**）
- 本機 docker Postgres 持續運作至少 1 個月，確認模式穩
- 真要上雲時：`pg_dump` → RDS Postgres Taipei (ap-east-2)，db.t4g.small 起步（~$33/月）
- 三個 repo 的 DB URL 改 env var 切過去；worker 仍可本機跑（讀寫遠端 RDS）

---

## Stability Considerations

- **Postgres 穩定性** = 整個資料層穩定性。RDS Multi-AZ 之後 99.95% SLA
- **Worker 掛掉不影響分析** — 三個 repo 仍可讀歷史資料；只是新資料停留
- **Queue 處理失敗** — `fetch_request.attempts` + exponential backoff，3 次失敗標 `failed` 並記 error
- **DB 連線池** — 三個 repo 各跑 SQLAlchemy pool (size=5)，Postgres `max_connections=100` 足夠
- **Schema 版本相容** — Alembic 嚴格 forward-only migrations，SDK 在啟動時檢查 schema_version 對得上

---

## What's Out of Scope (留各專案)

- 各 repo 的 screening_result / backtest_run / teacher_picks / 分析輸出
- K 線型態識別、shakeout 訊號（屬 stock-k-bar 領域邏輯）
- 四季投資法 § 條件運算（屬 four-seasons 領域邏輯）
- Zhuli 課程結構整理（屬 stock-k-bar/docs）

這些可選擇性地之後再評估是否上 shared DB。

---

## Critical Files to Create / Modify

### 新建
- `stock-data-core/` 整個 repo（新獨立 git repo，**code 在 worktree 寫**）
- `stock-data-core/migrations/versions/0001_initial.py`
- `stock-data-core/src/stock_data_core/worker/clients/finmind.py`（移自 `stock-analysis-system/clients/finmind_client.py`）
- `stock-data-core/src/stock_data_core/worker/clients/fubon.py`（移自 `stock-analysis-system/clients/fubon_client.py`）
- `stock-data-core/src/stock_data_core/worker/clients/etf_crawlers/`（移自 `stock-research/src/crawlers/`）

### 三 repo 改動點
- `four-seasons-investment/src/data_sources/finmind_adapter.py` → 改 import SDK
- `stock-analysis-system/clients/finmind_client.py` → 刪除，改 SDK
- `stock-research/src/crawlers/` → 移到 worker 後 stub 保留 import path
- `stock-k-bar/scripts/.../load_bars.py` → 改 `client.ohlcv.get(...)`

---

## Verification Plan

1. **Schema migrations**：`alembic upgrade head` 在乾淨 docker compose 環境跑過
2. **遷移正確性**：`migrate_legacy.py` 後跑 `tests/test_migration_parity.py` — 隨機抽 100 ticker × 60 trading days 對拍 OHLCV / 三大法人數值
3. **Rate limiter**：壓測 worker — 同時觸發 50 個 fetch_request，確認 FinMind 不超 4500/hr
4. **SDK 讀取**：三個 repo 各跑一個 minimal smoke test：`get_ohlcv("2330", "2026-05-01", "2026-05-27")` 回 17 rows
5. **Queue 故障演練**：手動殺 worker，分析 repo 跑 `request_fetch(wait=True)` 確認 timeout 不卡死
6. **資料新鮮度**：worker 跑滿 5 個交易日後，`SELECT MAX(trade_date) FROM ohlcv_daily` = T-0（盤後跑完）

---

## Open Questions

- 預設 SDK auth 模式？本機 trust（localhost-only）；上 RDS 後改 IAM auth 或 password + VPC？
- Worker scheduler 用什麼？APScheduler 簡單；Prefect/Dagster 過殺。傾向 APScheduler。
- 三大法人 `investor_type` enum 對齊 — 既有 four-seasons 的命名與 FinMind 原始 key 不一致，遷移時要決定 canonical 拼法。
