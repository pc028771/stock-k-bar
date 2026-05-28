"""每日 21:00 晚間深度報告 — 戰略整合 + 隔日 SOP 候選.

整合：
    1. 當日 dage 報告（已存在 daily_brief/）
    2. holdings.json 全持倉狀態
    3. trade_journal 當日（若存在）
    4. 全方位培訓筆記當日（若存在）
    5. 當日 scanner 結果（若存在 /tmp/scanner_candidates_<DATE>.md）

輸出：
    docs/主力大課程/daily_brief/YYYY-MM-DD_evening.md

結尾包含「明日 SOP 候選」段落，可直接貼入隔日 trade_journal。

Usage:
    python scripts/zhuli/evening_brief.py [YYYY-MM-DD] [--no-dage]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO      = Path(__file__).parent.parent.parent
_DB        = Path.home() / ".four_seasons" / "data.sqlite"
_HOLDINGS  = _REPO / "docs" / "主力大課程" / "holdings.json"
_BRIEF_DIR = _REPO / "docs" / "主力大課程" / "daily_brief"
_JOURNAL_DIR = _REPO / "docs" / "主力大課程" / "trade_journal"
_NOTES_DIR = _REPO / "docs" / "主力大課程" / "全方位培訓筆記"

# 把 broker_dage_tracker 加入 path
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.broker_dage_tracker import (
    _load_holdings, _safe_float, _safe_int, _load_stock_names,
    _get_price_and_ma, _BRIEF_DIR as _DAGE_BRIEF_DIR,
    get_dage_daily_action, cross_reference_holdings, write_brief,
    _HOLDINGS_JSON,
)


# ── 輔助函式 ──────────────────────────────────────────────────────────────────

def _next_trading_day(d: date) -> date:
    """粗略計算下一個交易日（跳過週末；不含國定假日）。"""
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:  # 5=Sat, 6=Sun
        nxt += timedelta(days=1)
    return nxt


def _load_dage_action(target_date: str, no_dage: bool, mode: str) -> dict | None:
    """嘗試載入已存在的 dage 報告 JSON；若不存在才重新抓（除非 no_dage）。"""
    # 嘗試從已存在的報告反推（只是個備援；通常 evening 在 dage 之後跑）
    # 實際上重新呼叫 get_dage_daily_action 最可靠（有 cache）
    if no_dage:
        return None
    try:
        from zhuli.broker_dage_tracker import get_dage_daily_action
        print(f"[evening] 載入大哥動作資料（使用 cache）...", flush=True)
        return get_dage_daily_action(target_date, mode=mode)
    except Exception as e:
        print(f"[WARN] 大哥資料載入失敗：{e}", file=sys.stderr)
        return None


def _get_close_and_ma(ticker: str, trade_date: str) -> dict:
    """從 DB 取完整 MA 狀態。"""
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=5)
        row = con.execute(
            "SELECT close, ma5, ma10, ma20, stop_loss_ref FROM standard_daily_bar "
            "WHERE ticker=? AND trade_date=?",
            (ticker, trade_date)
        ).fetchone()
        con.close()
        if row is None:
            # stop_loss_ref 欄位不一定存在，改用基本欄位
            con2 = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=5)
            row2 = con2.execute(
                "SELECT close, ma5, ma10, ma20 FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date=?",
                (ticker, trade_date)
            ).fetchone()
            con2.close()
            if row2 is None:
                return {}
            close, ma5, ma10, ma20 = row2
            return {"close": close, "ma5": ma5, "ma10": ma10, "ma20": ma20}
        close, ma5, ma10, ma20, sl_ref = row
        return {"close": close, "ma5": ma5, "ma10": ma10, "ma20": ma20, "stop_loss_ref": sl_ref}
    except Exception:
        try:
            con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=5)
            row = con.execute(
                "SELECT close, ma5, ma10, ma20 FROM standard_daily_bar "
                "WHERE ticker=? AND trade_date=?",
                (ticker, trade_date)
            ).fetchone()
            con.close()
            if row is None:
                return {}
            close, ma5, ma10, ma20 = row
            return {"close": close, "ma5": ma5, "ma10": ma10, "ma20": ma20}
        except Exception:
            return {}


def _ma_emoji(close, ma) -> str:
    """收盤 vs MA：綠燈站上/黃燈接近/紅燈跌破。"""
    if close is None or ma is None:
        return "⬜"
    try:
        c, m = float(close), float(ma)
        diff_pct = (c - m) / m * 100
        if diff_pct >= 1.0:
            return "🟢"
        elif diff_pct >= -1.0:
            return "🟡"
        else:
            return "🔴"
    except (TypeError, ZeroDivisionError):
        return "⬜"


def _analyze_holding(ticker: str, info: dict, trade_date: str) -> dict:
    """分析單一持倉狀態，產出警示 + 建議。"""
    cost       = _safe_float(info.get("cost"))
    stop_loss  = _safe_float(info.get("stop_loss"))
    shares     = _safe_float(info.get("shares"))

    price_info = _get_close_and_ma(ticker, trade_date)
    close = price_info.get("close")
    ma5   = price_info.get("ma5")
    ma10  = price_info.get("ma10")

    warnings = []
    sop_actions = []

    if close is not None and stop_loss is not None:
        if float(close) < float(stop_loss):
            warnings.append(f"收盤 ${close:.2f} < 停損 ${stop_loss:.2f} — 停損觸發！")
            sop_actions.append("STOP_LOSS")

    # 加碼條件：脫離成本 ≥+10% + 回支撐（MA5/10 附近）
    if close is not None and cost is not None and ma10 is not None:
        c, co, m10 = float(close), float(cost), float(ma10)
        pnl_pct = (c - co) / co * 100 if co > 0 else 0
        dist_ma10 = (c - m10) / m10 * 100 if m10 > 0 else 0
        if pnl_pct >= 10 and -3 <= dist_ma10 <= 5:
            warnings.append(f"脫離成本 +{pnl_pct:.1f}% + 距MA10 {dist_ma10:+.1f}% — 加碼條件成立！")
            sop_actions.append("ADD_POSITION")

    return {
        "ticker":      ticker,
        "name":        info.get("name", ""),
        "close":       close,
        "cost":        cost,
        "stop_loss":   stop_loss,
        "shares":      shares,
        "ma5":         ma5,
        "ma10":        ma10,
        "warnings":    warnings,
        "sop_actions": sop_actions,
    }


def _find_today_journal(trade_date: str) -> Path | None:
    """找當日 trade_journal（多種命名格式）。"""
    patterns = [
        f"⭐_{trade_date}.md",
        f"{trade_date}.md",
        f"{trade_date}_*.md",
    ]
    for p in patterns:
        matches = list(_JOURNAL_DIR.glob(p))
        if matches:
            return matches[0]
    return None


def _find_today_notes(trade_date: str) -> list[Path]:
    """找全方位培訓筆記當日新增的檔案（日期在檔名中）。"""
    found = []
    for p in _NOTES_DIR.glob(f"*{trade_date}*"):
        if p.suffix in (".md", ".txt"):
            found.append(p)
    return found


def _read_first_n_lines(path: Path, n: int = 30) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[:n])
    except Exception:
        return "(讀取失敗)"


# ── 報告產生 ──────────────────────────────────────────────────────────────────

def generate_evening_brief(target_date: str, dage_mode: str = "extended",
                            no_dage: bool = False) -> Path:
    """整合所有資料，產出 evening markdown 報告。"""
    fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    next_day   = _next_trading_day(date.fromisoformat(target_date))
    next_date  = next_day.isoformat()

    stock_names = _load_stock_names()
    holdings_raw = _load_holdings(_HOLDINGS)
    holdings   = holdings_raw.get("holdings", {})
    watchlist  = holdings_raw.get("watchlist", {})
    exclusion  = holdings_raw.get("exclusion_list", {})

    # ── 大哥資料 ────────────────────────────────────────────
    action = _load_dage_action(target_date, no_dage, dage_mode)
    xref = cross_reference_holdings(action, _HOLDINGS) if action else None

    # ── 持倉分析 ─────────────────────────────────────────────
    holding_analyses = {}
    for ticker, info in holdings.items():
        holding_analyses[ticker] = _analyze_holding(ticker, info, target_date)

    # SOP 分類
    stop_loss_triggers = [a for a in holding_analyses.values() if "STOP_LOSS" in a["sop_actions"]]
    add_position_triggers = [a for a in holding_analyses.values() if "ADD_POSITION" in a["sop_actions"]]

    # Watchlist 大哥大買 → 明日重點
    watchlist_upgrades = []
    if action:
        all_actions = action.get("all_actions", {})
        for ticker, info in watchlist.items():
            net = all_actions.get(ticker, 0)
            if net > 200:
                close, dist = _get_price_and_ma(ticker, target_date)
                watchlist_upgrades.append({
                    "ticker": ticker,
                    "name": info.get("name", stock_names.get(ticker, "")),
                    "dage_net_lots": net,
                    "close": close,
                    "dist_ma10_pct": dist,
                    "reason": info.get("reason", ""),
                })

    # 新候選（大哥買 + 不在持倉/watchlist/exclusion）
    new_candidates = xref.get("new_candidates", []) if xref else []

    # ── Scanner 結果 ─────────────────────────────────────────
    # 14:30 scanner 已停用（改為 13:10 intraday scanner）。
    # 若 /tmp/scanner_candidates_DATE.md 不存在，evening_brief 自行跑 daily_scanner_job。
    scanner_file = Path(f"/tmp/scanner_candidates_{target_date}.md")
    if not scanner_file.exists():
        print(f"[evening] scanner cache 不存在，自行跑 daily_scanner_job...", flush=True)
        try:
            from zhuli.daily_scanner_job import run_scanners, render_markdown
            _scan_results = run_scanners(target_date, _DB)
            _scan_md = render_markdown(target_date, _scan_results)
            scanner_file.write_text(_scan_md, encoding="utf-8")
            flag_path = Path(f"/tmp/scanner_done_{target_date}.flag")
            from datetime import datetime as _dt
            flag_path.write_text(f"done at {_dt.now().isoformat()} (evening_brief fallback)\n")
            print(f"[evening] scanner fallback 完成 → {scanner_file}", flush=True)
        except Exception as _e:
            print(f"[WARN] evening_brief scanner fallback 失敗: {_e}", file=sys.stderr)
    scanner_summary = None
    if scanner_file.exists():
        scanner_summary = _read_first_n_lines(scanner_file, 50)

    # ── Trade Journal ─────────────────────────────────────────
    journal_path = _find_today_journal(target_date)
    journal_excerpt = None
    if journal_path:
        journal_excerpt = _read_first_n_lines(journal_path, 40)

    # ── 課程筆記 ─────────────────────────────────────────────
    notes_paths = _find_today_notes(target_date)

    # ── 組裝報告 ─────────────────────────────────────────────
    lines = [
        f"# {target_date} 晚間深度報告（明日 {next_date} 前夕）",
        f"",
        f"> 產生時間：{fetch_time}",
        f"> 整合來源：大哥追蹤 | 持倉狀態 | Scanner | trade_journal | 課程筆記",
        f"",
        f"---",
        f"",
    ]

    # Section 1: 持倉狀態快照
    lines += [
        f"## 持倉狀態快照（{target_date} 收盤後）",
        f"",
        f"| Ticker | 名稱 | 持倉 | 成本 | 收盤 | MA5 | MA10 | 停損 | 狀態 |",
        f"|---|---|---|---|---|---|---|---|---|",
    ]
    for a in holding_analyses.values():
        c     = f"${a['close']:.2f}" if a['close'] else "—"
        ma5   = f"${a['ma5']:.2f}" if a['ma5'] else "—"
        ma10  = f"${a['ma10']:.2f}" if a['ma10'] else "—"
        cost  = f"${a['cost']:.2f}" if a['cost'] else "TODO"
        sl    = f"${a['stop_loss']:.2f}" if a['stop_loss'] else "TODO"
        sh    = f"{a['shares']:.0f}張" if a['shares'] else "TODO"
        m5e   = _ma_emoji(a['close'], a['ma5'])
        m10e  = _ma_emoji(a['close'], a['ma10'])
        status_icons = ""
        if "STOP_LOSS" in a["sop_actions"]:
            status_icons += "🚨停損!"
        elif a["warnings"]:
            status_icons += "⚠️"
        else:
            status_icons = "✅"
        lines.append(
            f"| {a['ticker']} | {a['name']} | {sh} | {cost} | {c} | "
            f"{m5e}{ma5} | {m10e}{ma10} | {sl} | {status_icons} |"
        )
    lines.append(f"")

    # Section 2: 大哥 Top 動作摘要
    if action:
        lines += [
            f"## 大哥今日動作摘要",
            f"",
            f"- 掃描範圍：{action['tickers_scanned']} 檔（`{action.get('fetch_mode','')}`）",
            f"- 進貨標的：{action['total_buy_tickers']} 檔 | 出貨：{action['total_sell_tickers']} 檔",
            f"- 淨買合計：{action['total_net_lots']:+,} 張",
            f"",
        ]
        if action["top_buy"]:
            lines += [
                f"**Top 5 買超：**",
                f"",
                f"| Ticker | 名稱 | 大哥淨買 | 收盤 | 距MA10 |",
                f"|---|---|---|---|---|",
            ]
            for item in action["top_buy"][:5]:
                d = item.get("dist_ma10_pct")
                close_str = f"${item['close']:.2f}" if item["close"] else "—"
                dist_str  = f"{d:+.1f}%" if d is not None else "—"
                lines.append(
                    f"| {item['ticker']} | {item['name']} | {item['net_lots']:+,} | "
                    f"{close_str} | {dist_str} |"
                )
            lines.append(f"")

        # 完整 dage 報告連結
        dage_path = _BRIEF_DIR / f"{target_date}_dage.md"
        if dage_path.exists():
            lines.append(f"> 完整大哥報告：`{dage_path.relative_to(_REPO)}`")
            lines.append(f"")
    else:
        lines += [
            f"## 大哥動作（無資料）",
            f"",
            f"> 大哥資料未取得（可執行 `python scripts/zhuli/broker_dage_tracker.py {target_date}` 補抓）",
            f"",
        ]

    # Section 3: Scanner 摘要
    if scanner_summary:
        lines += [
            f"## Scanner 摘要",
            f"",
            f"```",
            scanner_summary[:2000],
            f"```",
            f"",
            f"> 完整 scanner：`/tmp/scanner_candidates_{target_date}.md`",
            f"",
        ]
    else:
        lines += [
            f"## Scanner（無資料）",
            f"",
            f"> scanner 今日未跑或檔案不存在（`/tmp/scanner_candidates_{target_date}.md`）",
            f"",
        ]

    # Section 4: Trade Journal 摘要
    if journal_excerpt:
        lines += [
            f"## Trade Journal 今日摘要",
            f"",
            f"> 來源：`{journal_path.relative_to(_REPO)}`",
            f"",
            journal_excerpt,
            f"",
            f"...(詳見完整 journal)",
            f"",
        ]
    else:
        lines += [
            f"## Trade Journal（今日無記錄）",
            f"",
        ]

    # Section 5: 課程筆記
    if notes_paths:
        lines += [
            f"## 今日課程筆記",
            f"",
        ]
        for p in notes_paths:
            lines += [
                f"### {p.name}",
                _read_first_n_lines(p, 20),
                f"",
            ]

    # ═══════════════════════════════════════════════════════
    # Section 6: 明日 SOP 候選（核心輸出）
    # ═══════════════════════════════════════════════════════
    lines += [
        f"---",
        f"",
        f"## 明日（{next_date}）SOP 候選",
        f"",
        f"> 此段可直接複製貼入 `trade_journal/⭐_{next_date}.md`",
        f"",
    ]

    # 6-A: 停損候選
    if stop_loss_triggers:
        lines += [
            f"### 停損候選（收盤跌破停損位）",
            f"",
            f"| Ticker | 名稱 | 收盤 | 停損 | 行動 |",
            f"|---|---|---|---|---|",
        ]
        for a in stop_loss_triggers:
            lines.append(
                f"| {a['ticker']} | {a['name']} | "
                f"${a['close']:.2f} | ${a['stop_loss']:.2f} | "
                f"**明日開盤出清** |"
            )
        lines.append(f"")
        lines.append(f"> ⚠️ 以收盤確認為準（課程原則）；隔日開盤執行。")
        lines.append(f"")
    else:
        lines += [f"### 停損候選", f"", f"> 今日無持倉觸及停損位。", f""]

    # 6-B: 加碼候選
    if add_position_triggers:
        lines += [
            f"### 加碼候選（脫離成本 ≥+10% + 回支撐）",
            f"",
            f"| Ticker | 名稱 | 成本 | 收盤 | 距MA10 | 行動 |",
            f"|---|---|---|---|---|---|",
        ]
        for a in add_position_triggers:
            cost   = a['cost']
            close  = a['close']
            ma10   = a['ma10']
            pnl    = ((close - cost) / cost * 100) if (cost and close) else None
            dist   = ((close - ma10) / ma10 * 100) if (ma10 and close) else None
            lines.append(
                f"| {a['ticker']} | {a['name']} | ${cost:.2f} | ${close:.2f} | "
                f"{f'{dist:+.1f}%' if dist is not None else '—'} | "
                f"評估加碼（條件：+{pnl:.1f}% + 距MA10 {dist:+.1f if dist else '—'}%）|"
            )
        lines.append(f"")
        lines.append(f"> 老師規則：脫離成本 ≥+10% **且** 回支撐才加碼（雙閘門）。")
        lines.append(f"")
    else:
        lines += [
            f"### 加碼候選",
            f"",
            f"> 今日無持倉達到加碼條件（需脫離成本 ≥+10% 且回 MA10 附近）。",
            f"",
        ]

    # 6-C: Watchlist 升格
    if watchlist_upgrades:
        lines += [
            f"### Watchlist 升格（大哥大買 > 200 張）",
            f"",
            f"| Ticker | 名稱 | 大哥淨買 | 收盤 | 距MA10 | 原因 |",
            f"|---|---|---|---|---|---|",
        ]
        for w in watchlist_upgrades:
            d = w.get("dist_ma10_pct")
            w_close_str = f"${w['close']:.2f}" if w["close"] else "—"
            w_dist_str  = f"{d:+.1f}%" if d is not None else "—"
            lines.append(
                f"| {w['ticker']} | {w['name']} | {w['dage_net_lots']:+,} | "
                f"{w_close_str} | {w_dist_str} | "
                f"{w['reason'][:30] if w['reason'] else '—'} |"
            )
        lines.append(f"")
    else:
        lines += [
            f"### Watchlist 升格",
            f"",
            f"> 今日 watchlist 無大哥大買（> 200 張）標的。",
            f"",
        ]

    # 6-D: 新候選（大哥 + scanner 交叉）
    if new_candidates:
        lines += [
            f"### 新候選（大哥買進 × 不在現有追蹤清單）",
            f"",
            f"| Ticker | 名稱 | 大哥淨買 | 收盤 | 距MA10 | 建議 |",
            f"|---|---|---|---|---|---|",
        ]
        for c in new_candidates[:10]:  # 最多顯示前 10
            d = c.get("dist_ma10_pct")
            suggestion = "加入watchlist" if d is not None and d <= 10 else \
                         "距MA10過遠" if d is not None else "—"
            c_close_str = f"${c['close']:.2f}" if c.get("close") else "—"
            c_dist_str  = f"{d:+.1f}%" if d is not None else "—"
            lines.append(
                f"| {c['ticker']} | {c['name']} | {c['net_lots']:+,} | "
                f"{c_close_str} | {c_dist_str} | {suggestion} |"
            )
        lines.append(f"")

    # 6-E: 需要確認的 TODO 持倉
    todo_holdings = [(t, info) for t, info in holdings.items()
                     if any(str(v) == "TODO"
                            for k, v in info.items()
                            if k in ("shares", "cost", "entry_date"))]
    if todo_holdings:
        lines += [
            f"### TODO 持倉（需補全資料）",
            f"",
            f"| Ticker | 名稱 | 缺少的欄位 |",
            f"|---|---|---|",
        ]
        for t, info in todo_holdings:
            missing = [k for k in ("shares", "cost", "entry_date")
                       if str(info.get(k, "")) == "TODO"]
            lines.append(f"| {t} | {info.get('name', '')} | {', '.join(missing)} |")
        lines.append(f"")

    lines += [
        f"---",
        f"",
        f"晚間報告產生時間：{fetch_time}",
        f"明日準備：{next_date}（{['一','二','三','四','五','六','日'][next_day.weekday()]}）",
    ]

    # 寫出檔案
    out_path = _BRIEF_DIR / f"{target_date}_evening.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ 晚間報告寫入：{out_path}")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="每日晚間深度報告")
    ap.add_argument("date", nargs="?", default=None,
                    help="目標日期 YYYY-MM-DD（預設今天）")
    ap.add_argument("--no-dage", action="store_true",
                    help="不重新抓大哥資料（若當日 dage 報告已存在）")
    ap.add_argument("--dage-mode", default="extended",
                    choices=["priority", "extended", "full"],
                    help="大哥掃描範圍（預設 extended）")
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()

    print(f"=== 晚間深度報告 ===")
    print(f"日期: {target_date}")

    out_path = generate_evening_brief(target_date, dage_mode=args.dage_mode,
                                      no_dage=args.no_dage)

    print(f"\n完成！報告：{out_path}")
    print(f"大小：{out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
