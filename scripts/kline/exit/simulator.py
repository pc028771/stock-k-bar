"""Vectorized trade simulator.

For each entry signal, compute exit by:
  1. Run every condition's mark(df, entries) to get bool columns.
  2. For each trade (entry occurrence per ticker), look at bars from the
     day AFTER entry signal (entry executes at next-day open).
  3. Walk forward; on the first bar where ANY condition is True, exit at
     the bar's NEXT-day open. The exit_reason is determined by exit priority.
  4. If no condition fires, exit at the last available bar's open.

Output: trades DataFrame matching spec §3.4.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import EXIT_REGISTRY

ROUND_TRIP_COST = 0.00585  # tax + brokerage


def simulate(
    df: pd.DataFrame,
    entries: pd.Series,
    entry_name: str | None = None,
    exit_priority: list[str] | None = None,
    exit_registry: dict | None = None,
    extra_exits: list[tuple[str, callable]] | None = None,
    cost: float = ROUND_TRIP_COST,
) -> pd.DataFrame:
    """Run vectorized exit simulation for every entry signal.

    df must be sorted by (ticker, trade_date).
    entries: bool Series aligned with df.

    Args:
        entry_name: If provided, looks up the course-correct exit priority
                    via kline.exit.groups.get_exit_priority(entry_name).
                    Required unless exit_priority is explicitly provided.
        exit_priority: Override the per-entry priority. If neither
                       entry_name nor exit_priority is provided, raises.
    """
    if exit_priority is None:
        if entry_name is None:
            raise ValueError(
                "Either entry_name or exit_priority must be provided. "
                "Course requires rally-type-specific exits (see kline.exit.groups)."
            )
        from .groups import get_exit_priority
        exit_priority = get_exit_priority(entry_name)
    if exit_registry is None:
        exit_registry = EXIT_REGISTRY

    if len(entries) != len(df):
        raise ValueError(
            f"entries length {len(entries)} != df length {len(df)}"
        )

    # Course exits first; extras appended at end (lowest priority — safety net).
    full_priority: list[str] = list(exit_priority)
    extras_fns: dict[str, callable] = {}
    if extra_exits:
        for name, fn in extra_exits:
            full_priority.append(name)
            extras_fns[name] = fn

    # Compute every exit condition column once.
    exit_cols: dict[str, pd.Series] = {}
    for name in full_priority:
        fn = extras_fns.get(name) or exit_registry[name]
        exit_cols[name] = (
            fn(df, entries)
            .reindex(df.index)
            .fillna(False)
            .astype(bool)
            .reset_index(drop=True)
        )

    work = df.reset_index(drop=True).copy()
    work["_entries"] = entries.reset_index(drop=True).values

    # Hot-loop perf: pre-extract hot columns to numpy. The original looped
    # ~14k trades × ~6 exit conditions, each doing several pandas scalar
    # .loc[pos, col] lookups — each lookup pays full pandas indexing overhead.
    # numpy array indexing is ~100x faster per access; trades CSV byte-equal.
    open_arr  = work["open"].to_numpy()
    close_arr = work["close"].to_numpy()
    date_arr  = work["trade_date"].to_numpy()
    ticker_arr = work["ticker"].to_numpy()
    entries_arr = work["_entries"].to_numpy()
    exit_cols_np: dict[str, np.ndarray] = {
        name: col.to_numpy() for name, col in exit_cols.items()
    }

    records: list[dict] = []

    # Build per-ticker start/end positions in one pass (work is sorted by ticker).
    n = len(work)
    ticker_changes = np.concatenate(([0], np.where(ticker_arr[1:] != ticker_arr[:-1])[0] + 1, [n]))
    for gi in range(len(ticker_changes) - 1):
        start = int(ticker_changes[gi])
        ticker_last = int(ticker_changes[gi + 1] - 1)
        ticker = ticker_arr[start]
        # entries in this ticker's slice
        entry_positions = np.nonzero(entries_arr[start:ticker_last + 1])[0]
        if len(entry_positions) == 0:
            continue
        entry_positions = entry_positions + start

        for entry_pos in entry_positions:
            entry_pos = int(entry_pos)
            next_pos = entry_pos + 1
            if next_pos > ticker_last:
                continue

            entry_open = float(open_arr[next_pos])
            if entry_open <= 0:
                continue

            best_pos = None
            best_reason = None
            for name in full_priority:
                col = exit_cols_np[name]
                # find first True position in [next_pos, ticker_last]
                window = col[next_pos:ticker_last + 1]
                if not window.any():
                    continue
                first = next_pos + int(np.argmax(window))
                if best_pos is None or first < best_pos:
                    best_pos = first
                    best_reason = name

            if best_pos is not None:
                exit_signal_pos = best_pos
                exit_execute_pos = exit_signal_pos + 1
                if exit_execute_pos > ticker_last:
                    exit_open = float(close_arr[exit_signal_pos])
                    exit_date = date_arr[exit_signal_pos]
                    hold_days = exit_signal_pos - next_pos + 1
                else:
                    exit_open = float(open_arr[exit_execute_pos])
                    exit_date = date_arr[exit_execute_pos]
                    hold_days = exit_execute_pos - next_pos
                exit_reason = best_reason
            else:
                exit_open = float(open_arr[ticker_last])
                if exit_open <= 0:
                    exit_open = float(close_arr[ticker_last])
                exit_date = date_arr[ticker_last]
                hold_days = ticker_last - next_pos + 1
                exit_reason = "open"

            trade_return = exit_open / entry_open - 1
            records.append({
                "ticker": ticker,
                "entry_date": date_arr[entry_pos],
                "entry_open": round(entry_open, 4),
                "exit_date": exit_date,
                "exit_open": round(exit_open, 4),
                "exit_reason": exit_reason,
                "hold_days": int(hold_days),
                "trade_return": round(trade_return, 6),
                "trade_return_net": round(trade_return - cost, 6),
            })

    return pd.DataFrame(records)
