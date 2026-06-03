"""Branch / Light condition mini-DSL evaluator.

This module implements a safe, vectorizable mini-language for expressing
``Branch.when`` and ``Light.trigger_condition`` dicts.

Design principles
-----------------
- **Whitelist only**: Any field or operator not in the explicit whitelist raises
  ``UnknownTokenError`` immediately (fail loud, per CLAUDE.md + spec §4.2).
- **RHS must be a scalar or another whitelisted field**: Arithmetic expressions
  like ``"today.volume * 1.5"`` are rejected. This keeps vectorize safe.
- **Nested depth ≤ 2**: Deeper nesting raises ``UnknownTokenError``.
- **next_day.* in scalar mode**: Returns ``None`` (pending) because next-day
  values are unknown at evaluation time.  A ``None`` result means "not yet
  confirmed", not "false".
- **next_day_n**: Controls ``shift(-N)`` in vectorized mode (default 1).
  Passed as a parameter; not embedded in the YAML condition itself.

Usage
-----
Scalar (single-row, advisor usage)::

    from scripts.kline.scenarios.condition import evaluate, UnknownTokenError
    result = evaluate(when_dict, row_series, ctx_snapshot, next_day_n=1)
    # True / False / None (None = pending because next_day.* not known yet)

Vectorized (simulator / backtest usage)::

    from scripts.kline.scenarios.condition import evaluate_vectorized
    bool_series = evaluate_vectorized(when_dict, df, ctx_df, next_day_n=1)
    # pd.Series[bool] aligned with df.index; NaN rows become False
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from ._schema import ContextSnapshot

# ---------------------------------------------------------------------------
# Whitelist of allowed field tokens
# ---------------------------------------------------------------------------

_TODAY_FIELDS = frozenset({"open", "high", "low", "close", "volume"})
_PREV_FIELDS = frozenset({"open", "high", "low", "close"})
_NEXT_DAY_FIELDS = frozenset({"open", "high", "low", "close", "gap_up", "gap_down", "fills_gap"})
_CONTEXT_FIELDS = frozenset({
    "ma5_will_rise",
    "ma10_will_rise",
    "ma20_will_rise",
    "ma60_will_rise",
    # 大盤創紀錄跌點 §30 (Task 3.S4)
    "taiex_record_drop_point",
    "taiex_record_drop_pct",
    "taiex_record_limit_down_count",
    "taiex_record_any_criterion",
    "taiex_no_new_low_next_day",
})
_TOPLEVEL_FIELDS = frozenset({
    "prev_high_60",
    "prior_low_60",
    "attack_cost",
    "attack_intent_zone_high",
    "attack_intent_zone_low",
    "defensive_low",
    "merged_high",
    "merged_low",
})

# Full whitelist (string representations for fast lookup)
_ALL_ALLOWED_FIELDS: frozenset[str] = (
    frozenset(f"today.{f}" for f in _TODAY_FIELDS)
    | frozenset(f"prev.{f}" for f in _PREV_FIELDS)
    | frozenset(f"next_day.{f}" for f in _NEXT_DAY_FIELDS)
    | frozenset(f"context.{f}" for f in _CONTEXT_FIELDS)
    | _TOPLEVEL_FIELDS
)

# Boolean-only fields (only accept true/false)
_BOOL_FIELDS = frozenset({
    "next_day.gap_up",
    "next_day.gap_down",
    "next_day.fills_gap",
    "context.ma5_will_rise",
    "context.ma10_will_rise",
    "context.ma20_will_rise",
    "context.ma60_will_rise",
    # 大盤創紀錄跌點 §30 (Task 3.S4)
    "context.taiex_record_drop_point",
    "context.taiex_record_drop_pct",
    "context.taiex_record_limit_down_count",
    "context.taiex_record_any_criterion",
    "context.taiex_no_new_low_next_day",
})

# Logical operator keys
_LOGIC_KEYS = frozenset({"all", "any", "not"})

# Comparison operators (for string-expression RHS)
_COMPARISON_OPS = frozenset({">", "<", ">=", "<=", "==", "!="})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UnknownTokenError(Exception):
    """Raised when the when-dict contains an unknown field, operator, or RHS."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_field(field: str) -> None:
    """Raise ``UnknownTokenError`` if *field* is not in the whitelist."""
    if field not in _ALL_ALLOWED_FIELDS:
        raise UnknownTokenError(f"unknown field: {field!r}")


