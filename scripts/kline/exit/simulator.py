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

    records: list[dict] = []

    for ticker, grp in work.groupby("ticker", sort=False):
        grp_idx = grp.index.to_numpy()
        entry_positions = grp_idx[grp["_entries"].to_numpy()]
        if len(entry_positions) == 0:
            continue

        for entry_pos in entry_positions:
            next_pos = entry_pos + 1
            ticker_last = grp_idx[-1]
            if next_pos > ticker_last:
                continue  # signal on last bar — no next open available

            entry_open = float(work.loc[next_pos, "open"])
            if entry_open <= 0:
                continue

            window_positions = grp_idx[grp_idx >= next_pos]

            best_pos = None
            best_reason = None
            for name in full_priority:
                col = exit_cols[name]
                trigger_positions = window_positions[col.iloc[window_positions].to_numpy()]
                if len(trigger_positions) == 0:
                    continue
                first = trigger_positions[0]
                # Priority order wins on ties: strict < keeps higher-priority condition.
                if best_pos is None or first < best_pos:
                    best_pos = int(first)
                    best_reason = name

            if best_pos is not None:
                exit_signal_pos = best_pos
                exit_execute_pos = exit_signal_pos + 1
                if exit_execute_pos > ticker_last:
                    # Exit signal fires on last available bar — no next-open available.
                    # exit_open = close of signal bar; hold_days counts this day inclusively.
                    exit_open = float(work.loc[exit_signal_pos, "close"])
                    exit_date = work.loc[exit_signal_pos, "trade_date"]
                    hold_days = exit_signal_pos - next_pos + 1
                else:
                    exit_open = float(work.loc[exit_execute_pos, "open"])
                    exit_date = work.loc[exit_execute_pos, "trade_date"]
                    hold_days = exit_execute_pos - next_pos
                exit_reason = best_reason
            else:
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
