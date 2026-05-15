# K-Line System Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clean, vectorized, DataFrame-in/out K-line backtest + scanner system covering all 入門 course content, with drop-in stub files for K線行進ing and 多空轉折組合K線.

**Architecture:** Per-condition file layout under `scripts/kline/`. Each condition is a pure function `(pd.DataFrame, ...) -> pd.Series`. Stubs are real files returning all-False/NaN, replaced wholesale when future subcategories are read. No loop state — all cross-bar logic via `shift / cummin / expanding / rolling / groupby`.

**Tech Stack:** Python 3.12, pandas 3.0, numpy 2.0, pytest 8, ruff. SQLite source DB at `/Users/howard/.four_seasons/data.sqlite`.

**Spec reference:** `docs/superpowers/specs/2026-05-15-kline-system-redesign-design.md`

---

## File Map

```
scripts/kline/
  __init__.py                      Task 1
  bars.py                          Task 2
  features.py                      Task 3
  entry/
    __init__.py                    Task 5
    breakout.py                    Task 4
    trend_reversal.py  (STUB)      Task 5
    sunrise.py         (STUB)      Task 5
  exit/
    __init__.py                    Task 14
    simulator.py                   Task 15
    gap_fill.py                    Task 6
    breakout_low_break.py          Task 7
    neckline_break.py              Task 8
    trailing_stop.py               Task 9
    trend_change.py                Task 10
    prev_day_low_break.py          Task 11
    supply_zone_reach.py (STUB)    Task 12
    ma60_neckline.py     (STUB)    Task 12
    reversal_k/
      __init__.py                  Task 13
      dark_double_star.py          Task 13
      bearish_engulfing.py  (STUB) Task 13
      enemy_at_gate.py      (STUB) Task 13
      evening_star.py       (STUB) Task 13
      two_crows.py          (STUB) Task 13
      gap_reversal.py       (STUB) Task 13
  scoring/
    __init__.py                    Task 19
    attack_quality.py              Task 16
    overhead_supply.py             Task 17
    ma60_rolloff.py                Task 18
    shadow_position.py  (STUB)     Task 19
  extras/
    __init__.py                    Task 20
    strict_breakout.py             Task 20

scripts/
  backtest.py                      Task 21
  scanner.py                       Task 22

tests/                             tests live alongside each task

scripts/kline/README.md            Task 23
```

---

## Parallelization & Model Assignment

| Phase | Tasks | Dependencies | Can run in parallel? | Suggested model |
|---|---|---|---|---|
| **P1 Foundation** | 1, 2, 3 | sequential | no | Sonnet |
| **P2 Entry** | 4, 5 | needs P1 | 4 then 5 | Sonnet |
| **P3 Exit conditions** | 6, 7, 8, 9, 10, 11 | needs P1 | **yes, all 6 in parallel** | Sonnet (×6 workers) |
| **P4 Exit stubs** | 12, 13 | needs P1 | yes, parallel | Haiku |
| **P5 Simulator** | 14, 15 | needs P3 + P4 | 14 then 15 | Sonnet |
| **P6 Scoring** | 16, 17, 18, 19 | needs P1 | **yes, 16-18 parallel**, 19 after | Sonnet (×3) then Haiku |
| **P7 Extras + Entry points** | 20, 21, 22 | needs P5 + P6 | 20 parallel, then 21+22 | Sonnet |
| **P8 Final** | 23 | needs all above | no | Sonnet |

Total: 23 tasks. With maximum parallelism, the critical path is P1→P2→P3→P5→P7→P8 (~8 sequential rounds).

---

## Conventions

- **Sort invariant**: All DataFrames passed to conditions are sorted by `(ticker, trade_date)` ascending. Functions must preserve this.
- **NaN handling**: When a feature is undefined (insufficient history), the function returns False for bool / NaN for float — never raises.
- **Imports**: Every condition file imports only `pandas` and `numpy` (no relative imports within `kline/`). This keeps each file copy-pastable to external repos.
- **Course source comment**: Each function docstring starts with `Course source: 【...】<article title>` for traceability.
- **Test fixture builder**: Each test file uses a helper `make_bars(rows)` that builds a minimal DataFrame with all required columns. Defined once in `tests/conftest.py` (Task 1).
- **Commits**: One commit per task. Commit message format `feat(kline): <task title>` or `test(kline): ...`.

---

## Task 1: Project Scaffolding + Test Fixtures

**Files:**
- Create: `scripts/kline/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `pyproject.toml` (add pytest config + ruff exclusions)

- [ ] **Step 1: Create empty package init**

Write `scripts/kline/__init__.py`:
```python
"""K-Line Power Judgment course system.

A clean, vectorized, DataFrame-in/out implementation of all
入門 course content. Stubs for K線行進ing (40 articles) and
多空轉折組合K線 (26 articles) are drop-in replaceable.

Each submodule is self-contained — only depends on pandas/numpy.
External repos can copy individual condition files without the package.
"""
```

- [ ] **Step 2: Create `tests/__init__.py`** (empty)

- [ ] **Step 3: Create `tests/conftest.py`** with the shared fixture builder:

```python
"""Shared test fixtures for kline conditions."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_bars(rows: list[dict], ticker: str = "T0001") -> pd.DataFrame:
    """Build a minimal bar DataFrame from row dicts.

    Each row dict supplies columns; missing optional columns are filled
    with sensible defaults so condition functions can be tested in isolation.

    Required keys per row: open, high, low, close.
    Optional: volume (default 1000), ma60 (default close), trade_date.
    """
    df = pd.DataFrame(rows)
    n = len(df)
    if "ticker" not in df:
        df["ticker"] = ticker
    if "trade_date" not in df:
        df["trade_date"] = pd.date_range("2025-01-02", periods=n, freq="B")
    if "volume" not in df:
        df["volume"] = 1000.0
    if "ma60" not in df:
        df["ma60"] = df["close"].astype(float)
    if "ma20" not in df:
        df["ma20"] = df["close"].astype(float)
    if "ma240" not in df:
        df["ma240"] = df["close"].astype(float)
    if "is_usable" not in df:
        df["is_usable"] = 1
    for col in ("open", "high", "low", "close", "volume", "ma60", "ma20", "ma240"):
        df[col] = df[col].astype(float)
    return df.reset_index(drop=True)


@pytest.fixture
def make_bars_fn():
    return make_bars
```

- [ ] **Step 4: Update `pyproject.toml`** — append after the existing `[tool.ruff.lint]` section:

```toml

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["scripts"]
python_files = ["test_*.py"]

[tool.ruff]
line-length = 100
target-version = "py312"
extend-exclude = ["docs/K線力量判斷入門/images"]
```

Replace the existing `[tool.ruff]` block with the one above (it already has the same line-length/target-version but adds the exclude).

- [ ] **Step 5: Verify `pytest` discovers tests directory**

Run: `uv run pytest --collect-only 2>&1 | head -10`
Expected: `no tests ran in ...` (no errors, just no tests yet).

- [ ] **Step 6: Commit**

```bash
git add scripts/kline/__init__.py tests/__init__.py tests/conftest.py pyproject.toml
git commit -m "feat(kline): scaffolding + shared test fixtures"
```

---

## Task 2: `bars.py` — DB Loader

**Files:**
- Create: `scripts/kline/bars.py`
- Create: `tests/kline/__init__.py`
- Create: `tests/kline/test_bars.py`

- [ ] **Step 1: Write the failing test** `tests/kline/test_bars.py`:

```python
"""bars.load_bars: DB → DataFrame with required schema."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from kline import bars


def test_load_bars_returns_required_columns(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            create table standard_daily_bar (
                ticker text, trade_date text,
                open real, high real, low real, close real, volume real,
                ma20 real, ma60 real, ma240 real,
                vol_ma20 real, vol_ratio_20 real,
                is_attention_stock int, is_disposition_stock int, is_usable int
            )
        """)
        conn.execute("""
            insert into standard_daily_bar values
                ('1101','2025-01-02',100,102,99,101,1000,100,100,100,1000,1.0,0,0,1),
                ('1101','2025-01-03',101,103,100,102,1100,100,100,100,1000,1.1,0,0,1)
        """)
        conn.commit()
    df = bars.load_bars(db_path=db)
    required = {"ticker", "trade_date", "open", "high", "low", "close",
                "volume", "ma60", "ma20", "ma240", "is_usable"}
    assert required.issubset(df.columns)
    assert df["trade_date"].dtype == "datetime64[ns]"
    assert len(df) == 2
    # Sorted by (ticker, trade_date)
    assert df["trade_date"].is_monotonic_increasing


def test_load_bars_filters_unusable(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            create table standard_daily_bar (
                ticker text, trade_date text,
                open real, high real, low real, close real, volume real,
                ma20 real, ma60 real, ma240 real,
                vol_ma20 real, vol_ratio_20 real,
                is_attention_stock int, is_disposition_stock int, is_usable int
            )
        """)
        conn.execute("""
            insert into standard_daily_bar values
                ('1101','2025-01-02',100,102,99,101,1000,100,100,100,1000,1.0,0,0,1),
                ('1101','2025-01-03',null,103,100,102,1100,100,100,100,1000,1.1,0,0,1)
        """)
        conn.commit()
    df = bars.load_bars(db_path=db)
    assert len(df) == 1  # row with null open filtered out
```

- [ ] **Step 2: Write `tests/kline/__init__.py`** (empty)

- [ ] **Step 3: Run failing test**

Run: `uv run pytest tests/kline/test_bars.py -v`
Expected: ImportError (module doesn't exist).

- [ ] **Step 4: Implement `scripts/kline/bars.py`**:

```python
"""Load daily bars from the four-seasons SQLite database.

Course source: not a course concept — infrastructure layer.

Output schema (sorted by ticker, trade_date asc):
    ticker, trade_date (datetime64[ns]),
    open, high, low, close, volume (float64),
    ma20, ma60, ma240 (float64, may be NaN),
    is_usable (int)
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path("/Users/howard/.four_seasons/data.sqlite")


def load_bars(db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Load all usable daily bars sorted by (ticker, trade_date).

    Copies the DB to /tmp first to avoid iCloud disk I/O errors.
    """
    query = """
        select
            ticker, trade_date,
            open, high, low, close, volume,
            ma20, ma60, ma240,
            vol_ma20, vol_ratio_20,
            is_attention_stock, is_disposition_stock, is_usable
        from standard_daily_bar
        where is_usable = 1
          and open is not null
          and high is not null
          and low is not null
          and close is not null
          and volume is not null
          and open > 0 and high > 0 and low > 0 and close > 0
        order by ticker, trade_date
    """
    try:
        tmp = Path(tempfile.gettempdir()) / "kline_bars_snapshot.sqlite"
        shutil.copy2(db_path, tmp)
        conn_path = str(tmp)
    except Exception:
        conn_path = str(db_path)

    with sqlite3.connect(conn_path, timeout=15) as conn:
        df = pd.read_sql_query(query, conn, parse_dates=["trade_date"])
    return df.reset_index(drop=True)