def _parse_comparison_expr(expr: str) -> tuple[str, Any]:
    """Parse a string like ``"> today.high"`` or ``"<= 100.5"`` into
    ``(operator, rhs)`` where *rhs* is either a float/int or a field name.

    Raises ``UnknownTokenError`` on unknown operator or invalid RHS.
    """
    expr = expr.strip()
    op: Optional[str] = None
    for candidate in (">=", "<=", "!=", ">", "<", "=="):
        if expr.startswith(candidate):
            op = candidate
            rhs_str = expr[len(candidate):].strip()
            break
    if op is None:
        raise UnknownTokenError(f"unknown operator in expression: {expr!r}")

    # RHS: numeric constant, whitelisted field name, or plain string literal
    # (string literals are only valid with == / != operators)
    try:
        rhs: Any = float(rhs_str)
        # Keep as float for simplicity.
    except ValueError:
        # Check for forbidden arithmetic expressions first
        # Note: "-" alone is not treated as arithmetic (e.g. negative numbers are
        # handled by float() above); we only block "field OP number" patterns
        if "*" in rhs_str or (
            "+" in rhs_str and not rhs_str.startswith("+")
        ):
            raise UnknownTokenError(
                f"RHS expressions are not allowed (only constants or field refs): {rhs_str!r}"
            )
        if rhs_str in _ALL_ALLOWED_FIELDS:
            rhs = rhs_str  # field reference
        elif op in ("==", "!="):
            # Allow plain string literals for equality comparisons
            # (e.g. context.ma5_will_rise == true, taiex_record_any_criterion == true)
            rhs = rhs_str
        else:
            raise UnknownTokenError(
                f"unknown field in RHS (string literals only allowed with == / !=): {rhs_str!r}"
            )
    return op, rhs


def _parse_between_value(val: Any) -> tuple[float, float]:
    """Parse the value of a ``between`` condition; must be a list [lo, hi]."""
    if not (isinstance(val, (list, tuple)) and len(val) == 2):
        raise UnknownTokenError(
            f"'between' requires a 2-element list [lo, hi], got: {val!r}"
        )
    try:
        lo, hi = float(val[0]), float(val[1])
    except (TypeError, ValueError) as exc:
        raise UnknownTokenError(
            f"'between' bounds must be numeric, got: {val!r}"
        ) from exc
    return lo, hi


# ---------------------------------------------------------------------------
# Scalar evaluation helpers
# ---------------------------------------------------------------------------


def _resolve_scalar(field: str, row: pd.Series, ctx: ContextSnapshot) -> Any:
    """Resolve a whitelisted field to its scalar value for today's row.

    Returns ``None`` when the field lives in the ``next_day.*`` namespace
    (values are unknown in scalar / advisor mode).
    """
    _validate_field(field)
    if field.startswith("next_day."):
        return None  # pending — unknown in scalar mode
    if field.startswith("today."):
        col = field[len("today."):]
        return row.get(col)
    if field.startswith("prev."):
        col = "prev_" + field[len("prev."):]
        return row.get(col)
    if field.startswith("context."):
        attr = field[len("context."):]
        return getattr(ctx, attr, None)
    # top-level field
    # First try row, then ctx attribute
    val = row.get(field)
    if val is None:
        val = getattr(ctx, field, None)
    return val


def _apply_op_scalar(lhs: Any, op: str, rhs: Any, row: pd.Series, ctx: ContextSnapshot) -> Optional[bool]:
    """Apply a comparison operator in scalar mode.

    If *lhs* or the resolved *rhs* is ``None``, return ``None`` (pending).
    """
    if lhs is None:
        return None
    # Resolve field-ref RHS (only if it's a known whitelisted field)
    if isinstance(rhs, str) and rhs in _ALL_ALLOWED_FIELDS:
        rhs = _resolve_scalar(rhs, row, ctx)
    if rhs is None:
        return None
    if op == ">":
        return bool(lhs > rhs)
    if op == "<":
        return bool(lhs < rhs)
    if op == ">=":
        return bool(lhs >= rhs)
    if op == "<=":
        return bool(lhs <= rhs)
    if op == "==":
        return bool(lhs == rhs)
    if op == "!=":
        return bool(lhs != rhs)
    raise UnknownTokenError(f"unknown operator: {op!r}")


