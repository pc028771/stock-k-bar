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