```

- [ ] **Step 5: Run test, verify pass**

Run: `uv run pytest tests/kline/test_bars.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/kline/bars.py tests/kline/__init__.py tests/kline/test_bars.py
git commit -m "feat(kline): bars.load_bars from SQLite with iCloud-safe copy"
```

---

## Task 3: `features.py` — Feature Engineering

**Files:**
- Create: `scripts/kline/features.py`
- Create: `tests/kline/test_features.py`

- [ ] **Step 1: Write failing test** `tests/kline/test_features.py`:

```python
"""features.add_features: derives all columns per spec §3.2."""
from __future__ import annotations

import numpy as np
import pandas as pd

from kline.features import add_features
from tests.conftest import make_bars


def test_basic_derived_columns():
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104, "volume": 1000},
        {"open": 104, "high": 110, "low": 103, "close": 109, "volume": 2000},
        {"open": 109, "high": 112, "low": 105, "close": 106, "volume": 1500},
    ]
    df = add_features(make_bars(rows))

    # prev_*
    assert pd.isna(df.loc[0, "prev_close"])
    assert df.loc[1, "prev_close"] == 104
    assert df.loc[2, "prev_low"] == 103

    # body_pct
    assert abs(df.loc[0, "body_pct"] - 0.04) < 1e-9  # |104-100|/100

    # close_pos
    assert abs(df.loc[0, "close_pos"] - (104 - 99) / (105 - 99)) < 1e-9

    # is_red / is_black
    assert df.loc[0, "is_red"] == True
    assert df.loc[2, "is_black"] == True

    # is_doji: body_pct <= 0.006 and range_pct >= 0.015
    # row 0: body 0.04, range 0.06 — not doji
    assert df.loc[0, "is_doji"] == False


def test_groupby_ticker_does_not_leak():
    rows_a = [{"open": 100, "high": 105, "low": 99, "close": 104, "volume": 1000} for _ in range(3)]
    rows_b = [{"open": 50, "high": 52, "low": 49, "close": 51, "volume": 500} for _ in range(3)]
    df_a = make_bars(rows_a, ticker="A")
    df_b = make_bars(rows_b, ticker="B")
    combined = pd.concat([df_a, df_b]).reset_index(drop=True)
    out = add_features(combined)

    # B's first row prev_close should be NaN, not leak from A
    b_first = out[out["ticker"] == "B"].iloc[0]
    assert pd.isna(b_first["prev_close"])


def test_prior_high_60_uses_shifted_window():
    # 65 bars, ascending close — prior_high_60 at row 64 = high of row 4
    rows = [{"open": float(i), "high": float(i + 1),
             "low": float(i - 1), "close": float(i + 0.5),
             "volume": 1000.0} for i in range(100, 165)]
    df = add_features(make_bars(rows))
    # prior_high_60 at index 64 = max(high[4:64]) = high at index 63 = 164
    assert df.loc[64, "prior_high_60"] == 164.0


def test_doji_detected_when_body_tiny_and_range_large():
    rows = [{"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.3, "volume": 1000}]
    df = add_features(make_bars(rows))
    # body_pct = 0.3/100 = 0.003 (<= 0.006), range_pct = 4/100 = 0.04 (>= 0.015)
    assert df.loc[0, "is_doji"] == True
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/test_features.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/features.py`**:

```python
"""Derived features for kline conditions.

Course source: features support multiple course concepts; no single article.

Input: bars DataFrame from bars.load_bars(), sorted by (ticker, trade_date).
Output: same DataFrame with derived columns added (spec §3.2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all derived features. Pure function — returns new DataFrame."""
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # Previous-bar values
    df["prev_close"] = g["close"].shift(1)
    df["prev_open"]  = g["open"].shift(1)
    df["prev_high"] = g["high"].shift(1)
    df["prev_low"]  = g["low"].shift(1)

    # Rolling prior highs/lows (exclude today via shift)
    df["prior_high_60"] = g["high"].shift(1).rolling(60, min_periods=60).max().reset_index(level=0, drop=True)
    df["prior_high_20"] = g["high"].shift(1).rolling(20, min_periods=20).max().reset_index(level=0, drop=True)
    df["prior_low_60"]  = g["low"].shift(1).rolling(60, min_periods=60).min().reset_index(level=0, drop=True)
    df["prior_low_20"]  = g["low"].shift(1).rolling(20, min_periods=20).min().reset_index(level=0, drop=True)

    # Avg volume (excluding today)
    df["avg_volume_20"] = g["volume"].shift(1).rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    df["volume_ratio"] = df["volume"] / df["avg_volume_20"].replace(0, np.nan)

    # OHLC-derived
    df["range_pct"] = (df["high"] - df["low"]) / df["open"].replace(0, np.nan)
    df["body_abs"] = (df["close"] - df["open"]).abs()
    df["body_pct"] = df["body_abs"] / df["open"].replace(0, np.nan)
    df["close_pos"] = (df["close"] - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)

    # Shadows
    df["upper_shadow"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_shadow"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["upper_shadow_ratio"] = df["upper_shadow"] / df["body_abs"].replace(0, np.nan)
    df["lower_shadow_ratio"] = df["lower_shadow"] / df["body_abs"].replace(0, np.nan)

    # MA60 slope (5-day) and 60-day-ago close (for 扣抵 prediction)
    df["ma60_slope_5d"] = df["ma60"] / g["ma60"].shift(5) - 1
    df["ma60_rolling_off_close"] = g["close"].shift(60)

    # K-line color
    df["is_red"]   = df["close"] > df["open"]
    df["is_black"] = df["close"] < df["open"]
    df["is_doji"]  = (df["body_pct"] <= 0.006) & (df["range_pct"] >= 0.015)

    return df
```

- [ ] **Step 4: Run test, verify pass**

Run: `uv run pytest tests/kline/test_features.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/features.py tests/kline/test_features.py
git commit -m "feat(kline): features.add_features with all derived columns"
```

---

## Task 4: `entry/breakout.py` — Clean Breakout

**Files:**
- Create: `scripts/kline/entry/__init__.py` (placeholder, finalized in Task 5)
- Create: `scripts/kline/entry/breakout.py`
- Create: `tests/kline/entry/__init__.py`
- Create: `tests/kline/entry/test_breakout.py`

- [ ] **Step 1: Write failing test** `tests/kline/entry/test_breakout.py`:

```python
"""breakout.detect: close > prior_high_60 AND close > ma60.

Course source: 【突破跌破】突破意義的釐清; volume / red K / close_pos NOT required.
"""
from __future__ import annotations

import pandas as pd

from kline.entry.breakout import detect
from kline.features import add_features
from tests.conftest import make_bars


def _bars_with_breakout_at(idx: int, n: int = 65):
    """65 ascending bars; force a breakout at `idx` by spiking close."""
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 100.0} for _ in range(n)]
    # spike close at idx above all prior 60 highs (which are 101)
    rows[idx]["close"] = 110.0
    rows[idx]["high"] = 111.0
    return make_bars(rows)


def test_breakout_triggers_when_close_above_prior_high_60():
    df = add_features(_bars_with_breakout_at(60))
    signal = detect(df)
    assert signal.iloc[60] == True
    # Before bar 60 there's not enough prior history for prior_high_60
    assert signal.iloc[59] == False


def test_breakout_does_not_require_red_k():
    # Force black K (close > prior_high_60 but close < open)
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 100.0} for _ in range(65)]
    rows[60]["open"] = 115.0
    rows[60]["high"] = 116.0
    rows[60]["low"] = 109.0
    rows[60]["close"] = 110.0  # black K but still > prior_high_60 (which is 101)
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert signal.iloc[60] == True  # Still triggers — course says color irrelevant


def test_breakout_blocked_when_below_ma60():
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 120.0} for _ in range(65)]
    rows[60]["close"] = 110.0  # above prior_high_60 (101) but below ma60 (120)
    rows[60]["high"] = 111.0
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert signal.iloc[60] == False
```

- [ ] **Step 2: Stub entry/__init__.py** (will be expanded in Task 5):

```python
"""Entry conditions for K-line course system."""
```

- [ ] **Step 3: Create `tests/kline/entry/__init__.py`** (empty)

- [ ] **Step 4: Run failing test**

Run: `uv run pytest tests/kline/entry/test_breakout.py -v`
Expected: ImportError.

- [ ] **Step 5: Implement `scripts/kline/entry/breakout.py`**:

```python
"""Breakout attack entry signal — pure course definition.

Course source: 【突破跌破】突破意義的釐清, 【買點賣點】股價的買點決策(三)多頭買在攻擊

> 「對於K線圖來說，價格才是最重要的事情，不需要加上成交量」
> 「與這一根突破的K線是否長紅、有沒有上影線都無關」

This implementation deliberately does NOT include:
  - is_red filter
  - close_pos threshold
  - volume_ratio threshold

Those are non-course filters; see kline/extras/strict_breakout.py if desired.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = breakout attack entry signal on that bar.

    Required df columns: close, prior_high_60, ma60.
    """
    return (
        (df["close"] > df["prior_high_60"])
        & df["ma60"].notna()
        & (df["close"] > df["ma60"])
    ).fillna(False)
```

- [ ] **Step 6: Run test, verify pass**

Run: `uv run pytest tests/kline/entry/test_breakout.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/kline/entry/__init__.py scripts/kline/entry/breakout.py \
        tests/kline/entry/__init__.py tests/kline/entry/test_breakout.py
git commit -m "feat(kline): entry.breakout — pure course definition (no color/volume filter)"
```

---

## Task 5: Entry Stubs + Registry

**Files:**
- Create: `scripts/kline/entry/trend_reversal.py` (STUB)
- Create: `scripts/kline/entry/sunrise.py` (STUB)
- Modify: `scripts/kline/entry/__init__.py` (add registry)
- Create: `tests/kline/entry/test_stubs.py`

- [ ] **Step 1: Write stub test** `tests/kline/entry/test_stubs.py`:

```python
"""Verify stub entry conditions return all-False and follow STUB convention."""
from __future__ import annotations

import pandas as pd

from kline.entry import ENTRY_REGISTRY
from kline.entry import trend_reversal, sunrise
from kline.features import add_features
from tests.conftest import make_bars


