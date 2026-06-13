"""凱基-站前（大哥）每日追蹤器.

抓凱基-站前分點當日跨市場買賣動作、對照持倉/watchlist、產生 markdown 報告。

Public API:
    get_dage_daily_action(target_date, ticker_universe) -> dict
    cross_reference_holdings(action, holdings_path) -> dict
    write_brief(target_date, action, xref, output_path)

CLI:
    python scripts/zhuli/broker_dage_tracker.py [YYYY-MM-DD] [--full] [--output-dir DIR]

注意：
    - TaiwanStockTradingDailyReport 不支援全市場 mode，需逐 ticker 抓
    - 預設抓 holdings + watchlist + teacher_picks + sector_tickers（~350 檔）
    - --full 旗標才跑完整 2300+ 市場（約 20 分鐘）
    - 所有數字單位：「張」= 1000 股（buy/sell 欄位是「股」，÷1000 = 張）
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_DB = MAIN_DB
_CACHE_DIR = Path.home() / ".zhuli_cache" / "broker"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# ── 分點 pattern ───────────────────────────────────────────────────────────────
DAGE_PATTERN = re.compile(r"凱基.*站前")
DAGE_TRADER_ID = "920F"   # 凱基站前 trader_id（驗證用，FinMind 不支援 filter）

# ── 檔案路徑常數 ──────────────────────────────────────────────────────────────
_HOLDINGS_JSON = _REPO / "docs" / "主力大課程" / "holdings.json"
_PICKS_JSON    = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"
_SECTORS_JSON  = _REPO / "docs" / "主力大課程" / "teacher_sector_tickers.json"
_BRIEF_DIR     = _REPO / "docs" / "主力大課程" / "daily_brief"


# ── FinMind 工具函式 ───────────────────────────────────────────────────────────

def _fetch_broker_daily(ticker: str, date_str: str) -> list[dict]:
    """單日 broker raw fetch，含 disk cache。回傳 list of {securities_trader, price, buy, sell, ...}."""
    cache = _CACHE_DIR / f"{ticker}_{date_str}.json"
    if cache.exists():
        try:
            with cache.open() as f:
                return json.load(f)
        except Exception:
            cache.unlink(missing_ok=True)  # 損壞 cache，刪掉重抓

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        raise RuntimeError("FINMIND_TOKEN 環境變數未設定")

    try:
        r = requests.get(_FINMIND_URL, params={
            "dataset": "TaiwanStockTradingDailyReport",
            "data_id": ticker,
            "start_date": date_str,
            "token": token,
        }, timeout=30)
        body = r.json()
    except Exception as exc:
        raise RuntimeError(f"FinMind fetch 失敗 ({ticker} {date_str}): {exc}") from exc

    if body.get("status") not in (200, None):
        # status 欄位有時不存在（成功時回 200 但字典裡沒有 status key）
        msg = body.get("msg", "")
        raise RuntimeError(f"FinMind API 錯誤 ({ticker}): {msg}")

    data = body.get("data", [])
    with cache.open("w") as f:
        json.dump(data, f)
    time.sleep(0.35)  # rate limit（sponsor tier 600 req/hr ≒ 0.1s/req，保守加大到 0.35）
    return data


def _is_dage(name: str) -> bool:
    return bool(DAGE_PATTERN.search(name))


# ── 載入輔助資料 ───────────────────────────────────────────────────────────────

def _load_holdings(holdings_path: Path) -> dict:
    """讀 holdings.json，graceful handle TODO 值。"""
    try:
        raw = json.loads(holdings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[WARN] holdings.json 不存在：{holdings_path}", file=sys.stderr)
        return {"holdings": {}, "watchlist": {}, "exclusion_list": {}}

    return raw


def _safe_float(val, fallback=None):
    """把 'TODO'、None 等非數字值轉為 fallback（不 crash）。"""
    if val is None or val == "TODO":
        return fallback
    try:
        return float(val)
    except (ValueError, TypeError):
        return fallback


def _safe_int(val, fallback=None):
    if val is None or val == "TODO":
        return fallback
    try:
        return int(val)
    except (ValueError, TypeError):
        return fallback


def _build_ticker_universe(mode: str = "extended") -> list[str]:
    """建立要掃描的 ticker 清單。

    mode:
        "priority"  — holdings + watchlist（~20 檔，最快）
        "extended"  — priority + teacher_picks + sector_tickers（~350 檔）
        "full"      — 從 DB 取全市場（~2300 檔，慢）
    """
    tickers: set[str] = set()

    # Holdings + Watchlist（永遠包含）
    holdings_raw = _load_holdings(_HOLDINGS_JSON)
    for t in holdings_raw.get("holdings", {}).keys():
        tickers.add(t)
    for t in holdings_raw.get("watchlist", {}).keys():
        tickers.add(t)
    for t in holdings_raw.get("exclusion_list", {}).keys():
        tickers.add(t)

    if mode in ("extended", "full"):
        # Teacher picks
        if _PICKS_JSON.exists():
            picks = json.loads(_PICKS_JSON.read_text())
            for t in picks.keys():
                if t != "_meta":
                    tickers.add(t)

        # Sector tickers
        if _SECTORS_JSON.exists():
            sectors = json.loads(_SECTORS_JSON.read_text())
            for ts in sectors.values():
                tickers.update(ts)

    if mode == "full":
        # DB 全市場
        try:
            con = get_conn(_DB, timeout=5)
            rows = con.execute(
                "SELECT DISTINCT ticker FROM standard_daily_bar ORDER BY ticker"
            ).fetchall()
            con.close()
            tickers.update(r[0] for r in rows)
        except Exception as e:
            print(f"[WARN] 無法讀取 DB 全市場 ticker：{e}", file=sys.stderr)

    return sorted(tickers)


def _load_stock_names() -> dict[str, str]:
    """從 DB 載入 {ticker: name} 對照。"""
    try:
        con = get_conn(_DB, timeout=5)
        rows = con.execute("SELECT ticker, stock_name FROM stock_info").fetchall()
        con.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def _get_price_and_ma(ticker: str, target_date: str) -> tuple[float | None, float | None]:
    """從 DB 取收盤價 + MA10，算距 MA10%。回傳 (close, dist_ma10_pct)。"""
    try:
        con = get_conn(_DB, timeout=5)
        row = con.execute(
            "SELECT close, ma10 FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
            (ticker, target_date)
        ).fetchone()
        con.close()
        if row is None:
            return None, None
        close, ma10 = row
        if close is None:
            return None, None
        dist = round((float(close) - float(ma10)) / float(ma10) * 100, 1) if ma10 else None
        return float(close), dist
    except Exception:
        return None, None


# ── 核心功能 ──────────────────────────────────────────────────────────────────

def get_dage_daily_action(target_date: str, ticker_universe: list[str] | None = None,
                          mode: str = "extended") -> dict:
    """抓凱基-站前當日跨市場買賣動作。

    Returns:
        {
            "date": "2026-05-27",
            "broker": "凱基-站前",
            "fetch_mode": "extended",
            "tickers_scanned": int,
            "top_buy": [{"ticker": "...", "name": "...", "net_lots": int,
                         "buy_lots": int, "sell_lots": int, "close": float|None,
                         "dist_ma10_pct": float|None}, ...],  # top 20 淨買
            "top_sell": [...],  # top 20 淨賣（net_lots 最負）
            "all_actions": {ticker: net_lots, ...},  # 所有有動作的 ticker
            "total_buy_tickers": int,
            "total_sell_tickers": int,
            "total_net_lots": int,
            "fetch_errors": int,  # 抓取失敗的 ticker 數（已略過）
        }
    """
    if ticker_universe is None:
        ticker_universe = _build_ticker_universe(mode)

    stock_names = _load_stock_names()
    dage_net: dict[str, int] = defaultdict(int)     # ticker → 大哥淨買（張）
    dage_buy: dict[str, int] = defaultdict(int)
    dage_sell: dict[str, int] = defaultdict(int)
    errors = 0

    total = len(ticker_universe)
    print(f"[大哥追蹤] 掃描 {total} 檔 ({mode} mode) | 日期: {target_date}", flush=True)

    for i, ticker in enumerate(ticker_universe, 1):
        if i % 50 == 0:
            print(f"  [{i}/{total}] ...", flush=True)
        try:
            data = _fetch_broker_daily(ticker, target_date)
        except RuntimeError as e:
            errors += 1
            if errors <= 5:  # 前幾個錯誤才印，避免洗版
                print(f"  [SKIP] {ticker}: {e}", file=sys.stderr)
            continue

        for row in data:
            name = row.get("securities_trader", "")
            if not _is_dage(name):
                continue
            buy  = row.get("buy", 0) or 0
            sell = row.get("sell", 0) or 0
            net  = (buy - sell) // 1000  # 股 → 張
            dage_net[ticker]  += net
            dage_buy[ticker]  += buy // 1000
            dage_sell[ticker] += sell // 1000

    # 過濾掉淨買賣 = 0 的（沒有大哥動作）
    active = {t: v for t, v in dage_net.items() if v != 0}

    buy_tickers  = {t: v for t, v in active.items() if v > 0}
    sell_tickers = {t: v for t, v in active.items() if v < 0}

    def _enrich(ticker: str, net: int) -> dict:
        close, dist = _get_price_and_ma(ticker, target_date)
        return {
            "ticker": ticker,
            "name": stock_names.get(ticker, ""),
            "net_lots": net,
            "buy_lots": dage_buy[ticker],
            "sell_lots": dage_sell[ticker],
            "close": close,
            "dist_ma10_pct": dist,
        }

    top_buy  = sorted(buy_tickers.items(),  key=lambda x: -x[1])[:20]
    top_sell = sorted(sell_tickers.items(), key=lambda x:  x[1])[:20]

    return {
        "date": target_date,
        "broker": "凱基-站前",
        "fetch_mode": mode,
        "tickers_scanned": total,
        "top_buy":  [_enrich(t, v) for t, v in top_buy],
        "top_sell": [_enrich(t, v) for t, v in top_sell],
        "all_actions": dict(active),
        "total_buy_tickers":  len(buy_tickers),
        "total_sell_tickers": len(sell_tickers),
        "total_net_lots": sum(active.values()),
        "fetch_errors": errors,
    }


def cross_reference_holdings(action: dict, holdings_path: Path) -> dict:
    """對照持倉/watchlist/exclusion，回傳分析結果。

    Returns:
        {
            "holdings_action": [
                {"ticker", "name", "shares", "cost", "stop_loss",
                 "dage_net_lots", "category", "interpretation", "notes"}, ...
            ],
            "watchlist_action": [
                {"ticker", "name", "reason", "dage_net_lots", "interpretation"}, ...
            ],
            "exclusion_violation": [
                {"ticker", "name", "exclusion_reason", "dage_net_lots",
                 "interpretation"}, ...
            ],
            "new_candidates": [
                {"ticker", "name", "net_lots", "close", "dist_ma10_pct"}, ...
            ],
        }
    """
    holdings_raw = _load_holdings(holdings_path)
    holdings     = holdings_raw.get("holdings", {})
    watchlist    = holdings_raw.get("watchlist", {})
    exclusion    = holdings_raw.get("exclusion_list", {})
    all_actions  = action.get("all_actions", {})
    stock_names  = _load_stock_names()

    # 持倉對照
    holdings_action = []
    for ticker, info in holdings.items():
        net = all_actions.get(ticker, 0)
        shares   = _safe_float(info.get("shares"))
        cost     = _safe_float(info.get("cost"))
        stop_loss = _safe_float(info.get("stop_loss"))
        category = info.get("category", "")

        if net > 500:
            interp = "大哥大幅加碼 ✅ 戰略對齊"
        elif net > 100:
            interp = "大哥持續進貨 ✅"
        elif net > 0:
            interp = "大哥小量買進"
        elif net < -100:
            interp = "大哥出貨中 ⚠️"
        elif net < 0:
            interp = "大哥小量賣出"
        else:
            interp = "今日無大哥動作"

        holdings_action.append({
            "ticker":        ticker,
            "name":          info.get("name", stock_names.get(ticker, "")),
            "shares":        shares,
            "cost":          cost,
            "stop_loss":     stop_loss,
            "category":      category,
            "dage_net_lots": net,
            "interpretation": interp,
            "notes":         info.get("notes", ""),
        })

    # 排序：大哥有動作的排前面
    holdings_action.sort(key=lambda x: -abs(x["dage_net_lots"]))

    # Watchlist 對照
    watchlist_action = []
    for ticker, info in watchlist.items():
        # Skip non-dict entries (e.g. user notes added as strings in holdings.json watchlist)
        if not isinstance(info, dict):
            continue
        net = all_actions.get(ticker, 0)
        if net > 200:
            interp = "大哥大買 → 升格觀察 🔥"
        elif net > 0:
            interp = "大哥有買進"
        elif net < 0:
            interp = "大哥有賣出 ⚠️"
        else:
            interp = "今日無大哥動作"

        watchlist_action.append({
            "ticker":         ticker,
            "name":           info.get("name", stock_names.get(ticker, "")),
            "reason":         info.get("reason", ""),
            "dage_net_lots":  net,
            "interpretation": interp,
        })

    watchlist_action.sort(key=lambda x: -abs(x["dage_net_lots"]))

    # Exclusion 異常（被大哥大買）
    exclusion_violation = []
    for ticker, info in exclusion.items():
        net = all_actions.get(ticker, 0)
        if net > 200:
            exclusion_violation.append({
                "ticker":           ticker,
                "name":             info.get("name", stock_names.get(ticker, "")),
                "exclusion_reason": info.get("reason", ""),
                "dage_net_lots":    net,
                "interpretation":   "排除清單被大哥大買 — 老師可能改觀點 ❗",
            })

    # 新候選（top_buy 中不在持倉/watchlist/exclusion 的）
    tracked = set(holdings.keys()) | set(watchlist.keys()) | set(exclusion.keys())
    new_candidates = []
    for item in action.get("top_buy", []):
        t = item["ticker"]
        if t not in tracked:
            new_candidates.append({
                "ticker":       t,
                "name":         item.get("name", stock_names.get(t, "")),
                "net_lots":     item["net_lots"],
                "close":        item.get("close"),
                "dist_ma10_pct": item.get("dist_ma10_pct"),
            })

    return {
        "holdings_action":      holdings_action,
        "watchlist_action":     watchlist_action,
        "exclusion_violation":  exclusion_violation,
        "new_candidates":       new_candidates,
    }


# ── 報告產生 ──────────────────────────────────────────────────────────────────

def _fmt_lots(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n:+,}" if n != 0 else "—"


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "—"
    return f"${p:.2f}"


def _fmt_dist(d: float | None) -> str:
    if d is None:
        return "—"
    return f"{d:+.1f}%"


def _fmt_shares(s) -> str:
    if s is None:
        return "TODO"
    return f"{s:.0f}張"


def _fmt_cost(c) -> str:
    if c is None:
        return "TODO"
    return f"${c:.2f}"


def write_brief(target_date: str, action: dict, xref: dict, output_path: Path) -> None:
    """產出 markdown 報告到 output_path。"""
    fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    mode_label = {"priority": "priority（持倉+Watchlist）",
                  "extended": "extended（持倉+Watchlist+老師指名+族群）",
                  "full":     "full（全市場）"}.get(action.get("fetch_mode", ""), "")

    lines = [
        f"# {target_date} 凱基-站前（大哥）每日動作",
        f"",
        f"> 來源：FinMind TaiwanStockTradingDailyReport",
        f"> 抓取時間：{fetch_time}",
        f"> 掃描範圍：{mode_label}（共 {action['tickers_scanned']} 檔）",
        f"> 持倉 source：`docs/主力大課程/holdings.json`",
        f"> 抓取失敗（已略過）：{action.get('fetch_errors', 0)} 檔",
        f"",
        f"## 大哥當日總覽",
        f"",
        f"| 指標 | 數值 |",
        f"|---|---|",
        f"| 進貨標的數 | {action['total_buy_tickers']} 檔 |",
        f"| 出貨標的數 | {action['total_sell_tickers']} 檔 |",
        f"| 淨買合計 | {action['total_net_lots']:+,} 張 |",
        f"",
    ]

    # Top 買超
    if action["top_buy"]:
        lines += [
            f"## 大哥 Top {len(action['top_buy'])} 買超（掃描範圍內）",
            f"",
            f"| Rank | Ticker | 名稱 | 大哥淨買 | 買進 | 賣出 | 收盤 | 距MA10 | 持倉狀態 |",
            f"|---|---|---|---|---|---|---|---|---|",
        ]
        tracked_all = (
            set(xref["holdings_action"][i]["ticker"] for i in range(len(xref["holdings_action"])))
            | set(xref["watchlist_action"][i]["ticker"] for i in range(len(xref["watchlist_action"])))
        )
        for rank, item in enumerate(action["top_buy"], 1):
            t = item["ticker"]
            status = "持倉" if any(h["ticker"] == t for h in xref["holdings_action"]) \
                     else "watchlist" if any(w["ticker"] == t for w in xref["watchlist_action"]) \
                     else "新候選"
            lines.append(
                f"| {rank} | {t} | {item['name']} | {_fmt_lots(item['net_lots'])} | "
                f"{item['buy_lots']:,} | {item['sell_lots']:,} | "
                f"{_fmt_price(item['close'])} | {_fmt_dist(item['dist_ma10_pct'])} | {status} |"
            )
        lines.append(f"")

    # Top 賣超
    if action["top_sell"]:
        lines += [
            f"## 大哥 Top {len(action['top_sell'])} 賣超",
            f"",
            f"| Rank | Ticker | 名稱 | 大哥淨賣 | 收盤 | 持倉狀態 |",
            f"|---|---|---|---|---|---|",
        ]
        for rank, item in enumerate(action["top_sell"], 1):
            t = item["ticker"]
            status = "持倉 ⚠️" if any(h["ticker"] == t for h in xref["holdings_action"]) \
                     else "watchlist" if any(w["ticker"] == t for w in xref["watchlist_action"]) \
                     else "—"
            lines.append(
                f"| {rank} | {t} | {item['name']} | {_fmt_lots(item['net_lots'])} | "
                f"{_fmt_price(item['close'])} | {status} |"
            )
        lines.append(f"")

    # 持倉對照
    lines += [
        f"## 持倉對照（你的所有持倉，大哥動作如何）",
        f"",
        f"| Ticker | 名稱 | 持倉 | 成本 | 停損 | 大哥動作 | 解讀 |",
        f"|---|---|---|---|---|---|---|",
    ]
    for h in xref["holdings_action"]:
        lines.append(
            f"| {h['ticker']} | {h['name']} | {_fmt_shares(h['shares'])} | "
            f"{_fmt_cost(h['cost'])} | {_fmt_cost(h['stop_loss'])} | "
            f"{_fmt_lots(h['dage_net_lots'])} | {h['interpretation']} |"
        )
    lines.append(f"")

    # Watchlist 動作
    if xref["watchlist_action"]:
        lines += [
            f"## Watchlist 動作",
            f"",
            f"| Ticker | 名稱 | 大哥動作 | 解讀 | 備註 |",
            f"|---|---|---|---|---|",
        ]
        for w in xref["watchlist_action"]:
            lines.append(
                f"| {w['ticker']} | {w['name']} | {_fmt_lots(w['dage_net_lots'])} | "
                f"{w['interpretation']} | {w['reason'][:40] if w['reason'] else '—'} |"
            )
        lines.append(f"")

    # Exclusion 異常
    if xref["exclusion_violation"]:
        lines += [
            f"## 排除清單異動（大哥大買 = 老師可能改觀點）",
            f"",
            f"| Ticker | 名稱 | 大哥淨買 | 排除原因 |",
            f"|---|---|---|---|",
        ]
        for e in xref["exclusion_violation"]:
            lines.append(
                f"| {e['ticker']} | {e['name']} | {_fmt_lots(e['dage_net_lots'])} | "
                f"{e['exclusion_reason'][:40] if e['exclusion_reason'] else '—'} |"
            )
        lines.append(f"")

    # 新候選
    if xref["new_candidates"]:
        lines += [
            f"## 新候選（不在持倉/Watchlist/排除的 Top 買超）",
            f"",
            f"| Ticker | 名稱 | 大哥淨買 | 收盤 | 距MA10 | 建議 |",
            f"|---|---|---|---|---|---|",
        ]
        for c in xref["new_candidates"]:
            dist = c.get("dist_ma10_pct")
            suggestion = "距MA10適中，可考慮加入watchlist" if dist is not None and dist <= 10 else \
                         "距MA10過遠，等回測" if dist is not None and dist > 10 else "—"
            lines.append(
                f"| {c['ticker']} | {c['name']} | {_fmt_lots(c['net_lots'])} | "
                f"{_fmt_price(c['close'])} | {_fmt_dist(dist)} | {suggestion} |"
            )
        lines.append(f"")

    lines += [
        f"---",
        f"",
        f"產生時間：{fetch_time}  |  掃描模式：`{action.get('fetch_mode', '?')}`",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ dage 報告寫入：{output_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="凱基-站前（大哥）每日追蹤器")
    ap.add_argument("date", nargs="?", default=None,
                    help="目標日期 YYYY-MM-DD（預設今天）")
    ap.add_argument("--full", action="store_true",
                    help="全市場掃描（~2300 檔，約 20 分鐘）")
    ap.add_argument("--priority", action="store_true",
                    help="只掃持倉+Watchlist（最快）")
    ap.add_argument("--output-dir", default=None,
                    help="報告輸出目錄（預設 docs/主力大課程/daily_brief/）")
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    mode = "full" if args.full else "priority" if args.priority else "extended"

    out_dir = Path(args.output_dir) if args.output_dir else _BRIEF_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== 凱基-站前 大哥追蹤器 ===")
    print(f"日期: {target_date} | 模式: {mode}")

    # Step 1: 抓動作
    action = get_dage_daily_action(target_date, mode=mode)

    print(f"\n大哥動作統計:")
    print(f"  進貨標的: {action['total_buy_tickers']} 檔")
    print(f"  出貨標的: {action['total_sell_tickers']} 檔")
    print(f"  淨買合計: {action['total_net_lots']:+,} 張")
    if action["top_buy"]:
        print(f"  Top 3 買超: " + ", ".join(
            f"{x['ticker']}({x['name']}) {_fmt_lots(x['net_lots'])}"
            for x in action["top_buy"][:3]
        ))

    # Step 2: 對照持倉
    xref = cross_reference_holdings(action, _HOLDINGS_JSON)

    # Step 3: 寫報告
    out_md = out_dir / f"{target_date}_dage.md"
    write_brief(target_date, action, xref, out_md)

    print(f"\n完成！報告：{out_md}")
    print(f"大小：{out_md.stat().st_size:,} bytes")

    return action, xref


if __name__ == "__main__":
    main()
