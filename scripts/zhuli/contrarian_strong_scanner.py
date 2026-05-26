"""逆勢強勢 scanner — 抓「老師近期 mention + 打擊區 + 起漲特徵」的候選.

設計動機：5/26 大盤跌 -0.25%、但 18 檔老師清單漲停。回溯 5/25 收盤特徵發現
「距 MA10 ≤ +10% + 紅 K 收最高 + MA5>MA10 + 老師近 7-14 天 mention」是可
辨識的早期訊號（4526/2344/2481/8996 等都符合）。

非課程框架、僅是「老師清單 + 健康打擊區」的整合篩選器、不發明新的進場條件。

Usage:
    python scripts/zhuli/contrarian_strong_scanner.py [--date YYYY-MM-DD] [--min-score 5]

Output:
    /tmp/contrarian_strong_<DATE>.md   markdown 報告
    Stdout: score >= min-score 的候選

評分（總分 0-12）：
    機械條件 (max 7):
      +2 距 MA10 ≤ +10%（健康打擊區、課程心法 +15% 紅線之內）
      +1 距 MA10 +10~15%（邊緣）
      +2 量比 ≥ 1.5x（vs 過去 5 日均、不含當日）
      +1 量比 1.0~1.5x
      +1 紅 K 收最高（收盤位置 ≥ 80% 高低）
      +1 MA5 > MA10（短均向上）
      +1 5d 漲幅 ≤ 20%（未過熱）

    老師訊號 (max 3):
      +2 近 7 天 mention
      +1 近 8-14 天 mention
      +1 近 14 天 mention ≥ 2 次

    主力分點 (max 2):
      +2 broker_activity_notes 有當週老師分點大買註記

判讀：
    ≥7 ⭐⭐⭐ 高信心、可下 3-5 張
    5-6 ⭐⭐ 中信心、1-2 張試水
    3-4 ⭐  低信心、觀察
    <3  跳過
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
_SYS = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_DB = Path.home() / ".four_seasons" / "data.sqlite"
_PICKS = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"
_BROKER_NOTES = _REPO / "docs" / "主力大課程" / "broker_activity_notes.md"

try:
    from zhuli.teacher_broker_signal import main_force_5d
    HAS_BROKER = True
except Exception:
    HAS_BROKER = False


def load_picks() -> dict:
    return {t: info for t, info in json.load(open(_PICKS)).items() if not t.startswith("_")}


def mention_features(info: dict, target_date: str) -> dict:
    """回傳 mention 相關特徵 dict."""
    mentions = info.get("mentions", [])
    if not mentions:
        return {"recent_7d": False, "recent_14d": False, "mention_14d_count": 0, "last_days": 999}

    ref = date.fromisoformat(target_date)
    days_list = []
    for m in mentions:
        try:
            d = date.fromisoformat(m["date"])
            if d <= ref:
                days_list.append((ref - d).days)
        except (KeyError, ValueError):
            continue
    if not days_list:
        return {"recent_7d": False, "recent_14d": False, "mention_14d_count": 0, "last_days": 999}

    last_days = min(days_list)
    cnt14 = sum(1 for d in days_list if d <= 14)
    return {
        "recent_7d": last_days <= 7,
        "recent_14d": 7 < last_days <= 14,
        "mention_14d_count": cnt14,
        "last_days": last_days,
    }


def broker_strong_buy(ticker: str) -> bool:
    """檢查 broker_activity_notes 是否有此 ticker 的當週重大買盤註記."""
    if not _BROKER_NOTES.exists():
        return False
    txt = _BROKER_NOTES.read_text(encoding="utf-8")
    # 簡單 heuristic：ticker 後 100 字內出現「大買」「重大買盤」「累買」
    import re
    for m in re.finditer(rf"\b{ticker}\b", txt):
        window = txt[m.end():m.end() + 200]
        if any(kw in window for kw in ("大買", "重大買盤", "累買", "尾盤大量", "管錢哥", "站前哥")):
            return True
    return False


def get_bar_features(conn: sqlite3.Connection, ticker: str, target_date: str) -> dict | None:
    """取 ticker 在 target_date 的 K 棒特徵 + 過去 5 日量均."""
    rows = conn.execute(
        """SELECT trade_date, open, high, low, close, volume, ma5, ma10, ma20
           FROM standard_daily_bar
           WHERE ticker=? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT 10""",
        (ticker, target_date),
    ).fetchall()
    if not rows:
        return None
    d, o, h, l, c, v, m5, m10, m20 = rows[0]
    if d != target_date:
        return None  # target_date 沒資料、跳過

    if not (m10 and m5):
        return None

    bias10 = (c - m10) / m10 * 100
    bias20 = (c - m20) / m20 * 100 if m20 else 0
    past5 = sum(r[5] for r in rows[1:6]) / 5 if len(rows) >= 6 else v
    vol_ratio = v / past5 if past5 else 1.0
    red_high = ((c - l) / (h - l) * 100) >= 80 if h > l else False
    c5 = rows[5][4] if len(rows) >= 6 else c
    ret5 = (c - c5) / c5 * 100 if c5 else 0

    return {
        "close": c, "ma5": m5, "ma10": m10, "ma20": m20,
        "bias10": bias10, "bias20": bias20,
        "vol_ratio": vol_ratio,
        "red_high": red_high,
        "ret5": ret5,
        "ma5_above_ma10": m5 > m10,
    }


def score_candidate(bar: dict, mention: dict, broker_strong: bool) -> tuple[int, list[str]]:
    """評分並回傳 (score, 命中條件 list)."""
    score = 0
    hits = []

    # 距 MA10 — soft scoring（不 hard gate、極端才扣分）
    b = bar["bias10"]
    if b <= 5:
        score += 3; hits.append(f"最佳區+3({b:+.1f}%)")
    elif b <= 10:
        score += 2; hits.append(f"打擊區+2({b:+.1f}%)")
    elif b <= 15:
        score += 1; hits.append(f"邊緣+1({b:+.1f}%)")
    elif b <= 20:
        hits.append(f"中性({b:+.1f}%)")
    elif b <= 25:
        score -= 1; hits.append(f"追高-1({b:+.1f}%)")
    else:
        score -= 2; hits.append(f"嚴重追高-2({b:+.1f}%)")

    # 量比
    if bar["vol_ratio"] >= 1.5:
        score += 2; hits.append("量比≥1.5x+2")
    elif bar["vol_ratio"] >= 1.0:
        score += 1; hits.append("量比≥1.0x+1")

    # 紅K 收最高
    if bar["red_high"]:
        score += 1; hits.append("紅高+1")

    # MA5 > MA10
    if bar["ma5_above_ma10"]:
        score += 1; hits.append("均向上+1")

    # 未過熱
    if bar["ret5"] <= 20:
        score += 1; hits.append("未過熱+1")

    # 老師 mention
    if mention["recent_7d"]:
        score += 2; hits.append(f"近7d({mention['last_days']}d前)+2")
    elif mention["recent_14d"]:
        score += 1; hits.append(f"近14d({mention['last_days']}d前)+1")
    if mention["mention_14d_count"] >= 2:
        score += 1; hits.append("頻繁mention+1")

    # 主力分點
    if broker_strong:
        score += 2; hits.append("分點大買+2")

    return score, hits


def run_scan(target_date: str, min_score: int = 5, include_broker: bool = True, broker_top_n: int = 30) -> list[dict]:
    picks = load_picks()
    conn = sqlite3.connect(_DB)
    results = []
    for ticker, info in picks.items():
        bar = get_bar_features(conn, ticker, target_date)
        if not bar:
            continue
        # Hard gate 嚴重追高（>30% 直接剔除、派發區）
        if bar["bias10"] > 30:
            continue
        # 分區標記（gate 在 +15% 老師紅線）
        zone = "🟢可進場" if bar["bias10"] <= 15 else "🟡觀察區" if bar["bias10"] <= 25 else "🔴不碰"
        mention = mention_features(info, target_date)
        if mention["last_days"] > 14:  # 老師近 14 天沒提、跳過
            continue
        broker = broker_strong_buy(ticker)
        score, hits = score_candidate(bar, mention, broker)
        results.append({
            "ticker": ticker,
            "name": info.get("name", "?"),
            "tier": info.get("tier_signal") or "-",
            "sectors": info.get("sectors", []),
            "close": bar["close"],
            "bias10": bar["bias10"],
            "bias20": bar["bias20"],
            "vol_ratio": bar["vol_ratio"],
            "ret5": bar["ret5"],
            "tech_score": score,
            "hits": hits,
            "last_mention_days": mention["last_days"],
            "broker_strong": broker,
            "broker_score": 0,
            "broker_detail": {},
            "score": score,  # combined later
            "zone": zone,
        })
    conn.close()

    # 先依 tech_score 排序、只 enrich top N 的 broker signal（節省 API call）
    results.sort(key=lambda x: -x["tech_score"])
    if include_broker and HAS_BROKER:
        for r in results[:broker_top_n]:
            try:
                bs = main_force_5d(r["ticker"], target_date)
                r["broker_score"] = bs["score"]
                r["broker_detail"] = {
                    "teacher": bs["teacher_total"],
                    "foreign": bs["foreign_total"],
                    "anomaly": len(bs["standalone_anomalies"]),
                }
                r["score"] = r["tech_score"] + bs["score"]
                if bs["strong"]:
                    r["hits"].append(f"主力共振+{bs['score']}")
            except Exception as exc:
                r["hits"].append(f"broker_err:{type(exc).__name__}")

    return sorted(
        [r for r in results if r["score"] >= min_score],
        key=lambda x: (-x["score"], x["bias10"]),
    )


def write_report(target_date: str, results: list[dict], out_path: Path) -> None:
    lines = [
        f"# 逆勢強勢 scanner — {target_date} 收盤後（隔日開盤候選）",
        "",
        f"> 篩出條件：teacher_picks 近 14 天 mention + 距 MA10 ≤ +15%",
        f"> 評分：機械條件(7) + 老師訊號(3) + 主力分點(2) = max 12",
        f"> 判讀：≥7 ⭐⭐⭐ 重壓 / 5-6 ⭐⭐ 試水 / 3-4 ⭐ 觀察",
        "",
        f"## 候選清單（共 {len(results)} 檔）",
        "",
        f"| 排名 | ticker | name | tier | 距MA10 | 量比 | 5d% | 評分 | 命中條件 |",
        f"|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        rating = "⭐⭐⭐" if r["score"] >= 7 else "⭐⭐" if r["score"] >= 5 else "⭐"
        hits_str = " / ".join(r["hits"])
        lines.append(
            f"| {i} | {r['ticker']} | {r['name']} | {r['tier']} | "
            f"{r['bias10']:+.2f}% | {r['vol_ratio']:.2f}x | {r['ret5']:+.1f}% | "
            f"{rating} {r['score']} | {hits_str} |"
        )
    lines += ["", f"產生時間: {datetime.now().isoformat(timespec='seconds')}", ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=str(date.today()), help="目標收盤日 YYYY-MM-DD")
    ap.add_argument("--min-score", type=int, default=5)
    ap.add_argument("--db", default=str(_DB))
    ap.add_argument("--no-broker", action="store_true", help="跳過 broker API call (快速 mode)")
    ap.add_argument("--broker-top-n", type=int, default=30, help="只對 tech_score top N 跑 broker")
    args = ap.parse_args()

    print(f"=== 逆勢強勢 scanner — {args.date} ===\n")
    results = run_scan(args.date, args.min_score, include_broker=not args.no_broker, broker_top_n=args.broker_top_n)

    if not results:
        print("無符合條件的候選")
        return

    # 分區輸出
    zones = {"🟢可進場": [], "🟡觀察區": [], "🔴不碰": []}
    for r in results:
        zones[r["zone"]].append(r)

    for zone_name in ["🟢可進場", "🟡觀察區"]:
        zlist = zones[zone_name]
        if not zlist:
            continue
        print(f"\n=== {zone_name} ({len(zlist)} 檔) ===")
        print(f"{'#':<3}{'tk':<6}{'name':<10}{'tier':<10}{'距MA10':>8}{'量比':>6}{'5d%':>7}{'tech':>5}{'brok':>5}{'total':>6}  {'命中'}")
        print("-" * 140)
        for i, r in enumerate(zlist, 1):
            rating = "⭐⭐⭐" if r["score"] >= 14 else "⭐⭐" if r["score"] >= 10 else "⭐"
            hits_str = " / ".join(r["hits"][-3:])
            print(
                f"{i:<3}{r['ticker']:<6}{r['name']:<10}{r['tier']:<10}"
                f"{r['bias10']:>+7.2f}%{r['vol_ratio']:>5.2f}x{r['ret5']:>+6.1f}%"
                f"{r['tech_score']:>5}{r['broker_score']:>5}{r['score']:>6} {rating}  {hits_str}"
            )

    out = Path("/tmp") / f"contrarian_strong_{args.date}.md"
    write_report(args.date, results, out)
    print(f"\n→ 寫入 {out}")


if __name__ == "__main__":
    main()
