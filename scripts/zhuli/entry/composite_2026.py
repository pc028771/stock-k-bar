"""composite_2026 detector — 4 條 stack 超嚴格組合、2026 regime specialized.

⚠️ Regime-specialized (per memory feedback_detector_regime_conditional):
  - 設計專為 2026 H1 強多升 / 整理盤、未驗證 2024/2025
  - 出現時 = 高 conviction signal、可直接進 Top3 P3
  - 老師大盤 call regime 變化時 (殺盤期 / 趨勢改變) 自動降權

5 條 stack 物理意義:
  1. **老師 universe** — 老師明示族群 / picks 內、strategic alignment
  2. **籌碼共識** — foreign_lead 任一 (v06/v07/v08/v15) 或 institutional_swing 命中
  3. **大盤 regime gate** — TAIEX 20d return ≥ -10%（排除殺盤期）
  4. **位階不過熱** — 距 MA60 < +30%（避免追飆股末端）
  5. **last-mile 外資不轉空** — 近 2 天外資累計 ≥ -500 張（per memory
     feedback_chip_trend_not_aggregate「last-mile 比 aggregate 重要」、
     避免「籌碼累積但 last-mile 主力撤」假訊號）

物理意義一句話: 「老師明示族群 + 籌碼累積中 + 大盤健康 + 個股仍在合理位階 + 外資 last-mile 沒撤」= 主力共識輪動進場時點。

Backtest 預期: 6/12 整理盤可能 0 hit、強多升段 (4 月) 預期 2-3 檔/週、命中後 hold ~10 天 +5-15%。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).parent.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
from zhuli.entry.foreign_lead import detect as detect_foreign_lead

PICKS_JSON = _REPO / "docs" / "主力大課程" / "teacher_picks_2026.json"
SECTORS_JSON = _REPO / "docs" / "主力大課程" / "teacher_sector_tickers.json"


def load_teacher_universe() -> set[str]:
    """老師 universe (~344 檔) = picks ∪ sectors."""
    universe: set[str] = set()
    if PICKS_JSON.exists():
        picks = json.loads(PICKS_JSON.read_text(encoding="utf-8"))
        universe.update(k for k in picks.keys() if not k.startswith("_"))
    if SECTORS_JSON.exists():
        sectors = json.loads(SECTORS_JSON.read_text(encoding="utf-8"))
        for v in sectors.values():
            if isinstance(v, list):
                universe.update(v)
    return universe


def compute_taiex_20d_ret(con: sqlite3.Connection, target_date: str) -> Optional[float]:
    """TAIEX 20 個交易日報酬 %."""
    rows = con.execute(
        """SELECT close FROM standard_daily_bar
           WHERE ticker='TAIEX' AND trade_date <= ?
             AND close > 0
           ORDER BY trade_date DESC LIMIT 21""",
        (target_date,),
    ).fetchall()
    if len(rows) < 21:
        return None
    return (rows[0][0] - rows[20][0]) / rows[20][0] * 100


def check_inst_swing_hit(
    con: sqlite3.Connection, ticker: str, target_date: str
) -> bool:
    """簡化版 institutional_swing 命中檢查.

    5d 投信買進 > min threshold + 前 30 天乾淨 + MA align (MA5>MA10>MA20).
    用簡化版 (跳過股本 1.5% 換算、用絕對張數)、夠 fire 即可。
    """
    # 5d sitc_net
    sitc_5d_rows = con.execute(
        """SELECT sitc_net FROM institutional_investors
           WHERE ticker=? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT 5""",
        (ticker, target_date),
    ).fetchall()
    if len(sitc_5d_rows) < 5:
        return False
    sitc_5d = sum(r[0] or 0 for r in sitc_5d_rows)
    if sitc_5d < 500:  # 5d 累計買 < 500 張 = 不算累積
        return False

    # 前 30 天乾淨 (sitc_5d <= 0 在 entry 前的窗口、避免追高已啟動)
    prev_30_rows = con.execute(
        """SELECT trade_date, sitc_net FROM institutional_investors
           WHERE ticker=? AND trade_date < ?
             AND trade_date >= date(?, '-35 days')
           ORDER BY trade_date""",
        (ticker, target_date, target_date),
    ).fetchall()
    if len(prev_30_rows) < 20:
        return False
    # check 滾動 5d sitc 累計是否曾 > 500 (代表 entry 前已 fire 過、現在就不算 first)
    nets = [r[1] or 0 for r in prev_30_rows]
    for i in range(len(nets) - 5):
        if sum(nets[i:i + 5]) > 500:
            return False  # 30 天內已 fire 過、不算「剛上榜」

    # MA align
    bar = con.execute(
        """SELECT close, ma5, ma10, ma20 FROM standard_daily_bar
           WHERE ticker=? AND trade_date=?
             AND close > 0 AND ma5 > 0 AND ma10 > 0 AND ma20 > 0""",
        (ticker, target_date),
    ).fetchone()
    if not bar:
        return False
    close_, ma5, ma10, ma20 = bar
    if not (ma5 > ma10 > ma20):
        return False

    return True


def detect(
    target_date: str,
    db_path: Path = MAIN_DB,
) -> list[dict]:
    """掃指定日期、回傳 composite_2026 命中清單.

    每個命中 = 4 條 stack 全過 + 標 metadata.
    """
    teacher_universe = load_teacher_universe()
    if not teacher_universe:
        return []

    with get_conn(db_path) as con:
        # 3. 大盤 regime gate
        taiex_20d = compute_taiex_20d_ret(con, target_date)
        if taiex_20d is None or taiex_20d < -10:
            return []  # 殺盤期、不 fire

        # 2. 籌碼共識：撈 foreign_lead + institutional_swing 命中
        chip_candidates: dict[str, list[str]] = {}  # ticker → [source labels]

        # foreign_lead variants (排除 v12_skip)
        fl_results = detect_foreign_lead(target_date, db_path=db_path)
        for vid, items in fl_results.items():
            if vid == "v12_skip":
                continue
            for it in items:
                tk = it["ticker"]
                chip_candidates.setdefault(tk, []).append(f"foreign_lead_{vid}")

        # institutional_swing
        for tk in teacher_universe:
            if check_inst_swing_hit(con, tk, target_date):
                chip_candidates.setdefault(tk, []).append("institutional_swing")

        # 1+4+5. 老師 universe + 位階不過熱 + last-mile 外資 check
        hits: list[dict] = []
        for tk, sources in chip_candidates.items():
            if tk not in teacher_universe:
                continue

            # 位階不過熱
            bar = con.execute(
                """SELECT close, ma60 FROM standard_daily_bar
                   WHERE ticker=? AND trade_date=?
                     AND close > 0 AND ma60 > 0""",
                (tk, target_date),
            ).fetchone()
            if not bar:
                continue
            close_, ma60 = bar
            dist_ma60 = (close_ - ma60) / ma60 * 100
            if dist_ma60 > 30:
                continue  # 距 MA60 > +30%、過熱

            # ⭐ Condition 5: last-mile 外資不轉空 (近 2 個 trading 日累計 ≥ -500)
            # per memory feedback_chip_trend_not_aggregate
            lm_rows = con.execute(
                """SELECT foreign_net FROM institutional_investors
                   WHERE ticker=? AND trade_date <= ?
                   ORDER BY trade_date DESC LIMIT 2""",
                (tk, target_date),
            ).fetchall()
            foreign_last_2d = sum(r[0] or 0 for r in lm_rows)
            if foreign_last_2d < -500:
                continue  # last-mile 外資撤、訊號模糊、skip

            # name
            nm = con.execute(
                "SELECT stock_name FROM stock_info WHERE ticker=? LIMIT 1", (tk,)
            ).fetchone()

            hits.append({
                "ticker": tk,
                "name": nm[0] if nm else "",
                "close": close_,
                "dist_ma60_pct": round(dist_ma60, 1),
                "sources": sources,
                "n_sources": len(sources),
                "taiex_20d_ret": round(taiex_20d, 1),
                "foreign_last_2d": round(foreign_last_2d, 0),
                "priority": 3,
                "label": "⭐⭐⭐ 2026 Composite",
                "tier_tag": "2026_specialized",
                "note": (
                    f"5 條 stack 全過: 老師 universe + {len(sources)} 籌碼共識 "
                    f"+ TAIEX 20d {taiex_20d:+.1f}% + 距 MA60 {dist_ma60:+.1f}% "
                    f"+ 外資 last-2d {foreign_last_2d:+.0f} 張"
                ),
            })

        # 排序: n_sources desc、dist_ma60 asc (越低越好)
        hits.sort(key=lambda x: (-x["n_sources"], x["dist_ma60_pct"]))
        return hits


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    args = p.parse_args()

    result = detect(args.date)
    print(f"\n=== composite_2026 ({args.date}): {len(result)} 檔 ===")
    for h in result:
        print(f"  {h['ticker']:>6} {h['name']:<10} "
              f"close={h['close']:>7.2f}  距MA60 {h['dist_ma60_pct']:+5.1f}%  "
              f"sources={'+'.join(h['sources'])}")