def _eval_condition_scalar(
    field: str,
    val: Any,
    row: pd.Series,
    ctx: ContextSnapshot,
) -> Optional[bool]:
    """Evaluate a single ``{field: val}`` condition in scalar mode.

    ``val`` can be:
    - A bool (for boolean fields)
    - A string starting with a comparison operator
    - A dict with key ``between`` and value ``[lo, hi]``

    Returns ``True``, ``False``, or ``None`` (pending).
    """
    _validate_field(field)

    # ---- Boolean field (gap_up, gap_down, fills_gap, context.broker_*) ----
    if field in _BOOL_FIELDS:
        if not isinstance(val, bool):
            raise UnknownTokenError(
                f"field {field!r} requires a boolean value (true/false), got {val!r}"
            )
        lhs = _resolve_scalar(field, row, ctx)
        if lhs is None:
            return None
        return bool(lhs) == val

    # ---- between ----
    if isinstance(val, dict) and "between" in val:
        lo, hi = _parse_between_value(val["between"])
        lhs = _resolve_scalar(field, row, ctx)
        if lhs is None:
            return None
        return lo <= float(lhs) <= hi

    # ---- comparison string ----
    if isinstance(val, str):
        op, rhs = _parse_comparison_expr(val)
        lhs = _resolve_scalar(field, row, ctx)
        return _apply_op_scalar(lhs, op, rhs, row, ctx)

    # ---- direct equality (numeric or string constant) ----
    if isinstance(val, (int, float, str)):
        lhs = _resolve_scalar(field, row, ctx)
        if lhs is None:
            return None
        return lhs == val

    raise UnknownTokenError(
        f"unsupported value type for field {field!r}: {type(val).__name__}"
    )


def _eval_node_scalar(
    node: dict,
    row: pd.Series,
    ctx: ContextSnapshot,
    depth: int = 0,
) -> Optional[bool]:
    """Recursively evaluate a when-dict node in scalar mode.

    *depth* tracks nesting level; raises ``UnknownTokenError`` beyond 2.
    """
    if depth > 2:
        raise UnknownTokenError(
            f"when-dict nesting depth exceeds 2 layers (current depth={depth})"
        )

    # ---- all: [...] ----
    if "all" in node:
        items = node["all"]
        if not isinstance(items, list):
            raise UnknownTokenError("'all' value must be a list")
        result: Optional[bool] = True
        for item in items:
            if not isinstance(item, dict):
                raise UnknownTokenError(f"'all' items must be dicts, got {type(item).__name__}")
            sub = _eval_node_scalar(item, row, ctx, depth + 1)
            if sub is None:
                result = None  # pending — don't short-circuit
            elif sub is False:
                return False  # short-circuit on definite false
        return result

    # ---- any: [...] ----
    if "any" in node:
        items = node["any"]
        if not isinstance(items, list):
            raise UnknownTokenError("'any' value must be a list")
        result = False
        for item in items:
            if not isinstance(item, dict):
                raise UnknownTokenError(f"'any' items must be dicts, got {type(item).__name__}")
            sub = _eval_node_scalar(item, row, ctx, depth + 1)
            if sub is True:
                return True  # short-circuit on definite true
            if sub is None:
                result = None  # pending
        return result

    # ---- not: {...} ----
    if "not" in node:
        inner = node["not"]
        if not isinstance(inner, dict):
            raise UnknownTokenError("'not' value must be a dict")
        sub = _eval_node_scalar(inner, row, ctx, depth + 1)
        if sub is None:
            return None
        return not sub

    # ---- leaf condition(s): {field: val, ...} ----
    # A node can have multiple field conditions at once (implicit AND)
    results: list[Optional[bool]] = []
    for key, val in node.items():
        if key in _LOGIC_KEYS:
            continue  # already handled above
        results.append(_eval_condition_scalar(key, val, row, ctx))

    if not results:
        raise UnknownTokenError(f"empty condition node: {node!r}")

    # Implicit AND across multiple fields in same dict
    if False in results:
        return False
    if None in results:
        return None
    return True


# ---------------------------------------------------------------------------
# Vectorized evaluation helpers
# ---------------------------------------------------------------------------


