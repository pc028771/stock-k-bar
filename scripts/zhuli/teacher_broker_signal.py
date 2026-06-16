"""自動偵測老師主力分點訊號（管錢哥/站前哥/永豐金等）.

不靠手動 line_chat 更新、只用 FinMind TaiwanStockTradingDailyReport.

Public API:
    teacher_broker_5d(ticker, target_date) -> dict
        {"net_lots": int, "details": list, "score": int, "strong": bool}

策略（與 [[reference_broker_aliases]] 對齊）：
    - 站前哥 = 凱基證券 站前分公司
    - 管錢哥 = 元大證券 館前分公司（含元大證 9800/9805 系列）
    - 永豐金惠利 = 永豐金 惠利分公司
    - 永豐金戰隊 = 永豐金 潮州/屏東 + 台星屏東

評分（max +5）：
    +2 任一老師分點 5d 累計淨買 ≥ 1000 張
    +1 累計 500-999 張
    +1 多個老師分點同步累買（≥ 2 個分點都淨買）
    +1 最近 1-2 日才大量加碼（≥ 500 張在最近 2 日）
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

_CACHE_DIR = Path.home() / ".zhuli_cache" / "broker"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 老師分點 patterns（match against securities_trader name）
# Tier 1 = 特別被老師說「很強」（管錢哥、站前哥）
# Tier 2 = 老師說「厲害」（永豐金惠利、永豐金戰隊）
TEACHER_BROKERS_TIER1 = {
    "管錢哥（元大館前）": [r"元大.*館前"],
    "站前哥（凱基站前）": [r"凱基.*站前"],
    "凱基-信義（波段大戶）": [r"凱基.*信義"],  # 6/9 加入、ch9-1 老師波段大戶清單 + ch1 2486 案例
}
TEACHER_BROKERS_TIER2 = {
    "永豐金惠利": [r"永豐.*惠利"],
    "永豐金潮州": [r"永豐.*潮州"],
    "永豐金屏東": [r"永豐.*屏東"],
    "台新屏東": [r"台新.*屏東"],
}
# 合併供 _match_teacher_broker 使用
TEACHER_BROKERS = {**TEACHER_BROKERS_TIER1, **TEACHER_BROKERS_TIER2}


def _match_teacher_broker(name: str) -> str | None:
    for label, patterns in TEACHER_BROKERS.items():
        for p in patterns:
            if re.search(p, name):
                return label
    return None


def _fetch_broker_daily(ticker: str, date_str: str) -> list[dict]:
    """單日 broker raw fetch、含 disk cache。回傳 list of {trader, buy, sell}.

    2026-06-16: 改用 common/finmind_client (quota-aware + drain)。
    """
    cache = _CACHE_DIR / f"{ticker}_{date_str}.json"
    if cache.exists():
        with cache.open() as f:
            return json.load(f)

    _common_parent = Path(__file__).parent.parent
    if str(_common_parent) not in sys.path:
        sys.path.insert(0, str(_common_parent))
    from common.finmind_client import get_client  # type: ignore
    df = get_client().fetch_dataset(
        dataset="TaiwanStockTradingDailyReport",
        data_id=ticker,
        start_date=date_str,
        bypass_cache=True,
    )
    data = df.to_dict(orient="records") if not df.empty else []
    with cache.open("w") as f:
        json.dump(data, f)
    return data


def _trading_dates_lookback(target_date: str, n: int = 5) -> list[str]:
    """從 target_date 倒推 n 個 weekday（粗略）."""
    out = []
    d = date.fromisoformat(target_date)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


FOREIGN_PATTERNS = [
    r"瑞銀", r"美商高盛|高盛", r"美林", r"摩根大通", r"台灣摩根|摩根",
    r"野村", r"麥格理", r"花旗", r"匯豐", r"渣打", r"港商", r"巴黎",
    r"瑞士信貸|瑞信", r"美商|美林", r"亞洲",
]


def _is_foreign(name: str) -> bool:
    return any(re.search(p, name) for p in FOREIGN_PATTERNS)


def main_force_5d(ticker: str, target_date: str) -> dict:
    """偵測過去 5 個交易日全方位主力訊號 (老師分點 + 外資集中 + 異常單一分點).

    Returns dict with 3-tier signal detection.
    """
    dates = _trading_dates_lookback(target_date, 5)
    tier1_net = defaultdict(int)  # 管錢哥/站前哥
    tier2_net = defaultdict(int)  # 永豐金惠利/戰隊
    foreign_broker_net = defaultdict(int)
    all_broker_net = defaultdict(int)

    for d in dates:
        try:
            data = _fetch_broker_daily(ticker, d)
        except Exception:
            continue
        for row in data:
            name = row.get("securities_trader", "")
            buy = row.get("buy", 0)
            sell = row.get("sell", 0)
            net = (buy - sell) // 1000  # 張
            all_broker_net[name] += net

            # Tier 1 (強)
            for label, patterns in TEACHER_BROKERS_TIER1.items():
                if any(re.search(p, name) for p in patterns):
                    tier1_net[label] += net
                    break
            else:
                # Tier 2 (中)
                for label, patterns in TEACHER_BROKERS_TIER2.items():
                    if any(re.search(p, name) for p in patterns):
                        tier2_net[label] += net
                        break

            if _is_foreign(name):
                foreign_broker_net[name] += net

    tier1_total = sum(tier1_net.values())
    tier2_total = sum(tier2_net.values())
    teacher_total = tier1_total + tier2_total  # 整體合計（兼容舊欄位）
    teacher_active = sum(1 for v in {**tier1_net, **tier2_net}.values() if v >= 100)
    foreign_total = sum(foreign_broker_net.values())
    foreign_active = sum(1 for v in foreign_broker_net.values() if v >= 200)

    # 異常單一大買分點 (非老師、非外資、5d 累買 ≥ 500 張)
    standalone_anomalies = [
        (n, v) for n, v in all_broker_net.items()
        if v >= 500
        and not _match_teacher_broker(n)
        and not _is_foreign(n)
    ]
    standalone_anomalies.sort(key=lambda x: -x[1])

    # 評分（tier-based）：
    score = 0
    # Tier 1 (管錢哥/站前哥) — 強訊號
    if tier1_total >= 2000: score += 5  # 大買 ≥ 2k 張
    elif tier1_total >= 1000: score += 3
    elif tier1_total >= 500: score += 2
    # Tier 2 (永豐金惠利/戰隊) — 中訊號
    if tier2_total >= 1000: score += 2
    elif tier2_total >= 500: score += 1
    # 外資集中（保留、獨立加分）
    if foreign_total >= 5000: score += 2
    elif foreign_total >= 3000: score += 1
    # 單分點異常（保留）
    if len(standalone_anomalies) >= 1 and standalone_anomalies[0][1] >= 2000: score += 1

    return {
        "teacher_broker_net": {**dict(tier1_net), **dict(tier2_net)},
        "tier1_net": dict(tier1_net),
        "tier2_net": dict(tier2_net),
        "tier1_total": tier1_total,
        "tier2_total": tier2_total,
        "teacher_total": teacher_total,
        "foreign_broker_net": dict(foreign_broker_net),
        "foreign_total": foreign_total,
        "foreign_active": foreign_active,
        "standalone_anomalies": standalone_anomalies[:3],
        "recent_2d_teacher": 0,  # 已 deprecated
        "recent_2d_foreign": 0,
        "score": score,
        "strong": score >= 4,
    }


def teacher_broker_5d(ticker: str, target_date: str) -> dict:
    """偵測過去 5 個交易日老師分點動作.

    Returns:
        {
          "broker_net": {"管錢哥": net_lots, ...},
          "total_net_lots": int,    # 全部老師分點合計
          "active_brokers": int,    # 有淨買 ≥ 100 張的老師分點數
          "recent_2d_net": int,     # 最近 2 日淨買（檢測「快速加碼」）
          "score": int (0-5),
          "strong": bool (score ≥ 3)
        }
    """
    dates = _trading_dates_lookback(target_date, 5)
    broker_net = defaultdict(int)
    recent_2d_net = 0

    for d in dates:
        try:
            data = _fetch_broker_daily(ticker, d)
        except Exception:
            continue
        for row in data:
            name = row.get("securities_trader", "")
            label = _match_teacher_broker(name)
            if not label:
                continue
            buy = row.get("buy", 0)
            sell = row.get("sell", 0)
            net = (buy - sell) // 1000  # 張
            broker_net[label] += net
            if d in dates[-2:]:
                recent_2d_net += net

    total = sum(broker_net.values())
    active = sum(1 for v in broker_net.values() if v >= 100)

    score = 0
    if total >= 1000: score += 2
    elif total >= 500: score += 1
    if active >= 2: score += 1
    if recent_2d_net >= 500: score += 1

    return {
        "broker_net": dict(broker_net),
        "total_net_lots": total,
        "active_brokers": active,
        "recent_2d_net": recent_2d_net,
        "score": score,
        "strong": score >= 3,
    }


def main():
    import sys
    if len(sys.argv) < 3:
        print("Usage: teacher_broker_signal.py <ticker> <date>")
        sys.exit(1)
    ticker, d = sys.argv[1], sys.argv[2]
    r = main_force_5d(ticker, d)
    print(f"\n=== {ticker} 主力 5d 訊號 (截至 {d}) ===")
    print(f"Layer 1 老師分點: {r['teacher_total']:+,} 張 / 近2d {r['recent_2d_teacher']:+,}")
    for k, v in sorted(r['teacher_broker_net'].items(), key=lambda x: -x[1])[:3]:
        if abs(v) >= 50: print(f"  {k}: {v:+,}")
    print(f"Layer 2 外資集中: {r['foreign_total']:+,} 張 / 活躍 {r['foreign_active']} 家")
    fo = sorted(r['foreign_broker_net'].items(), key=lambda x: -x[1])[:3]
    for k, v in fo:
        if abs(v) >= 100: print(f"  {k}: {v:+,}")
    print(f"Layer 3 異常單分點: {len(r['standalone_anomalies'])} 家")
    for k, v in r['standalone_anomalies'][:3]:
        print(f"  {k}: {v:+,}")
    print(f"\n總分: {r['score']} {'⭐ STRONG' if r['strong'] else ''}")


if __name__ == "__main__":
    main()
