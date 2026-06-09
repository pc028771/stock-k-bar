"""Tier-1 老師重點分點每日追蹤 (聚合報告).

涵蓋 3 個 Tier-1 分點:
    - 管錢哥 (元大-館前)
    - 站前哥 (凱基-站前)
    - 凱基-信義 (波段大戶、6/9 加入、ch9-1 老師清單)

單次 ticker scan 同時 match 3 個 pattern、accumulate per-broker 桶、產生一份合併 markdown。

CLI:
    python scripts/zhuli/tier1_brokers_daily_tracker.py [YYYY-MM-DD] [--full|--priority]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# 借用 broker_dage_tracker 的 universe/fetch/price 工具
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from broker_dage_tracker import (  # noqa: E402
    _BRIEF_DIR,
    _HOLDINGS_JSON,
    _build_ticker_universe,
    _fetch_broker_daily,
    _get_price_and_ma,
    _load_holdings,
    _load_stock_names,
)
from teacher_broker_signal import TEACHER_BROKERS_TIER1  # noqa: E402

# 編譯 patterns (label → compiled regex)
_TIER1_PATTERNS: dict[str, list[re.Pattern]] = {
    label: [re.compile(p) for p in patterns]
    for label, patterns in TEACHER_BROKERS_TIER1.items()
}


def _match_tier1(name: str) -> str | None:
    """回傳第一個 match 的 broker label、無 match 則 None。"""
    for label, patterns in _TIER1_PATTERNS.items():
        for p in patterns:
            if p.search(name):
                return label
    return None


def scan_all_tier1(target_date: str, mode: str = "extended") -> dict:
    """一次 scan、同時 match 3 個 Tier-1 broker、回傳 per-broker breakdown。

    Returns:
        {
            "date": ...,
            "mode": ...,
            "tickers_scanned": int,
            "fetch_errors": int,
            "per_broker": {
                "管錢哥（元大館前）": {
                    "top_buy":  [{ticker, name, net, buy, sell, close, dist_ma10}],
                    "top_sell": [...],
                    "total_buy_tickers": int,
                    "total_sell_tickers": int,
                },
                ...
            },
        }
    """
    universe = _build_ticker_universe(mode)
    stock_names = _load_stock_names()
    total = len(universe)

    # per-broker accumulators
    net  = {label: defaultdict(int) for label in _TIER1_PATTERNS}
    buy  = {label: defaultdict(int) for label in _TIER1_PATTERNS}
    sell = {label: defaultdict(int) for label in _TIER1_PATTERNS}
    errors = 0

    print(f"[Tier-1 追蹤] 掃描 {total} 檔 ({mode}) | {target_date}", flush=True)
    for i, ticker in enumerate(universe, 1):
        if i % 50 == 0:
            print(f"  [{i}/{total}] …", flush=True)
        try:
            rows = _fetch_broker_daily(ticker, target_date)
        except RuntimeError as e:
            errors += 1
            if errors <= 5:
                print(f"  [SKIP] {ticker}: {e}", file=sys.stderr)
            continue

        for row in rows:
            name = row.get("securities_trader", "")
            label = _match_tier1(name)
            if not label:
                continue
            b = row.get("buy", 0) or 0
            s = row.get("sell", 0) or 0
            n = (b - s) // 1000
            net[label][ticker]  += n
            buy[label][ticker]  += b // 1000
            sell[label][ticker] += s // 1000

    def enrich(label: str, ticker: str, n: int) -> dict:
        close, dist = _get_price_and_ma(ticker, target_date)
        return {
            "ticker": ticker,
            "name": stock_names.get(ticker, ""),
            "net_lots": n,
            "buy_lots": buy[label][ticker],
            "sell_lots": sell[label][ticker],
            "close": close,
            "dist_ma10_pct": dist,
        }

    per_broker = {}
    for label in _TIER1_PATTERNS:
        active = {t: v for t, v in net[label].items() if v != 0}
        top_b = sorted(active.items(), key=lambda x: -x[1])[:20]
        top_s = sorted(active.items(), key=lambda x:  x[1])[:20]
        per_broker[label] = {
            "top_buy":  [enrich(label, t, v) for t, v in top_b if v > 0],
            "top_sell": [enrich(label, t, v) for t, v in top_s if v < 0],
            "total_buy_tickers":  sum(1 for v in active.values() if v > 0),
            "total_sell_tickers": sum(1 for v in active.values() if v < 0),
            "total_net_lots": sum(active.values()),
        }

    return {
        "date": target_date,
        "mode": mode,
        "tickers_scanned": total,
        "fetch_errors": errors,
        "per_broker": per_broker,
    }


def _fmt_lots(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n:+,}"


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "—"
    return f"{p:.2f}"


def _fmt_dist(d: float | None) -> str:
    if d is None:
        return "—"
    return f"{d:+.1f}%"


def write_brief(target_date: str, scan: dict, output_path: Path) -> None:
    """產生 Tier-1 聚合 markdown 報告 + 持倉/watchlist 交叉。"""
    held = _load_holdings(_HOLDINGS_JSON)
    # holdings dict: key 多半是 ticker、但也有 _meta 等 summary key、只取 4 碼數字
    raw_h = held.get("holdings", {})
    if isinstance(raw_h, dict):
        held_tickers = {k: v for k, v in raw_h.items() if re.fullmatch(r"\d{4,5}", k)}
    elif isinstance(raw_h, list):
        held_tickers = {str(h.get("ticker", "")): h for h in raw_h if isinstance(h, dict)}
    else:
        held_tickers = {}

    lines = [
        f"# {target_date} Tier-1 老師重點分點每日動作",
        "",
        f"**掃描範圍**: {scan['tickers_scanned']} 檔 ({scan['mode']})  ",
        f"**抓取失敗**: {scan['fetch_errors']} 檔  ",
        "",
        "---",
        "",
    ]

    for label, data in scan["per_broker"].items():
        lines += [
            f"## {label}",
            "",
            f"進貨 {data['total_buy_tickers']} 檔 / 出貨 {data['total_sell_tickers']} 檔 / 淨 {_fmt_lots(data['total_net_lots'])} 張",
            "",
        ]

        if data["top_buy"]:
            lines += [
                "### 🟢 Top 20 進貨",
                "",
                "| 代號 | 股名 | 淨買 | 買 | 賣 | 收盤 | 離MA10 | 持倉 |",
                "|---|---|---:|---:|---:|---:|---:|---|",
            ]
            for r in data["top_buy"]:
                tk = r["ticker"]
                in_held = "✅" if tk in held_tickers else ""
                lines.append(
                    f"| {tk} | {r['name']} | {_fmt_lots(r['net_lots'])} | {r['buy_lots']} | {r['sell_lots']} | "
                    f"{_fmt_price(r['close'])} | {_fmt_dist(r['dist_ma10_pct'])} | {in_held} |"
                )
            lines.append("")
        else:
            lines += ["### 🟢 進貨", "", "_今日無動作_", ""]

        if data["top_sell"]:
            lines += [
                "### 🔴 Top 20 出貨",
                "",
                "| 代號 | 股名 | 淨賣 | 買 | 賣 | 收盤 | 離MA10 | 持倉 |",
                "|---|---|---:|---:|---:|---:|---:|---|",
            ]
            for r in data["top_sell"]:
                tk = r["ticker"]
                in_held = "⚠️ 持倉" if tk in held_tickers else ""
                lines.append(
                    f"| {tk} | {r['name']} | {_fmt_lots(r['net_lots'])} | {r['buy_lots']} | {r['sell_lots']} | "
                    f"{_fmt_price(r['close'])} | {_fmt_dist(r['dist_ma10_pct'])} | {in_held} |"
                )
            lines.append("")
        else:
            lines += ["### 🔴 出貨", "", "_今日無動作_", ""]

        lines += ["---", ""]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✅ 報告寫入 {output_path}")


def main():
    ap = argparse.ArgumentParser(description="Tier-1 老師重點分點每日追蹤 (聚合)")
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (預設今天)")
    ap.add_argument("--full", action="store_true", help="全市場 ~2300 檔 (~20 分)")
    ap.add_argument("--priority", action="store_true", help="只掃 holdings + watchlist")
    ap.add_argument("--output-dir", default=None)
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    mode = "full" if args.full else "priority" if args.priority else "extended"
    out_dir = Path(args.output_dir) if args.output_dir else _BRIEF_DIR
    out_path = out_dir / f"tier1_brokers_{target_date}.md"

    print(f"=== Tier-1 分點聚合追蹤 ===")
    print(f"日期: {target_date} | 模式: {mode}")
    print(f"涵蓋: {list(_TIER1_PATTERNS.keys())}")

    scan = scan_all_tier1(target_date, mode=mode)

    print(f"\n=== 結果 ===")
    for label, data in scan["per_broker"].items():
        print(f"  {label}: 買 {data['total_buy_tickers']} / 賣 {data['total_sell_tickers']} / 淨 {data['total_net_lots']:+,} 張")

    write_brief(target_date, scan, out_path)


if __name__ == "__main__":
    main()
