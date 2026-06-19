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

import sys
from datetime import datetime
from pathlib import Path

# Path setup
_WORKTREE = Path(__file__).parent.parent.parent
for _p in [str(_WORKTREE), str(_WORKTREE / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn
import pandas as pd

from common.clients.fubon_client import FubonClient  # noqa: E402
from kline.bars import DEFAULT_DB_PATH  # noqa: E402

# 族群定義 (供法人籌碼過濾器用)
_GROUP_TICKERS = {
    "半導體": {"2330","2454","8110","3583","6770","6669","3260","3017","3711","6488","2308","6451"},
    "被動元件": {"2327","2492","2472","3026","6173","2375","2456","2354","2308","2317"},
    "機器人": {"4540","1597","2464","4576","2049","8027","3552","2233","3041","2059"},
    "記憶體": {"2344","2337","2408","3006","8150","2351","3105","2329","8048"},
    "玻璃基板": {"8064","3055","3580","3663","4916","6139","1560","3481"},
}
_TICKER_TO_GROUP = {t: g for g, ts in _GROUP_TICKERS.items() for t in ts}

# 法人籌碼流向門檻 (5 日累計，張)
_FLOW_THRESHOLD = 5000

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
    with get_conn(db_path) as conn:
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


def get_group_flow_state(db_path: Path, ticker: str) -> tuple[str, float, str]:
    """取 ticker 所屬族群最近 5 日法人合計買賣超 + 流向 state.

    Returns (state, net_5d_張, group_name)
        state: "流入" / "中性" / "流出" / "未知(無族群)"
    """
    group = _TICKER_TO_GROUP.get(ticker)
    if not group:
        return ("未知", 0.0, "")
    tickers = _GROUP_TICKERS[group]
    try:
        with get_conn(db_path, timeout=15) as conn:
            placeholders = ",".join(["?"] * len(tickers))
            df = pd.read_sql_query(
                f"SELECT trade_date, sitc_net, foreign_net "
                f"FROM institutional_investors WHERE ticker IN ({placeholders}) "
                f"ORDER BY trade_date DESC LIMIT 500",
                conn, params=list(tickers),
            )
        if df.empty:
            return ("未知", 0.0, group)
        df["net"] = df["sitc_net"] + df["foreign_net"]
        grp_daily = df.groupby("trade_date")["net"].sum().reset_index()
        grp_daily = grp_daily.sort_values("trade_date", ascending=False).head(5)
        net_5d = grp_daily["net"].sum()
        if net_5d > _FLOW_THRESHOLD:
            state = "流入"
        elif net_5d < -_FLOW_THRESHOLD:
            state = "流出"
        else:
            state = "中性"
        return (state, float(net_5d), group)
    except Exception:
        return ("未知", 0.0, group)


def baseline_ch2_warnings(db_path: Path, ticker: str) -> tuple[int, list[str]]:
    """依課程 Ch2 規則對「昨日 + 前 N 日」算多條件警示, 分數累積式.

    每個觸發條件給 1 分; 總分等級:
      0     ✓ 無警示
      1     🟡 觀察 (單一條件, 可能假警報)
      2     ⚠️ 警示 (兩條件 AND, 應檢核)
      3+    🔴 強警示 (多條件確認賣壓)
      含「大量黑K」單獨 = 強警示 (因課程明示出場訊號)

    Returns (score, warning_lines).
    """
    triggers = []
    try:
        with get_conn(db_path, timeout=15) as conn:
            df = pd.read_sql_query(
                "SELECT trade_date, open, high, low, close, volume "
                "FROM standard_daily_bar WHERE ticker=? AND is_usable=1 "
                "ORDER BY trade_date DESC LIMIT 6",
                conn, params=(ticker,),
            )
        if len(df) < 2:
            return 0, []
        df = df.sort_values("trade_date").reset_index(drop=True)
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 1. Ch2-1 單日上影 > 3.5%
        upper_pct = (latest["high"] - latest["close"]) / latest["close"] * 100
        if upper_pct > 3.5:
            triggers.append((
                "Ch2-1 上影線",
                f"H {latest['high']:.2f} 離 C {latest['close']:.2f} = {upper_pct:.1f}%",
                2 if upper_pct > 7 else 1,   # 大上影 7%+ 給 2 分
            ))

        # 2. Ch2-1 多日上影 (近 3 天 ≥ 2 根 > 3%)
        if len(df) >= 3:
            shadows = (df.tail(3)["high"] - df.tail(3)["close"]) / df.tail(3)["close"] * 100
            big = (shadows > 3).sum()
            if big >= 2:
                triggers.append((
                    "Ch2-1 多日上影",
                    f"{big}/3 天 > 3% 上影 ({[f'{s:.1f}%' for s in shadows]})",
                    1,
                ))

        # 3. Ch2-4 大量黑K
        body_pct = (latest["close"] - latest["open"]) / latest["open"] * 100
        vol_ratio = latest["volume"] / prev["volume"] if prev["volume"] > 0 else 0
        if body_pct < -3 and vol_ratio > 1.3:
            triggers.append((
                "Ch2-4 大量黑K",
                f"body {body_pct:.1f}% + 量×{vol_ratio:.2f}",
                3,  # 課程明示出場訊號，單獨給 3 分
            ))

        # 4. 連 3 天低點下降 (5 停損 ③)
        if len(df) >= 3:
            r = df.tail(3).reset_index(drop=True)
            if r["low"].iloc[2] < r["low"].iloc[1] < r["low"].iloc[0]:
                triggers.append((
                    "5 停損 ③ 連 3 天低點下降",
                    f"{r['low'].iloc[0]:.1f}→{r['low'].iloc[1]:.1f}→{r['low'].iloc[2]:.1f}",
                    2,
                ))
            elif latest["low"] < prev["low"]:
                triggers.append((
                    "低點破前低",
                    f"L {latest['low']:.2f} < 前日 L {prev['low']:.2f}",
                    1,
                ))

        # 5. 量爆 (vol > prev × 2) — 加分項
        if vol_ratio >= 2.0:
            triggers.append((
                "Ch2-4 量爆",
                f"今量×{vol_ratio:.2f} (vs 前日)",
                1,
            ))

        # 6. 收盤跌破 MA5 (短均跌破 = 早期警示)
        if "ma5" not in df.columns:
            with get_conn(db_path, timeout=15) as _con:
                cur = _con.execute(
                    "SELECT ma5 FROM standard_daily_bar WHERE ticker=? AND trade_date=?",
                    (ticker, latest["trade_date"]),
                ).fetchone()
            ma5 = cur[0] if cur else None
        else:
            ma5 = latest.get("ma5")
        if ma5 and latest["close"] < ma5:
            triggers.append((
                "收盤跌破 MA5",
                f"C {latest['close']:.2f} < MA5 {ma5:.2f}",
                1,
            ))

    except Exception as exc:
        return 0, [f"  ? Ch2 warnings 計算錯誤: {exc}"]

    score = sum(t[2] for t in triggers)

    # === 法人籌碼過濾器：調整警示等級 ===
    # 流入期: 法人在加倉, 個股留上影/破前低多半是健康整理 → 降 1 分 (除大量黑K真背離保留)
    # 流出期: 法人賣超中, 警示更可信 → 升 1 分
    flow_state, flow_5d, group = get_group_flow_state(db_path, ticker)
    has_big_black = any(label.startswith("Ch2-4 大量黑K") for label, _, _ in triggers)
    adjusted_score = score
    flow_note = ""
    if flow_state == "流入" and not has_big_black:
        adjusted_score = max(0, score - 1)
        flow_note = f" [法人 5d 流入 {flow_5d:+.0f} 張 → 警示降 1]"
    elif flow_state == "流出":
        adjusted_score = score + 1
        flow_note = f" [法人 5d 流出 {flow_5d:+.0f} 張 → 警示升 1]"
    elif flow_state == "中性" and score > 0:
        flow_note = f" [法人 5d 中性 {flow_5d:+.0f} 張]"
    elif flow_state == "未知" and score > 0:
        flow_note = " [未在 4 大族群分類]"

    # === 持股集中度 chip 警示 ===
    from zhuli.chip_concentration import concentration_warnings
    conc_score, conc_lines = concentration_warnings(db_path, ticker)
    if conc_lines:
        adjusted_score += conc_score

    # === 主力分點異常 chip 警示 ===
    from zhuli.chip_broker import broker_warnings
    try:
        broker_score, broker_lines = broker_warnings(ticker, lookback_days=5)
    except Exception as exc:
        broker_score, broker_lines = 0, [f"  ? broker 警示計算失敗: {exc}"]
    if broker_lines:
        adjusted_score += broker_score

    # 等級 (用 adjusted_score，含 chip)
    if adjusted_score == 0:
        sub_lines = []
        if score > 0 and flow_state == "流入":
            sub_lines.append(f"✓ 無警示 (原 score={score}, 法人流入降級){flow_note}")
        if conc_lines:
            sub_lines.append("      ─── 持股集中度 ───")
            sub_lines.extend(conc_lines)
        if broker_lines:
            sub_lines.append("      ─── 主力分點 ───")
            sub_lines.extend(broker_lines)
        return 0, sub_lines

    if adjusted_score == 1:
        prefix = "🟡 觀察"
    elif adjusted_score == 2:
        prefix = "⚠️  警示"
    elif adjusted_score >= 3 and adjusted_score < 5:
        prefix = "🔴 強警示"
    else:
        prefix = "💀 致命警示"

    if group:
        header = f"{prefix} (Ch2 score={score}→{adjusted_score} after 法人 [{group}]{flow_note})"
    else:
        header = f"{prefix} (Ch2 score={score}→{adjusted_score}){flow_note}"
    lines = [header]
    for label, detail, pts in triggers:
        lines.append(f"      [{pts}分] {label} — {detail}")

    if conc_lines:
        lines.append("      ─── 持股集中度 ───")
        lines.extend(conc_lines)
    if broker_lines:
        lines.append("      ─── 主力分點 ───")
        lines.extend(broker_lines)

    return adjusted_score, lines


def intraday_ch2_warnings(live: dict, prev_close: float, prev_volume: float, ticker: str = "") -> list[str]:
    """依即時 Fubon snapshot 算 Ch2 盤中警示.

    Returns list of warning strings.
    """
    warnings = []
    try:
        h = live.get("high", 0)
        l = live.get("low", 0)
        o = live.get("open", 0)
        c = live.get("price") or live.get("close", 0)
        v = live.get("volume", 0)
        if c == 0 or h == 0:
            return warnings

        # Ch2-1 即時上影 (盤中高離現價 %)
        upper_shadow = (h - c) / c * 100
        if upper_shadow > 5:
            warnings.append(
                f"⚠️  Ch2-1 盤中上影警示: 高 {h:.2f} 離 C {c:.2f} = {upper_shadow:.1f}% (>5% 盤中賣壓)"
            )

        # Ch2-4 盤中量爆 (相對昨日全日)
        if prev_volume > 0 and v > 0:
            v_張 = v / 1000 if v > 100000 else v  # 不確定 unit 兼容
            prev_v_張 = prev_volume / 1000
            vol_ratio = v_張 / prev_v_張 if prev_v_張 > 0 else 0
            # 量比昨日全日 > 1.5 = 盤中已大量
            if vol_ratio > 1.5:
                warnings.append(
                    f"⚠️  Ch2-4 盤中量爆: 已 {v_張:.0f} 張 vs 昨全日 {prev_v_張:.0f} "
                    f"({vol_ratio:.2f}x, >1.5x 大量出貨/進貨)"
                )

        # 跌停接近
        if prev_close > 0:
            change_pct = (c - prev_close) / prev_close * 100
            if change_pct < -8:
                warnings.append(
                    f"🔴 接近跌停: {change_pct:.2f}% (10% 限制 80% = -8% 警戒)"
                )

    except Exception as exc:
        warnings.append(f"  ? intraday warnings 錯誤: {exc}")

    # === 5 分 K 量價結構警示 ===
    try:
        from zhuli.chip_intraday_5min import intraday_5min_warnings
        score_5m, lines_5m = intraday_5min_warnings(ticker)
        if lines_5m:
            warnings.append("  ─── 5min ───")
            warnings.extend([f"  {ln}" for ln in lines_5m])
    except Exception as exc:
        warnings.append(f"  ? 5min check failed: {exc}")

    return warnings


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
        # === Ch2 警示 (分數累積系統) ===
        ch2_score, ch2_lines = baseline_ch2_warnings(db_path, ticker)
        live_warnings = intraday_ch2_warnings(live, b["prev_close"], b["vol_ma20"], ticker)
        if ch2_lines or live_warnings:
            print(f"  🚨 Ch2 課程警示:")
            for line in ch2_lines:
                print(f"    {line}")
            for w in live_warnings:
                print(f"    {w}")

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