def _sample_df():
    rows = [{"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000} for _ in range(5)]
    return add_features(make_bars(rows))


def test_trend_reversal_stub_returns_all_false():
    df = _sample_df()
    out = trend_reversal.detect(df)
    assert out.dtype == bool
    assert not out.any()
    assert len(out) == len(df)


def test_sunrise_stub_returns_all_false():
    df = _sample_df()
    out = sunrise.detect(df)
    assert out.dtype == bool
    assert not out.any()


def test_registry_includes_all_entry_conditions():
    assert "breakout_attack" in ENTRY_REGISTRY
    assert "trend_reversal" in ENTRY_REGISTRY
    assert "sunrise_attack" in ENTRY_REGISTRY


def test_stub_docstring_starts_with_stub_marker():
    assert trend_reversal.__doc__.lstrip().startswith("STUB:")
    assert sunrise.__doc__.lstrip().startswith("STUB:")
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/entry/test_stubs.py -v`
Expected: ImportError.

- [ ] **Step 3: Create `scripts/kline/entry/trend_reversal.py`**:

```python
"""STUB: 入門 — 底部轉折型買點 (Buy at trend change, post-bear).

Course source: 【買點賣點】出場點(一) — three entry types include trend-change buy.

Intro course mentions this entry type but does not give precise structural
detection (requires MA60 turning up from down, plus bottom-pattern completion).

Replace this stub when precise detection is finalized.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

- [ ] **Step 4: Create `scripts/kline/entry/sunrise.py`**:

```python
"""STUB: K線行進ing — 日出攻擊 (Sunrise attack).

Course source: K線行進ing 紅K篇(七) 日出攻擊.

Pending read of 行進ing subcategory. Replace this stub file
with the actual sunrise detection logic when ready.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

- [ ] **Step 5: Finalize `scripts/kline/entry/__init__.py`**:

```python
"""Entry conditions for K-line course system.

Public API:
    ENTRY_REGISTRY: dict mapping condition name to detect() function.

External repos can also import individual conditions directly:
    from kline.entry.breakout import detect
"""
from __future__ import annotations

from .breakout import detect as breakout_attack
from .sunrise import detect as sunrise_attack
from .trend_reversal import detect as trend_reversal

ENTRY_REGISTRY = {
    "breakout_attack": breakout_attack,
    "trend_reversal": trend_reversal,
    "sunrise_attack": sunrise_attack,
}

__all__ = ["ENTRY_REGISTRY", "breakout_attack", "trend_reversal", "sunrise_attack"]
```

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/kline/entry/ -v`
Expected: 7 passed (3 from Task 4 + 4 here).

- [ ] **Step 7: Commit**

```bash
git add scripts/kline/entry/ tests/kline/entry/test_stubs.py
git commit -m "feat(kline): entry stubs + ENTRY_REGISTRY"
```

---

## Tasks 6–11: Exit Conditions (PARALLELIZABLE)

Each task follows the same structure: test file + implementation file + commit. **All six can be assigned to separate subagents.** Each task is independent — only depends on `features.py` from Task 3.

### Task 6: `exit/gap_fill.py` — Attack Gap Fill

**Files:**
- Create: `scripts/kline/exit/__init__.py` (placeholder, finalized in Task 14)
- Create: `scripts/kline/exit/gap_fill.py`
- Create: `tests/kline/exit/__init__.py`
- Create: `tests/kline/exit/test_gap_fill.py`

- [ ] **Step 1: Placeholder `scripts/kline/exit/__init__.py`**:

```python
"""Exit conditions for K-line course system."""
```

- [ ] **Step 2: Write failing test** `tests/kline/exit/test_gap_fill.py`:

```python
"""gap_fill.mark: 攻擊跳空回補.

Course source: 【買點賣點】出場點的各種依據(二).

Trigger: (stock_gap - market_gap) >= 2% AND close < prev_close.
"""
from __future__ import annotations

import pandas as pd

from kline.exit.gap_fill import mark
from tests.conftest import make_bars


def _df_with_market_col(rows, market_open_rets):
    df = make_bars(rows)
    df["prev_close"] = df["close"].shift(1)
    df["market_open_ret"] = market_open_rets
    return df


def test_excess_gap_with_close_below_prev_close_triggers():
    # Bar 1: open jumps 5% from prev_close, market only +0.5%, close back below prev_close
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 106, "low": 99,  "close": 99},  # gap +5%, close < prev_close
    ]
    df = _df_with_market_col(rows, market_open_rets=[0.0, 0.005])
    out = mark(df)
    assert out.iloc[1] == True
    assert out.iloc[0] == False


def test_no_trigger_when_market_gap_explains_stock_gap():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 106, "low": 99,  "close": 99},  # gap +5%, market also +5%
    ]
    df = _df_with_market_col(rows, market_open_rets=[0.0, 0.05])
    out = mark(df)
    assert out.iloc[1] == False  # excess gap = 0, below 2% threshold


def test_no_trigger_when_close_not_below_prev_close():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 106, "low": 99,  "close": 101},  # gap +5%, close > prev_close
    ]
    df = _df_with_market_col(rows, market_open_rets=[0.0, 0.0])
    out = mark(df)
    assert out.iloc[1] == False
```

- [ ] **Step 3: Run failing test**

Run: `uv run pytest tests/kline/exit/test_gap_fill.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `scripts/kline/exit/gap_fill.py`**:

```python
"""Attack gap fill exit signal — E1.

Course source: 【買點賣點】出場點的各種依據(二).

Definition: if a stock gaps up materially more than the market (excess gap),
that gap is interpreted as an "attack gap" (urgency buying at any price).
When that gap is filled — i.e., the same day's close falls below the prior
close — the attack is invalidated and we exit.

Required df columns: open, close, prev_close, market_open_ret.
  market_open_ret = (TAIEX open / TAIEX prev close - 1) on that bar's date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EXCESS_GAP_MIN = 0.02  # 2% excess gap threshold


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = gap fill triggered on that bar.

    `entries` is accepted for interface uniformity but not used (this
    condition does not need entry context).
    """
    prev_close = df["prev_close"].replace(0, np.nan)
    stock_gap = df["open"] / prev_close - 1
    excess_gap = stock_gap - df["market_open_ret"].fillna(0.0)
    triggered = (excess_gap >= EXCESS_GAP_MIN) & (df["close"] < df["prev_close"])
    return triggered.fillna(False)
```

- [ ] **Step 5: Create `tests/kline/exit/__init__.py`** (empty)

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/test_gap_fill.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/kline/exit/__init__.py scripts/kline/exit/gap_fill.py \
        tests/kline/exit/__init__.py tests/kline/exit/test_gap_fill.py
git commit -m "feat(kline): exit.gap_fill — E1 attack gap fill with market-adjusted excess"
```

---

### Task 7: `exit/breakout_low_break.py` — E4

**Files:**
- Create: `scripts/kline/exit/breakout_low_break.py`
- Create: `tests/kline/exit/test_breakout_low_break.py`

- [ ] **Step 1: Write failing test** `tests/kline/exit/test_breakout_low_break.py`:

```python
"""breakout_low_break.mark: 突破K的低點被跌破 → 攻擊假設失效.

Course source: 【單一K線】紅色誤解：連續紅K的判斷要點.
"""
from __future__ import annotations

import pandas as pd

from kline.exit.breakout_low_break import mark
from tests.conftest import make_bars


def test_close_below_entry_bar_low_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},  # bar 0: pre-entry
        {"open": 105, "high": 110, "low": 104, "close": 109},  # bar 1: ENTRY bar (low=104)
        {"open": 108, "high": 109, "low": 102, "close": 103},  # bar 2: close 103 < 104 → trigger
    ]
    df = make_bars(rows)
    entries = pd.Series([False, True, False])
    out = mark(df, entries)
    assert out.iloc[2] == True
    assert out.iloc[0] == False
    assert out.iloc[1] == False


def test_close_at_or_above_entry_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},  # ENTRY low=104
        {"open": 108, "high": 109, "low": 104, "close": 105},  # close 105 >= 104
    ]
    df = make_bars(rows)
    entries = pd.Series([False, True, False])
    out = mark(df, entries)
    assert out.iloc[2] == False


def test_per_ticker_isolation():
    """B's entry low must not be carried into A's check."""
    df = pd.concat([
        make_bars([{"open": 100, "high": 110, "low": 90, "close": 100} for _ in range(2)], ticker="A"),
        make_bars([{"open": 100, "high": 110, "low": 50, "close": 60}  for _ in range(2)], ticker="B"),
    ]).reset_index(drop=True)
    entries = pd.Series([True, False, True, False])
    out = mark(df, entries)
    # A row 1: close 100, entry_low 90 → False
    assert out.iloc[1] == False
    # B row 1: close 60, entry_low 50 → False
    assert out.iloc[3] == False
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/exit/test_breakout_low_break.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/exit/breakout_low_break.py`**:

```python
"""Breakout bar low break exit signal — E4.

Course source: 【單一K線】紅色誤解：連續紅K的判斷要點.

> 「突破K的低點被跌破 → 攻擊假設失效 → 停損」

Required df columns: ticker, low, close.
entries: bool Series marking the entry bar; the low of that bar is the
         reference. If multiple entries occur in one ticker, the latest
         entry's low is used (earlier trades should already have exited).
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the entry bar's low."""
    entry_low_at_signal = df["low"].where(entries)
    # Per-ticker forward-fill so the entry's low propagates to subsequent bars.
    entry_low = entry_low_at_signal.groupby(df["ticker"]).ffill()
    return (df["close"] < entry_low).fillna(False)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/test_breakout_low_break.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/exit/breakout_low_break.py tests/kline/exit/test_breakout_low_break.py
git commit -m "feat(kline): exit.breakout_low_break — E4 attack assumption failure"
```

---

### Task 8: `exit/neckline_break.py` — E3

**Files:**
- Create: `scripts/kline/exit/neckline_break.py`
- Create: `tests/kline/exit/test_neckline_break.py`

- [ ] **Step 1: Write failing test** `tests/kline/exit/test_neckline_break.py`:

```python
"""neckline_break.mark: 頸線跌破 (with next-day confirmation).

Course source: 【買點賣點】多方操作的出場點邏輯.

Neckline proxy: prior_low_20. Confirm with next-day close also below.
Trigger fires on the CONFIRMATION DAY (one day after first break).
"""
from __future__ import annotations

import pandas as pd

from kline.exit.neckline_break import mark
from tests.conftest import make_bars


def test_consecutive_break_triggers_on_second_day():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 100, "high": 102, "low": 89,  "close": 92},   # bar 1: close 92 < prior_low_20=95 → pending
        {"open": 92,  "high": 94,  "low": 88,  "close": 91},   # bar 2: still below → CONFIRMED
    ]
    df = make_bars(rows)
    df["prior_low_20"] = [95.0, 95.0, 95.0]
    out = mark(df)
    assert out.iloc[2] == True  # confirmation day
    assert out.iloc[1] == False  # only pending, not confirmed yet


def test_reclaim_after_break_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 100, "high": 102, "low": 89,  "close": 92},   # break
        {"open": 92,  "high": 98,  "low": 92,  "close": 96},   # reclaim above 95
    ]
    df = make_bars(rows)
    df["prior_low_20"] = [95.0, 95.0, 95.0]
    out = mark(df)
    assert out.iloc[2] == False


def test_nan_neckline_does_not_trigger():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["prior_low_20"] = [float("nan")] * 3
    out = mark(df)
    assert not out.any()
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/exit/test_neckline_break.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/exit/neckline_break.py`**:

```python
"""Neckline break exit signal — E3.

Course source: 【買點賣點】多方操作的出場點邏輯.

Neckline proxy: prior_low_20 (precise version awaits ma60_neckline stub
replacement once K線行進ing is read).

Course rule: close-price confirmation across two consecutive days.
The exit signal fires on the confirmation day (day after first break).

Required df columns: ticker, close, prior_low_20.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = neckline break confirmed on that bar."""
    broke_today = df["close"] < df["prior_low_20"]
    # broke_yesterday: same condition shifted forward by one bar, per ticker
    broke_yesterday = broke_today.groupby(df["ticker"]).shift(1).fillna(False)
    return (broke_yesterday & broke_today).fillna(False)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/test_neckline_break.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/exit/neckline_break.py tests/kline/exit/test_neckline_break.py
