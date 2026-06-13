"""框架內標的每日掃描模組.

職責：對「最新老師框架」下所有 ticker，跑三軸 + 籌碼分析，
      輸出分群報告（領頭/中段/落後/新進候選/排除清單）。

整合用法（evening_brief.py）：
    from zhuli.framework_daily_scan import (
        load_latest_framework, scan_framework, generate_framework_report
    )
    framework = load_latest_framework()
    scan_result = scan_framework(framework, db_path)
    md = generate_framework_report(scan_result, framework)

CLI 用法（直接執行驗證）：
    python scripts/zhuli/framework_daily_scan.py [YYYY-MM-DD]
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO      = Path(__file__).parent.parent.parent
_DB = MAIN_DB
_DOCS_DIR  = _REPO / "docs" / "主力大課程"
_BRIEF_DIR = _DOCS_DIR / "daily_brief"

sys.path.insert(0, str(_REPO / "scripts"))


# ── 老師指名分點（Tier 1 大哥）────────────────────────────────────────────────
_TEACHER_BROKERS: set[str] = {
    "凱基-站前", "凱基站前", "站前",          # 站前哥
    "元大-館前", "元大館前", "館前",           # 館前哥
    "永豐金",                                  # 永豐金
    "富邦",                                    # 富邦
    "管錢哥",                                  # 籠統稱呼
}


# ── DB 工具 ───────────────────────────────────────────────────────────────────

def _db_connect(db_path: Path, retries: int = 3) -> sqlite3.Connection:
    """連 DB，含簡易 retry。"""
    for i in range(retries):
        try:
            con = get_conn(db_path, timeout=10)
            return con
        except sqlite3.OperationalError as e:
            if i == retries - 1:
                raise
            import time
            time.sleep(1)
    raise RuntimeError("DB connect 失敗")


def _load_stock_names(db_path: Path) -> dict[str, str]:
    """讀取 stock_name 對照表。"""
    try:
        con = _db_connect(db_path)
        rows = con.execute("SELECT ticker, name FROM stock_name").fetchall()
        con.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def _get_latest_trade_dates(db_path: Path, n: int = 5) -> list[str]:
    """取最近 n 個有資料的交易日。"""
    try:
        con = _db_connect(db_path)
        rows = con.execute(
            "SELECT DISTINCT trade_date FROM standard_daily_bar "
            "ORDER BY trade_date DESC LIMIT ?", (n,)
        ).fetchall()
        con.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def _get_price_info(ticker: str, trade_date: str, db_path: Path) -> dict:
    """取單一 ticker 單日 price + MA 資料。"""
    try:
        con = _db_connect(db_path)
        row = con.execute(
            "SELECT close, open, high, low, volume, "
            "ma5, ma10, ma20, ma60, vol_ma20, "
            "is_disposition_stock, disposition_pending, disposition_just_exited_days, "
            "main_force_5d "
            "FROM standard_daily_bar "
            "WHERE ticker=? AND trade_date=?",
            (ticker, trade_date)
        ).fetchone()
        con.close()
        if row is None:
            return {}
        (close, open_, high, low, vol,
         ma5, ma10, ma20, ma60, vol_ma20,
         is_disp, disp_pending, disp_exited,
         main_force_5d) = row
        return {
            "close": close, "open": open_, "high": high, "low": low, "volume": vol,
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "vol_ma20": vol_ma20,
            "is_disposition": bool(is_disp),
            "disposition_pending": bool(disp_pending) if disp_pending is not None else False,
            "disposition_exited_days": disp_exited or 0,
            "main_force_5d": main_force_5d or 0,
        }
    except Exception:
        return {}


def _get_institutional(ticker: str, trade_date: str, db_path: Path, days: int = 5) -> dict:
    """取法人近 N 日累計 + 當日資料。"""
    try:
        # 計算 N 日起始日（粗略，含周末不影響查詢，DB 內只有交易日）
        end = date.fromisoformat(trade_date)
        start = (end - timedelta(days=days * 2)).isoformat()  # 多抓幾天確保 N 個交易日

        con = _db_connect(db_path)
        rows = con.execute(
            "SELECT trade_date, foreign_net, sitc_net "
            "FROM institutional_investors "
            "WHERE ticker=? AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT ?",
            (ticker, start, trade_date, days)
        ).fetchall()
        con.close()

        if not rows:
            return {"foreign_1d": None, "foreign_5d": None, "sitc_1d": None, "sitc_5d": None}

        # 最新一日
        latest = rows[0]
        foreign_1d = latest[1]
        sitc_1d    = latest[2]

        # 5 日累計（以張為單位，DB 儲存單位 = 張 or 千股，需檢查量級）
        foreign_5d = sum(r[1] for r in rows if r[1] is not None)
        sitc_5d    = sum(r[2] for r in rows if r[2] is not None)

        return {
            "foreign_1d": foreign_1d,
            "foreign_5d": foreign_5d,
            "sitc_1d": sitc_1d,
            "sitc_5d": sitc_5d,
        }
    except Exception:
        return {"foreign_1d": None, "foreign_5d": None, "sitc_1d": None, "sitc_5d": None}


def _get_broker_dage(ticker: str, trade_date: str) -> dict:
    """查指定 ticker 當日 broker cache，計算老師指名分點淨買（張）。"""
    cache_dir = Path.home() / ".zhuli_cache" / "broker"
    cache_file = cache_dir / f"{ticker}_{trade_date}.json"
    if not cache_file.exists():
        return {"dage_net": None, "dage_brokers": []}
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        dage_net = 0
        dage_brokers = []
        for row in data:
            name = str(row.get("securities_trader", row.get("broker_name", "")))
            # 比對老師指名分點
            is_teacher = any(t in name for t in _TEACHER_BROKERS)
            if is_teacher:
                net = (row.get("buy", 0) - row.get("sell", 0)) // 1000
                dage_net += net
                if abs(net) > 0:
                    dage_brokers.append(f"{name}({net:+,})")
        return {"dage_net": dage_net, "dage_brokers": dage_brokers[:3]}
    except Exception:
        return {"dage_net": None, "dage_brokers": []}


# ── 框架載入 ──────────────────────────────────────────────────────────────────

def load_latest_framework(docs_dir: Path | None = None) -> dict:
    """
    讀取最新框架。優先序：
      1. docs/主力大課程/teacher_sectors_<latest_date>.json
      2. live_position_monitor.py TEACHER_SECTORS_20260602 dict
      3. teacher_sector_tickers.json（default fallback）

    回傳：
    {
      'date': '2026-06-02',
      'sectors': {
        'GT基底': {'tickers': [...], 'priority': '⭐⭐⭐', 'note': '...'},
        ...
      },
      'priority_tickers': [...],
      'avoid_tickers': {...},
    }
    """
    docs_dir = docs_dir or _DOCS_DIR

    # ── 1. 找最新的 teacher_sectors_<date>.json ───────────────────────────
    sector_files = sorted(docs_dir.glob("teacher_sectors_*.json"), reverse=True)
    if sector_files:
        latest_file = sector_files[0]
        try:
            raw = json.loads(latest_file.read_text(encoding="utf-8"))
            print(f"[framework] 載入框架：{latest_file.name}", flush=True)
            return {
                "date":             raw.get("date", "unknown"),
                "source_file":      str(latest_file),
                "sectors":          raw.get("sectors", {}),
                "priority_tickers": raw.get("priority_tickers", []),
                "avoid_tickers":    raw.get("avoid_tickers", {}),
            }
        except Exception as e:
            print(f"[WARN] 讀 {latest_file} 失敗：{e}", file=sys.stderr)

    # ── 2. Fallback：從 live_position_monitor 讀硬編碼 dict ──────────────
    try:
        sys.path.insert(0, str(_REPO / "scripts"))
        from zhuli.live_position_monitor import TEACHER_SECTORS_20260602  # type: ignore
        print("[framework] Fallback：使用 live_position_monitor TEACHER_SECTORS_20260602", flush=True)
        sectors: dict = {}
        for sector_name, note in TEACHER_SECTORS_20260602.items():
            # 解析 tickers from WATCH list
            sectors[sector_name] = {"tickers": [], "priority": "⭐", "note": note}
        # 補充 WATCH list 的 tickers
        try:
            from zhuli.live_position_monitor import WATCH  # type: ignore
            for tk, name, *_ in WATCH:
                for sname, note_str in TEACHER_SECTORS_20260602.items():
                    if any(kw in note_str for kw in [tk]):
                        sectors[sname]["tickers"].append(tk)
        except Exception:
            pass
        return {
            "date":             "2026-06-02",
            "source_file":      "live_position_monitor.py",
            "sectors":          sectors,
            "priority_tickers": [],
            "avoid_tickers":    {},
        }
    except ImportError:
        pass

    # ── 3. 最終 fallback：teacher_sector_tickers.json ────────────────────
    legacy_file = docs_dir / "teacher_sector_tickers.json"
    if legacy_file.exists():
        print(f"[framework] Fallback：使用 {legacy_file.name}", flush=True)
        raw = json.loads(legacy_file.read_text(encoding="utf-8"))
        sectors = {}
        for sector_name, tickers in raw.items():
            sectors[sector_name] = {"tickers": tickers, "priority": "⭐", "note": ""}
        return {
            "date":             "legacy",
            "source_file":      str(legacy_file),
            "sectors":          sectors,
            "priority_tickers": [],
            "avoid_tickers":    {},
        }

    raise FileNotFoundError("找不到任何框架資料，請建立 teacher_sectors_<date>.json")


# ── MA 排列分析 ───────────────────────────────────────────────────────────────

def _ma_emoji(close: float | None, ma: float | None) -> str:
    if close is None or ma is None:
        return "⬜"
    try:
        diff = (float(close) - float(ma)) / float(ma) * 100
        if diff >= 1.0:
            return "🟢"
        elif diff >= -1.0:
            return "🟡"
        else:
            return "🔴"
    except (TypeError, ZeroDivisionError):
        return "⬜"


def _ma_alignment(p: dict) -> str:
    """四軸 MA5/10/20/60 emoji 串。"""
    c = p.get("close")
    return (
        _ma_emoji(c, p.get("ma5"))
        + _ma_emoji(c, p.get("ma10"))
        + _ma_emoji(c, p.get("ma20"))
        + _ma_emoji(c, p.get("ma60"))
    )


def _dist_ma10_pct(close: float | None, ma10: float | None) -> float | None:
    if close is None or ma10 is None or ma10 == 0:
        return None
    return (float(close) - float(ma10)) / float(ma10) * 100


def _vol_ratio(vol: float | None, vol_ma20: float | None) -> float | None:
    if vol is None or vol_ma20 is None or vol_ma20 == 0:
        return None
    return float(vol) / float(vol_ma20)


# ── Stage 評估 ────────────────────────────────────────────────────────────────

def _assess_stage(
    p: dict,
    inst: dict,
    dage: dict,
    is_priority: bool,
    is_avoid: bool,
) -> str:
    """
    簡化 Stage 評估：
      Stage2+ = 三軸全綠 + 外資 5d 正 + 量增
      Stage1  = 部分條件成立（仍有機會）
      StageC  = 已壞（結構破 / 處置 C）
      Avoid   = 老師明確排除

    回傳：'leaders' | 'middle' | 'laggards' | 'avoid'
    """
    if is_avoid:
        return "avoid"

    c     = p.get("close")
    ma5   = p.get("ma5")
    ma10  = p.get("ma10")
    ma20  = p.get("ma20")
    is_disp = p.get("is_disposition", False)

    # 處置股 C 類 = 直接落後（後面 generate 報告會加標籤）
    if is_disp:
        # 但如果是老師明示 priority 還是留在 middle
        if not is_priority:
            return "laggards"

    # 三軸站 MA（MA5/10/20 全綠）
    ma_green_count = sum(
        1 for ma in [ma5, ma10, ma20]
        if c is not None and ma is not None and float(c) > float(ma)
    )

    foreign_5d  = inst.get("foreign_5d") or 0
    foreign_1d  = inst.get("foreign_1d") or 0
    dage_net    = dage.get("dage_net") or 0
    vol_r       = _vol_ratio(p.get("volume"), p.get("vol_ma20")) or 0

    # 距 MA10
    dist10 = _dist_ma10_pct(c, ma10)

    # Leaders: 三軸全綠 + 外資 5d 正
    if ma_green_count >= 3 and foreign_5d > 0:
        return "leaders"

    # 強勢 leaders（外資大買 + priority + 三軸 ≥2）
    if is_priority and ma_green_count >= 2 and foreign_1d > 5000:
        return "leaders"

    # Laggards: 三軸全紅 or 結構壞 or 跌 MA20
    if ma_green_count == 0:
        return "laggards"
    if c is not None and ma20 is not None and float(c) < float(ma20) * 0.97:
        return "laggards"

    # stage1 候選：MA5 上 + 外資轉正
    if c is not None and ma5 is not None and float(c) >= float(ma5):
        if foreign_1d is not None and foreign_1d > 0:
            return "stage1"

    # Middle: 其他
    return "middle"


# ── 主掃描函式 ────────────────────────────────────────────────────────────────

def scan_framework(framework: dict, db_path: Path) -> dict:
    """
    對框架內每個 ticker 跑三軸 + 籌碼分析。

    回傳：
    {
      'trade_date': '2026-06-02',
      'leaders': [...],
      'middle': [...],
      'laggards': [...],
      'stage1': [...],
      'avoid': [...],
    }
    """
    # 取最新交易日
    dates = _get_latest_trade_dates(db_path, n=3)
    trade_date = dates[0] if dates else date.today().isoformat()
    print(f"[framework_scan] 掃描日期：{trade_date}", flush=True)

    stock_names    = _load_stock_names(db_path)
    priority_set   = set(framework.get("priority_tickers", []))
    avoid_dict     = framework.get("avoid_tickers", {})
    avoid_set      = set(avoid_dict.keys()) if isinstance(avoid_dict, dict) else set(avoid_dict)

    # 收集所有 tickers（按族群）
    all_tickers: dict[str, str] = {}  # ticker → sector_name
    for sector_name, sector_info in framework.get("sectors", {}).items():
        tickers = sector_info.get("tickers", []) if isinstance(sector_info, dict) else []
        for t in tickers:
            if t not in all_tickers:
                all_tickers[t] = sector_name

    print(f"[framework_scan] 總標的數：{len(all_tickers)}", flush=True)

    results: dict[str, list] = {
        "leaders": [], "middle": [], "laggards": [], "stage1": [], "avoid": []
    }

    for ticker, sector_name in all_tickers.items():
        # 取 price + 法人 + 大哥
        p    = _get_price_info(ticker, trade_date, db_path)
        inst = _get_institutional(ticker, trade_date, db_path, days=5)
        dage = _get_broker_dage(ticker, trade_date)

        is_priority = ticker in priority_set
        is_avoid    = ticker in avoid_set

        stage = _assess_stage(p, inst, dage, is_priority, is_avoid)

        name     = stock_names.get(ticker, ticker)
        ma_str   = _ma_alignment(p)
        dist10   = _dist_ma10_pct(p.get("close"), p.get("ma10"))
        close    = p.get("close")
        foreign_1d = inst.get("foreign_1d")
        foreign_5d = inst.get("foreign_5d")
        sitc_1d    = inst.get("sitc_1d")
        dage_net   = dage.get("dage_net")
        dage_brkrs = dage.get("dage_brokers", [])
        is_disp    = p.get("is_disposition", False)

        entry = {
            "ticker":       ticker,
            "name":         name,
            "sector":       sector_name,
            "close":        close,
            "ma_str":       ma_str,
            "dist_ma10":    dist10,
            "foreign_1d":   foreign_1d,
            "foreign_5d":   foreign_5d,
            "sitc_1d":      sitc_1d,
            "dage_net":     dage_net,
            "dage_brokers": dage_brkrs,
            "is_priority":  is_priority,
            "is_avoid":     is_avoid,
            "is_disp":      is_disp,
            "avoid_reason": avoid_dict.get(ticker, "") if isinstance(avoid_dict, dict) else "",
            "stage":        stage,
            "trade_date":   trade_date,
        }
        results[stage].append(entry)

    # 按 foreign_5d 降序排列
    def _sort_key(e):
        return -(e.get("foreign_5d") or 0)

    for key in results:
        results[key].sort(key=_sort_key)

    results["trade_date"]       = trade_date  # type: ignore
    results["framework_date"]   = framework.get("date", "unknown")  # type: ignore
    results["total_scanned"]    = len(all_tickers)  # type: ignore
    return results


# ── 報告產生 ──────────────────────────────────────────────────────────────────

def _fmt_inst(val: float | None, unit: str = "") -> str:
    if val is None:
        return "—"
    return f"{val:+,.0f}{unit}"


def _fmt_close(val: float | None) -> str:
    if val is None:
        return "—"
    return f"${val:.2f}"


def _fmt_dist(val: float | None) -> str:
    if val is None:
        return "—"
    return f"{val:+.1f}%"


def generate_framework_report(scan_result: dict, framework: dict) -> str:
    """
    產出 markdown 報告段落（直接嵌入 evening_brief 的 ## 框架內標的全掃）。
    """
    trade_date    = scan_result.get("trade_date", "unknown")
    framework_date = scan_result.get("framework_date", "unknown")
    total         = scan_result.get("total_scanned", 0)

    leaders  = scan_result.get("leaders", [])
    middle   = scan_result.get("middle", [])
    laggards = scan_result.get("laggards", [])
    stage1   = scan_result.get("stage1", [])
    avoid    = scan_result.get("avoid", [])

    lines = [
        f"## 框架內標的全掃 ({framework_date} 框架 / {total} 檔評估)",
        f"",
        f"> 掃描日期：{trade_date} | 框架版本：{framework_date}",
        f"> 資料來源：standard_daily_bar + institutional_investors + broker cache",
        f"",
    ]

    # ── 領頭 ──────────────────────────────────────────────────────────────────
    lines += [
        f"### 🥇 領頭 (Stage 2 / 加碼候選)",
        f"",
    ]
    if leaders:
        lines += [
            f"| Ticker | 名稱 | 族群 | MA5/10/20/60 | 外資1d | 外資5d | 投信1d | 老師分點 | 距MA10 |",
            f"|---|---|---|---|---|---|---|---|---|",
        ]
        for e in leaders:
            priority_star = " ⭐" if e["is_priority"] else ""
            lines.append(
                f"| {e['ticker']}{priority_star} | {e['name']} | {e['sector']} | "
                f"{e['ma_str']} | {_fmt_inst(e['foreign_1d'])} | {_fmt_inst(e['foreign_5d'])} | "
                f"{_fmt_inst(e['sitc_1d'])} | {', '.join(e['dage_brokers']) or '—'} | "
                f"{_fmt_dist(e['dist_ma10'])} |"
            )
    else:
        lines.append(f"> 今日無明確領頭標的。")
    lines.append(f"")

    # ── 中段 ──────────────────────────────────────────────────────────────────
    lines += [
        f"### 🥈 中段 (繼續觀察)",
        f"",
    ]
    if middle:
        lines += [
            f"| Ticker | 名稱 | 族群 | MA5/10/20/60 | 外資1d | 外資5d | 距MA10 |",
            f"|---|---|---|---|---|---|---|",
        ]
        for e in middle:
            priority_star = " ⭐" if e["is_priority"] else ""
            disp_tag = " 🔒" if e["is_disp"] else ""
            lines.append(
                f"| {e['ticker']}{priority_star} | {e['name']}{disp_tag} | {e['sector']} | "
                f"{e['ma_str']} | {_fmt_inst(e['foreign_1d'])} | {_fmt_inst(e['foreign_5d'])} | "
                f"{_fmt_dist(e['dist_ma10'])} |"
            )
    else:
        lines.append(f"> 無中段標的。")
    lines.append(f"")

    # ── 落後 ──────────────────────────────────────────────────────────────────
    lines += [
        f"### 🥉 落後 (Stage C / 結構弱)",
        f"",
    ]
    if laggards:
        lines += [
            f"| Ticker | 名稱 | 族群 | MA5/10/20/60 | 外資5d | 距MA10 | 備註 |",
            f"|---|---|---|---|---|---|---|",
        ]
        for e in laggards:
            disp_tag = " 🔒處置" if e["is_disp"] else ""
            lines.append(
                f"| {e['ticker']} | {e['name']}{disp_tag} | {e['sector']} | "
                f"{e['ma_str']} | {_fmt_inst(e['foreign_5d'])} | "
                f"{_fmt_dist(e['dist_ma10'])} | — |"
            )
    else:
        lines.append(f"> 無落後標的。")
    lines.append(f"")

    # ── 新進候選 ──────────────────────────────────────────────────────────────
    lines += [
        f"### 🎯 新進候選 (Stage 1 試水)",
        f"",
    ]
    if stage1:
        lines += [
            f"| Ticker | 名稱 | 族群 | MA5/10/20/60 | 外資1d | 外資5d | 距MA10 |",
            f"|---|---|---|---|---|---|---|",
        ]
        for e in stage1:
            lines.append(
                f"| {e['ticker']} | {e['name']} | {e['sector']} | "
                f"{e['ma_str']} | {_fmt_inst(e['foreign_1d'])} | {_fmt_inst(e['foreign_5d'])} | "
                f"{_fmt_dist(e['dist_ma10'])} |"
            )
    else:
        lines.append(f"> 無新進 Stage 1 候選。")
    lines.append(f"")

    # ── 排除清單 ──────────────────────────────────────────────────────────────
    lines += [
        f"### ⚠️ 排除清單",
        f"",
    ]
    if avoid:
        lines += [
            f"| Ticker | 名稱 | 排除原因 | 收盤 | MA5/10/20/60 |",
            f"|---|---|---|---|---|",
        ]
        for e in avoid:
            lines.append(
                f"| {e['ticker']} | {e['name']} | {e['avoid_reason'] or '老師明確排除'} | "
                f"{_fmt_close(e['close'])} | {e['ma_str']} |"
            )
    else:
        # 從 framework avoid_tickers 補入（即使 DB 無資料）
        avoid_dict = framework.get("avoid_tickers", {})
        if avoid_dict:
            lines += [
                f"| Ticker | 排除原因 |",
                f"|---|---|",
            ]
            for tk, reason in (avoid_dict.items() if isinstance(avoid_dict, dict) else [(t, "") for t in avoid_dict]):
                lines.append(f"| {tk} | {reason} |")
        else:
            lines.append(f"> 無排除標的。")
    lines.append(f"")

    return "\n".join(lines)


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main():
    import argparse
    from datetime import datetime

    ap = argparse.ArgumentParser(description="框架內標的每日掃描")
    ap.add_argument("date", nargs="?", default=None,
                    help="目標日期 YYYY-MM-DD（預設最新 DB 日期）")
    ap.add_argument("--output", "-o", default=None,
                    help="輸出 markdown 路徑（預設輸出至 stdout）")
    ap.add_argument("--save-brief", action="store_true",
                    help="另存為 daily_brief/<date>_evening_v2.md")
    args = ap.parse_args()

    framework   = load_latest_framework()
    scan_result = scan_framework(framework, _DB)
    md          = generate_framework_report(scan_result, framework)

    trade_date = scan_result.get("trade_date", args.date or date.today().isoformat())

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"→ 報告寫入：{args.output}")
    elif args.save_brief:
        out_path = _BRIEF_DIR / f"{trade_date}_evening_v2.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# {trade_date} 框架掃描報告（v2）\n\n"
            f"> 產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"---\n\n"
        )
        out_path.write_text(header + md, encoding="utf-8")
        print(f"→ 報告寫入：{out_path}")
        print(f"  領頭：{len(scan_result.get('leaders', []))} 檔")
        print(f"  中段：{len(scan_result.get('middle', []))} 檔")
        print(f"  落後：{len(scan_result.get('laggards', []))} 檔")
        print(f"  新進：{len(scan_result.get('stage1', []))} 檔")
        print(f"  排除：{len(scan_result.get('avoid', []))} 檔")
    else:
        print(md)

    return scan_result


if __name__ == "__main__":
    main()
