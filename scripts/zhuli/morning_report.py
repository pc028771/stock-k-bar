"""主力大每日晨報產生器.

每天早 07:00 由 launchd 觸發（週一~五）。

輸出:
  /tmp/morning_report_<YYYY-MM-DD>.md        — 詳細版（完整課程框架分析）
  /tmp/morning_report_<YYYY-MM-DD>_summary.md — 短摘要（Slack 推送用）

用法（手動跑）:
  python scripts/zhuli/morning_report.py
  python scripts/zhuli/morning_report.py --date 2026-05-21
  python scripts/zhuli/morning_report.py --output /tmp/my_report.md

設計限制:
  - 此 script 只讀 DB + 計算，不呼叫 Fubon 即時 API（避免 daemon 需認證）
  - 即時股價需在 Claude session 中搭配 watchlist_intraday.py 使用
  - Ch2 警示用 baseline_ch2_warnings()（已含籌碼集中度 + 主力分點）
"""
from __future__ import annotations

from zhuli.db import get_conn, MAIN_DB

import argparse
import sys
from datetime import datetime, date
from pathlib import Path
from textwrap import dedent

# Path setup
_WORKTREE = Path(__file__).parent.parent.parent
_SYS_DIR = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_WORKTREE), str(_WORKTREE / "scripts"), str(_SYS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DB = MAIN_DB
# 嘗試引入 kline DB 路徑 (標準日 K baseline)
try:
    from kline.bars import DEFAULT_DB_PATH as _KLINE_DB  # noqa: E402
except Exception:
    _KLINE_DB = MAIN_DB
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _db():
    return get_conn(_DB, timeout=15)


def get_active_holdings() -> list[dict]:
    """讀 zhuli_holdings WHERE is_active=1."""
    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT ticker, name, avg_cost, shares, entry_date, note
                FROM zhuli_holdings WHERE is_active=1
                ORDER BY entry_date
            """).fetchall()
        return [
            {"ticker": r[0], "name": r[1], "avg_cost": r[2],
             "shares": r[3], "entry_date": r[4], "note": r[5]}
            for r in rows
        ]
    except Exception as exc:
        return []


def get_latest_stance(ticker: str) -> dict | None:
    """從 zhuli_mentions 找最新 level / status / note."""
    try:
        with _db() as conn:
            row = conn.execute("""
                SELECT mention_date, level, status, note, source_quote
                FROM zhuli_mentions WHERE ticker=?
                ORDER BY mention_date DESC, id DESC LIMIT 1
            """, (ticker,)).fetchone()
        if row:
            return {"date": row[0], "level": row[1], "status": row[2],
                    "note": row[3], "quote": row[4]}
    except Exception:
        pass
    return None


def get_db_ohlcv(ticker: str, n: int = 10) -> pd.DataFrame:
    """取最近 n 日 OHLCV + MA baseline."""
    try:
        with get_conn(_KLINE_DB, timeout=15) as conn:
            df = pd.read_sql_query(
                """SELECT trade_date, open, high, low, close, volume,
                          ma5, ma10, ma20, ma60, ma20_slope, vol_ma20
                   FROM standard_daily_bar WHERE ticker=? AND is_usable=1
                   ORDER BY trade_date DESC LIMIT ?""",
                conn, params=(ticker, n),
            )
        if df.empty:
            return pd.DataFrame()
        return df.sort_values("trade_date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def get_kickout_closes(ticker: str) -> dict:
    """取 MA5/10/20/60 扣抵 close（N 天前 close）."""
    result = {}
    try:
        with get_conn(_KLINE_DB, timeout=15) as conn:
            for n, label in [(5, "ma5"), (10, "ma10"), (20, "ma20"), (60, "ma60")]:
                row = conn.execute(
                    "SELECT trade_date, close FROM standard_daily_bar "
                    "WHERE ticker=? AND is_usable=1 ORDER BY trade_date DESC "
                    "LIMIT 1 OFFSET ?",
                    (ticker, n),
                ).fetchone()
                if row:
                    result[label] = {"date": row[0], "close": row[1]}
    except Exception:
        pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 停損訊號檢核
# ─────────────────────────────────────────────────────────────────────────────

def check_stop_loss_signals(df: pd.DataFrame, avg_cost: float) -> list[str]:
    """課程 5 大停損訊號檢核（以昨收為基準）.

    ① 結構低跌破（今收跌破近期結構低）
    ② 大黑K 包覆（昨收 < 前日開）
    ③ 連 3 天低點下降
    ④ 跳空缺口（昨開 > 前收，但昨收跌破缺口）
    ⑤ MA5 扣抵預警（昨收 < MA5）

    Returns list of triggered warning strings.
    """
    warnings = []
    if len(df) < 3:
        return warnings

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # ① 收盤跌破結構支撐（簡化：跌破近 5 日低點）
    recent_low = df.tail(5)["low"].min()
    if latest["close"] < recent_low and latest["close"] < avg_cost:
        warnings.append(
            f"① 結構低跌破：昨收 {latest['close']:.2f} < 近5日低 {recent_low:.2f}（均成本 {avg_cost:.2f}）"
        )

    # ② 大黑K 包覆（昨K棒實體 > 3%，且收黑，且包覆前日）
    body_pct = (latest["close"] - latest["open"]) / latest["open"] * 100 if latest["open"] else 0
    if (body_pct < -3
            and latest["open"] >= prev["high"]  # 開高
            and latest["close"] <= prev["low"]):  # 完整包覆
        warnings.append(
            f"② 大黑K 包覆：昨 body {body_pct:.1f}%，開 {latest['open']:.2f} ≥ 前高 {prev['high']:.2f}，"
            f"收 {latest['close']:.2f} ≤ 前低 {prev['low']:.2f}"
        )
    elif body_pct < -3:
        warnings.append(
            f"② 大黑K 警示（未完整包覆）：昨 body {body_pct:.1f}%，收 {latest['close']:.2f}"
        )

    # ③ 連 3 天低點下降
    if len(df) >= 3:
        r = df.tail(3).reset_index(drop=True)
        lows = [r["low"].iloc[i] for i in range(3)]
        if lows[2] < lows[1] < lows[0]:
            warnings.append(
                f"③ 連3天低點下降：{lows[0]:.2f} → {lows[1]:.2f} → {lows[2]:.2f}"
            )

    # ④ 跳空缺口回補失敗（最近一個跳空 gap，且當天收盤未回填）
    if prev["open"] > df.iloc[-3]["close"] * 1.005:  # 昨開跳空
        gap_top = prev["open"]
        gap_bottom = df.iloc[-3]["close"]
        if prev["close"] < gap_bottom:  # 跳空當天回補 → 出場訊號
            warnings.append(
                f"④ 跳空缺口回補失敗：缺口 {gap_bottom:.2f}~{gap_top:.2f}，昨收 {prev['close']:.2f} 跌破"
            )

    # ⑤ MA5 扣抵：收盤跌破 MA5
    ma5 = latest.get("ma5")
    if ma5 and latest["close"] < ma5:
        warnings.append(
            f"⑤ MA5 跌破：昨收 {latest['close']:.2f} < MA5 {ma5:.2f}"
        )

    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# 扣抵預判
# ─────────────────────────────────────────────────────────────────────────────

def rolloff_status(prev_close: float, kickout: dict) -> list[str]:
    """MA5/10/20/60 扣抵預判亮燈.

    prev_close: 昨收盤
    kickout: dict from get_kickout_closes()
    Returns list of formatted lines.
    """
    lines = []
    for label in ("ma5", "ma10", "ma20", "ma60"):
        k = kickout.get(label)
        if not k:
            continue
        kc = k["close"]
        kd = k["date"]
        if kc <= 0:
            continue
        diff_pct = (prev_close / kc - 1) * 100
        if diff_pct > 0.5:
            icon = "🟢"
            direction = "將上揚"
        elif diff_pct < -0.5:
            icon = "🔴"
            direction = "將下彎（早期出場警示）"
        else:
            icon = "🟡"
            direction = "臨界（1-2 天內可能轉折）"
        sign = "+" if diff_pct >= 0 else ""
        prefix = "  ⚠️ " if icon == "🔴" else "  "
        lines.append(f"{prefix}{label.upper():5} {icon} {direction}  昨收 {prev_close:.2f} vs 扣抵 {kc:.2f}（{kd}）= {sign}{diff_pct:.2f}%")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# 開盤情境預備動作
# ─────────────────────────────────────────────────────────────────────────────

def build_scenario_table(holding: dict, df: pd.DataFrame) -> str:
    """依均成本 + 昨收 + MA 建開盤情境 table."""
    if df.empty:
        return "  （無日 K 資料，無法建情境）"

    latest = df.iloc[-1]
    prev_close = latest["close"]
    ma5 = latest.get("ma5") or 0
    ma20 = latest.get("ma20") or 0
    avg_cost = holding["avg_cost"]

    # 情境門檻計算
    gap_up_thresh = round(prev_close * 1.02, 2)   # 開高 +2%
    gap_down_thresh = round(prev_close * 0.97, 2)  # 開低 -3%
    atk_thresh = round(max(latest["high"], prev_close * 1.015), 2)  # 盤中突破前高

    lines = [
        f"  開盤情境（基準：昨收 {prev_close:.2f}，均成本 {avg_cost:.2f}，MA5 {ma5:.2f}，MA20 {ma20:.2f}）",
        "",
        f"  A. 跳空開高 > {gap_up_thresh:.2f}（+2%）",
        f"       → 觀察是否守住缺口，不回補視為強勢；若盤中跌回缺口下緣留意出場",
        f"  B. 開盤平盤（{gap_down_thresh:.2f} ~ {gap_up_thresh:.2f}）",
        f"       → 盤中守 MA5 {ma5:.2f} 則維持觀察；跌破 MA5 收盤確認後評估停損",
        f"  C. 開低 < {gap_down_thresh:.2f}（-3%）",
        f"       → 確認是否跌破結構支撐（課程紅線：收盤確認）；跌破均成本 {avg_cost:.2f} 特別注意",
        f"  D. 盤中突破昨高 {atk_thresh:.2f}",
        f"       → 攻擊訊號；量能需 > vol_ma20；確認後加碼候選（依老師守則）",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 單檔報告組裝
# ─────────────────────────────────────────────────────────────────────────────

def build_holding_section(holding: dict, report_date: str) -> tuple[str, str]:
    """組裝單檔詳細報告 + 摘要.

    Returns (detail_section, summary_line).
    """
    ticker = holding["ticker"]
    name = holding["name"] or ""
    avg_cost = holding["avg_cost"]
    shares = holding["shares"]
    entry_date = holding["entry_date"] or ""

    market_value = avg_cost * shares

    df = get_db_ohlcv(ticker, n=10)
    kickout = get_kickout_closes(ticker)
    stance = get_latest_stance(ticker)

    # --- baseline ---
    prev_close = df.iloc[-1]["close"] if not df.empty else None
    if prev_close and avg_cost > 0:
        pnl_pct = (prev_close / avg_cost - 1) * 100
        pnl_str = f"{pnl_pct:+.1f}%"
    else:
        pnl_str = "N/A"

    # --- Ch2 + chip 警示 ---
    try:
        from zhuli.watchlist_intraday import baseline_ch2_warnings
        ch2_score, ch2_lines = baseline_ch2_warnings(_KLINE_DB, ticker)
    except Exception as exc:
        ch2_score, ch2_lines = 0, [f"  ? Ch2 計算失敗: {exc}"]

    # --- 停損訊號 ---
    stop_signals = check_stop_loss_signals(df, avg_cost) if not df.empty else []

    # --- 扣抵 ---
    rolloff_lines = rolloff_status(prev_close, kickout) if prev_close else []

    # --- 老師 stance ---
    if stance:
        stance_str = (f"[{stance['level']}] {stance['status']}  "
                      f"({stance['date']})")
        if stance.get("quote"):
            stance_str += f"\n  老師: 「{stance['quote'][:80]}」"
    else:
        stance_str = "（DB 無記錄，請手動確認）"

    # --- 開盤情境 ---
    scenario = build_scenario_table(holding, df)

    # === 詳細報告 ===
    lines = [
        f"## {ticker} {name}",
        f"",
        f"**持股資訊**  均成本 {avg_cost:.2f}  股數 {shares:,}  進場 {entry_date}",
        f"昨收 {f'{prev_close:.2f}' if prev_close else 'N/A'}  浮盈 {pnl_str}  市值 {market_value:,.0f}",
        f"",
        f"**老師 Stance**  {stance_str}",
        f"",
    ]

    if stop_signals:
        lines.append("**🔴 課程停損訊號（昨日收盤基準）**")
        for s in stop_signals:
            lines.append(f"  - {s}")
        lines.append("")
    else:
        lines.append("**✓ 停損訊號**  昨日收盤無觸發")
        lines.append("")

    if ch2_lines:
        ch2_icon = "🔴" if ch2_score >= 3 else ("⚠️" if ch2_score >= 2 else "🟡")
        lines.append(f"**{ch2_icon} Ch2 + 籌碼警示** (score={ch2_score})")
        for l in ch2_lines:
            lines.append(f"  {l}")
        lines.append("")
    else:
        lines.append("**✓ Ch2 警示**  無")
        lines.append("")

    if rolloff_lines:
        lines.append("**📊 扣抵預判（明日 MA 方向）**")
        lines.extend(rolloff_lines)
        lines.append("")

    lines.append("**開盤預備動作**")
    lines.append(scenario)
    lines.append("")
    lines.append("---")
    lines.append("")

    # === 摘要行 ===
    stop_flag = "🔴停損" if stop_signals else "✓"
    ch2_flag = f"⚠️Ch2={ch2_score}" if ch2_score >= 2 else "✓"
    prev_close_str = f"{prev_close:.2f}" if prev_close else "?"
    summary = (f"  {ticker} {name:6}  昨收 {prev_close_str:>8}  "
               f"浮盈 {pnl_str:>7}  {stop_flag}  {ch2_flag}")

    return "\n".join(lines), summary


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="主力大每日晨報")
    parser.add_argument("--date", default=None,
                        help="報告日期 YYYY-MM-DD（預設今天）")
    parser.add_argument("--output", default=None,
                        help="詳細報告路徑（預設 /tmp/morning_report_<date>.md）")
    args = parser.parse_args()

    report_date = args.date or date.today().isoformat()
    out_path = Path(args.output) if args.output else Path(f"/tmp/morning_report_{report_date}.md")
    summary_path = out_path.with_name(out_path.stem + "_summary.md")

    holdings = get_active_holdings()
    if not holdings:
        print(f"⚠️  zhuli_holdings 無 active 記錄。先跑 tracker.py add-holding 加入持股。")
        # 仍產出空殼報告
        holdings = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 詳細報告 header
    detail_lines = [
        f"# 主力大每日晨報 — {report_date}",
        f"",
        f"> 產生時間：{now_str}  |  持股數：{len(holdings)}",
        f"> 資料來源：DB baseline（昨收盤）；即時股價請搭配 watchlist_intraday.py",
        f"",
        f"---",
        f"",
    ]

    # 摘要 header
    summary_lines = [
        f"# 晨報摘要 — {report_date}",
        f"",
        f"產生：{now_str}",
        f"",
        f"| ticker | 昨收 | 浮盈 | 停損訊號 | Ch2 |",
        f"|--------|------|------|----------|-----|",
    ]

    for holding in holdings:
        try:
            detail_sec, summary_line = build_holding_section(holding, report_date)
            detail_lines.append(detail_sec)
            # 轉為 markdown table row
            parts = summary_line.strip().split("  ")
            summary_lines.append("| " + " | ".join(p.strip() for p in parts if p.strip()) + " |")
        except Exception as exc:
            detail_lines.append(f"## {holding['ticker']} {holding.get('name','')}")
            detail_lines.append(f"\n❌ 報告產生失敗: {exc}\n\n---\n")
            summary_lines.append(f"| {holding['ticker']} | ERROR: {exc} |")

    detail_lines += [
        "",
        "---",
        "",
        "## 備註",
        "",
        "- **課程紅線**：所有跌破 / 站回以**收盤價確認**，不以盤中判斷",
        "- **停損訊號①**: 結構支撐跌破 → 停損出清",
        "- **停損訊號②**: 大黑K 完整包覆前段漲幅 → 停損訊號",
        "- **停損訊號③**: 低點越來越高規律不再成立 → 停損出清",
        "- **停損訊號④**: 跳空缺口當天回補失敗 → 出場訊號",
        "- **停損訊號⑤**: MA5 扣抵預判下彎 → 早期警示",
        "- **Ch2 警示** = K線結構 + 籌碼集中度 + 主力分點（已內建 baseline_ch2_warnings）",
        "- **扣抵預判** 🟢=將上揚  🟡=臨界(1-2天內可能轉折)  🔴=將下彎(早期出場警示)",
        f"- 即時盤中：`python scripts/zhuli/watchlist_intraday.py`",
        f"- 加入持股：`python scripts/zhuli/tracker.py add-holding <ticker> --avg-cost X --shares N`",
    ]

    # 寫出
    out_path.write_text("\n".join(detail_lines), encoding="utf-8")
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    print(f"✅ 晨報產生完成")
    print(f"   詳細報告: {out_path}")
    print(f"   摘要:     {summary_path}")
    if holdings:
        print(f"\n--- 摘要預覽 ---")
        for holding in holdings:
            print(f"  {holding['ticker']} {holding.get('name','')}")


if __name__ == "__main__":
    main()