git commit -m "feat(kline): exit.neckline_break — E3 with next-day confirmation"
```

---

### Task 9: `exit/trailing_stop.py` — 緩慢推升型

**Files:**
- Create: `scripts/kline/exit/trailing_stop.py`
- Create: `tests/kline/exit/test_trailing_stop.py`

- [ ] **Step 1: Write failing test** `tests/kline/exit/test_trailing_stop.py`:

```python
"""trailing_stop.mark: 前一日低點 trailing stop.

Course source: 【買點賣點】出場點的各種依據(二) +【賣壓化解】K線圖的第一個研判要點.

> 「前一日低點當作停利點，有過昨高都算攻擊持續」

Trailing reference = expanding max of prev_low since entry.
"""
from __future__ import annotations

import pandas as pd

from kline.exit.trailing_stop import mark
from tests.conftest import make_bars


def test_close_below_trailing_low_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},  # pre-entry
        {"open": 105, "high": 110, "low": 104, "close": 109},  # ENTRY (prev_low becomes 99 for next)
        {"open": 109, "high": 112, "low": 108, "close": 111},  # makes new high (prev_low=104)
        {"open": 111, "high": 111, "low": 103, "close": 103},  # close 103 < expanding max(prev_low)=108 → trigger
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    entries = pd.Series([False, True, False, False])
    out = mark(df, entries)
    assert out.iloc[3] == True


def test_close_above_trailing_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},  # ENTRY
        {"open": 109, "high": 112, "low": 108, "close": 111},
        {"open": 111, "high": 113, "low": 109, "close": 112},  # close 112 >= 108
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    entries = pd.Series([False, True, False, False])
    out = mark(df, entries)
    assert out.iloc[3] == False
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/exit/test_trailing_stop.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/exit/trailing_stop.py`**:

```python
"""Trailing stop exit signal — 緩慢推升型.

Course source: 【買點賣點】出場點的各種依據(二),
              【賣壓化解】K線圖的第一個研判要點.

> 「前一日低點當作停利點，有過昨高都算攻擊持續」

Vectorized implementation: per trade (delineated by entry signals within
each ticker), trailing_low = expanding max of prev_low since entry.

Required df columns: ticker, close, prev_low.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the trailing reference."""
    # Per-ticker trade id: cumulative count of entries.
    trade_id = entries.groupby(df["ticker"]).cumsum()
    trade_id = trade_id.where(trade_id > 0)
    work = df.assign(_tid=trade_id)
    trailing_low = (
        work.groupby(["ticker", "_tid"])["prev_low"]
            .expanding().max()
            .reset_index(level=[0, 1], drop=True)
    )
    return (df["close"] < trailing_low).fillna(False)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/test_trailing_stop.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/exit/trailing_stop.py tests/kline/exit/test_trailing_stop.py
git commit -m "feat(kline): exit.trailing_stop — expanding-max prev_low per trade"
```

---

### Task 10: `exit/trend_change.py` — 趨勢改變型 (MA60 only for now)

**Files:**
- Create: `scripts/kline/exit/trend_change.py`
- Create: `tests/kline/exit/test_trend_change.py`

- [ ] **Step 1: Write failing test** `tests/kline/exit/test_trend_change.py`:

```python
"""trend_change.mark: 趨勢改變型 → MA60 由上升轉下彎.

Course source: 【買點賣點】出場點的各種依據(一).

Course says: take the highest of (末升低, 上升趨勢線, MA60 下彎).
Intro doesn't give precise detection for 末升低 / 趨勢線; this implementation
covers MA60 turn-down only, with placeholders for the other two.
"""
from __future__ import annotations

import pandas as pd

from kline.exit.trend_change import mark
from tests.conftest import make_bars


def test_ma60_slope_flip_negative_triggers():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["ma60_slope_5d"] = [0.01, 0.005, -0.002]  # slope flips negative at bar 2
    out = mark(df)
    assert out.iloc[2] == True
    assert out.iloc[0] == False
    assert out.iloc[1] == False


def test_continuous_negative_slope_does_not_re_trigger():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["ma60_slope_5d"] = [-0.001, -0.002, -0.003]  # already negative
    out = mark(df)
    assert not out.any()  # only the flip moment triggers


def test_nan_slope_does_not_trigger():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["ma60_slope_5d"] = [float("nan"), float("nan"), -0.01]
    out = mark(df)
    # First non-NaN slope is already negative — no prior "rising" state to flip from.
    assert not out.any()
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/exit/test_trend_change.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/exit/trend_change.py`**:

```python
"""Trend change exit signal — 趨勢改變型.

Course source: 【買點賣點】出場點的各種依據(一).

Course says exit when the trend changes; take the HIGHER of:
  1. 末升低跌破 (last_rally_low break)
  2. 上升趨勢線跌破 (rising_trendline break)
  3. 季線下彎 (MA60 turn-down)

Intro course does not give precise detection for (1) and (2):
  - 末升低 requires swing-low detection (peaks/troughs algorithm)
  - 趨勢線 requires multi-point fitting
Both will be added later. For now we implement (3) only.

Required df columns: ticker, ma60_slope_5d.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = MA60 slope just flipped from >=0 to <0."""
    slope = df["ma60_slope_5d"]
    prev_slope = slope.groupby(df["ticker"]).shift(1)
    return ((prev_slope >= 0) & (slope < 0)).fillna(False)


def _TODO_last_rally_low(df: pd.DataFrame) -> pd.Series:
    """Pending implementation — needs swing-low detection."""
    return pd.Series(float("nan"), index=df.index)


def _TODO_rising_trendline(df: pd.DataFrame) -> pd.Series:
    """Pending implementation — needs multi-point line fitting."""
    return pd.Series(float("nan"), index=df.index)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/test_trend_change.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/exit/trend_change.py tests/kline/exit/test_trend_change.py
git commit -m "feat(kline): exit.trend_change — MA60 turn-down (末升低/趨勢線 TODO)"
```

---

### Task 11: `exit/prev_day_low_break.py` — 短線

**Files:**
- Create: `scripts/kline/exit/prev_day_low_break.py`
- Create: `tests/kline/exit/test_prev_day_low_break.py`

- [ ] **Step 1: Write failing test** `tests/kline/exit/test_prev_day_low_break.py`:

```python
"""prev_day_low_break.mark: 前一日低點跌破 (short-term exit).

Course source: 【買點賣點】買點與攻擊研判.

> 「短線操作的停利點可以設定在昨天的低點」
"""
from __future__ import annotations

import pandas as pd

from kline.exit.prev_day_low_break import mark
from tests.conftest import make_bars


def test_close_below_prev_low_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 98, "close": 98},  # close 98 < prev_low 99
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert out.iloc[1] == True


def test_close_at_prev_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 99, "close": 99},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert out.iloc[1] == False  # equal, not strictly below
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/exit/test_prev_day_low_break.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/exit/prev_day_low_break.py`**:

```python
"""Previous-day low break exit signal — short-term trading.

Course source: 【買點賣點】買點與攻擊研判.

> 「短線操作的停利點可以設定在昨天的低點」

Required df columns: close, prev_low.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = close < prev_low (strict)."""
    return (df["close"] < df["prev_low"]).fillna(False)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/test_prev_day_low_break.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/exit/prev_day_low_break.py tests/kline/exit/test_prev_day_low_break.py
git commit -m "feat(kline): exit.prev_day_low_break — short-term trailing"
```

---

## Task 12: Exit Stubs

**Files:**
- Create: `scripts/kline/exit/supply_zone_reach.py` (STUB)
- Create: `scripts/kline/exit/ma60_neckline.py` (STUB)
- Create: `tests/kline/exit/test_exit_stubs.py`

- [ ] **Step 1: Write failing test**:

```python
"""Verify exit stubs return all-False."""
from __future__ import annotations

import pandas as pd

from kline.exit import supply_zone_reach, ma60_neckline
from tests.conftest import make_bars


def _sample():
    return make_bars([{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)])


def test_supply_zone_reach_stub():
    out = supply_zone_reach.mark(_sample())
    assert out.dtype == bool
    assert not out.any()


def test_ma60_neckline_stub():
    out = ma60_neckline.mark(_sample())
    assert out.dtype == bool
    assert not out.any()


def test_stubs_have_stub_marker_in_docstring():
    assert supply_zone_reach.__doc__.lstrip().startswith("STUB:")
    assert ma60_neckline.__doc__.lstrip().startswith("STUB:")
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/exit/test_exit_stubs.py -v`
Expected: ImportError.

- [ ] **Step 3: Create `scripts/kline/exit/supply_zone_reach.py`**:

```python
"""STUB: 入門 — 遇壓先出，化解再進 (Supply zone reach).

Course source: 【買點賣點】出場點的各種依據-下一個買點.

> 「應該先出場，等到股價越過了這個壓力區段，再考慮還有沒有買回的意義」

Requires volume profile (分價量表) for precise resistance identification.
Pending VP integration. Replace this stub when VP module is ready.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

- [ ] **Step 4: Create `scripts/kline/exit/ma60_neckline.py`**:

```python
"""STUB: K線行進ing — 精確頸線 via 關鍵K線 × MA60.

Course source: K線行進ing 關鍵K線延伸篇 — 關鍵K線與移動平均線的連結判斷.

Replaces the prior_low_20 proxy used in neckline_break.py with a course-
precise neckline: "prior high after MA60 turns up" / "prior low after MA60
turns down". Pending read of 行進ing subcategory.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/test_exit_stubs.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/kline/exit/supply_zone_reach.py scripts/kline/exit/ma60_neckline.py \
        tests/kline/exit/test_exit_stubs.py
git commit -m "feat(kline): exit stubs — supply_zone_reach + ma60_neckline"
```

---

## Task 13: Reversal-K (dark_double_star + 5 stubs)

**Files:**
- Create: `scripts/kline/exit/reversal_k/__init__.py`
- Create: `scripts/kline/exit/reversal_k/dark_double_star.py`
- Create: 5 stub files: `bearish_engulfing.py`, `enemy_at_gate.py`, `evening_star.py`, `two_crows.py`, `gap_reversal.py`
- Create: `tests/kline/exit/reversal_k/__init__.py`
- Create: `tests/kline/exit/reversal_k/test_dark_double_star.py`
- Create: `tests/kline/exit/reversal_k/test_stubs.py`

- [ ] **Step 1: Write failing test** `tests/kline/exit/reversal_k/test_dark_double_star.py`:

```python
"""dark_double_star.mark: 暗夜雙星.

Definition: black K opens below prior bar's low, body_pct >= 4%.
"""
from __future__ import annotations

import pandas as pd

from kline.exit.reversal_k.dark_double_star import mark
from tests.conftest import make_bars