def _resolve_vectorized(
    field: str,
    df: pd.DataFrame,
    ctx_df: pd.DataFrame,
    next_day_n: int,
) -> pd.Series:
    """Resolve a whitelisted field to a pd.Series aligned with df.index."""
    _validate_field(field)

    if field.startswith("next_day."):
        sub = field[len("next_day."):]
        if sub == "gap_up":
            # gap_up: next_day open > today close
            return df["close"].shift(-next_day_n) < df["open"].shift(-next_day_n)
        if sub == "gap_down":
            # gap_down: next_day open < today close
            return df["open"].shift(-next_day_n) < df["close"]
        if sub == "fills_gap":
            # fills_gap: if today had gap_up, next_day low <= today high
            #            if today had gap_down, next_day high >= today low
            gap_up_mask = df["open"] > df["close"].shift(1)
            gap_down_mask = df["open"] < df["close"].shift(1)
            nd_low = df["low"].shift(-next_day_n)
            nd_high = df["high"].shift(-next_day_n)
            fills = (gap_up_mask & (nd_low <= df["high"])) | (
                gap_down_mask & (nd_high >= df["low"])
            )
            return fills.fillna(False)
        # Regular OHLC next-day field
        col_map = {"open": "open", "high": "high", "low": "low", "close": "close"}
        col = col_map.get(sub)
        if col is None:
            raise UnknownTokenError(f"unknown next_day sub-field: {sub!r}")
        return df[col].shift(-next_day_n)

    if field.startswith("today."):
        col = field[len("today."):]
        if col not in df.columns:
            raise UnknownTokenError(f"column {col!r} not in df for field {field!r}")
        return df[col].astype(float)

    if field.startswith("prev."):
        col = field[len("prev."):]
        if col not in df.columns:
            raise UnknownTokenError(f"column {col!r} not in df for field prev.{col!r}")
        return df[col].shift(1)

    if field.startswith("context."):
        attr = field[len("context."):]
        if attr not in ctx_df.columns:
            # Return NaN series — None context treated as False
            return pd.Series([None] * len(df), index=df.index, dtype=object)
        return ctx_df[attr]

    # top-level field: try df first, then ctx_df
    if field in df.columns:
        return df[field].astype(float)
    if field in ctx_df.columns:
        return ctx_df[field]
    # Return NaN — will produce False in comparisons
    return pd.Series([None] * len(df), index=df.index, dtype=object)


def _apply_op_vectorized(
    lhs: pd.Series,
    op: str,
    rhs: Any,
    df: pd.DataFrame,
    ctx_df: pd.DataFrame,
    next_day_n: int,
) -> pd.Series:
    """Apply comparison operator element-wise."""
    if isinstance(rhs, str) and rhs in _ALL_ALLOWED_FIELDS:
        rhs_series = _resolve_vectorized(rhs, df, ctx_df, next_day_n)
        rhs_val: Any = rhs_series
    else:
        rhs_val = rhs

    if op == ">":
        result = lhs > rhs_val
    elif op == "<":
        result = lhs < rhs_val
    elif op == ">=":
        result = lhs >= rhs_val
    elif op == "<=":
        result = lhs <= rhs_val
    elif op == "==":
        result = lhs == rhs_val
    elif op == "!=":
        result = lhs != rhs_val
    else:
        raise UnknownTokenError(f"unknown operator: {op!r}")

    return result.fillna(False)


def _eval_condition_vectorized(
    field: str,
    val: Any,
    df: pd.DataFrame,
    ctx_df: pd.DataFrame,
    next_day_n: int,
) -> pd.Series:
    """Evaluate a single ``{field: val}`` condition in vectorized mode."""
    _validate_field(field)

    lhs = _resolve_vectorized(field, df, ctx_df, next_day_n)

    # ---- Boolean field ----
    if field in _BOOL_FIELDS:
        if not isinstance(val, bool):
            raise UnknownTokenError(
                f"field {field!r} requires a boolean value (true/false), got {val!r}"
            )
        result = lhs.astype(object) == val
        return result.fillna(False)

    # ---- between ----
    if isinstance(val, dict) and "between" in val:
        lo, hi = _parse_between_value(val["between"])
        lhs_float = pd.to_numeric(lhs, errors="coerce")
        result = (lhs_float >= lo) & (lhs_float <= hi)
        return result.fillna(False)

    # ---- comparison string ----
    if isinstance(val, str):
        op, rhs = _parse_comparison_expr(val)
        lhs_numeric = pd.to_numeric(lhs, errors="coerce")
        return _apply_op_vectorized(lhs_numeric, op, rhs, df, ctx_df, next_day_n)

    # ---- direct equality ----
    if isinstance(val, (int, float)):
        lhs_numeric = pd.to_numeric(lhs, errors="coerce")
        return (lhs_numeric == float(val)).fillna(False)
    if isinstance(val, str):
        return (lhs == val).fillna(False)

    raise UnknownTokenError(
        f"unsupported value type for field {field!r}: {type(val).__name__}"
    )


