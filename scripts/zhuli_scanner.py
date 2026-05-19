"""主力大 zhuli daily scanner entry point.

Loads bars, computes features, runs zhuli entry detection, writes ranked CSV.
Currently supports: H 窒息量（zhuli_suffocation）

Usage:
    python scripts/zhuli_scanner.py --help
    python scripts/zhuli_scanner.py --signal suffocation --date 2026-05-19
    python scripts/zhuli_scanner.py --signal suffocation --top-n 50
    python scripts/zhuli_scanner.py --signal suffocation --config-override max20_volume_ratio=0.12
    python scripts/zhuli_scanner.py --signal suffocation --config path/to/config.json

Course: 主力大全方位操盤教戰守則 (林家洋)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Allow running as "python scripts/zhuli_scanner.py" from repo root
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from kline.bars import DEFAULT_DB_PATH, load_bars
from kline.features import add_features
from zhuli.config import SuffocationConfig
from zhuli.entry import ENTRY_REGISTRY
from zhuli.features import add_zhuli_features

DEFAULT_OUT = Path("data/analysis/zhuli/suffocation_scanner.csv")


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path = DEFAULT_OUT,
    as_of: pd.Timestamp | None = None,
    signal_name: str = "suffocation",
    cfg: SuffocationConfig | None = None,
    top_n: int | None = None,
) -> pd.DataFrame:
    """Run the zhuli scanner. Returns signal candidates DataFrame.

    Args:
        db_path:     Path to SQLite database (default: ~/.four_seasons/data.sqlite).
        out_path:    Output CSV path.
        as_of:       Filter signals to this date only. None = all dates.
        signal_name: Entry signal to use (see ENTRY_REGISTRY).
        cfg:         SuffocationConfig. Uses defaults if None.
        top_n:       If set, return only top N rows (by ideal_ma_align desc, then ticker).

    Returns:
        DataFrame of signal candidates.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if cfg is None:
        cfg = SuffocationConfig()

    detect_fn = ENTRY_REGISTRY.get(signal_name)
    if detect_fn is None:
        raise ValueError(
            f"Unknown signal: '{signal_name}'. "
            f"Available: {list(ENTRY_REGISTRY.keys())}"
        )

    bars = load_bars(db_path=db_path)
    feats = add_features(bars)
    feats = add_zhuli_features(feats)

    signals = detect_fn(feats, cfg=cfg)

    if as_of is not None:
        signals = signals[signals["signal_date"] == as_of].copy()

    # Sort: ideal alignment first, then scenario A before B, then ticker
    if len(signals) > 0:
        signals = signals.sort_values(
            ["ideal_ma_align", "scenario", "ticker"],
            ascending=[False, True, True],
        ).reset_index(drop=True)

    if top_n is not None:
        signals = signals.head(top_n)

    signals.to_csv(out_path, index=False)
    return signals


def _parse_config_overrides(overrides_list: list[str] | None) -> dict[str, str]:
    """Parse ['KEY=VALUE', ...] list into dict."""
    if not overrides_list:
        return {}
    result = {}
    for item in overrides_list:
        if "=" not in item:
            raise argparse.ArgumentTypeError(
                f"Config override must be KEY=VALUE format, got: '{item}'"
            )
        k, v = item.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def main():
    parser = argparse.ArgumentParser(
        prog="zhuli_scanner",
        description=(
            "主力大 daily scanner — 窒息量（H策略）及其他主力大進場訊號。\n"
            "Course: 主力大全方位操盤教戰守則 (林家洋)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan for today's suffocation signals
  python scripts/zhuli_scanner.py --signal suffocation

  # Scan a specific date, show top 20
  python scripts/zhuli_scanner.py --date 2021-03-10 --top-n 20

  # Override config threshold
  python scripts/zhuli_scanner.py --config-override max20_volume_ratio=0.12

  # Load config from JSON file
  python scripts/zhuli_scanner.py --config path/to/my_config.json

  # Run sanity check on instructor cases
  python -m zhuli.sanity_check --verbose
""",
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        help="Path to SQLite database (default: ~/.four_seasons/data.sqlite)",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help=f"Output CSV path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--date", "--as-of", type=str, default=None, metavar="YYYY-MM-DD",
        help="Filter to signals on this date. Omit to show all dates.",
    )
    parser.add_argument(
        "--signal",
        default="suffocation",
        choices=list(ENTRY_REGISTRY.keys()),
        help="Entry signal to use (default: suffocation)",
    )
    parser.add_argument(
        "--top-n", type=int, default=None, metavar="N",
        help="Return only top N candidates (sorted by ideal alignment, then ticker).",
    )
    parser.add_argument(
        "--config", type=Path, default=None, metavar="JSON_PATH",
        help="Load SuffocationConfig overrides from a JSON file.",
    )
    parser.add_argument(
        "--config-override", nargs="*", metavar="KEY=VALUE",
        help=(
            "Override individual SuffocationConfig values. "
            "Example: --config-override max20_volume_ratio=0.12 min_close=15"
        ),
    )
    parser.add_argument(
        "--show-config", action="store_true",
        help="Print effective config and exit.",
    )
    parser.add_argument(
        "--sanity-check", action="store_true",
        help="Run instructor case sanity check and exit.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose output (used with --sanity-check).",
    )

    args = parser.parse_args()

    # Build config
    if args.config:
        cfg = SuffocationConfig.from_json(args.config)
    else:
        cfg = SuffocationConfig()

    if args.config_override:
        overrides = _parse_config_overrides(args.config_override)
        cfg = cfg.apply_overrides(overrides)

    if args.show_config:
        print("Effective SuffocationConfig:")
        for k, v in cfg.to_dict().items():
            print(f"  {k}: {v}")
        return

    if args.sanity_check:
        # Delegate to sanity_check module
        from zhuli.sanity_check import run_sanity_check, print_report
        result = run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
        print_report(result)
        sys.exit(0 if result["passed"] else 1)

    as_of = pd.Timestamp(args.date) if args.date else None
    df = run(
        db_path=args.db,
        out_path=args.out,
        as_of=as_of,
        signal_name=args.signal,
        cfg=cfg,
        top_n=args.top_n,
    )

    date_label = args.date if args.date else "all dates"
    print(f"Signal: {args.signal} | Date: {date_label} | Found: {len(df)} candidates")
    if len(df) > 0:
        print(f"Wrote → {args.out}")
        # Print summary table
        summary_cols = [
            c for c in [
                "ticker", "signal_date", "scenario", "breakout_close",
                "stop_loss", "ideal_ma_align", "suffocation_vol_ratio",
                "breakout_bar_type",
            ]
            if c in df.columns
        ]
        print(df[summary_cols].to_string(index=False))
    else:
        print("No signals found.")


if __name__ == "__main__":
    main()
