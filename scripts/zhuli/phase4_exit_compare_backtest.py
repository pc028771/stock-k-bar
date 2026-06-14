"""Phase 4 出場策略對比 Backtest — 真實交易紀錄版。

使用 user 真實交易紀錄 (2026-05-19 ~ 2026-06-03) 模擬 4 個出場 detector，
對比 user 實際出場 vs detector 觸發出場的損益差異。

Usage:
    python scripts/zhuli/phase4_exit_compare_backtest.py
    python scripts/zhuli/phase4_exit_compare_backtest.py --verbose
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# ── Path setup ─────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
_DB = MAIN_DB
# ── Import detectors ────────────────────────────────────────────────────────
from scripts.zhuli.exit.detectors import (
    check_umbrella_exit_daily,
    check_high_long_black,
    check_profit_milestone,
    check_gap_down_emergency,
)

# ── Real Trade Records (from holdings.json + trade_history) ────────────────
# 格式: (ticker, name, entry_date, entry_price, shares, actual_exit_date,
#         actual_exit_price, actual_pnl, notes)
# actual_exit_date = None 代表仍持有 (以 2026-06-03 收盤評估)
REAL_TRADES = [
    # ── 已出清 (closed) ──────────────────────────────────────────────────────
    # 東捷 8064: 5/19 買 1000@136.5，5/20 買 4000@135.0，陸續賣出
    ("8064", "東捷",  "2026-05-19", 136.5,  1000, "2026-05-20", 126.5, -10000, "東捷 -10k 教訓 (結構底失守)"),
    # 2476 鉅祥: 5/20 買 2000@114.5，5/28 賣 @121.5
    ("2476", "鉅祥",  "2026-05-20", 114.5,  2000, "2026-05-28", 121.5,  -6395, "拉高出貨日清倉、虧損 (手續費侵蝕)"),
    # 3162 精確: 5/26 新進場 1 張 @83.7 估 (日均附近)，5/28 出 @81.4
    ("3162", "精確",  "2026-05-26",  88.5,  1000, "2026-05-28",  81.4, -10412, "小部位認損"),
    # 3149 正達: entry ~5/22 @57.8 估 (日均)，5/28 出 @67.2，+23k
    ("3149", "正達",  "2026-05-22",  59.1,  4000, "2026-05-28",  67.2,  23036, "強檔鎖利 +13%"),
    # 2464 盟立: 5/22 進 3000@143.5，5/27 賣 1@176.5，5/28 賣 2@170.5，獲利 85k
    ("2464", "盟立",  "2026-05-22", 143.5,  3000, "2026-05-28", 172.0,  85185, "機器人族群大波段"),
    # 3265 台星科: 5/26 持有 ~@190.5，5/28 出 @189，小虧
    ("3265", "台星科", "2026-05-26", 186.0,  1000, "2026-05-28", 189.0,   3000, "光通族群持有 3 天"),
    # 6282 康舒: 5/22 進 3000@57.7 估，5/28 持有到近停損
    ("6282", "康舒",  "2026-05-22",  57.7,  3000, "2026-05-28",  57.7,      0, "BBU 強勢、5/28 守在 56.8 未跌破"),
    # 8027 鈦昇: 5/19 買 1000@273.5，5/20 賣 3000@245，虧 (FIFO 推算)
    ("8027", "鈦昇",  "2026-05-19", 273.5,  1000, "2026-05-20", 245.0, -28500, "鈦昇早出 -28k (結構壞)"),
    # 2485 兆赫: 6/1 買 5@73.4，6/2 守成本出 @73.5
    ("2485", "兆赫",  "2026-06-01",  73.4,  5000, "2026-06-02",  73.5,   -894, "MA5/10 破 + 外資出、紀律停損"),
    # 3016 嘉晶: 6/2 試撮 FOMO 進 1000@~134，同日 -21k (9:00-9:05 違規)
    ("3016", "嘉晶",  "2026-06-02", 134.0,  1000, "2026-06-02", 113.0, -21388, "試撮 FOMO 違紀 -21k (最大教訓)"),
    # 6285 啟碁: 6/1 進 1000@315，6/2 加碼 1000@313.5，6/2 尾盤出 1@306
    ("6285", "啟碁",  "2026-06-01", 315.0,  1000, "2026-06-02", 306.0,  -6705, "老師明示加碼 6/2 尾盤出 -6.7k"),
    # ── 仍持有 (以 6/3 收盤為基準) ─────────────────────────────────────────
    # 1605 華新: 6/1 進 8000@40.1，6/3 收 42.7
    ("1605", "華新",  "2026-06-01",  40.1,  8000, None,           42.7,   None, "Tier-S core、仍持有"),
    # 2885 元大金: 5/27 進 10000@58.0，6/3 收 63.7
    ("2885", "元大金", "2026-05-27",  58.0, 10000, None,           63.7,   None, "券商族群 core"),
    # 8046 南電: 進場估 5/21 @862，6/3 收 904 (假設 1000 股)
    ("8046", "南電",  "2026-05-21", 862.0,  1000, None,           904.0,  None, "PCB 警示族群、持有"),
    # 3481 星宇: 假設 5/21 @40.6 進 (漲停那天)，6/3 收 59.4
    ("3481", "星宇航", "2026-05-21",  40.6,  5000, None,           59.4,   None, "AI 飛機題材、仍持有"),
]

FEE_RATE  = 0.000399  # 手續費單邊
TAX_RATE  = 0.003     # 證交稅 (賣方)


def calc_pnl(entry: float, exit_p: float, shares: int) -> float:
    """計算損益 (含手續費+證交稅)。"""
    buy_cost  = entry  * shares * (1 + FEE_RATE)
    sell_net  = exit_p * shares * (1 - FEE_RATE - TAX_RATE)
    return sell_net - buy_cost


def load_daily_bars(ticker: str, start_date: str, end_date: str = "2026-06-03") -> pd.DataFrame:
    """從 DB 取日線資料。"""
    try:
        with get_conn(_DB, timeout=10) as con:
            rows = con.execute(
                """SELECT trade_date, open, high, low, close, volume, ma10, vol_ma20
                   FROM standard_daily_bar
                   WHERE ticker=? AND trade_date >= ? AND trade_date <= ?
                   ORDER BY trade_date""",
                (ticker, start_date, end_date),
            ).fetchall()
        df = pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close", "volume", "ma10", "vol_ma20"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        return df
    except Exception as e:
        print(f"[WARN] load_daily_bars({ticker}) 失敗: {e}")
        return pd.DataFrame()


def simulate_trade(
    ticker: str,
    name: str,
    entry_date: str,
    entry_price: float,
    shares: int,
    actual_exit_date: Optional[str],
    actual_exit_price: float,
    actual_pnl: Optional[float],
    notes: str,
    verbose: bool = False,
) -> dict:
    """模擬單筆 trade，跑 4 個 detector，回傳結果 dict。"""

    end_ref = actual_exit_date if actual_exit_date else "2026-06-03"
    df = load_daily_bars(ticker, entry_date, end_date="2026-06-03")

    if df.empty:
        return {
            "ticker": ticker, "name": name,
            "entry_date": entry_date, "entry_price": entry_price,
            "actual_exit_date": actual_exit_date, "actual_exit_price": actual_exit_price,
            "actual_pnl": actual_pnl,
            "detectors": {}, "notes": notes, "error": "無日線資料",
        }

    # 只取進場後的 bars
    df = df[df["trade_date"] >= entry_date].reset_index(drop=True)
    if df.empty:
        return {"ticker": ticker, "name": name, "error": "進場後無資料"}

    detector_exits: dict[str, dict] = {}
    milestones_hit: set = set()

    for i in range(1, len(df)):  # 從第 2 根開始 (第 1 根是進場日)
        today_row = df.iloc[:i+1]  # 含當日的累積 df
        today = df.iloc[i]
        trade_date_str = str(today["trade_date"])

        # 如果已過 actual exit date，不再模擬
        if actual_exit_date and trade_date_str > actual_exit_date:
            break

        current_close = float(today["close"])
        current_open  = float(today["open"])
        prev_close    = float(df.iloc[i-1]["close"])

        # ── Detector 1: 掀傘 ──────────────────────────────────────────────
        if "掀傘" not in detector_exits:
            r = check_umbrella_exit_daily(today_row, entry_price)
            if r["triggered"]:
                pnl = calc_pnl(entry_price, current_close, shares)
                detector_exits["掀傘"] = {
                    "date": trade_date_str,
                    "price": current_close,
                    "pnl": pnl,
                    "reason": r["reason"],
                }
                if verbose:
                    print(f"  [{ticker}] 🌂 掀傘 @ {trade_date_str} ${current_close:.2f} PNL={pnl:+.0f}")

        # ── Detector 2: 高檔長黑 K ────────────────────────────────────────
        if "高檔長黑" not in detector_exits:
            r = check_high_long_black(today_row)
            if r["triggered"]:
                pnl = calc_pnl(entry_price, current_close, shares)
                detector_exits["高檔長黑"] = {
                    "date": trade_date_str,
                    "price": current_close,
                    "pnl": pnl,
                    "reason": r["reason"],
                }
                if verbose:
                    print(f"  [{ticker}] 🦘 高檔長黑 @ {trade_date_str} ${current_close:.2f} PNL={pnl:+.0f}")

        # ── Detector 3: 分批停利里程碑 ────────────────────────────────────
        r = check_profit_milestone(current_close, entry_price, milestones_hit)
        if r["triggered"]:
            key = r["milestone_key"]
            milestones_hit.add(key)
            if key not in detector_exits:
                partial_shares = shares // 3
                pnl = calc_pnl(entry_price, current_close, partial_shares)
                detector_exits[key] = {
                    "date": trade_date_str,
                    "price": current_close,
                    "pnl_partial": pnl,  # 1/3 倉位
                    "reason": r["reason"],
                    "action": r["action"],
                }
                if verbose:
                    print(f"  [{ticker}] 💰 {key} @ {trade_date_str} ${current_close:.2f} (1/3={partial_shares}股 PNL={pnl:+.0f})")

        # ── Detector 4: 隔日跳空大跌 ─────────────────────────────────────
        if "隔日急殺" not in detector_exits:
            r = check_gap_down_emergency(current_open, prev_close)
            if r["triggered"] and r["level"] in ("emergency", "warning"):
                pnl = calc_pnl(entry_price, current_open, shares)
                detector_exits["隔日急殺"] = {
                    "date": trade_date_str,
                    "price": current_open,
                    "pnl": pnl,
                    "reason": r["reason"],
                    "level": r["level"],
                }
                if verbose:
                    print(f"  [{ticker}] 📉 隔日急殺 @ {trade_date_str} ${current_open:.2f} PNL={pnl:+.0f} [{r['level']}]")

    # 計算 user 實際損益
    if actual_pnl is None:
        user_pnl = calc_pnl(entry_price, actual_exit_price, shares)
    else:
        user_pnl = actual_pnl

    return {
        "ticker": ticker,
        "name": name,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "shares": shares,
        "actual_exit_date": actual_exit_date or "仍持有",
        "actual_exit_price": actual_exit_price,
        "user_pnl": user_pnl,
        "detectors": detector_exits,
        "notes": notes,
    }


def format_pnl(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:+,.0f}"


def run_backtest(verbose: bool = False) -> None:
    print("=" * 80)
    print("  Phase 4 出場 Detector Backtest — 真實交易紀錄 (2026-05-19 ~ 2026-06-03)")
    print("=" * 80)
    print()

    results = []
    for trade in REAL_TRADES:
        (ticker, name, entry_date, entry_price, shares,
         actual_exit_date, actual_exit_price, actual_pnl, notes) = trade

        if verbose:
            print(f"\n[{ticker} {name}] 進 {entry_date} @${entry_price:.2f} ×{shares}")

        r = simulate_trade(
            ticker, name, entry_date, entry_price, shares,
            actual_exit_date, actual_exit_price, actual_pnl, notes, verbose=verbose,
        )
        results.append(r)

    # ── 輸出對比表 ──────────────────────────────────────────────────────────
    print("\n" + "─" * 120)
    print(f"{'Ticker':<6}{'名稱':<8}{'進場日':<12}{'進場價':>7}  "
          f"{'User出場':>12}  {'User PNL':>10}  "
          f"{'掀傘出場':>12}  {'掀傘PNL':>9}  "
          f"{'高黑出場':>12}  {'高黑PNL':>9}  "
          f"{'急殺出場':>12}  {'急殺PNL':>9}")
    print("─" * 120)

    total_user_pnl = 0.0
    total_umbrella_pnl = 0.0
    total_high_black_pnl = 0.0
    total_gap_pnl = 0.0

    umbrella_triggered = 0
    high_black_triggered = 0
    gap_triggered = 0
    milestone_10_triggered = 0
    milestone_20_triggered = 0
    milestone_30_triggered = 0

    umbrella_delta_list = []
    high_black_delta_list = []
    gap_delta_list = []

    for r in results:
        if "error" in r:
            print(f"{'':6} {r.get('name','?'):<8} ⚠ {r.get('error','')}")
            continue

        user_pnl = r.get("user_pnl", 0.0) or 0.0
        dets = r.get("detectors", {})

        umbrella  = dets.get("掀傘")
        high_blk  = dets.get("高檔長黑")
        gap_down  = dets.get("隔日急殺")

        u_date  = umbrella["date"]  if umbrella  else "未觸發"
        u_pnl   = umbrella["pnl"]   if umbrella  else None
        h_date  = high_blk["date"]  if high_blk  else "未觸發"
        h_pnl   = high_blk["pnl"]   if high_blk  else None
        g_date  = gap_down["date"]  if gap_down  else "未觸發"
        g_pnl   = gap_down["pnl"]   if gap_down  else None

        actual_exit_str = r["actual_exit_date"]
        if actual_exit_str != "仍持有":
            actual_exit_str = f"{actual_exit_str} ${r['actual_exit_price']:.0f}"

        print(f"{r['ticker']:<6}{r['name']:<8}{r['entry_date']:<12}{r['entry_price']:>7.2f}  "
              f"{actual_exit_str:>12}  {format_pnl(user_pnl):>10}  "
              f"{u_date:>12}  {format_pnl(u_pnl):>9}  "
              f"{h_date:>12}  {format_pnl(h_pnl):>9}  "
              f"{g_date:>12}  {format_pnl(g_pnl):>9}")

        total_user_pnl += user_pnl
        if umbrella:
            umbrella_triggered += 1
            total_umbrella_pnl += u_pnl or 0.0
            umbrella_delta_list.append((u_pnl or 0.0) - user_pnl)
        if high_blk:
            high_black_triggered += 1
            total_high_black_pnl += h_pnl or 0.0
            high_black_delta_list.append((h_pnl or 0.0) - user_pnl)
        if gap_down:
            gap_triggered += 1
            total_gap_pnl += g_pnl or 0.0
            gap_delta_list.append((g_pnl or 0.0) - user_pnl)

        # 里程碑計數
        if "分批停利_10%" in dets: milestone_10_triggered += 1
        if "分批停利_20%" in dets: milestone_20_triggered += 1
        if "分批停利_30%" in dets: milestone_30_triggered += 1

    print("─" * 120)
    print(f"\n總計 User PNL: {total_user_pnl:+,.0f}")

    # ── 統計摘要 ────────────────────────────────────────────────────────────
    n = len([r for r in results if "error" not in r])
    print(f"\n{'─'*60}")
    print(f"  分析筆數: {n} 筆真實 trade")
    print()
    print(f"  🌂 掀傘:    觸發 {umbrella_triggered}/{n} 次")
    if umbrella_delta_list:
        avg_d = sum(umbrella_delta_list) / len(umbrella_delta_list)
        print(f"             平均 Δ PNL vs User: {avg_d:+,.0f}  "
              f"(正=比User更好)")
    print()
    print(f"  🦘 高檔長黑: 觸發 {high_black_triggered}/{n} 次")
    if high_black_delta_list:
        avg_d = sum(high_black_delta_list) / len(high_black_delta_list)
        print(f"             平均 Δ PNL vs User: {avg_d:+,.0f}")
    print()
    print(f"  💰 分批停利: +10% 觸發 {milestone_10_triggered} / +20% 觸發 {milestone_20_triggered} / +30% 觸發 {milestone_30_triggered}")
    print()
    print(f"  📉 隔日急殺: 觸發 {gap_triggered}/{n} 次")
    if gap_delta_list:
        avg_d = sum(gap_delta_list) / len(gap_delta_list)
        print(f"             平均 Δ PNL vs User: {avg_d:+,.0f}")

    # ── 重要案例點評 ────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  重要案例點評:")
    _print_case_notes(results)

    print()


def _print_case_notes(results: list[dict]) -> None:
    """針對特殊案例輸出人工點評。"""
    case_map = {r["ticker"]: r for r in results if "error" not in r}

    # 3016 嘉晶 — 急殺
    r3016 = case_map.get("3016")
    if r3016:
        gap = r3016["detectors"].get("隔日急殺")
        if gap:
            actual_pnl = r3016.get("user_pnl", -21388)
            delta = gap["pnl"] - actual_pnl
            print(f"  3016 嘉晶: 若 📉 急殺 Detector 觸發 @ {gap['date']} ${gap['price']:.2f}")
            print(f"    → User 出場 PNL {actual_pnl:+,.0f}  |  Detector 出場 PNL {gap['pnl']:+,.0f}  |  Δ {delta:+,.0f}")
            print(f"    → 嘉晶案: 試撮 FOMO 9:00-9:05 進場 = 違紀 (無 detector 能救)。急殺偵測需先有合法進場。")
        else:
            print(f"  3016 嘉晶: 急殺 Detector 未觸發 (進場當天即損失、無觀察期)")

    # 3149 正達 — 高檔長黑
    r3149 = case_map.get("3149")
    if r3149:
        hb = r3149["detectors"].get("高檔長黑")
        user_pnl = r3149.get("user_pnl", 23036)
        if hb:
            delta = hb["pnl"] - user_pnl
            print(f"  3149 正達: 若 🦘 高檔長黑 @ {hb['date']} ${hb['price']:.2f}")
            print(f"    → User {user_pnl:+,.0f}  |  Detector {hb['pnl']:+,.0f}  |  Δ {delta:+,.0f}")
        else:
            print(f"  3149 正達: 高檔長黑 Detector 未觸發 → 確認 user 5/28 出場時機合理")

    # 2464 盟立 — 掀傘 / 分批停利
    r2464 = case_map.get("2464")
    if r2464:
        umb = r2464["detectors"].get("掀傘")
        m30 = r2464["detectors"].get("分批停利_30%")
        user_pnl = r2464.get("user_pnl", 85185)
        if umb:
            delta = umb["pnl"] - user_pnl
            print(f"  2464 盟立: 🌂 掀傘 @ {umb['date']} ${umb['price']:.2f}")
            print(f"    → User {user_pnl:+,.0f}  |  Detector {umb['pnl']:+,.0f}  |  Δ {delta:+,.0f}")
        if m30:
            print(f"    → 💰 +30% 里程碑觸發 @ {m30['date']} ${m30['price']:.2f}")

    # 6285 啟碁 — 高檔長黑 / 掀傘
    r6285 = case_map.get("6285")
    if r6285:
        hb  = r6285["detectors"].get("高檔長黑")
        umb = r6285["detectors"].get("掀傘")
        user_pnl = r6285.get("user_pnl", -6705)
        if hb:
            delta = hb["pnl"] - user_pnl
            print(f"  6285 啟碁: 🦘 高檔長黑 @ {hb['date']} ${hb['price']:.2f}")
            print(f"    → User {user_pnl:+,.0f}  |  Detector {hb['pnl']:+,.0f}  |  Δ {delta:+,.0f}")
        elif umb:
            delta = umb["pnl"] - user_pnl
            print(f"  6285 啟碁: 🌂 掀傘 @ {umb['date']} ${umb['price']:.2f}")
            print(f"    → User {user_pnl:+,.0f}  |  Detector {umb['pnl']:+,.0f}  |  Δ {delta:+,.0f}")

    # 1605 華新 — 分批停利
    r1605 = case_map.get("1605")
    if r1605:
        m10 = r1605["detectors"].get("分批停利_10%")
        if m10:
            print(f"  1605 華新: 💰 +10% 里程碑 @ {m10['date']} ${m10['price']:.2f} → 建議鎖 1/3")
            print(f"    → 進場 $40.1，{m10['date']} 達 ${m10['price']:.2f} (+{(m10['price']/40.1-1)*100:.1f}%)，建議部分停利")


def main():
    p = argparse.ArgumentParser(description="Phase 4 出場 Detector Backtest")
    p.add_argument("--verbose", "-v", action="store_true", help="詳細輸出每個 trigger")
    args = p.parse_args()
    run_backtest(verbose=args.verbose)


if __name__ == "__main__":
    main()
