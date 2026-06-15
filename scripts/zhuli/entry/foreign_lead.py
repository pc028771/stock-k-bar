"""foreign_lead entry detector — 主力大老師外資 lead framework.

Course source:
  - 主力大 6/2-6/3 法人籌碼戰略: 「外資選股邏輯」「同向最好」「背離跟外資」
  - 主力大 6/14 直播: 「投信參考度變低」(ETF rebalance)
  - 6/15 user 拍板: deploy for current regime、新趨勢看老師後續課程調整

⚠️ Regime-conditional (per memory feedback_detector_regime_conditional)
  - Backtest 2026-01 ~ 2026-06: WR 70-83% / +14-20% ✅
  - 2024 / 2025 跨年: WR 36-49% ❌ (regime-specific edge)
  - 部署紀律: 走「人工 regime gate」、跟老師大盤判讀

⭐ 進場語意 (2026-06-15 user 校正):
  - detector hit = 自動「漏斗篩選 + 趨勢確認」(條件比老師 Q&A 三條件嚴)
  - 可正常進場 (不只觀察)
  - 對應 memory feedback_5347_add_position_condition 例外:
    跌破成本時、detector confirmed = 加碼條件成立、不用管 +10% 鐵則
  - v12_skip 觸發時降權 (反向警示)

Variants (5 個、不同物理意義):
  v08: 外資連3 + 黑K + 守MA10 (主訊號) — 主力連續吃貨遇洗盤、不破均線
  v06: 外資連3 + 黑K (放寬版) — 主力吃貨中遇洗盤、未必守均線
  v07: 外資連3 + 5d跌3% + 守MA20 (拉回承接) — 主力在拉回時加碼
  v15: 外資連5 + 量2x + 黑K (重押旗標) — 長期吃貨 + 放量洗盤、極稀有
  v12: 反向 skip 警示 — 外資買但投信背離大賣 = 訊號模糊、不進場
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).parent.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB


# ── 流動性 tier 門檻 (foreign_net 單日大買最低張數) ──────────────────

def fg_threshold(vol_ma20_lots: float, mult: float = 1.0) -> int:
    if vol_ma20_lots < 5000:
        return int(200 * mult)
    if vol_ma20_lots < 50000:
        return int(1000 * mult)
    return int(3000 * mult)


# ── Variants 定義 ─────────────────────────────────────────────────

VARIANTS: dict[str, dict] = {
    "v08": dict(
        streak=3, mult=1.0, same_dir=True, black_k=True, ma="ma10",
        decline=None, lmk=-500, vol_min=0, is_reverse=False,
        priority=3, label="⭐⭐⭐ v08 主訊號",
        note="外資連3買 + 黑K + 守MA10 = 主力連續吃貨遇洗盤不破均線",
    ),
    "v06": dict(
        streak=3, mult=1.0, same_dir=True, black_k=True, ma="none",
        decline=None, lmk=-500, vol_min=0, is_reverse=False,
        priority=3, label="⭐⭐ v06 放寬版",
        note="外資連3買 + 黑K = 主力吃貨中遇洗盤、未守均線版",
    ),
    "v07": dict(
        streak=3, mult=1.0, same_dir=True, black_k=False, ma="ma20",
        decline=-3, lmk=-500, vol_min=0, is_reverse=False,
        priority=2, label="🎯 v07 拉回承接",
        note="外資連3 + 5d跌3% + 守MA20 = 主力拉回加碼 (買跌不買漲)",
    ),
    "v15": dict(
        streak=5, mult=2.0, same_dir=True, black_k=True, ma="none",
        decline=None, lmk=-500, vol_min=0, is_reverse=False,
        priority=3, label="🚨 v15 重押旗標",
        note="外資連5 + 量2x + 黑K = 長期吃貨 + 放量洗盤、極稀有強訊號",
    ),
    "v12_skip": dict(
        streak=3, mult=1.0, same_dir=False, black_k=True, ma="ma10",
        decline=None, lmk=-500, vol_min=0, is_reverse=True,
        priority=-1, label="⛔ v12 SKIP 警示",
        note="外資買但投信背離大賣 = 訊號模糊、不進場 (背離反向訊號)",
    ),
}


# ── Core detection ────────────────────────────────────────────────

def _check_variant(
    ts: list[dict], bar: tuple, cfg: dict
) -> Optional[dict]:
    """單一變體條件檢查、回 hit 細節 or None."""
    open_, close_, ma10, ma20, vol_ma20 = bar
    if not close_:
        return None

    vol_ma20_lots = (vol_ma20 or 0) / 1000
    if vol_ma20_lots < cfg["vol_min"]:
        return None

    streak = cfg["streak"]
    if len(ts) < streak + 1:
        return None

    # 1. 外資連 streak 天大買
    thr = fg_threshold(vol_ma20_lots, cfg["mult"])
    tail = ts[-streak:]
    if not all((t["foreign_net"] or 0) > thr for t in tail):
        return None

    # 2. 同向 / 背離 過濾
    sitc_5d = sum(t["sitc_net"] or 0 for t in ts[-5:])
    if cfg["is_reverse"]:
        if sitc_5d >= 0:
            return None
    else:
        if cfg["same_dir"] and sitc_5d <= 0:
            return None

    # 3. 黑 K
    if cfg["black_k"]:
        if not open_ or close_ >= open_:
            return None

    # 4. 守均線
    ma_req = cfg["ma"]
    if ma_req == "ma10":
        if not ma10 or close_ <= ma10:
            return None
    elif ma_req == "ma20":
        if not ma20 or close_ <= ma20:
            return None
    elif ma_req == "either":
        if not ((ma10 and close_ > ma10) or (ma20 and close_ > ma20)):
            return None

    # 5. last-mile kill (近 2 天任一外資大賣 → skip)
    last_mile = ts[-2:]
    if any((t["foreign_net"] or 0) < cfg["lmk"] for t in last_mile):
        return None

    return {
        "foreign_streak_sum": int(sum(t["foreign_net"] or 0 for t in tail)),
        "sitc_5d": int(sitc_5d),
        "vol_ma20_lots": int(vol_ma20_lots),
        "thr": thr,
    }


def detect(
    target_date: str,
    db_path: Path = MAIN_DB,
    variants: Optional[list[str]] = None,
) -> dict[str, list[dict]]:
    """掃描指定日期、回傳各變體命中的 ticker list.

    Args:
        target_date: 'YYYY-MM-DD'
        db_path: DB path
        variants: 限制掃哪些變體、None 全掃

    Returns:
        {variant_id: [{ticker, name, close, ma10, ma20, foreign_streak_sum,
                       sitc_5d, vol_ma20_lots, thr, priority, label, note}, ...]}
    """
    variants_to_run = variants if variants else list(VARIANTS.keys())
    out: dict[str, list[dict]] = {v: [] for v in variants_to_run}

    with get_conn(db_path) as con:
        # 取 target_date 當日所有 ticker 的 bar
        bars = con.execute(
            """SELECT ticker, open, close, ma10, ma20, vol_ma20
               FROM standard_daily_bar
               WHERE trade_date = ? AND close IS NOT NULL""",
            (target_date,),
        ).fetchall()
        bar_map = {b[0]: (b[1], b[2], b[3], b[4], b[5]) for b in bars}

        if not bar_map:
            return out

        # 撈每檔近 15 天 institutional (覆蓋 streak 5 + 5d sitc + 2d last-mile + buffer)
        target_tickers = list(bar_map.keys())
        rows = con.execute(
            f"""SELECT ticker, trade_date, foreign_net, sitc_net
               FROM institutional_investors
               WHERE trade_date <= ? AND trade_date >= date(?, '-15 days')
                 AND ticker IN ({','.join('?' for _ in target_tickers)})
               ORDER BY ticker, trade_date""",
            (target_date, target_date, *target_tickers),
        ).fetchall()
        by_ticker: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_ticker[r[0]].append({
                "trade_date": r[1],
                "foreign_net": r[2],
                "sitc_net": r[3],
            })

        # 對每檔跑各變體
        for tk, ts in by_ticker.items():
            ts.sort(key=lambda x: x["trade_date"])
            if not ts or ts[-1]["trade_date"] != target_date:
                continue
            bar = bar_map.get(tk)
            if not bar:
                continue

            for vid in variants_to_run:
                cfg = VARIANTS[vid]
                hit = _check_variant(ts, bar, cfg)
                if hit:
                    # 5d 跌幅 condition (v07)
                    if cfg["decline"] is not None:
                        bars5 = con.execute(
                            """SELECT close FROM standard_daily_bar
                               WHERE ticker=? AND trade_date <= ?
                               ORDER BY trade_date DESC LIMIT 6""",
                            (tk, target_date),
                        ).fetchall()
                        if len(bars5) < 6 or not bars5[5][0]:
                            continue
                        ret_5d = (bars5[0][0] - bars5[5][0]) / bars5[5][0] * 100
                        if ret_5d > cfg["decline"]:
                            continue

                    # name
                    nm = con.execute(
                        "SELECT stock_name FROM stock_info WHERE ticker=? LIMIT 1",
                        (tk,),
                    ).fetchone()
                    out[vid].append({
                        "ticker": tk,
                        "name": nm[0] if nm else "",
                        "close": bar[1],
                        "ma10": bar[2],
                        "ma20": bar[3],
                        "priority": cfg["priority"],
                        "label": cfg["label"],
                        "note": cfg["note"],
                        **hit,
                    })

    return out


if __name__ == "__main__":
    import json
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--variants", nargs="*", default=None)
    args = p.parse_args()

    result = detect(args.date, variants=args.variants)
    for vid, items in result.items():
        cfg = VARIANTS[vid]
        print(f"\n{cfg['label']} ({vid}): {len(items)} 檔")
        for it in items[:20]:
            print(f"  {it['ticker']:>6} {it['name']:<12} close={it['close']:>7.2f} "
                  f"fg_streak={it['foreign_streak_sum']:>8} sitc_5d={it['sitc_5d']:>7}")