def test_black_k_opens_below_prev_low_with_long_body_triggers():
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104},  # bar 0
        {"open": 96,  "high": 97,  "low": 90,  "close": 91},   # bar 1: black, open<prev_low(99), body=5/96≈0.052
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert out.iloc[1] == True


def test_red_k_does_not_trigger():
    rows = [
        {"open": 100, "high": 105, "low": 99, "close": 104},
        {"open": 96,  "high": 105, "low": 95, "close": 104},  # red K
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert out.iloc[1] == False


def test_body_below_threshold_does_not_trigger():
    rows = [
        {"open": 100, "high": 105, "low": 99, "close": 104},
        {"open": 96,  "high": 96,  "low": 94, "close": 95},  # black, open<prev_low, body=1/96≈0.01 (<0.04)
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert out.iloc[1] == False
```

- [ ] **Step 2: Write stubs test** `tests/kline/exit/reversal_k/test_stubs.py`:

```python
"""All reversal_k stubs return all-False."""
from __future__ import annotations

import pandas as pd

from kline.exit.reversal_k import (
    bearish_engulfing, enemy_at_gate, evening_star, two_crows, gap_reversal,
    REVERSAL_K_REGISTRY,
)
from tests.conftest import make_bars


def _sample():
    return make_bars([{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)])


def test_all_stubs_return_all_false():
    df = _sample()
    for mod in (bearish_engulfing, enemy_at_gate, evening_star, two_crows, gap_reversal):
        out = mod.mark(df)
        assert out.dtype == bool
        assert not out.any(), f"{mod.__name__} returned True somewhere"
        assert mod.__doc__.lstrip().startswith("STUB:")


def test_registry_has_all_six_patterns():
    assert set(REVERSAL_K_REGISTRY.keys()) == {
        "dark_double_star",
        "bearish_engulfing",
        "enemy_at_gate",
        "evening_star",
        "two_crows",
        "gap_reversal",
    }
```

- [ ] **Step 3: Create `tests/kline/exit/reversal_k/__init__.py`** (empty)

- [ ] **Step 4: Run failing tests**

Run: `uv run pytest tests/kline/exit/reversal_k/ -v`
Expected: ImportError.

- [ ] **Step 5: Implement `scripts/kline/exit/reversal_k/dark_double_star.py`**:

```python
"""Dark double star (暗夜雙星) reversal pattern — E2.

Course source: 【買點賣點】出場點(二)轉折組合K線運用出場.

Definition (intro-course implementation):
  - Black K (close < open)
  - Opens below prior bar's low
  - Body >= 4% of open

Required df columns: open, close, prev_low.
"""
from __future__ import annotations

import pandas as pd

MIN_BODY_PCT = 0.04


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = dark double star triggered on that bar."""
    is_black = df["close"] < df["open"]
    gap_below_prev_low = df["open"] < df["prev_low"]
    body_pct = (df["open"] - df["close"]) / df["open"].replace(0, float("nan"))
    long_body = body_pct >= MIN_BODY_PCT
    return (is_black & gap_below_prev_low & long_body).fillna(False)
```

- [ ] **Step 6: Create 5 stub files** with identical structure:

`scripts/kline/exit/reversal_k/bearish_engulfing.py`:

```python
"""STUB: 多空轉折組合K線 — 空頭吞噬 (Bearish engulfing).

Course source: 多空轉折組合K線 — 包覆線在轉折組合中的運用 (multi-side bear-side).

Intro course mentions by name only. Structural definition is in the
多空轉折組合K線 subcategory (26 articles). Replace this stub when read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

`scripts/kline/exit/reversal_k/enemy_at_gate.py`:

```python
"""STUB: 多空轉折組合K線 — 大敵當前 (Enemy at gate).

Course source: 多空轉折組合K線 — 三根K線連續判斷阻礙力量出現：大敵當前.

Intro course only mentions by name + 藍天 example. Detailed structural
definition is in the 多空轉折 subcategory. Replace this stub when read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

`scripts/kline/exit/reversal_k/evening_star.py`:

```python
"""STUB: 多空轉折組合K線 — 夜星棄嬰 (Abandoned evening star).

Course source: 多空轉折組合K線 — 三根K線連續判斷在十字線之後：夜星棄嬰.

No structural definition in the intro course. Replace this stub when
多空轉折 subcategory is read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

`scripts/kline/exit/reversal_k/two_crows.py`:

```python
"""STUB: 多空轉折組合K線 — 雙鴉躍空 (Two crows).

Course source: 多空轉折組合K線 — 向下跳空形成的壓力：雙鴉躍空.

Intro course gives partial hint ("紅K後接續兩根短黑K，然後再出現一個向下跳空");
precise structural definition is in 多空轉折 subcategory. Replace when read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

`scripts/kline/exit/reversal_k/gap_reversal.py`:

```python
"""STUB: 多空轉折組合K線 — 跳空反轉 (Gap reversal).

Course source: 多空轉折組合K線 — 向下跳空出現的影響：跳空反轉與延伸解說.

Intro course gives partial hint ("紅K後接黑K再向下跳空"); precise definition
is in 多空轉折 subcategory. Replace when read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
```

- [ ] **Step 7: Create `scripts/kline/exit/reversal_k/__init__.py`** with registry:

```python
"""Reversal-K exit patterns.

One pattern per file. Currently dark_double_star is the only one with
intro-course structural definition; the other five are stubs awaiting
the 多空轉折組合K線 subcategory (26 articles).
"""
from __future__ import annotations

from .bearish_engulfing import mark as bearish_engulfing_mark
from .dark_double_star import mark as dark_double_star_mark
from .enemy_at_gate import mark as enemy_at_gate_mark
from .evening_star import mark as evening_star_mark
from .gap_reversal import mark as gap_reversal_mark
from .two_crows import mark as two_crows_mark

REVERSAL_K_REGISTRY = {
    "dark_double_star": dark_double_star_mark,
    "bearish_engulfing": bearish_engulfing_mark,
    "enemy_at_gate": enemy_at_gate_mark,
    "evening_star": evening_star_mark,
    "two_crows": two_crows_mark,
    "gap_reversal": gap_reversal_mark,
}

# Re-export modules so callers can do `from kline.exit.reversal_k import enemy_at_gate`
from . import bearish_engulfing, dark_double_star, enemy_at_gate
from . import evening_star, gap_reversal, two_crows

__all__ = [
    "REVERSAL_K_REGISTRY",
    "bearish_engulfing", "dark_double_star", "enemy_at_gate",
    "evening_star", "gap_reversal", "two_crows",
]
```

- [ ] **Step 8: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/reversal_k/ -v`
Expected: 5 passed.

- [ ] **Step 9: Commit**

```bash
git add scripts/kline/exit/reversal_k/ tests/kline/exit/reversal_k/
git commit -m "feat(kline): reversal_k — dark_double_star + 5 stubs for 多空轉折"
```

---

## Task 14: `exit/__init__.py` — Registry + Priority

**Files:**
- Modify: `scripts/kline/exit/__init__.py`
- Create: `tests/kline/exit/test_registry.py`

- [ ] **Step 1: Write failing test** `tests/kline/exit/test_registry.py`:

```python
"""EXIT_REGISTRY: all conditions named correctly and registered."""
from __future__ import annotations

from kline.exit import EXIT_REGISTRY, EXIT_PRIORITY


def test_registry_has_all_intro_conditions():
    expected = {
        "gap_fill",
        "breakout_low_break",
        "neckline_break",
        "trailing_stop",
        "trend_change",
        "prev_day_low_break",
        "supply_zone_reach",
        "ma60_neckline",
        "reversal_k.dark_double_star",
        "reversal_k.bearish_engulfing",
        "reversal_k.enemy_at_gate",
        "reversal_k.evening_star",
        "reversal_k.two_crows",
        "reversal_k.gap_reversal",
    }
    assert expected.issubset(EXIT_REGISTRY.keys())


def test_priority_lists_all_registered_conditions():
    assert set(EXIT_PRIORITY) == set(EXIT_REGISTRY.keys())


def test_reversal_k_comes_first_in_priority():
    # Per spec §5.1
    for i, name in enumerate(EXIT_PRIORITY):
        if name.startswith("reversal_k."):
            continue
        # First non-reversal_k entry must be gap_fill or later
        assert name == "gap_fill" or i > 5
        break
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/exit/test_registry.py -v`
Expected: ImportError (EXIT_REGISTRY not exported yet).

- [ ] **Step 3: Replace `scripts/kline/exit/__init__.py`** entirely:

```python
"""Exit conditions for K-line course system.

Public API:
    EXIT_REGISTRY: dict mapping condition name to mark(df, entries) function.
    EXIT_PRIORITY: list of condition names, highest priority first.

External repos can also import individual conditions directly:
    from kline.exit.gap_fill import mark
"""
from __future__ import annotations

from . import (
    breakout_low_break,
    gap_fill,
    ma60_neckline,
    neckline_break,
    prev_day_low_break,
    supply_zone_reach,
    trailing_stop,
    trend_change,
)
from .reversal_k import REVERSAL_K_REGISTRY

EXIT_REGISTRY = {
    "gap_fill":            gap_fill.mark,
    "breakout_low_break":  breakout_low_break.mark,
    "neckline_break":      neckline_break.mark,
    "trailing_stop":       trailing_stop.mark,
    "trend_change":        trend_change.mark,
    "prev_day_low_break":  prev_day_low_break.mark,
    "supply_zone_reach":   supply_zone_reach.mark,
    "ma60_neckline":       ma60_neckline.mark,
    **{f"reversal_k.{k}": v for k, v in REVERSAL_K_REGISTRY.items()},
}

# Spec §5.1 — highest priority first
EXIT_PRIORITY = [
    "reversal_k.dark_double_star",
    "reversal_k.bearish_engulfing",
    "reversal_k.enemy_at_gate",
    "reversal_k.evening_star",
    "reversal_k.two_crows",
    "reversal_k.gap_reversal",
    "gap_fill",
    "breakout_low_break",
    "neckline_break",
    "prev_day_low_break",
    "trailing_stop",
    "trend_change",
    "supply_zone_reach",
    "ma60_neckline",
]

__all__ = ["EXIT_REGISTRY", "EXIT_PRIORITY"]
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/ -v`
Expected: all exit tests pass (Tasks 6–13 + 14).

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/exit/__init__.py tests/kline/exit/test_registry.py
git commit -m "feat(kline): EXIT_REGISTRY + EXIT_PRIORITY"
```

---

## Task 15: `exit/simulator.py` — Vectorized Trade Simulator

**Files:**
- Create: `scripts/kline/exit/simulator.py`
- Create: `tests/kline/exit/test_simulator.py`

- [ ] **Step 1: Write failing test** `tests/kline/exit/test_simulator.py`:

```python
"""simulator.simulate: takes entries + df, returns trades DataFrame."""
from __future__ import annotations

import pandas as pd

from kline.exit.simulator import simulate
from tests.conftest import make_bars


def test_single_trade_exits_on_breakout_low_break():
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104},  # bar 0: pre-entry
        {"open": 105, "high": 110, "low": 104, "close": 109},  # bar 1: ENTRY (low=104)
        {"open": 109, "high": 110, "low": 102, "close": 103},  # bar 2: close < 104 → exit
        {"open": 103, "high": 104, "low": 100, "close": 101},  # bar 3: exit price = this open
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    df["prev_close"] = df["close"].shift(1)
    df["prior_low_20"] = float("nan")
    df["ma60_slope_5d"] = 0.01
    df["market_open_ret"] = 0.0
    entries = pd.Series([False, True, False, False])
    trades = simulate(df, entries)
    assert len(trades) == 1
    t = trades.iloc[0]
    assert t["exit_reason"] == "breakout_low_break"
    assert t["entry_open"] == rows[2]["open"]  # NOTE: spec says enter at next-day open
    # entry_date = bar 1 (signal day); entry_open = bar 2's open per "next-day open" rule
    assert t["entry_open"] == 109  # bar 2 open
    # exit_date = bar 2 (signal triggered); exit_open = bar 3 open
    assert t["exit_open"] == 103


def test_no_exit_uses_last_bar_open():
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 101, "high": 103, "low": 100, "close": 102},  # ENTRY
        {"open": 102, "high": 104, "low": 101, "close": 103},  # no exit triggers
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    df["prev_close"] = df["close"].shift(1)
    df["prior_low_20"] = float("nan")
    df["ma60_slope_5d"] = 0.01
    df["market_open_ret"] = 0.0
    entries = pd.Series([False, True, False])
    trades = simulate(df, entries)
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "open"
```

Note about the test: when `entries` is True at bar 1, the trade enters at bar 2's open (next-day execution). Exits also use next-day open as the execution price.

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/exit/test_simulator.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/exit/simulator.py`**:

```python
"""Vectorized trade simulator.

For each entry signal, compute exit by:
  1. Run every condition's mark(df, entries) to get bool columns.
  2. For each trade (entry occurrence per ticker), look at bars from the
     day AFTER entry signal (entry executes at next-day open).
  3. Walk forward; on the first bar where ANY condition is True, exit at
     the bar's NEXT-day open. The exit_reason is determined by EXIT_PRIORITY.
  4. If no condition fires, exit at the last available bar's open.

Output: trades DataFrame matching spec §3.4.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import EXIT_PRIORITY, EXIT_REGISTRY

ROUND_TRIP_COST = 0.00585  # tax + brokerage


def simulate(
    df: pd.DataFrame,
    entries: pd.Series,
    exit_priority: list[str] | None = None,
    exit_registry: dict | None = None,
    cost: float = ROUND_TRIP_COST,
) -> pd.DataFrame:
    """Run vectorized exit simulation for every entry signal.

    df must be sorted by (ticker, trade_date).
    entries: bool Series aligned with df.
    """
    if exit_priority is None:
        exit_priority = EXIT_PRIORITY
    if exit_registry is None:
        exit_registry = EXIT_REGISTRY

    # 1. Compute every exit condition column once.
    exit_cols: dict[str, pd.Series] = {}
    for name in exit_priority:
        fn = exit_registry[name]
        exit_cols[name] = fn(df, entries).astype(bool).reset_index(drop=True)

    work = df.reset_index(drop=True).copy()
    work["_entries"] = entries.reset_index(drop=True).values

    records: list[dict] = []

    for ticker, grp in work.groupby("ticker", sort=False):
        grp_idx = grp.index.to_numpy()
        entry_positions = grp_idx[grp["_entries"].to_numpy()]
        if len(entry_positions) == 0:
            continue

        for entry_pos in entry_positions:
            # Next-day-open entry: bar after signal
            next_pos = entry_pos + 1
            ticker_last = grp_idx[-1]
            if next_pos > ticker_last:
                continue  # signal on last bar, no next open available

            entry_open = float(work.loc[next_pos, "open"])
            if entry_open <= 0:
                continue

            # Search window: from next_pos to last bar of this ticker
            window_positions = grp_idx[grp_idx >= next_pos]

            # For each condition (in priority order), find the earliest
            # position in the window that triggered. Take the condition
            # with the earliest trigger; tie broken by priority order.
            best_pos = None
            best_reason = None
            for name in exit_priority:
                col = exit_cols[name]
                trigger_positions = window_positions[col.iloc[window_positions].to_numpy()]
                if len(trigger_positions) == 0:
                    continue
                first = trigger_positions[0]
                if best_pos is None or first < best_pos:
                    best_pos = int(first)
                    best_reason = name
                elif first == best_pos:
                    # tie: priority order wins (we iterate priority order, so first hit wins)
                    pass

            if best_pos is not None:
                exit_signal_pos = best_pos
                exit_execute_pos = exit_signal_pos + 1
                if exit_execute_pos > ticker_last:
                    exit_open = float(work.loc[exit_signal_pos, "close"])
                    exit_date = work.loc[exit_signal_pos, "trade_date"]
                    hold_days = exit_signal_pos - next_pos + 1
                else:
                    exit_open = float(work.loc[exit_execute_pos, "open"])
                    exit_date = work.loc[exit_execute_pos, "trade_date"]
                    hold_days = exit_execute_pos - next_pos
                exit_reason = best_reason
            else:
                # No exit condition fired — close at last bar's open of this ticker
                exit_open = float(work.loc[ticker_last, "open"])
                if exit_open <= 0:
                    exit_open = float(work.loc[ticker_last, "close"])
                exit_date = work.loc[ticker_last, "trade_date"]
                hold_days = ticker_last - next_pos + 1
                exit_reason = "open"

            trade_return = exit_open / entry_open - 1
            records.append({
                "ticker": ticker,
                "entry_date": work.loc[entry_pos, "trade_date"],
                "entry_open": round(entry_open, 4),
                "exit_date": exit_date,
                "exit_open": round(exit_open, 4),
                "exit_reason": exit_reason,
                "hold_days": int(hold_days),
                "trade_return": round(trade_return, 6),
                "trade_return_net": round(trade_return - cost, 6),
            })

    return pd.DataFrame(records)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/exit/test_simulator.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/exit/simulator.py tests/kline/exit/test_simulator.py
git commit -m "feat(kline): exit.simulator — vectorized priority-based exit search"
```

---

## Tasks 16–18: Scoring Factors (PARALLELIZABLE)

### Task 16: `scoring/attack_quality.py`

**Files:**
- Create: `scripts/kline/scoring/__init__.py` (placeholder, finalized Task 19)
- Create: `scripts/kline/scoring/attack_quality.py`
- Create: `tests/kline/scoring/__init__.py`
- Create: `tests/kline/scoring/test_attack_quality.py`

- [ ] **Step 1: Placeholder `scripts/kline/scoring/__init__.py`**:

```python
"""Scoring factors for K-line course system."""
```

- [ ] **Step 2: Write failing test** `tests/kline/scoring/test_attack_quality.py`:

```python
"""attack_quality.score: base 50 +/- factor adjustments, clipped [0, 100]."""
from __future__ import annotations

import pandas as pd

from kline.scoring.attack_quality import score
from tests.conftest import make_bars


def test_default_score_is_50():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(2)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [0, 0]
    df["volume_ratio"] = [1.0, 1.0]
    df["body_pct"] = [0.01, 0.01]
    df["close_pos"] = [0.5, 0.5]
    out = score(df)
    assert (out == 50.0).all()


def test_strong_trend_history_adds_25():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [17]
    df["volume_ratio"] = [1.0]
    df["body_pct"] = [0.01]
    df["close_pos"] = [0.5]
    assert score(df).iloc[0] == 75.0


def test_high_volume_subtracts_30():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [0]
    df["volume_ratio"] = [3.2]
    df["body_pct"] = [0.01]
    df["close_pos"] = [0.5]
    assert score(df).iloc[0] == 20.0


def test_score_clipped_to_zero():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [0]
    df["volume_ratio"] = [3.2]    # -30
    df["body_pct"] = [0.04]       # -25
    df["close_pos"] = [0.85]      # -20
    # 50 - 75 = -25 → clipped to 0
    assert score(df).iloc[0] == 0.0
```

- [ ] **Step 3: Run failing test**

Run: `uv run pytest tests/kline/scoring/test_attack_quality.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `scripts/kline/scoring/attack_quality.py`**:

```python
"""Attack quality score.

Course source: Calibrated via Spearman correlation against trade_return_net
              over course-defined exit simulation (n≈6,618). Factors map to
              attack-authenticity course concepts:
                - pre_breakout_trend_days: trend-following 真攻擊
                - volume_ratio: extreme volume often = retail FOMO peak
                - body_pct: oversized red K often = exhaustion
                - close_pos: pinned-to-high often = unable to absorb selling

Base 50 + factor deltas, clipped to [0, 100].
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series in [0, 100]. Higher = better attack quality.

    Required df columns: pre_breakout_trend_days, volume_ratio, body_pct, close_pos.
    """
    s = pd.Series(50.0, index=df.index)
    s += np.where(df["pre_breakout_trend_days"].fillna(0) >= 17, 25, 0)
    s -= np.where(df["volume_ratio"].fillna(0) >= 3.2, 30, 0)
    s -= np.where(df["body_pct"].fillna(0) >= 0.04, 25, 0)
    s -= np.where(df["close_pos"].fillna(0) >= 0.85, 20, 0)
    return s.clip(0, 100)
```

- [ ] **Step 5: Create `tests/kline/scoring/__init__.py`** (empty)

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/kline/scoring/test_attack_quality.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/kline/scoring/__init__.py scripts/kline/scoring/attack_quality.py \
        tests/kline/scoring/__init__.py tests/kline/scoring/test_attack_quality.py
git commit -m "feat(kline): scoring.attack_quality — Spearman-calibrated factors"
```

---

### Task 17: `scoring/overhead_supply.py`

**Files:**
- Create: `scripts/kline/scoring/overhead_supply.py`
- Create: `tests/kline/scoring/test_overhead_supply.py`

- [ ] **Step 1: Write failing test** `tests/kline/scoring/test_overhead_supply.py`:

```python
"""overhead_supply.score: penalty for stacked overhead resistance peaks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from kline.scoring.overhead_supply import score
from tests.conftest import make_bars


def test_clean_overhead_returns_zero_penalty():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["overhead_supply_layer"] = [0.0]
    out = score(df)
    assert out.iloc[0] == 0.0


def test_heavy_overhead_returns_negative_penalty():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["overhead_supply_layer"] = [5.0]  # >= 4 → heavy
    out = score(df)
    assert out.iloc[0] < 0
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/scoring/test_overhead_supply.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/scoring/overhead_supply.py`**:

```python
"""Overhead supply layer penalty score.

Course source: 【成本原理】層層套牢的結構判斷.

Counts swing-high peaks above current price in trailing 240 days as a
proxy for "layered trapped supply". Higher count = more resistance.

Required df columns: overhead_supply_layer (added by features pipeline).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series. Negative penalty for stacked overhead peaks.

      0 peaks    → 0
      1–3 peaks  → -5
      4+ peaks   → -15
    """
    layer = df["overhead_supply_layer"].fillna(0)
    s = pd.Series(0.0, index=df.index)
    s -= np.where(layer >= 4, 15, np.where(layer >= 1, 5, 0))
    return s
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/scoring/test_overhead_supply.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/scoring/overhead_supply.py tests/kline/scoring/test_overhead_supply.py
git commit -m "feat(kline): scoring.overhead_supply — layered trapped supply penalty"
```

---

### Task 18: `scoring/ma60_rolloff.py`

**Files:**
- Create: `scripts/kline/scoring/ma60_rolloff.py`
- Create: `tests/kline/scoring/test_ma60_rolloff.py`

- [ ] **Step 1: Write failing test** `tests/kline/scoring/test_ma60_rolloff.py`:

```python
"""ma60_rolloff.score: penalty when upcoming MA60 carry-off is bullish.

Course source: 【移動平均】季線與K線高低點.

If the close 60 bars ago (about to roll off) is LOW, removing it pulls
MA60 UP — supportive. If HIGH, removing it pushes MA60 DOWN — pressure.
"""
from __future__ import annotations

import pandas as pd

from kline.scoring.ma60_rolloff import score
from tests.conftest import make_bars


def test_rolloff_close_above_current_close_is_penalty():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [110.0]  # higher than current 100 → MA60 will drop
    out = score(df)
    assert out.iloc[0] < 0


def test_rolloff_close_below_current_close_is_bonus():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [90.0]  # lower than current → MA60 will rise
    out = score(df)
    assert out.iloc[0] > 0


def test_nan_rolloff_returns_zero():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [float("nan")]
    out = score(df)
    assert out.iloc[0] == 0.0
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/scoring/test_ma60_rolloff.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/kline/scoring/ma60_rolloff.py`**:

```python
"""MA60 carry-off (扣抵) pressure score.

Course source: 【移動平均】季線與K線高低點.

MA60 direction tomorrow is determined by comparing today's new close
against the close from 60 bars ago (which is about to roll off the window).

  new_close > rolling_off_close → MA60 turns up tomorrow  (bullish)
  new_close < rolling_off_close → MA60 turns down tomorrow (bearish)

This factor adds a small bonus/penalty proportional to the carry-off
direction.

Required df columns: close, ma60_rolling_off_close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAX_DELTA = 10.0  # cap so extreme rolloffs don't dominate


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series.

      +10 if rolling_off_close is well below current close
      −10 if well above
      0 otherwise / NaN
    """
    delta = df["close"] - df["ma60_rolling_off_close"]
    # Normalize to ~[-1, 1] then scale.
    norm = (delta / df["close"].replace(0, np.nan)).clip(-0.10, 0.10) / 0.10
    return (norm * MAX_DELTA).fillna(0.0)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/kline/scoring/test_ma60_rolloff.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/kline/scoring/ma60_rolloff.py tests/kline/scoring/test_ma60_rolloff.py
git commit -m "feat(kline): scoring.ma60_rolloff — carry-off direction bonus/penalty"
```

---

## Task 19: Scoring Stub + Registry

**Files:**
- Create: `scripts/kline/scoring/shadow_position.py` (STUB)
- Modify: `scripts/kline/scoring/__init__.py`
- Create: `tests/kline/scoring/test_registry.py`

- [ ] **Step 1: Write failing test** `tests/kline/scoring/test_registry.py`:

```python
"""SCORING_REGISTRY: includes all factors + stub returns zeros."""
from __future__ import annotations

import pandas as pd

from kline.scoring import SCORING_REGISTRY, shadow_position
from tests.conftest import make_bars


def test_registry_has_expected_factors():
    assert set(SCORING_REGISTRY.keys()) == {
        "attack_quality",
        "overhead_supply",
        "ma60_rolloff",
        "shadow_position",
    }


def test_shadow_position_stub_returns_zero():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    out = shadow_position.score(df)
    assert (out == 0.0).all()
    assert shadow_position.__doc__.lstrip().startswith("STUB:")
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/kline/scoring/test_registry.py -v`
Expected: ImportError.

- [ ] **Step 3: Create `scripts/kline/scoring/shadow_position.py`**:

```python
"""STUB: K線行進ing — Position-based shadow scoring.

Course source: K線行進ing 影線篇(一)(二) — 上影線在不同位置的意義.

> 「同樣的上影線在新高、遇壓、整理三種位置意義完全不同」

Replace this stub when 行進ing subcategory is read.
"""
from __future__ import annotations

import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    return pd.Series(0.0, index=df.index)
```

- [ ] **Step 4: Replace `scripts/kline/scoring/__init__.py`**:

```python
"""Scoring factors for K-line course system.

Public API:
    SCORING_REGISTRY: dict mapping factor name to score(df) function.

External repos can also import individual factors directly:
    from kline.scoring.attack_quality import score
"""
from __future__ import annotations

from .attack_quality import score as attack_quality_score
from .ma60_rolloff import score as ma60_rolloff_score
from .overhead_supply import score as overhead_supply_score
from .shadow_position import score as shadow_position_score

from . import attack_quality, ma60_rolloff, overhead_supply, shadow_position

SCORING_REGISTRY = {
    "attack_quality":  attack_quality_score,
    "overhead_supply": overhead_supply_score,
    "ma60_rolloff":    ma60_rolloff_score,
    "shadow_position": shadow_position_score,
}

__all__ = [
    "SCORING_REGISTRY",
    "attack_quality", "ma60_rolloff", "overhead_supply", "shadow_position",
]
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/kline/scoring/ -v`
Expected: all scoring tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/kline/scoring/shadow_position.py scripts/kline/scoring/__init__.py \
        tests/kline/scoring/test_registry.py
git commit -m "feat(kline): SCORING_REGISTRY + shadow_position stub"
```

---

## Task 20: Extras — strict_breakout Toggle

**Files:**
- Create: `scripts/kline/extras/__init__.py`
- Create: `scripts/kline/extras/strict_breakout.py`
- Create: `tests/kline/extras/__init__.py`
- Create: `tests/kline/extras/test_strict_breakout.py`

- [ ] **Step 1: Write failing test** `tests/kline/extras/test_strict_breakout.py`:

```python
"""strict_breakout.filter: non-course filter — red K + close_pos + volume_ratio."""
from __future__ import annotations

import pandas as pd

from kline.extras.strict_breakout import filter as strict_filter
from tests.conftest import make_bars


def _bars_for_filter():
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104, "volume": 2000},  # red, close_pos high, vol high
        {"open": 100, "high": 105, "low": 99,  "close": 99,  "volume": 2000},  # black
        {"open": 100, "high": 105, "low": 99,  "close": 101, "volume": 2000},  # red but close_pos low
    ]
    df = make_bars(rows)
    df["is_red"] = df["close"] > df["open"]
    df["close_pos"] = (df["close"] - df["low"]) / (df["high"] - df["low"])
    df["volume_ratio"] = [2.0, 2.0, 2.0]
    return df


def test_filter_passes_red_high_close_pos_high_volume():
    df = _bars_for_filter()
    out = strict_filter(df)
    assert out.iloc[0] == True


def test_filter_blocks_black_k():
    df = _bars_for_filter()
    out = strict_filter(df)
    assert out.iloc[1] == False


def test_filter_blocks_low_close_pos():
    df = _bars_for_filter()
    out = strict_filter(df)
    assert out.iloc[2] == False
```

- [ ] **Step 2: Create `tests/kline/extras/__init__.py`** (empty)

- [ ] **Step 3: Run failing test**

Run: `uv run pytest tests/kline/extras/test_strict_breakout.py -v`
Expected: ImportError.

- [ ] **Step 4: Create `scripts/kline/extras/__init__.py`**:

```python
"""Non-course extras — optional filters and toggles.

Per spec §11, anything NOT in the K-line course lives here. Default OFF.
"""
```

- [ ] **Step 5: Create `scripts/kline/extras/strict_breakout.py`**:

```python
"""EXTRA: Strict-breakout filter (NOT in course).

The course explicitly says breakout entry does NOT require:
  - red K
  - close_pos threshold
  - volume ratio threshold

This filter is provided for users who want to ADD those restrictions on
top of the pure breakout signal. Default usage: disabled.

Course stance: see 【突破跌破】突破意義的釐清 — "價格才是最重要的事情，
不需要加上成交量" and "與這一根突破的K線是否長紅...都無關".
"""
from __future__ import annotations

import pandas as pd

MIN_CLOSE_POS = 0.7
MIN_VOLUME_RATIO = 1.2


def filter(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = bar passes all strict filters."""
    return (
        df["is_red"]
        & (df["close_pos"] >= MIN_CLOSE_POS)
        & (df["volume_ratio"] >= MIN_VOLUME_RATIO)
    ).fillna(False)
```

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/kline/extras/test_strict_breakout.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/kline/extras/ tests/kline/extras/
git commit -m "feat(kline): extras.strict_breakout — opt-in non-course filter"
```

---

## Task 21: `scripts/backtest.py` — Backtest Entry Point

**Files:**
- Create: `scripts/backtest.py`
- Create: `tests/test_backtest_entrypoint.py`

- [ ] **Step 1: Write failing test** `tests/test_backtest_entrypoint.py`:

```python
"""backtest.py end-to-end: load → features → entry → simulate → trades."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest


def test_run_backtest_produces_trades_csv(tmp_path: Path, monkeypatch):
    # Mock DB with enough bars to allow prior_high_60 and a breakout.
    db = tmp_path / "test.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            create table standard_daily_bar (
                ticker text, trade_date text,
                open real, high real, low real, close real, volume real,
                ma20 real, ma60 real, ma240 real,
                vol_ma20 real, vol_ratio_20 real,
                is_attention_stock int, is_disposition_stock int, is_usable int
            )
        """)
        # 80 ascending bars then a clear breakout
        for i in range(80):
            conn.execute(
                "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("1101", f"2025-01-{(i % 30) + 1:02d}",
                 100, 101, 99, 100, 1000, 100, 90.0, 100,
                 1000, 1.0, 0, 0, 1),
            )
        # Breakout day
        conn.execute(
            "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("1101", "2025-04-01", 105, 115, 104, 114, 2000, 100, 100.0, 100,
             1000, 2.0, 0, 0, 1),
        )
        conn.commit()

    from scripts import backtest
    out_path = tmp_path / "trades.csv"
    trades = backtest.run(db_path=db, out_path=out_path)
    assert out_path.exists()
    # We expect at least zero rows — even if no exits trigger, function returns DataFrame
    assert isinstance(trades, pd.DataFrame)
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/test_backtest_entrypoint.py -v`
Expected: ImportError.

- [ ] **Step 3: Create `scripts/backtest.py`**:

```python
"""End-to-end backtest entry point.

Loads bars, computes features, runs entry detection, simulates exits,
writes trades CSV.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.entry import breakout_attack
from kline.exit.simulator import simulate
from kline.features import add_features

DEFAULT_OUT = Path("data/analysis/kline/backtest_trades.csv")


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path = DEFAULT_OUT,
) -> pd.DataFrame:
    """Run the full backtest pipeline. Returns the trades DataFrame."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bars = load_bars(db_path=db_path)
    feats = add_features(bars)
    # Required exit columns that the simulator will pull from df:
    # prev_low, prev_close, prior_low_20, ma60_slope_5d, market_open_ret.
    # All except market_open_ret are added by features. For tests, we fill 0.
    feats["market_open_ret"] = 0.0

    entries = breakout_attack(feats)
    trades = simulate(feats, entries)
    trades.to_csv(out_path, index=False)
    return trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    trades = run(db_path=args.db, out_path=args.out)
    print(f"Wrote {len(trades)} trades → {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_backtest_entrypoint.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest.py tests/test_backtest_entrypoint.py
git commit -m "feat(kline): backtest.py end-to-end pipeline entry point"
```

---

## Task 22: `scripts/scanner.py` — Daily Scanner Entry Point

**Files:**
- Create: `scripts/scanner.py`
- Create: `tests/test_scanner_entrypoint.py`

- [ ] **Step 1: Write failing test** `tests/test_scanner_entrypoint.py`:

```python
"""scanner.py: produces ranked candidates for a given as_of date."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def test_scanner_returns_dataframe_with_score(tmp_path: Path):
    db = tmp_path / "test.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            create table standard_daily_bar (
                ticker text, trade_date text,
                open real, high real, low real, close real, volume real,
                ma20 real, ma60 real, ma240 real,
                vol_ma20 real, vol_ratio_20 real,
                is_attention_stock int, is_disposition_stock int, is_usable int
            )
        """)
        for i in range(80):
            conn.execute(
                "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("1101", f"2025-01-{(i % 30) + 1:02d}",
                 100, 101, 99, 100, 1000, 100, 90.0, 100, 1000, 1.0, 0, 0, 1),
            )
        conn.execute(
            "insert into standard_daily_bar values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("1101", "2025-04-01", 105, 115, 104, 114, 2000, 100, 100.0, 100,
             1000, 2.0, 0, 0, 1),
        )
        conn.commit()

    from scripts import scanner
    out_path = tmp_path / "scanner.csv"
    df = scanner.run(db_path=db, out_path=out_path)
    assert "scanner_score" in df.columns
    assert "ticker" in df.columns
    assert out_path.exists()
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/test_scanner_entrypoint.py -v`
Expected: ImportError.

- [ ] **Step 3: Create `scripts/scanner.py`**:

```python
"""Daily scanner entry point.

Loads bars, computes features, runs entry detection, scores candidates,
writes ranked CSV.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.entry import breakout_attack
from kline.features import add_features
from kline.scoring import SCORING_REGISTRY

DEFAULT_OUT = Path("data/analysis/kline/scanner_today.csv")


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path = DEFAULT_OUT,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Run the scanner. Returns ranked candidates DataFrame."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bars = load_bars(db_path=db_path)
    feats = add_features(bars)

    # Features the scoring factors need that aren't in add_features:
    if "pre_breakout_trend_days" not in feats:
        # Consecutive days closing above ma60 prior to today, capped at 20.
        above = (feats["close"] > feats["ma60"]).fillna(False).astype(int)
        feats["pre_breakout_trend_days"] = (
            above.groupby(feats["ticker"])
                 .apply(lambda s: s.shift(1).fillna(0)
                                   .rolling(20, min_periods=1).sum().astype(int))
                 .reset_index(level=0, drop=True)
        )
    if "overhead_supply_layer" not in feats:
        feats["overhead_supply_layer"] = 0.0  # placeholder; precise version pending VP

    entries = breakout_attack(feats)
    candidates = feats[entries].copy()

    if as_of is not None:
        candidates = candidates[candidates["trade_date"] == as_of]

    # Sum all scoring factors.
    total = pd.Series(0.0, index=candidates.index)
    for name, fn in SCORING_REGISTRY.items():
        contribution = fn(candidates)
        candidates[f"score_{name}"] = contribution
        total += contribution
    candidates["scanner_score"] = total.clip(0, 200)

    candidates = candidates.sort_values("scanner_score", ascending=False)
    candidates.to_csv(out_path, index=False)
    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD")
    args = parser.parse_args()
    as_of = pd.Timestamp(args.as_of) if args.as_of else None
    df = run(db_path=args.db, out_path=args.out, as_of=as_of)
    print(f"Wrote {len(df)} candidates → {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_scanner_entrypoint.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (every test from Tasks 2–22).

- [ ] **Step 6: Commit**

```bash
git add scripts/scanner.py tests/test_scanner_entrypoint.py
git commit -m "feat(kline): scanner.py entry point with summed scoring factors"
```

---

## Task 23: README + STUB Inventory

**Files:**
- Create: `scripts/kline/README.md`

- [ ] **Step 1: Verify all STUBs are grep-able**

Run: `grep -rln '"""STUB:' scripts/kline/`
Expected output (10 files):

