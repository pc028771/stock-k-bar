"""13:10 尾盤前 intraday scanner — 用現價當收盤、預判尾盤進出。

執行流程:
1. 從 holdings.json 取持倉 + watchlist + 排除清單
2. FubonClient 一次抓全市場快照（TSE + OTC）
3. 對持倉 + watchlist 每檔:
   - 查 standard_daily_bar 取最近 200 日歷史 bars
   - 構造今日 bar: open/high/low/volume 用快照、close 用現價
   - 串接歷史 bars + 今日 bar
   - 計算 MA10、vol_ratio 等衍生欄位
   - 評估停損警示 + 加碼機會
4. 對全市場候選池跑 shakeout_strong / small_structure / w_bottom_launch
5. 輸出 markdown 到 docs/主力大課程/daily_brief/YYYY-MM-DD_intraday.md

尾盤風險判定規則（簡單 threshold）:
- 🚨 大量震盪: (high - low) / open > 5% 且 vol_ratio > 2.0 → 可能被拉尾盤
- ⚠️ 接近日低: 現價 < 日低 + range × 0.2 → 可能被拋售
- ⚠️ 接近日高: 現價 > 日高 - range × 0.2 → 可能尾盤殺
- 🟢 平靜: 日內 range < 2% 且現價在中段 → 風險低

Usage:
  python scripts/zhuli/intraday_scanner.py [YYYY-MM-DD] [--test]
  --test: 跑測試模式，允許非交易時間執行（快照失敗時用 DB 收盤價代替）
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_SYS  = Path("/Users/howard/Repository/stock-analysis-system")
for _p in [str(_REPO), str(_REPO / "scripts"), str(_SYS)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kline.extras.shakeout_strong import detect as detect_shakeout        # noqa
from zhuli.entry.small_structure import detect as detect_small_structure  # noqa
from zhuli.entry.w_bottom_launch import detect as detect_wbottom          # noqa
from zhuli.daily_scanner_job import (                                      # noqa
    _load_teacher_sectors, _load_teacher_picks,
    TIER_A_WBOTTOM, TIER_A_SMALLSTR, MA10_DIST_RISKY,
)

_DB         = Path.home() / ".four_seasons" / "data.sqlite"
_HOLDINGS   = _REPO / "docs" / "主力大課程" / "holdings.json"
_BRIEF_DIR  = _REPO / "docs" / "主力大課程" / "daily_brief"

TEACHER_SECTOR_MAP, _ = _load_teacher_sectors(), None  # type: ignore[assignment]
TEACHER_SECTOR_MAP = _load_teacher_sectors()
TEACHER_TIER, TEACHER_NAME, TEACHER_FIRST = _load_teacher_picks()

# ── 日內風險門檻 ──────────────────────────────────────────────────────────────
RANGE_VOLATILE_RATIO = 0.05   # (high - low) / open > 5%  → 大量震盪條件之一
VOL_RATIO_VOLATILE   = 2.0    # vol_ratio > 2.0 → 大量震盪條件之二
RANGE_EDGE_RATIO     = 0.20   # 現價在日內 range 20% 邊緣 → 接近日高/日低
RANGE_CALM_RATIO     = 0.02   # 日內 range / open < 2% → 平靜


def _db_uri(path: Path) -> str:
    return f"file:{path}?mode=ro"


def load_holdings() -> dict:
    """載入 holdings.json 全部內容。"""
    return json.loads(_HOLDINGS.read_text(encoding="utf-8"))


def load_stock_info(con: sqlite3.Connection) -> dict[str, dict]:
    rows = con.execute(
        "SELECT ticker, stock_name, industry_category FROM stock_info"
    ).fetchall()
    return {r[0]: {"name": r[1], "industry": r[2] or ""} for r in rows}


def load_hist_bars(ticker: str, ref_date: str, con: sqlite3.Connection) -> pd.DataFrame:
    """從 DB 取最近 200 日歷史 bars（不含 ref_date 當日）。"""
    df = pd.read_sql("""
        SELECT trade_date, open, high, low, close, volume,
               vol_ratio_20, ma5, ma10, ma20, ma60, vol_ma20,
               bb_upper, bb_lower, bb_mid, ma20_slope, ma20_slope_proxy
        FROM standard_daily_bar
        WHERE ticker=? AND trade_date >= date(?, '-200 days') AND trade_date < ?
        ORDER BY trade_date
    """, con, params=(ticker, ref_date, ref_date))
    return df


def _compute_vol_ratio(volume: float, vol_ma20: float | None) -> float | None:
    if vol_ma20 and vol_ma20 > 0:
        return round(volume / vol_ma20, 1)
    return None


def build_today_bar(snapshot: dict, hist: pd.DataFrame) -> pd.Series | None:
    """用快照構造今日假設 bar，close 為現價。"""
    close = snapshot.get("close")
    if not close:
        return None

    vol_ma20 = None
    if len(hist) >= 20:
        vol_ma20 = float(hist["volume"].iloc[-20:].mean())

    vol = snapshot.get("total_volume", 0) or 0
    # FubonClient total_volume 已是「張數」(1張=1000股)
    vol_raw = vol * 1000  # 還原成股數，和 standard_daily_bar 的 volume 一致

    row = {
        "trade_date": "today",
        "open":   snapshot.get("open")  or close,
        "high":   snapshot.get("high")  or close,
        "low":    snapshot.get("low")   or close,
        "close":  close,
        "volume": vol_raw,
        "vol_ratio_20": _compute_vol_ratio(vol_raw, vol_ma20),
        "ma5":    None, "ma10": None, "ma20": None, "ma60": None,
        "vol_ma20": vol_ma20,
        "bb_upper": None, "bb_lower": None, "bb_mid": None,
        "ma20_slope": None, "ma20_slope_proxy": None,
    }
    return pd.Series(row)


def append_today_bar(hist: pd.DataFrame, today_bar: pd.Series) -> pd.DataFrame:
    """串接歷史 bars + 今日 bar，並補齊 MA 等衍生欄位。"""
    today_df = pd.DataFrame([today_bar])
    df = pd.concat([hist, today_df], ignore_index=True)

    # 重新計算移動平均（用完整歷史）
    df["ma5"]  = df["close"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["close"].rolling(10, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(60, min_periods=1).mean()

    # 衍生欄位
    df["ticker"] = "T"
    df["date"] = df["trade_date"]
    df["prev_close"] = df["close"].shift(1)
    df["prev_open"]  = df["open"].shift(1)
    df["prev_high"]  = df["high"].shift(1)
    df["prev_low"]   = df["low"].shift(1)
    df["ma5_slope_5d"] = df["ma5"].diff(5)
    df["volume_ratio"] = df["vol_ratio_20"]  # alias

    return df


def assess_stop_loss(ticker: str, holding: dict, snapshot: dict | None,
                     hist: pd.DataFrame) -> dict:
    """檢查停損/加碼條件。回傳 assessment dict。"""
    cost = holding.get("cost")
    stop_loss = holding.get("stop_loss")
    stop_warn = holding.get("stop_warn")

    if snapshot:
        current_price = snapshot.get("close")
    else:
        current_price = None

    # 從 DB 取最後一筆 bar（當日可能無收盤、用前日）
    last_bar = hist.iloc[-1] if len(hist) > 0 else None
    ma10 = float(last_bar["ma10"]) if last_bar is not None and pd.notna(last_bar.get("ma10")) else None

    result = {
        "current_price": current_price,
        "cost": cost,
        "stop_loss": stop_loss,
        "stop_warn": stop_warn,
        "ma10": ma10,
        "pnl_pct": None,
        "dist_ma10_pct": None,
        "signals": [],
    }

    if current_price and cost:
        result["pnl_pct"] = round((current_price - cost) / cost * 100, 1)

    if current_price and ma10:
        result["dist_ma10_pct"] = round((current_price - ma10) / ma10 * 100, 1)

    if current_price:
        # 停損警示
        if stop_loss and current_price <= stop_loss:
            result["signals"].append("🚨停損觸發（現價≤停損位）")
        elif stop_warn and current_price <= stop_warn:
            result["signals"].append("⚠️停損警示（現價≤警示位）")

        # 加碼機會
        if cost and ma10:
            if result["pnl_pct"] is not None and result["pnl_pct"] >= 10.0:
                dist_from_ma10 = result["dist_ma10_pct"] or 999
                if dist_from_ma10 <= 5.0:
                    result["signals"].append("✅加碼機會（脫離成本≥+10%、距MA10≤5%）")

    return result


def intraday_risk_signal(snapshot: dict | None, vol_ma20: float | None) -> str:
    """判斷日內尾盤風險訊號（簡單 threshold）。"""
    if not snapshot:
        return "—（無快照）"

    open_p  = snapshot.get("open")  or 0
    high    = snapshot.get("high")  or 0
    low     = snapshot.get("low")   or 0
    close   = snapshot.get("close") or 0
    vol     = (snapshot.get("total_volume") or 0) * 1000  # 張→股

    if not open_p or not high or not low or not close:
        return "—（資料不完整）"

    intra_range = high - low
    range_ratio = intra_range / open_p if open_p > 0 else 0

    # vol_ratio 估算
    vol_ratio = _compute_vol_ratio(vol, vol_ma20) or 0

    # 平靜判定（優先）
    if range_ratio < RANGE_CALM_RATIO:
        return "🟢 平靜"

    # 大量震盪
    if range_ratio > RANGE_VOLATILE_RATIO and vol_ratio > VOL_RATIO_VOLATILE:
        return f"🚨 大量震盪 range={range_ratio:.1%} vol={vol_ratio:.1f}x 可能被拉尾盤"

    signals = []

    # 接近日低（可能被拋售）
    if intra_range > 0 and close < (low + intra_range * RANGE_EDGE_RATIO):
        signals.append(f"⚠️ 接近日低 ({low:.2f}) 可能被拋售")

    # 接近日高（可能尾盤殺）
    if intra_range > 0 and close > (high - intra_range * RANGE_EDGE_RATIO):
        signals.append(f"⚠️ 接近日高 ({high:.2f}) 可能尾盤殺")

    if signals:
        return " | ".join(signals)

    return "🟡 中性"


def watchlist_pullup_signal(snapshot: dict | None, hist: pd.DataFrame) -> str:
    """watchlist 拉尾盤嫌疑偵測。"""
    if not snapshot:
        return "—"

    close = snapshot.get("close") or 0
    # 取 hist 最後一日作為「今日開盤前參考」
    if len(hist) == 0:
        return "—"

    prev_close = float(hist.iloc[-1]["close"])
    if prev_close <= 0:
        return "—"

    change_pct = (close - prev_close) / prev_close * 100
    vol = (snapshot.get("total_volume") or 0) * 1000

    vol_ma20 = None
    if len(hist) >= 20:
        vol_ma20 = float(hist["volume"].iloc[-20:].mean())

    vol_ratio = _compute_vol_ratio(vol, vol_ma20) or 0

    if change_pct > 2.0 and vol_ratio > 1.5:
        return f"⚠️ 拉尾盤嫌疑（13:10漲幅{change_pct:+.1f}% vol{vol_ratio:.1f}x 避免追）"

    return "—"


def fetch_all_snapshots(client) -> dict[str, dict]:
    """一次抓 TSE + OTC 全市場快照，回傳 {ticker: snapshot_dict}。"""
    print("[intraday] 抓 TSE 全市場快照...", flush=True)
    tse_quotes = client.get_snapshot_quotes("TSE") or []
    print(f"  TSE: {len(tse_quotes)} 檔", flush=True)

    print("[intraday] 抓 OTC 全市場快照...", flush=True)
    otc_quotes = client.get_snapshot_quotes("OTC") or []
    print(f"  OTC: {len(otc_quotes)} 檔", flush=True)

    all_quotes = tse_quotes + otc_quotes
    snap_map: dict[str, dict] = {}

    for q in all_quotes:
        # Fubon API 欄位名稱（可能有不同命名）
        ticker = (
            q.get("symbol") or q.get("ticker") or q.get("stockId") or
            q.get("stock_id") or q.get("code") or ""
        )
        if not ticker:
            continue
        close = (
            _safe_float_local(q.get("closePrice")) or
            _safe_float_local(q.get("close_price")) or
            _safe_float_local(q.get("lastPrice")) or
            _safe_float_local(q.get("last_price"))
        )
        if not close:
            continue
        total = q.get("total") or {}
        trade_vol_shares = _safe_int_local(
            q.get("totalVolume") or q.get("total_volume") or
            total.get("tradeVolume") or total.get("trade_volume")
        ) or 0
        snap_map[ticker] = {
            "close":        close,
            "open":         _safe_float_local(q.get("openPrice")  or q.get("open_price"))  or close,
            "high":         _safe_float_local(q.get("highPrice")  or q.get("high_price"))  or close,
            "low":          _safe_float_local(q.get("lowPrice")   or q.get("low_price"))   or close,
            "change_rate":  _safe_float_local(q.get("changePercent") or q.get("change_percent")) or 0.0,
            "total_volume": trade_vol_shares // 1000,  # 股→張
        }

    return snap_map


def _safe_float_local(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int_local(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def run_scanner_on_df(df: pd.DataFrame) -> dict[str, bool]:
    """對單一 ticker 的 df 跑三個 scanner。"""
    hits = {}
    for name, fn in [
        ("shakeout_strong",  detect_shakeout),
        ("small_structure",  detect_small_structure),
        ("w_bottom_launch",  detect_wbottom),
    ]:
        try:
            sig = fn(df)
            hits[name] = bool(hasattr(sig, "iloc") and sig.iloc[-1])
        except Exception:
            hits[name] = False
    return hits


def _format_price(p) -> str:
    if p is None:
        return "—"
    return f"${p:.2f}"


def _format_pct(p) -> str:
    if p is None:
        return "—"
    return f"{p:+.1f}%"


def render_report(
    target_date: str,
    snapshot_time: str,
    holdings_data: dict,
    holding_analyses: list[dict],
    watchlist_analyses: list[dict],
    scanner_hits: list[dict],
) -> str:
    lines = [
        f"# {target_date} 尾盤 intraday scanner (13:10 快照)",
        f"",
        f"> 用 {snapshot_time} 即時現價當收盤、預判尾盤進出",
        f"> 結果僅供參考、實際以 13:30 收盤為準",
        f"> 快照時間: **{snapshot_time}**",
        f"",
        f"---",
        f"",
    ]

    # ── 持倉尾盤風險快照 ──────────────────────────────────────────────────────
    lines += [
        f"## 持倉尾盤風險快照 ({snapshot_time.split()[1] if ' ' in snapshot_time else snapshot_time})",
        f"",
        f"| Ticker | 名稱 | 13:10 現價 | 日內 high/low | 量比 | 風險訊號 |",
        f"|---|---|---|---|---|---|",
    ]
    for a in holding_analyses:
        snap = a.get("snapshot") or {}
        hi   = snap.get("high")
        lo   = snap.get("low")
        hl_str = f"{hi:.2f}/{lo:.2f}" if hi and lo else "—"
        vol_ratio_str = "—"
        if a.get("vol_ratio") is not None:
            vol_ratio_str = f"{a['vol_ratio']:.1f}x"
        lines.append(
            f"| {a['ticker']} | {a['name']} | {_format_price(a.get('current_price'))} | "
            f"{hl_str} | {vol_ratio_str} | {a.get('risk_signal', '—')} |"
        )
    lines.append(f"")

    # ── 出場警示 ──────────────────────────────────────────────────────────────
    stop_warnings = [a for a in holding_analyses if any(
        s.startswith("🚨") or s.startswith("⚠️停損") for s in a.get("signals", [])
    )]
    if stop_warnings:
        lines += [
            f"## 出場警示（持倉）",
            f"",
            f"| Ticker | 名稱 | 成本 | 現價 | 停損位 | 浮動 | 訊號 |",
            f"|---|---|---|---|---|---|---|",
        ]
        for a in stop_warnings:
            sigs = " | ".join(a.get("signals", []))
            lines.append(
                f"| **{a['ticker']}** | {a['name']} | {_format_price(a.get('cost'))} | "
                f"{_format_price(a.get('current_price'))} | {_format_price(a.get('stop_loss'))} | "
                f"{_format_pct(a.get('pnl_pct'))} | {sigs} |"
            )
        lines.append(f"")
    else:
        lines += [f"## 出場警示（持倉）", f"", f"> 無持倉觸發停損/警示", f""]

    # ── 加碼機會 ──────────────────────────────────────────────────────────────
    add_opps = [a for a in holding_analyses if any(
        s.startswith("✅加碼") for s in a.get("signals", [])
    )]
    if add_opps:
        lines += [
            f"## 加碼機會（持倉）",
            f"",
            f"| Ticker | 名稱 | 成本 | 現價 | 浮動 | 距MA10 | 訊號 |",
            f"|---|---|---|---|---|---|---|",
        ]
        for a in add_opps:
            lines.append(
                f"| {a['ticker']} | {a['name']} | {_format_price(a.get('cost'))} | "
                f"{_format_price(a.get('current_price'))} | {_format_pct(a.get('pnl_pct'))} | "
                f"{_format_pct(a.get('dist_ma10_pct'))} | {'✅加碼機會'} |"
            )
        lines.append(f"")
    else:
        lines += [f"## 加碼機會（持倉）", f"", f"> 無持倉達到加碼條件（需脫離成本≥+10%且距MA10≤5%）", f""]

    # ── Watchlist 動作建議 ────────────────────────────────────────────────────
    lines += [
        f"## Watchlist 動作建議",
        f"",
        f"| Ticker | 名稱 | 13:10 現價 | 浮動（vs昨收） | 距MA10 | Scanner | 拉尾盤訊號 |",
        f"|---|---|---|---|---|---|---|",
    ]
    for a in watchlist_analyses:
        scanners_hit = [s for s, v in a.get("scanner_hits", {}).items() if v]
        scanner_str = "/".join(scanners_hit) if scanners_hit else "—"
        lines.append(
            f"| {a['ticker']} | {a['name']} | {_format_price(a.get('current_price'))} | "
            f"{_format_pct(a.get('pnl_pct'))} | {_format_pct(a.get('dist_ma10_pct'))} | "
            f"{scanner_str} | {a.get('pullup_signal', '—')} |"
        )
    lines.append(f"")

    # ── 新候選（非持倉、非排除、scanner 命中）────────────────────────────────
    if scanner_hits:
        lines += [
            f"## 新候選（scanner 命中、非持倉非排除）",
            f"",
            f"| Ticker | 名稱 | Scanner | 13:10 現價 | 量比 | 距MA10 | 老師 | 備註 |",
            f"|---|---|---|---|---|---|---|---|",
        ]
        for h in scanner_hits[:30]:
            ticker = h["ticker"]
            teacher_tier = TEACHER_TIER.get(ticker, "—") or "—"
            teacher_sectors = TEACHER_SECTOR_MAP.get(ticker, [])
            sector_str = "/".join(teacher_sectors) if teacher_sectors else h.get("industry", "")
            lines.append(
                f"| **{ticker}** | {h.get('name', '')} | {h.get('scanner_name', '')} | "
                f"{_format_price(h.get('close'))} | {h.get('vol_ratio', '—')}x | "
                f"{_format_pct(h.get('dist_ma10_pct'))} | {teacher_tier} | {sector_str} |"
            )
        lines.append(f"")
    else:
        lines += [f"## 新候選（scanner 命中）", f"", f"> 無新候選", f""]

    lines += [
        f"---",
        f"",
        f"產生時間: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"快照時間: {snapshot_time}",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="13:10 尾盤 intraday scanner")
    ap.add_argument("date", nargs="?", default=None, help="目標日期 YYYY-MM-DD（預設今天）")
    ap.add_argument("--test", action="store_true", help="測試模式：快照失敗時用 DB 收盤價代替")
    ap.add_argument("--db", default=str(_DB))
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()
    db_path     = Path(args.db)
    is_test     = args.test

    print(f"=== 13:10 尾盤 intraday scanner ===")
    print(f"目標日期: {target_date} | 測試模式: {is_test}")
    print()

    _BRIEF_DIR.mkdir(parents=True, exist_ok=True)

    # ── 載入 holdings.json ────────────────────────────────────────────────────
    holdings_data = load_holdings()
    holdings      = holdings_data.get("holdings", {})
    watchlist     = holdings_data.get("watchlist", {})
    exclusion     = holdings_data.get("exclusion_list", {})
    excluded_tickers = set(exclusion.keys())
    holding_tickers  = set(holdings.keys())

    print(f"持倉: {len(holdings)} 檔 | watchlist: {len(watchlist)} 檔 | 排除: {len(excluded_tickers)} 檔")

    # ── FubonClient + 全市場快照 ─────────────────────────────────────────────
    snap_map: dict[str, dict] = {}
    snapshot_time = f"{target_date} 13:10:XX"
    fubon_ok = False

    try:
        from clients.fubon_client import FubonClient
        client = FubonClient()
        snap_map = fetch_all_snapshots(client)
        snapshot_time = f"{target_date} {datetime.now():%H:%M:%S}"
        fubon_ok = True
        print(f"✅ 全市場快照: {len(snap_map)} 檔 ({snapshot_time})")
        client.disconnect()
    except Exception as e:
        print(f"⚠️ FubonClient 快照失敗: {e}", flush=True)
        if is_test:
            print("  測試模式：改用 DB 最後收盤價當現價", flush=True)
        else:
            print("  非測試模式：仍繼續（快照欄位全為 None）", flush=True)

    # ── 連接 DB ───────────────────────────────────────────────────────────────
    con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=15)
    stock_info = load_stock_info(con)

    # ── 持倉分析 ──────────────────────────────────────────────────────────────
    holding_analyses: list[dict] = []

    for ticker, info in holdings.items():
        name = info.get("name") or stock_info.get(ticker, {}).get("name", ticker)
        hist = load_hist_bars(ticker, target_date, con)

        # 快照 fallback
        snapshot = snap_map.get(ticker)
        if not snapshot and is_test and len(hist) > 0:
            # 測試模式：用 DB 最後收盤價模擬
            last = hist.iloc[-1]
            snapshot = {
                "close": float(last["close"]),
                "open":  float(last["open"]),
                "high":  float(last["high"]),
                "low":   float(last["low"]),
                "total_volume": int(last["volume"] // 1000) if last["volume"] else 0,
            }

        assessment = assess_stop_loss(ticker, info, snapshot, hist)

        # vol_ratio for risk signal
        vol_ma20 = None
        if len(hist) >= 20:
            vol_ma20 = float(hist["volume"].iloc[-20:].mean())
        vol_ratio = None
        if snapshot:
            vol_raw = (snapshot.get("total_volume") or 0) * 1000
            vol_ratio = _compute_vol_ratio(vol_raw, vol_ma20)

        risk_signal = intraday_risk_signal(snapshot, vol_ma20)

        holding_analyses.append({
            "ticker":        ticker,
            "name":          name,
            "snapshot":      snapshot,
            "current_price": assessment["current_price"],
            "cost":          assessment["cost"],
            "stop_loss":     assessment["stop_loss"],
            "pnl_pct":       assessment["pnl_pct"],
            "dist_ma10_pct": assessment["dist_ma10_pct"],
            "signals":       assessment["signals"],
            "risk_signal":   risk_signal,
            "vol_ratio":     vol_ratio,
        })

    print(f"持倉分析完成: {len(holding_analyses)} 檔")

    # ── Watchlist 分析 ────────────────────────────────────────────────────────
    watchlist_analyses: list[dict] = []

    for ticker, info in watchlist.items():
        # holdings.json watchlist 混有筆記型條目 (key 非 ticker / value 非 dict)、跳過
        if not (ticker.isdigit() and isinstance(info, dict)):
            continue
        name = info.get("name") or stock_info.get(ticker, {}).get("name", ticker)
        hist = load_hist_bars(ticker, target_date, con)

        snapshot = snap_map.get(ticker)
        if not snapshot and is_test and len(hist) > 0:
            last = hist.iloc[-1]
            snapshot = {
                "close": float(last["close"]),
                "open":  float(last["open"]),
                "high":  float(last["high"]),
                "low":   float(last["low"]),
                "total_volume": int(last["volume"] // 1000) if last["volume"] else 0,
            }

        current_price = snapshot.get("close") if snapshot else None

        # 距 MA10
        dist_ma10 = None
        ma10_val = None
        if len(hist) > 0:
            last_ma10 = hist.iloc[-1]["ma10"]
            if pd.notna(last_ma10):
                ma10_val = float(last_ma10)
                if current_price and ma10_val > 0:
                    dist_ma10 = round((current_price - ma10_val) / ma10_val * 100, 1)

        # vs 昨收變動
        pnl_pct = None
        if current_price and len(hist) > 0:
            prev_close = float(hist.iloc[-1]["close"])
            if prev_close > 0:
                pnl_pct = round((current_price - prev_close) / prev_close * 100, 1)

        # 跑 scanner（用歷史 + 今日假設 bar）
        scanner_hits_map: dict[str, bool] = {}
        if snapshot and len(hist) >= 100:
            try:
                today_bar = build_today_bar(snapshot, hist)
                if today_bar is not None:
                    df = append_today_bar(hist.copy(), today_bar)
                    scanner_hits_map = run_scanner_on_df(df)
            except Exception as e:
                print(f"  [WARN] {ticker} scanner 失敗: {e}", flush=True)

        pullup_sig = watchlist_pullup_signal(snapshot, hist)

        watchlist_analyses.append({
            "ticker":         ticker,
            "name":           name,
            "snapshot":       snapshot,
            "current_price":  current_price,
            "pnl_pct":        pnl_pct,
            "dist_ma10_pct":  dist_ma10,
            "scanner_hits":   scanner_hits_map,
            "pullup_signal":  pullup_sig,
        })

    print(f"Watchlist 分析完成: {len(watchlist_analyses)} 檔")

    # ── 全市場新候選 scanner ──────────────────────────────────────────────────
    print("[intraday] 跑全市場 scanner...", flush=True)

    # 候選池：全市場 ticker（有歷史 bar 的）
    all_tickers_in_db = [
        r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar WHERE trade_date=?",
            (target_date,)
        ).fetchall()
    ] if not is_test else [
        r[0] for r in con.execute(
            "SELECT DISTINCT ticker FROM standard_daily_bar "
            "ORDER BY trade_date DESC LIMIT 5000"
        ).fetchall()
    ]

    # 排除持倉 + 排除清單
    candidate_tickers = [
        t for t in all_tickers_in_db
        if t not in holding_tickers and t not in excluded_tickers
    ]
    print(f"  候選池: {len(candidate_tickers)} 檔", flush=True)

    scanner_hits: list[dict] = []
    VOL_RATIO_MIN = {
        "shakeout_strong": 2.0,
        "w_bottom_launch": 2.0,
        "small_structure": 1.0,
    }

    for t in candidate_tickers:
        hist = load_hist_bars(t, target_date, con)
        if len(hist) < 100:
            continue

        # 取快照
        snapshot = snap_map.get(t)
        if not snapshot and is_test and len(hist) > 0:
            last = hist.iloc[-1]
            snapshot = {
                "close": float(last["close"]),
                "open":  float(last["open"]),
                "high":  float(last["high"]),
                "low":   float(last["low"]),
                "total_volume": int(last["volume"] // 1000) if last["volume"] else 0,
            }

        if not snapshot:
            continue

        try:
            today_bar = build_today_bar(snapshot, hist)
            if today_bar is None:
                continue
            df = append_today_bar(hist.copy(), today_bar)

            info_d = stock_info.get(t, {"name": "", "industry": ""})
            last_close = snapshot.get("close") or 0

            vol_ma20 = float(hist["volume"].iloc[-20:].mean()) if len(hist) >= 20 else None
            vol_raw  = (snapshot.get("total_volume") or 0) * 1000
            last_vol_ratio = _compute_vol_ratio(vol_raw, vol_ma20) or 0

            # 距 MA10
            last_bar = df.iloc[-1]
            ma10_v = float(last_bar["ma10"]) if pd.notna(last_bar["ma10"]) else None
            dist_ma10 = None
            if ma10_v and ma10_v > 0:
                dist_ma10 = round((float(last_close) - ma10_v) / ma10_v * 100, 1)

            hits_map = run_scanner_on_df(df)

            for scanner_name, did_hit in hits_map.items():
                if not did_hit:
                    continue
                if last_vol_ratio < VOL_RATIO_MIN[scanner_name]:
                    continue

                scanner_hits.append({
                    "ticker":         t,
                    "name":           info_d["name"],
                    "industry":       info_d["industry"],
                    "scanner_name":   scanner_name,
                    "close":          last_close,
                    "vol_ratio":      round(last_vol_ratio, 1),
                    "dist_ma10_pct":  dist_ma10,
                })

        except Exception:
            pass

    # 排序：老師指名 → vol_ratio
    def _sort_key(h: dict) -> tuple:
        tier = TEACHER_TIER.get(h["ticker"], "")
        tier_rank = 0 if tier in ("core", "frequent") else 1
        return (tier_rank, -(h.get("vol_ratio") or 0))

    scanner_hits.sort(key=_sort_key)
    print(f"全市場 scanner 命中: {len(scanner_hits)} 檔")

    con.close()

    # ── 輸出報告 ──────────────────────────────────────────────────────────────
    md = render_report(
        target_date      = target_date,
        snapshot_time    = snapshot_time,
        holdings_data    = holdings_data,
        holding_analyses = holding_analyses,
        watchlist_analyses = watchlist_analyses,
        scanner_hits     = scanner_hits,
    )

    out_path = _BRIEF_DIR / f"{target_date}_intraday.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"\n→ 報告: {out_path}")
    print(f"→ 大小: {out_path.stat().st_size:,} bytes")

    # 前 30 行預覽
    first_30 = "\n".join(md.splitlines()[:30])
    print(f"\n── 前 30 行預覽 ──\n{first_30}")

    return str(out_path)


if __name__ == "__main__":
    main()
