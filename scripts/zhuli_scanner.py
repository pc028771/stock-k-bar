"""主力大 zhuli daily scanner entry point.

Loads bars, computes features, runs zhuli entry detection, writes ranked CSV.
Supports:
  - H 窒息量（suffocation）
  - M 主力意圖收高開低/收低開高（open_signal_filter）
  - J 投信首買（institutional_firstbuy）
  - A 大波段選股（swing_breakout）— 族群+籌碼+技術三面

Usage:
    python scripts/zhuli_scanner.py --help
    python scripts/zhuli_scanner.py --signal suffocation --date 2026-05-19
    python scripts/zhuli_scanner.py --signal suffocation --top-n 50
    python scripts/zhuli_scanner.py --signal suffocation --config-override max20_volume_ratio=0.12
    python scripts/zhuli_scanner.py --signal suffocation --config path/to/config.json
    python scripts/zhuli_scanner.py --signal open_signal_filter --date 2026-05-15
    python scripts/zhuli_scanner.py --signal open_signal_filter --config-override prev_volume_multiplier=1.5
    python scripts/zhuli_scanner.py --signal institutional_firstbuy --date 2026-05-15
    python scripts/zhuli_scanner.py --signal institutional_firstbuy --config-override min_firstbuy_volume=50
    python scripts/zhuli_scanner.py --signal swing_breakout --date 2026-05-15
    python scripts/zhuli_scanner.py --signal swing_breakout --config-override enforce_dist_to_ma20=true

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
from zhuli.config import BBandsUpperBreakConfig, InstitutionalFirstBuyConfig, OpenSignalConfig, OvernightSwingConfig, PennantFlagConfig, ReversalBreakoutConfig, SuffocationConfig, SwingBreakoutConfig
from zhuli.entry import ENTRY_REGISTRY
from zhuli.features import add_zhuli_features

DEFAULT_OUT = Path("data/analysis/zhuli/suffocation_scanner.csv")

# 各 signal 對應的預設 config 類別與輸出路徑
_SIGNAL_DEFAULTS: dict[str, tuple[type, Path]] = {
    "suffocation": (SuffocationConfig, DEFAULT_OUT),
    "open_signal_filter": (
        OpenSignalConfig,
        Path("data/analysis/zhuli/open_signal_filter_scanner.csv"),
    ),
    "institutional_firstbuy": (
        InstitutionalFirstBuyConfig,
        Path("data/analysis/zhuli/institutional_firstbuy_scanner.csv"),
    ),
    "swing_breakout": (
        SwingBreakoutConfig,
        Path("data/analysis/zhuli/swing_breakout_scanner.csv"),
    ),
    "bbands_upper_break": (
        BBandsUpperBreakConfig,
        Path("data/analysis/zhuli/bbands_upper_break_scanner.csv"),
    ),
    "overnight_swing": (
        OvernightSwingConfig,
        Path("data/analysis/zhuli/overnight_swing_scanner.csv"),
    ),
    "reversal_breakout": (
        ReversalBreakoutConfig,
        Path("data/analysis/zhuli/reversal_breakout_scanner.csv"),
    ),
    "pennant_flag": (
        PennantFlagConfig,
        Path("data/analysis/zhuli/pennant_flag_scanner.csv"),
    ),
}

# swing_breakout 需要額外的資料表（法人全欄位 + stock_info）
_SIGNALS_WITH_DB_DEPS = {"institutional_firstbuy", "swing_breakout"}


def run(
    db_path: Path = DEFAULT_DB_PATH,
    out_path: Path | None = None,
    as_of: pd.Timestamp | None = None,
    signal_name: str = "suffocation",
    cfg: SuffocationConfig | OpenSignalConfig | None = None,
    top_n: int | None = None,
) -> pd.DataFrame:
    """Run the zhuli scanner. Returns signal candidates DataFrame.

    Args:
        db_path:     Path to SQLite database (default: ~/.four_seasons/data.sqlite).
        out_path:    Output CSV path. If None, uses signal-specific default.
        as_of:       Filter signals to this date only. None = all dates.
        signal_name: Entry signal to use (see ENTRY_REGISTRY).
        cfg:         Signal config. Uses signal-specific default if None.
        top_n:       If set, return only top N rows.

    Returns:
        DataFrame of signal candidates.
    """
    detect_fn = ENTRY_REGISTRY.get(signal_name)
    if detect_fn is None:
        raise ValueError(
            f"Unknown signal: '{signal_name}'. "
            f"Available: {list(ENTRY_REGISTRY.keys())}"
        )

    # Resolve default config and output path per signal
    cfg_cls, default_out = _SIGNAL_DEFAULTS.get(
        signal_name, (SuffocationConfig, DEFAULT_OUT)
    )
    if cfg is None:
        cfg = cfg_cls()
    if out_path is None:
        out_path = default_out

    out_path.parent.mkdir(parents=True, exist_ok=True)

    bars = load_bars(db_path=db_path)
    feats = add_features(bars)
    feats = add_zhuli_features(feats)

    # 部分 signal 需要額外的資料表（透過 db_path 傳入讓 detect() 自行讀取）
    if signal_name in _SIGNALS_WITH_DB_DEPS:
        signals = detect_fn(feats, cfg=cfg, db_path=db_path)
    else:
        signals = detect_fn(feats, cfg=cfg)

    if as_of is not None:
        signals = signals[signals["signal_date"] == as_of].copy()

    # Sort: prefer columns present in the result
    if len(signals) > 0:
        sort_cols = []
        sort_asc = []
        if "ideal_ma_align" in signals.columns:
            sort_cols.append("ideal_ma_align")
            sort_asc.append(False)
        if "signal_type" in signals.columns:
            sort_cols.append("signal_type")
            sort_asc.append(True)
        elif "scenario" in signals.columns:
            sort_cols.append("scenario")
            sort_asc.append(True)
        sort_cols.append("ticker")
        sort_asc.append(True)
        signals = signals.sort_values(sort_cols, ascending=sort_asc).reset_index(
            drop=True
        )

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
        "--out", type=Path, default=None,
        help="Output CSV path (default: signal-specific path under data/analysis/zhuli/)",
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
        help="Load signal config overrides from a JSON file.",
    )
    parser.add_argument(
        "--config-override", nargs="*", metavar="KEY=VALUE",
        help=(
            "Override individual signal config values. "
            "Example: --config-override max20_volume_ratio=0.12 min_close=15"
        ),
    )
    parser.add_argument(
        "--show-config", action="store_true",
        help="Print effective config and exit.",
    )
    parser.add_argument(
        "--sanity-check", action="store_true",
        help="Run instructor case sanity check for --signal and exit.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="With --sanity-check: 跑 4 套 sanity + 寫整合 markdown 報告。",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose output (used with --sanity-check).",
    )

    args = parser.parse_args()

    # Resolve signal-specific config class
    cfg_cls, _default_out = _SIGNAL_DEFAULTS.get(
        args.signal, (SuffocationConfig, DEFAULT_OUT)
    )

    # Build config
    if args.config:
        cfg = cfg_cls.from_json(args.config)
    else:
        cfg = cfg_cls()

    if args.config_override:
        overrides = _parse_config_overrides(args.config_override)
        cfg = cfg.apply_overrides(overrides)

    if args.show_config:
        print(f"Effective {cfg_cls.__name__} (signal={args.signal}):")
        for k, v in cfg.to_dict().items():
            print(f"  {k}: {v}")
        return

    if args.sanity_check:
        if args.all:
            # 跨 scanner 整合 sanity check
            from zhuli.sanity_check_all import run_all, write_markdown_report
            summary = run_all(args.db, verbose=args.verbose)
            print()
            print("=" * 60)
            print(f"跨 scanner 整合摘要：{summary['total_cases']} cases")
            print("=" * 60)
            t = summary["totals"]
            print(f"   strict_hit:        {t['strict_hit']} / {summary['total_cases']}")
            print(f"   partial_hit:       {t['partial_hit']}")
            print(f"   known_divergence:  {t['known_divergence']}")
            print(f"   data_gap:          {t['data_gap']}")
            print(f"   unexpected_miss:   {t['unexpected_miss']}")
            print(f"   {'✅ PASSED' if summary['passed'] else '❌ FAILED'}")
            print("=" * 60)
            out = Path("docs/主力大課程/all_instructor_cases_validation.md")
            write_markdown_report(summary, out)
            sys.exit(0 if summary["passed"] else 1)

        # 單一 scanner sanity dispatch
        _SANITY_MODULES = {
            "suffocation": "zhuli.sanity_check",
            "open_signal_filter": "zhuli.sanity_check_open_signal",
            "institutional_firstbuy": "zhuli.sanity_check_institutional",
            "swing_breakout": "zhuli.sanity_check_swing",
            "bbands_upper_break": "zhuli.sanity_check_bbands",
            "overnight_swing": "zhuli.sanity_check_overnight",
            "reversal_breakout": "zhuli.sanity_check_reversal",
            "pennant_flag": "zhuli.sanity_check_pennant",
        }
        mod_name = _SANITY_MODULES.get(args.signal)
        if not mod_name:
            sys.exit(f"ERROR: --signal={args.signal} has no sanity check module.")
        mod = __import__(mod_name, fromlist=["run_sanity_check", "print_report"])
        result = mod.run_sanity_check(db_path=args.db, cfg=cfg, verbose=args.verbose)
        mod.print_report(result)
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

    # Resolve effective output path for display
    _, effective_out = _SIGNAL_DEFAULTS.get(args.signal, (SuffocationConfig, DEFAULT_OUT))
    out_display = args.out if args.out else effective_out

    date_label = args.date if args.date else "all dates"
    print(f"Signal: {args.signal} | Date: {date_label} | Found: {len(df)} candidates")
    if len(df) > 0:
        print(f"Wrote → {out_display}")
        # Print summary table — prefer relevant columns, fall back gracefully
        preferred_cols = [
            # open_signal_filter columns
            "ticker", "signal_date", "signal_type",
            "prev_close", "today_open", "today_open_gap_pct", "stop_loss",
            # suffocation columns
            "scenario", "breakout_close",
            "ideal_ma_align", "suffocation_vol_ratio", "breakout_bar_type",
            # institutional_firstbuy columns
            "sitc_net", "price_divergence", "close", "ma10",
            # swing_breakout columns
            "name", "industry", "foreign_net", "inst_net", "vol_ratio",
            "ma20", "ma20_slope", "ma60_slope", "dist_to_ma20_pct",
            "sector_density", "sector_peers", "score",
        ]
        summary_cols = [c for c in preferred_cols if c in df.columns]
        print(df[summary_cols].to_string(index=False))
    else:
        print("No signals found.")


if __name__ == "__main__":
    main()