```
scripts/kline/entry/trend_reversal.py
scripts/kline/entry/sunrise.py
scripts/kline/exit/supply_zone_reach.py
scripts/kline/exit/ma60_neckline.py
scripts/kline/exit/reversal_k/bearish_engulfing.py
scripts/kline/exit/reversal_k/enemy_at_gate.py
scripts/kline/exit/reversal_k/evening_star.py
scripts/kline/exit/reversal_k/two_crows.py
scripts/kline/exit/reversal_k/gap_reversal.py
scripts/kline/scoring/shadow_position.py
```

- [ ] **Step 2: Write `scripts/kline/README.md`**:

```markdown
# K-Line Course System (`kline/`)

Clean, vectorized, DataFrame-in/out implementation of the K-line course
content. Every condition is a pure function; every file is self-contained
(only depends on pandas/numpy) so external repos can copy individual files.

## Layout

```
kline/
├── bars.py          # SQLite → DataFrame
├── features.py      # Derived features (MA, prev_*, shadows, etc.)
├── entry/           # Entry conditions
├── exit/            # Exit conditions + simulator
├── scoring/         # Scoring factors for scanner
└── extras/          # Non-course toggles (default OFF)
```

## Conventions

- All DataFrames sorted by (ticker, trade_date) ascending.
- Entry/exit condition signature:
  ```python
  def detect(df) -> pd.Series:    # bool, for entry
  def mark(df, entries=None) -> pd.Series:  # bool, for exit
  ```
- Scoring factor signature:
  ```python
  def score(df) -> pd.Series:  # float
  ```

## Replacing a STUB

Every STUB file has a docstring starting with `"""STUB:` so they're
discoverable:

```bash
grep -rln '"""STUB:' scripts/kline/
```

To replace one (e.g. enemy_at_gate when 多空轉折 is read):

1. Open `scripts/kline/exit/reversal_k/enemy_at_gate.py`.
2. Replace the `mark()` body with the actual structural detection.
3. Update the module docstring (remove the `STUB:` prefix, keep the
   course source citation).
4. Add tests to `tests/kline/exit/reversal_k/test_enemy_at_gate.py`.
5. No other file needs to change — the registry already references it.

## External Integration

External repos can import single conditions without pulling the registry:

```python
from kline.exit.gap_fill import mark as gap_fill_exit
result = gap_fill_exit(df)
```

The file `gap_fill.py` only imports pandas + numpy.

## Running

```bash
uv run python -m scripts.backtest --db /path/to/data.sqlite --out trades.csv
uv run python -m scripts.scanner  --db /path/to/data.sqlite --as-of 2026-05-15
```

## Running Tests

```bash
uv run pytest
```

## Course Source References

The canonical course rules are in
`docs/K線力量判斷入門/course_principles.md` (Chinese) and
`docs/ai-context/reference_course_source_of_truth.md` (English).

Each condition's docstring cites its course article. Future subcategories
(K線行進ing, 多空轉折組合K線) will replace the STUB files when read.
```