def _eval_node_vectorized(
    node: dict,
    df: pd.DataFrame,
    ctx_df: pd.DataFrame,
    next_day_n: int,
    depth: int = 0,
) -> pd.Series:
    """Recursively evaluate a when-dict node in vectorized mode."""
    if depth > 2:
        raise UnknownTokenError(
            f"when-dict nesting depth exceeds 2 layers (current depth={depth})"
        )

    false_series = pd.Series(False, index=df.index)
    true_series = pd.Series(True, index=df.index)

    # ---- all: [...] ----
    if "all" in node:
        items = node["all"]
        if not isinstance(items, list):
            raise UnknownTokenError("'all' value must be a list")
        acc = true_series.copy()
        for item in items:
            if not isinstance(item, dict):
                raise UnknownTokenError(f"'all' items must be dicts, got {type(item).__name__}")
            sub = _eval_node_vectorized(item, df, ctx_df, next_day_n, depth + 1)
            acc = acc & sub
        return acc

    # ---- any: [...] ----
    if "any" in node:
        items = node["any"]
        if not isinstance(items, list):
            raise UnknownTokenError("'any' value must be a list")
        acc = false_series.copy()
        for item in items:
            if not isinstance(item, dict):
                raise UnknownTokenError(f"'any' items must be dicts, got {type(item).__name__}")
            sub = _eval_node_vectorized(item, df, ctx_df, next_day_n, depth + 1)
            acc = acc | sub
        return acc

    # ---- not: {...} ----
    if "not" in node:
        inner = node["not"]
        if not isinstance(inner, dict):
            raise UnknownTokenError("'not' value must be a dict")
        sub = _eval_node_vectorized(inner, df, ctx_df, next_day_n, depth + 1)
        return ~sub

    # ---- leaf condition(s): {field: val, ...} ----
    results: list[pd.Series] = []
    for key, val in node.items():
        if key in _LOGIC_KEYS:
            continue
        results.append(_eval_condition_vectorized(key, val, df, ctx_df, next_day_n))

    if not results:
        raise UnknownTokenError(f"empty condition node: {node!r}")

    # Implicit AND across multiple fields in same dict
    acc = true_series.copy()
    for r in results:
        acc = acc & r
    return acc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate(
    when: dict,
    row: pd.Series,
    ctx: ContextSnapshot,
    next_day_n: int = 1,
) -> Optional[bool]:
    """Scalar evaluation of a ``when`` dict for a single bar.

    Parameters
    ----------
    when:
        The mini-DSL condition dict (from ``Branch.when`` or
        ``Light.trigger_condition``).
    row:
        A ``pd.Series`` representing today's OHLCV bar plus any derived
        features.  Expected columns include ``open``, ``high``, ``low``,
        ``close``, ``volume`` (today), and ``prev_open``, ``prev_high``,
        ``prev_low``, ``prev_close`` for the previous bar.
    ctx:
        A ``ContextSnapshot`` instance carrying context fields (broker,
        teacher, MA will-rise flags, etc.).
    next_day_n:
        Which future bar ``next_day.*`` should resolve to (default 1 =
        tomorrow).  In scalar mode, ``next_day.*`` is always ``None``
        (pending).

    Returns
    -------
    ``True`` if all conditions are satisfied, ``False`` if any are
    definitively false, ``None`` if the result is pending (i.e. at least one
    ``next_day.*`` condition cannot be evaluated yet).

    Raises
    ------
    UnknownTokenError
        If the when-dict contains an unknown field, operator, or RHS
        expression.
    """
    return _eval_node_scalar(when, row, ctx, depth=0)


def evaluate_vectorized(
    when: dict,
    df: pd.DataFrame,
    ctx_df: pd.DataFrame,
    next_day_n: int = 1,
) -> pd.Series:
    """Vectorized evaluation of a ``when`` dict across a historical DataFrame.

    Parameters
    ----------
    when:
        The mini-DSL condition dict.
    df:
        Historical OHLCV DataFrame.  Must contain at minimum ``open``,
        ``high``, ``low``, ``close``, ``volume`` columns.  Additional
        feature columns (e.g. ``prev_high_60``) may also live here.
    ctx_df:
        A DataFrame with the same index as *df* containing context columns
        (e.g. ``ma5_will_rise``, ``taiex_record_any_criterion``).  Missing columns
        are treated as ``None`` → ``False`` in comparisons.
    next_day_n:
        Which future bar ``next_day.*`` resolves to via ``shift(-N)``
        (default 1 = tomorrow).

    Returns
    -------
    A boolean ``pd.Series`` aligned with ``df.index``.  Rows where a
    ``next_day.*`` shift falls off the end of the DataFrame become ``False``.

    Raises
    ------
    UnknownTokenError
        On unknown fields, operators, or invalid RHS expressions.
    """
    result = _eval_node_vectorized(when, df, ctx_df, next_day_n, depth=0)
    return result.astype(bool)
