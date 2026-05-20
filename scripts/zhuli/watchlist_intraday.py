"""即時觀察 5 檔（明日進場 3 + 持股 2）量價指標。

用法：
    python scripts/zhuli/watchlist_intraday.py

需要環境變數：FUBON_PID / FUBON_API_KEY / FUBON_CREDENTIAL_FILE / FUBON_CREDENTIAL_PWD
（從 .env 自動載入，不要 curl Fubon API）

顯示：
  - 即時 OHLC + 漲跌幅
  - 量能 vs vol_ma20 (即時 vol_ratio)
  - ma20 / bias / slope
  - 各檔課程框架觀察指標即時狀態
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Path setup
_WORKTREE = Path(__file__).parent.parent.parent
_SYS_DIR = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_WORKTREE), str(_WORKTREE / "scripts"), str(_SYS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd

from clients.fubon_client import FubonClient  # noqa: E402
from kline.bars import DEFAULT_DB_PATH  # noqa: E402

# 共識分數 — scanner trades CSV 列表 (排除 G/F 短線時間框架不同)
_CONSENSUS_SCANNERS = {
    "A 大波段":      "swing_breakout_trades.csv",
    "I 投信跟單":     "institutional_swing_trades.csv",
    "J 投信首買":     "institutional_firstbuy_trades.csv",
    "H 窒息量":      "suffocation_trades.csv",
    "M+ 收低開高":   "open_signal_entry_trades.csv",
    "B 旗形":        "pennant_flag_trades.csv",
    "C 反轉形態":    "reversal_breakout_trades.csv",
    "D 布林上軌":    "bbands_upper_break_trades.csv",
    "E 布林回測":    "bollinger_pullback_trades.csv",
}

# 共識分數 → 預期績效 (從 backtest 統計)
_CONSENSUS_LEVELS = {
    1: ("baseline", "EV +1.75% / Hit 19.8% / PF 1.40"),
    2: ("中度確認", "EV +3.35% / Hit 21.8% / PF 1.70"),
    3: ("高度確認", "EV +5.28% / Hit 24.1% / PF 2.10"),
    4: ("極強共識", "EV +11.67% / Hit 31.5% / PF 3.56"),
}

# 5 檔清單：(ticker, name, role, sector)
WATCHLIST = [
    ("2472", "立隆電", "觀察首選", "被動元件"),
    ("6139", "亞翔", "觀察次選", "玻璃基板"),
    ("3663", "鑫科", "觀察攻擊", "玻璃基板"),
    ("8064", "東捷", "持股", "玻璃基板"),
    ("8027", "鈦昇", "持股", "機器人"),
]

# 每檔課程框架觀察指標（觀察/持股 通用 checklist）
CHECKS = {
    "2472": [
        ("守 ma20", lambda r: r["price"] > r["ma20"]),
        ("bias < +25% 健康", lambda r: r["bias"] < 0.25),
        ("ma20_slope 維持 >= +6%", lambda r: r["ma20_slope"] >= 0.06),
        ("未跌破前波低 (~210)", lambda r: r["low"] > 210),  # 估算前波低
    ],
    "6139": [
        ("守 ma20", lambda r: r["price"] > r["ma20"]),
        ("bias < +15% 健康", lambda r: r["bias"] < 0.15),
        ("量能放大 (vr >= 1.5)", lambda r: r["vol_ratio"] >= 1.5),
        ("動能啟動 slope >= +3%", lambda r: r["ma20_slope"] >= 0.03),
    ],
    "3663": [
        ("守 ma20", lambda r: r["price"] > r["ma20"]),
        ("守攻擊 K 半段 ~79.8", lambda r: r["price"] >= 79.8),
        ("ma20_slope 維持上彎 > 0", lambda r: r["ma20_slope"] > 0),
        ("未量縮收黑 (收紅 or 量增)",
         lambda r: r["price"] >= r["open"] or r["vol_ratio"] >= 1.0),
    ],
    "8064": [
        ("守 ma20", lambda r: r["price"] > r["ma20"]),
        ("守 5/15 低 117.5", lambda r: r["low"] > 117.5),
        ("低點走高（今低 > 昨低 130.5）", lambda r: r["low"] >= 130.5),
        ("未大黑K 包覆 (今 C >= 昨 O 130.5)",
         lambda r: r["price"] >= 130.5),
    ],
    "8027": [
        ("守 5/18 關鍵低 231.5", lambda r: r["price"] > 231.5),
        ("守 5/15 關鍵低 242.5", lambda r: r["price"] > 242.5),
        ("未進一步跌破 ma20", lambda r: r["price"] > r["ma20"]),
        ("低點不再下降（今低 > 昨低 257）",
         lambda r: r["low"] >= 257),
    ],
}


def get_db_baseline(db_path: Path, tickers: list[str]) -> dict:
    """取最後一筆 baseline: ma20 / ma60 / ma20_slope / vol_ma20."""
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        result = {}
        for t in tickers:
            cur.execute("""
                SELECT trade_date, close, ma20, ma60, ma20_slope, vol_ma20
                FROM standard_daily_bar
                WHERE ticker=? ORDER BY trade_date DESC LIMIT 1
            """, (t,))
            row = cur.fetchone()
            if row:
                result[t] = {
                    "baseline_date": row[0],
                    "prev_close": row[1],
                    "ma20": row[2] or 0,
                    "ma60": row[3] or 0,
                    "ma20_slope": row[4] or 0,
                    "vol_ma20": row[5] or 0,
                }
            # 取扣抵 close (N 天前) for MA 5/10/20/60
            kickout = {}
            for n in (5, 10, 20, 60):
                cur.execute(
                    "SELECT trade_date, close FROM standard_daily_bar "
                    "WHERE ticker=? ORDER BY trade_date DESC LIMIT 1 OFFSET ?",
                    (t, n),  # OFFSET n = 第 n+1 筆 = N 天前
                )
                r = cur.fetchone()
                if r:
                    kickout[f"ma{n}"] = {"date": r[0], "close": r[1]}
            if t in result:
                result[t]["kickout"] = kickout
        return result


def fetch_intraday(client: FubonClient, ticker: str) -> dict | None:
    snap = client.get_realtime_snapshot(ticker)
    if snap is None:
        return None
    # FubonClient.get_realtime_snapshot 回傳: close/open/high/low/change_price/change_rate/total_volume/total_amount
    return {
        "price": snap.get("close"),
        "open": snap.get("open"),
        "high": snap.get("high"),
        "low": snap.get("low"),
        "change_pct": snap.get("change_rate"),
        "volume": snap.get("total_volume", 0),  # 張
        "amount": snap.get("total_amount", 0),
    }


def fmt_check(label: str, ok: bool) -> str:
    icon = "✓" if ok else "✗"
    color = "  " if ok else "⚠ "
    return f"      {color}{icon} {label}"


def load_consensus_for_tickers(tickers: list[str], lookback_days: int = 30) -> dict:
    """對指定 ticker 列表，從 backtest CSV 找過去 N 天 (從今天往回) scanner 命中.

    Returns dict {ticker: {"score": int, "scanners": [(scanner_name, entry_date), ...]}}
    """
    backtest_dir = _WORKTREE / "data" / "analysis" / "zhuli" / "backtest"
    today = pd.Timestamp(datetime.now().date())
    cutoff = today - pd.Timedelta(days=lookback_days)
    result = {t: {"score": 0, "scanners": []} for t in tickers}

    for sname, fname in _CONSENSUS_SCANNERS.items():
        path = backtest_dir / fname
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, dtype={"ticker": str})
            df["entry_dt"] = pd.to_datetime(df["entry_date"])
            recent = df[(df["entry_dt"] >= cutoff) & (df["entry_dt"] <= today)]
            for t in tickers:
                hits = recent[recent["ticker"] == t]
                if not hits.empty:
                    latest = hits.iloc[-1]
                    result[t]["scanners"].append((sname, latest["entry_dt"].strftime("%Y-%m-%d")))
        except Exception:
            continue

    for t in result:
        result[t]["score"] = len(result[t]["scanners"])
    return result


def rolloff_status(price: float, kickout_close: float, kickout_date: str, ma_label: str) -> tuple[str, str]:
    """扣抵預判亮燈 — 返回 (icon, msg)

    🟢 將上揚 (price > kickout × 1.005)
    🟡 臨界 (差 ±1% 內 = 1-2 天可能轉折)
    🔴 將下彎 (price < kickout × 0.995) ← 課程系統最早期出場警示
    """
    if not kickout_close or kickout_close <= 0:
        return ("--", f"{ma_label} 無扣抵資料")
    diff_pct = (price / kickout_close - 1) * 100
    if diff_pct > 0.5:
        icon = "🟢"
        direction = "將上揚"
    elif diff_pct < -0.5:
        icon = "🔴"
        direction = "將下彎"
    else:
        icon = "🟡"
        direction = "臨界(1-2 天內可能轉折)"
    sign = "+" if diff_pct >= 0 else ""
    return (icon, f"{ma_label} {icon} {direction}  今 {price:.2f} vs 扣抵 {kickout_close:.2f}（{kickout_date}）= {sign}{diff_pct:.2f}%")


def main():
    db_path = DEFAULT_DB_PATH
    tickers = [t[0] for t in WATCHLIST]

    # 1. 從 DB 拿昨日 baseline
    baseline = get_db_baseline(db_path, tickers)

    # 2.5 共識分數 (從 backtest 過去 30 天 scanner 命中累計)
    consensus = load_consensus_for_tickers(tickers, lookback_days=30)

    # 2. Fubon 即時
    print(f"連線 Fubon API ...", end="", flush=True)
    client = FubonClient()
    print(" OK")

    # 3. 大盤 0050
    try:
        mkt = client.get_realtime_snapshot("0050")
        mkt_pct = mkt.get("change_rate", 0)
        mkt_price = mkt.get("close", 0)
    except Exception as e:
        mkt_pct = None
        mkt_price = None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print()
    print("=" * 78)
    print(f"  即時觀察盤面 — {now}")
    if mkt_pct is not None:
        sign = "+" if mkt_pct >= 0 else ""
        print(f"  大盤 0050: {mkt_price}  ({sign}{mkt_pct:.2f}%)")
    print("=" * 78)

    for ticker, name, role, sector in WATCHLIST:
        b = baseline.get(ticker)
        if not b:
            print(f"\n[{role}] {ticker} {name} — 無 DB baseline")
            continue
        live = fetch_intraday(client, ticker)
        if not live or live["price"] is None:
            print(f"\n[{role}] {ticker} {name} — 即時資料失敗")
            continue

        # 計算衍生
        price = live["price"]
        bias = (price / b["ma20"] - 1) if b["ma20"] else 0
        vol_ratio = (live["volume"] / b["vol_ma20"]) if b["vol_ma20"] else 0
        vs_prev = (price / b["prev_close"] - 1) * 100 if b["prev_close"] else 0
        rs = vs_prev - (mkt_pct or 0)  # vs 大盤 超額

        row = {
            "price": price, "open": live["open"], "high": live["high"], "low": live["low"],
            "ma20": b["ma20"], "ma60": b["ma60"],
            "ma20_slope": b["ma20_slope"],
            "bias": bias, "vol_ratio": vol_ratio,
        }

        sign = "+" if vs_prev >= 0 else ""
        print(f"\n[{role}] {ticker} {name} ({sector})")
        print(f"  即時 {price:>7.2f}  ({sign}{vs_prev:.2f}% vs 昨收 {b['prev_close']:.2f})  "
              f"超額 RS {rs:+.2f}%")
        print(f"  OHL  O:{live['open']:.2f}  H:{live['high']:.2f}  L:{live['low']:.2f}")
        print(f"  量能  {live['volume']:>10,} 張  (vr {vol_ratio:.2f} vs vol_ma20)")
        print(f"  MA20  {b['ma20']:>7.2f}  bias {bias*100:+.1f}%  "
              f"slope {b['ma20_slope']*100:+.1f}%")
        print(f"  MA60  {b['ma60']:>7.2f}")
        # 共識分數燈板 (過去 30 天 multi-scanner 累計)
        cons = consensus.get(ticker, {"score": 0, "scanners": []})
        score = cons["score"]
        if score >= 4:
            cons_icon, cons_label = "🟢🟢🟢", "極強共識"
        elif score == 3:
            cons_icon, cons_label = "🟢🟢", "高度確認"
        elif score == 2:
            cons_icon, cons_label = "🟢", "中度確認"
        elif score == 1:
            cons_icon, cons_label = "🟡", "單 scanner"
        else:
            cons_icon, cons_label = "⚪", "無 scanner 命中"
        ev_hint = _CONSENSUS_LEVELS.get(score, ("", ""))[1] if score > 0 else ""
        print(f"  🎯 跨 scanner 共識 (30D): {cons_icon} {cons_label} score={score}  歷史: {ev_hint}")
        if cons["scanners"]:
            for sname, sdate in cons["scanners"]:
                print(f"      ✓ {sname} (最近命中 {sdate})")

        # 扣抵亮燈 (課程系統最早期出場警示)
        kickout = b.get("kickout", {})
        if kickout:
            print(f"  📊 扣抵預判（明日 MA 方向 — 出場警示燈板）：")
            for ma_n, ma_label in [(5, "MA5 "), (10, "MA10"), (20, "MA20"), (60, "MA60")]:
                k = kickout.get(f"ma{ma_n}")
                if k:
                    icon, msg = rolloff_status(price, k["close"], k["date"], ma_label)
                    # 警示突出 (🔴 將下彎 = 早期出場警示)
                    prefix = "    ⚠️  " if icon == "🔴" else "    "
                    print(f"{prefix}{msg}")
        print(f"  觀察指標即時狀態：")
        for label, fn in CHECKS.get(ticker, []):
            try:
                ok = fn(row)
                print(fmt_check(label, ok))
            except Exception as e:
                print(f"      ? {label} (計算錯誤: {e})")

    print()
    print("=" * 78)
    print(" 備註：")
    print(" - ma20/slope/vol_ma20 取自昨日收盤 baseline (DB)")
    print(" - bias = (現價/ma20)-1，vol_ratio = (即時量/昨日 vol_ma20)")
    print(" - 扣抵 = N 天前收盤；今 close > 扣抵 close → 明日 MA 將上揚")
    print(" - 🟢 將上揚  🟡 臨界(1-2 天內可能轉折)  🔴 將下彎(早期出場警示)")
    print(" - 課程紅線：盤中亮燈為預判，最終以收盤確認")
    print(" - 共識分數: 過去 30 天 multi-scanner 累計命中 (排除 G/F 短線時間框架不同)")
    print("   Score 1 → EV +1.75% / 2 → +3.35% / 3 → +5.28% / 4+ → +11.67% (backtest 統計)")
    print(" - 重跑：python scripts/zhuli/watchlist_intraday.py")


if __name__ == "__main__":
    main()