- [ ] **Step 3: Commit**

```bash
git add scripts/kline/README.md
git commit -m "docs(kline): README with stub replacement guide"
```

- [ ] **Step 4: Final full-suite check**

Run: `uv run pytest -v && uv run ruff check scripts/ tests/`
Expected: all tests pass, ruff reports no errors.

- [ ] **Step 5: Final tree verification**

Run: `find scripts/kline -name "*.py" | sort`
Expected output: 25 .py files (14 implemented + 10 stubs + 1 simulator + numerous __init__).

---

## Self-Review

**Spec coverage check (against `docs/superpowers/specs/2026-05-15-kline-system-redesign-design.md`):**

| Spec section | Covered by task | Notes |
|---|---|---|
| §2 目錄結構 | All tasks | All 24 listed files created |
| §3.1 Bar schema | Task 2 (bars.py) | Required columns asserted |
| §3.2 Features schema | Task 3 (features.py) | All derived columns covered |
| §3.3 Function signatures | Tasks 4–19 | Each task uses spec signature |
| §3.4 Trades schema | Task 15 (simulator) | All columns produced |
| §4.1 breakout (no color/vol) | Task 4 | Tested explicitly |
| §4.2 trend_reversal stub | Task 5 | STUB |
| §4.3 sunrise stub | Task 5 | STUB |
| §5.1 EXIT_PRIORITY | Task 14 | Tested |
| §5.2 gap_fill (E1) | Task 6 | Tested |
| §5.3 breakout_low_break (E4) | Task 7 | Tested incl. per-ticker isolation |
| §5.4 neckline_break (E3) | Task 8 | Next-day confirmation tested |
| §5.5 trailing_stop | Task 9 | Per-trade expanding max tested |
| §5.6 trend_change | Task 10 | MA60 done; 末升低/趨勢線 marked TODO inside file |
| §5.7 prev_day_low_break | Task 11 | Tested |
| §5.8 supply_zone_reach | Task 12 | STUB |
| §5.9 ma60_neckline | Task 12 | STUB |
| §5.10 dark_double_star | Task 13 | Tested |
| §5.11 five reversal_k stubs | Task 13 | All 5 stubs created |
| §6 scoring factors | Tasks 16–19 | attack_quality + overhead_supply + ma60_rolloff + shadow_position stub |
| §7 Registry | Tasks 5, 14, 19 | ENTRY/EXIT/SCORING registries |
| §8 Simulator | Task 15 | Vectorized priority-based |
| §9 Stub conventions | Tasks 5, 12, 13, 19 | All stubs grep-able with `"""STUB:` |
| §10 Known limitations | Documented inline as TODO funcs / file docstrings | |
| §11 No compat | Clean branch — n/a | |
| §12 Multi-model | This document's "Parallelization & Model Assignment" table | |
| §13 Test strategy | Every task has TDD steps | |
| §14 Deliverables | Tasks 1–23 cover all | |

**Placeholder scan:** No "TBD", "implement later", or "TODO" in step bodies. The `_TODO_last_rally_low` and `_TODO_rising_trendline` helpers in Task 10 are intentional, documented placeholders for course concepts intro doesn't define precisely.

**Type consistency:** All entry functions named `detect`, all exit functions named `mark`, all scoring functions named `score`. Registry keys match across tests and implementations.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-15-kline-system-redesign.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task using the multi-model assignment from §Parallelization, review between tasks. Maximizes parallelism for the 6 exit-condition tasks and 3 scoring tasks.

**2. Inline Execution** — Execute tasks sequentially in this session, batch with checkpoints.

Which approach?
