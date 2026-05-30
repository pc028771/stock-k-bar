"""高檔收斂後平台 scanner (Mode C) — 老師 5/20 N字上攻教學實作.

課程來源：主力大全方位操盤教戰守則（林家洋）5/20 N字上攻教學
  - 群創 (3481) 圖 5:10: 從低 → ~$40 (漲一段)、5-7 天 $38-40 平台、突破再噴
  - 聯電 (2303) 圖 2:24: 漲一段、小平台收斂、再噴

## Mode C 定義

**高檔 (近期波段高點附近) + 短期平台收斂 + MA5 上揚 + 量縮 + 等突破**

關鍵分類：
  - Mode A (teacher_swing.py): 均線順向整理末端（強多頭中段）
  - Mode C (本檔): 漲一波後、高檔短期收斂平台（不是底部糾纏期）

## 訊號分類

  - 已突破: 今收盤 > 近 N-1 日最高收盤（打出新高）
  - 突破前夕: 平台 ≥ 5 天 + MA5 扣抵🟢 + 量縮
  - 高檔收斂中: 平台 3-5 天
  - 整理中: 其他（量縮但天數不足）

## 使用方式

    python scripts/zhuli/entry/teacher_small_structure.py --date 2026-05-29

    # 調整平台天數
    python scripts/zhuli/entry/teacher_small_structure.py --date 2026-05-29 \\
      --platform-days 5

    # 放寬平台 range（預設 5%，放寬到 10%）
    python scripts/zhuli/entry/teacher_small_structure.py --date 2026-05-29 \\
      --range-pct 10

    # 調整距 60 日高點容忍度（預設 8%）
    python scripts/zhuli/entry/teacher_small_structure.py --date 2026-05-29 \\
      --high-tolerance 12

    # 不顯示扣抵值 / 均線糾纏
    python scripts/zhuli/entry/teacher_small_structure.py --date 2026-05-29 \\
      --no-kou --no-coil

## 紀律備注

  - 此檔屬主力大課程 (zhuli) 目錄，不可混入 K線力量課程 (kline/)
  - 課程內邏輯：老師 5/20 親口示範（群創/聯電）
  - 禁止放進 extras/（非課程外條件）
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────

_REPO = Path(__file__).parent.parent.parent.parent  # stock-k-bar root
_DB   = Path.home() / ".four_seasons" / "data.sqlite"

for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Import teacher_swing helpers（不重寫）───────────────────────────────────

from zhuli.entry.teacher_swing import (  # noqa: E402
    compute_kou_value,
    compute_kou_block,
    compute_ma_state,
    compute_signal_combo,
    _load_stock_info,
    _db_uri,
)

# ── 預設設定 ─────────────────────────────────────────────────────────────────

DEFAULT_CFG: dict = {
    # ── 1. 高檔狀態 ──
    "high_tolerance_pct": 8.0,      # 距 60 日高點不超過 8%（close >= high_60 * 0.92）

    # ── 2. 平台收斂 ──
    "platform_days": 7,             # 觀察視窗 N 天（可調 5/7/10）
    "range_pct": 5.0,               # 7 日 close range < 5%（緊平台）

    # ── 3. MA5 扣抵向上 ──
    # close[-1] > close[-6] → MA5 明日繼續上揚（扣抵🟢）
    # 注：直接用 close[-1] > close[-6] 近似，而非嚴格 EMA
    "require_ma5_kou_up": True,

    # ── 4. 量縮 ──
    "vol_ratio_max": 1.3,           # vol_ratio_20 < 1.3（量不超過 20 日均量 30%）

    # ── 5. 多頭（鬆）：close > MA10（不要求 MA5 > MA10 > MA20 > MA60 全部）──
    "require_above_ma10": True,

    # ── 6. 收盤 > MA20 ──
    "require_above_ma20": True,

    # ── 最少需要 N 天的歷史 ──
    "min_bars": 65,                 # 需 60 日高點 + MA60 計算
}


# ── DB 工具 ───────────────────────────────────────────────────────────────────

def _load_all_tickers(con: sqlite3.Connection, target_date: str) -> list[str]:
    """回傳目標日有資料的所有個股 ticker（排除 ETF）."""
    rows = con.execute(
        "SELECT DISTINCT ticker FROM standard_daily_bar WHERE trade_date = ?",
        (target_date,)
    ).fetchall()
    return [r[0] for r in rows if r[0].isdigit()]


def _load_bars(
    con: sqlite3.Connection,
    ticker: str,
    target_date: str,
    lookback_days: int = 250,
) -> pd.DataFrame:
    """讀取近 N 日的日 K 資料."""
    return pd.read_sql(
        """
        SELECT trade_date, open, high, low, close, volume,
               ma5, ma10, ma20, ma60
        FROM standard_daily_bar
        WHERE ticker = ?
          AND trade_date >= date(?, ? || ' days')
          AND trade_date <= ?
        ORDER BY trade_date
        """,
        con,
        params=(ticker, target_date, f"-{lookback_days}", target_date),
    )


# ── 核心偵測邏輯 ──────────────────────────────────────────────────────────────

def _compute_vol_ratio(bars: pd.DataFrame, today_idx: int) -> float | None:
    """計算今日成交量 / 20 日均量."""
    if today_idx < 1:
        return None
    start = max(0, today_idx - 20)
    hist_vol = bars["volume"].iloc[start:today_idx]
    if hist_vol.empty or hist_vol.mean() == 0:
        return None
    return float(bars["volume"].iloc[today_idx]) / float(hist_vol.mean())


def _compute_platform_days(closes: pd.Series, today_idx: int, range_pct: float) -> int:
    """從今天向前統計「連續幾天 close range < range_pct%」(min 1 max 14)."""
    if today_idx < 1:
        return 1

    count = 1
    ref_high = float(closes.iloc[today_idx])
    ref_low  = float(closes.iloc[today_idx])

    for i in range(today_idx - 1, max(today_idx - 14, -1), -1):
        c = float(closes.iloc[i])
        new_high = max(ref_high, c)
        new_low  = min(ref_low, c)
        # 用目前 close 作分母
        cur_close = float(closes.iloc[today_idx])
        if cur_close <= 0:
            break
        if (new_high - new_low) / cur_close * 100 < range_pct:
            ref_high = new_high
            ref_low  = new_low
            count += 1
        else:
            break

    return min(count, 14)


def _signal_label(
    platform_days: int,
    kou_ma5_direction: str | None,
    vol_status: str,
    closes: pd.Series,
    today_idx: int,
    platform_days_cfg: int,
) -> str:
    """決定訊號標籤."""
    # 已突破：today close > max(close[-N:-1])（近期 N-1 日新高）
    lookback = platform_days_cfg
    if today_idx >= lookback:
        prev_max = float(closes.iloc[today_idx - lookback: today_idx].max())
        today_close = float(closes.iloc[today_idx])
        if today_close > prev_max:
            return "已突破"

    if platform_days >= 5 and kou_ma5_direction == "🟢" and vol_status in ("縮", "平"):
        return "突破前夕"
    elif platform_days >= 3:
        return "高檔收斂中"
    else:
        return "整理中"


def detect_one(
    bars_df: pd.DataFrame,
    target_date: str,
    cfg: dict | None = None,
) -> dict | None:
    """單一 ticker 偵測，回傳結果 dict 或 None（不符合）.

    Parameters
    ----------
    bars_df     : standard_daily_bar 資料，已按 trade_date 升冪排序
    target_date : 'YYYY-MM-DD'
    cfg         : 篩選設定，預設 DEFAULT_CFG

    Returns
    -------
    dict 或 None
    """
    if cfg is None:
        cfg = DEFAULT_CFG

    if bars_df.empty:
        return None

    # 取目標日 row
    target_rows = bars_df[bars_df["trade_date"] == target_date]
    if target_rows.empty:
        return None

    today_idx = bars_df.index.get_loc(target_rows.index[-1])
    row = target_rows.iloc[-1]

    # 基本欄位
    ticker = str(row.get("ticker", ""))
    close  = float(row["close"]) if pd.notna(row["close"]) else None
    volume = float(row["volume"]) if pd.notna(row["volume"]) else None
    ma5    = float(row["ma5"])  if pd.notna(row.get("ma5"))  else None
    ma10   = float(row["ma10"]) if pd.notna(row.get("ma10")) else None
    ma20   = float(row["ma20"]) if pd.notna(row.get("ma20")) else None
    ma60   = float(row["ma60"]) if pd.notna(row.get("ma60")) else None

    if close is None or volume is None:
        return None

    # 最少歷史天數
    if len(bars_df) < cfg.get("min_bars", 65):
        return None

    closes = bars_df["close"].reset_index(drop=True)

    # ── 1. 高檔狀態：close >= 60日高點 * (1 - tolerance%) ───────────────────
    lookback_60 = min(60, today_idx + 1)
    high_60 = float(closes.iloc[max(0, today_idx - 59): today_idx + 1].max())
    tol = cfg.get("high_tolerance_pct", 8.0) / 100
    is_high_zone = (close >= high_60 * (1 - tol))
    if not is_high_zone:
        return None

    # ── 2. 平台收斂：近 N 日 close range < range_pct% ───────────────────────
    N = cfg.get("platform_days", 7)
    range_pct = cfg.get("range_pct", 5.0)

    if today_idx < N - 1:
        return None

    recent_closes = closes.iloc[today_idx - N + 1: today_idx + 1]
    recent_range_pct = (float(recent_closes.max()) - float(recent_closes.min())) / close * 100
    is_platform = recent_range_pct < range_pct
    if not is_platform:
        return None

    # ── 3. MA5 扣抵向上：close[-1] > close[-6] ──────────────────────────────
    if cfg.get("require_ma5_kou_up", True):
        if today_idx < 5:
            return None
        ma5_kou_close = float(closes.iloc[today_idx - 5])
        ma5_kou_up = close > ma5_kou_close
        ma5_kou_direction = "🟢" if (close - ma5_kou_close) / ma5_kou_close * 100 > 0.5 else (
            "🔴" if (close - ma5_kou_close) / ma5_kou_close * 100 < -0.5 else "🟡"
        )
        if not ma5_kou_up:
            return None
    else:
        ma5_kou_direction = None

    # ── 4. 量縮：vol_ratio_20 < vol_ratio_max ───────────────────────────────
    vol_ratio = _compute_vol_ratio(bars_df.reset_index(drop=True), today_idx)
    vol_ratio_max = cfg.get("vol_ratio_max", 1.3)
    if vol_ratio is not None and vol_ratio >= vol_ratio_max:
        return None

    # 量狀態標籤
    if vol_ratio is None:
        vol_status = "未知"
    elif vol_ratio < 1.0:
        vol_status = "縮"
    elif vol_ratio < 1.3:
        vol_status = "平"
    else:
        vol_status = "量增"

    # ── 5. 多頭（鬆）：close > MA10 ─────────────────────────────────────────
    if cfg.get("require_above_ma10", True):
        if ma10 is None or close < ma10:
            return None

    # ── 6. 收盤 > MA20 ──────────────────────────────────────────────────────
    if cfg.get("require_above_ma20", True):
        if ma20 is None or close < ma20:
            return None

    # ── small_structure info layer ───────────────────────────────────────────

    # 連續平台天數（用展開方式計算）
    continuous_days = _compute_platform_days(
        closes, today_idx, range_pct
    )

    # 訊號標籤
    signal = _signal_label(
        platform_days=continuous_days,
        kou_ma5_direction=ma5_kou_direction,
        vol_status=vol_status,
        closes=closes,
        today_idx=today_idx,
        platform_days_cfg=N,
    )

    # 距 60日高點 %
    dist_from_high_60_pct = (high_60 - close) / high_60 * 100 if high_60 > 0 else None

    small_structure = {
        "is_high_consolidation": dist_from_high_60_pct is not None and dist_from_high_60_pct < 8.0,
        "dist_from_high_60_pct": round(dist_from_high_60_pct, 1) if dist_from_high_60_pct is not None else None,
        "range_pct_nd": round(recent_range_pct, 1),
        "platform_days": continuous_days,
        "vol_status": vol_status,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "kou_ma5": ma5_kou_direction,
        "signal": signal,
    }

    return {
        "ticker":          ticker,
        "close":           round(close, 2),
        "high_60":         round(high_60, 2),
        "ma5":             round(ma5, 2) if ma5 else None,
        "ma10":            round(ma10, 2) if ma10 else None,
        "ma20":            round(ma20, 2) if ma20 else None,
        "ma60":            round(ma60, 2) if ma60 else None,
        "vol_lots":        round(volume / 1000, 0),
        "small_structure": small_structure,
    }


# ── 全市場掃描 ────────────────────────────────────────────────────────────────

def run_scan(
    target_date: str,
    db_path: Path = _DB,
    cfg: dict | None = None,
    with_kou: bool = True,
    with_coil: bool = True,
) -> list[dict]:
    """掃描全市場，回傳命中的 ticker 清單（含 info layer）.

    Parameters
    ----------
    target_date : 'YYYY-MM-DD'
    db_path     : SQLite 資料庫路徑
    cfg         : 篩選設定，預設 DEFAULT_CFG
    with_kou    : 是否計算扣抵值（info layer）
    with_coil   : 是否計算均線糾纏（info layer）
    """
    if cfg is None:
        cfg = DEFAULT_CFG

    # 先做 SQL 預篩以減少 Python 迴圈量
    # 條件：close >= ma20、close >= ma10、volume > 0、ma5/ma10/ma20/ma60 不為 null
    pre_filter_sql = """
        SELECT DISTINCT b.ticker
        FROM standard_daily_bar b
        WHERE b.trade_date = ?
          AND b.ma5 IS NOT NULL
          AND b.ma10 IS NOT NULL
          AND b.ma20 IS NOT NULL
          AND b.ma60 IS NOT NULL
          AND b.close >= b.ma10
          AND b.close >= b.ma20
          AND b.volume > 0
    """

    try:
        con = sqlite3.connect(_db_uri(db_path), uri=True, timeout=30)
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e).lower():
            print("[ERROR] DB locked — 立刻停止", file=sys.stderr)
            sys.exit(1)
        raise

    stock_names = _load_stock_info(con)

    pre_tickers = [
        r[0] for r in con.execute(pre_filter_sql, (target_date,)).fetchall()
        if r[0].isdigit()
    ]

    results: list[dict] = []

    for ticker in pre_tickers:
        bars_df = pd.read_sql(
            """
            SELECT trade_date, open, high, low, close, volume,
                   ma5, ma10, ma20, ma60
            FROM standard_daily_bar
            WHERE ticker = ?
              AND trade_date >= date(?, '-250 days')
              AND trade_date <= ?
            ORDER BY trade_date
            """,
            con,
            params=(ticker, target_date, target_date),
        )

        if bars_df.empty:
            continue

        bars_df["ticker"] = ticker

        hit = detect_one(
            bars_df=bars_df,
            target_date=target_date,
            cfg=cfg,
        )

        if hit is None:
            continue

        hit["name"] = stock_names.get(ticker, "")

        # ── Info Layer 1：扣抵值 ──────────────────────────────────────────
        if with_kou:
            hit["kou_value"] = compute_kou_block(bars_df, target_date)
        else:
            hit["kou_value"] = None

        # ── Info Layer 2：均線糾纏 ────────────────────────────────────────
        if with_coil:
            hit["ma_state"] = compute_ma_state(
                ma5=hit.get("ma5"),
                ma10=hit.get("ma10"),
                ma20=hit.get("ma20"),
                close=hit["close"],
            )
        else:
            hit["ma_state"] = None

        # ── Info Layer 3：組合訊號 ────────────────────────────────────────
        if with_kou and with_coil and hit.get("kou_value") and hit.get("ma_state"):
            hit["signal_combo"] = compute_signal_combo(
                close=hit["close"],
                ma20=hit.get("ma20"),
                ma60=hit.get("ma60"),
                ma_state=hit["ma_state"],
                kou_block=hit["kou_value"],
                ma5=hit.get("ma5"),
                ma10=hit.get("ma10"),
            )
        else:
            hit["signal_combo"] = None

        results.append(hit)

    con.close()

    # 排序：訊號優先度 > 平台天數↓ > 量縮比例↓
    signal_order = {"突破前夕": 0, "已突破": 1, "高檔收斂中": 2, "整理中": 3}
    results.sort(key=lambda x: (
        signal_order.get(x["small_structure"]["signal"], 99),
        -(x["small_structure"]["platform_days"]),
        x["small_structure"]["vol_ratio"] or 99,
    ))

    return results


# ── 輸出格式 ──────────────────────────────────────────────────────────────────

def _fmt_kou(kv: dict | None) -> str:
    if kv is None:
        return "—"
    return f"{kv['direction']} {kv['diff_pct']:+.1f}%"


def _render_markdown(hits: list[dict], target_date: str, cfg: dict) -> str:
    lines: list[str] = []
    lines.append(f"## 📊 高檔收斂後平台 (Mode C) — {target_date}")
    lines.append(f"命中 **{len(hits)}** 檔")
    lines.append("")
    lines.append("### 篩選條件設定")
    lines.append(f"- 距 60 日高點容忍度: {cfg.get('high_tolerance_pct')}%")
    lines.append(f"- 平台觀察天數 N: {cfg.get('platform_days')}")
    lines.append(f"- 平台 range 上限: {cfg.get('range_pct')}%")
    lines.append(f"- 量縮上限 (vol_ratio_20): {cfg.get('vol_ratio_max')}")
    lines.append(f"- 要求 close > MA10: {cfg.get('require_above_ma10')}")
    lines.append(f"- 要求 close > MA20: {cfg.get('require_above_ma20')}")
    lines.append("")

    if not hits:
        lines.append("_沒有命中標的_")
        return "\n".join(lines)

    header = "| 代號 | 名稱 | 收盤 | 60日高 | 距高% | 平台天 | Range% | 量狀態 | MA5扣 | 訊號 |"
    sep    = "|------|------|-----:|-------:|------:|-------:|-------:|--------|------|------|"
    lines.append(header)
    lines.append(sep)

    for h in hits:
        ss = h["small_structure"]
        dist_h = f"-{ss['dist_from_high_60_pct']:.1f}%" if ss.get("dist_from_high_60_pct") is not None else "—"
        range_s = f"{ss['range_pct_nd']:.1f}%"
        lines.append(
            f"| {h['ticker']} | {h.get('name', '')} | {h['close']:.1f} "
            f"| {h['high_60']:.1f} | {dist_h} "
            f"| {ss['platform_days']} | {range_s} "
            f"| {ss['vol_status']} | {ss['kou_ma5'] or '—'} | {ss['signal']} |"
        )

    # Info Layer 詳情
    has_kou  = any(h.get("kou_value") for h in hits)
    has_coil = any(h.get("ma_state") for h in hits)
    if has_kou or has_coil:
        lines.append("")
        lines.append("### 扣抵值 & 均線糾纏（Info Layer）")
        for h in hits:
            lines.append(f"\n**{h['ticker']} {h.get('name', '')}**  收盤={h['close']:.2f}  "
                         f"訊號=【{h['small_structure']['signal']}】")
            kv = h.get("kou_value")
            ms = h.get("ma_state")
            sc = h.get("signal_combo")
            if kv:
                ma5k  = _fmt_kou(kv.get("ma5"))
                ma10k = _fmt_kou(kv.get("ma10"))
                ma20k = _fmt_kou(kv.get("ma20"))
                ma60k = _fmt_kou(kv.get("ma60"))
                lines.append(f"  扣抵: MA5={ma5k}  MA10={ma10k}  MA20={ma20k}  MA60={ma60k}")
            if ms and ms.get("spread_pct") is not None:
                coil_flag = "⭐" if ms["is_coil"] else ""
                lines.append(
                    f"  均線糾纏: {ms['label']}{coil_flag}  spread={ms['spread_pct']:.2f}%  "
                    f"MA5={ms['ma_values'].get('ma5', '—')}  MA10={ms['ma_values'].get('ma10', '—')}  "
                    f"MA20={ms['ma_values'].get('ma20', '—')}"
                )
            if sc:
                lines.append(f"  組合訊號: 【{sc['label']}】")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="高檔收斂後平台 scanner (Mode C) — 老師 5/20 N字上攻教學"
    )
    p.add_argument("--date", default=None,
                   help="目標日期 YYYY-MM-DD，預設今日")
    p.add_argument("--db", default=str(_DB),
                   help="SQLite 資料庫路徑")
    p.add_argument("--platform-days", type=int, default=None,
                   help="平台觀察天數 N（預設 7）")
    p.add_argument("--high-tolerance", type=float, default=None,
                   help="距 60 日高點容忍度 %%（預設 8）")
    p.add_argument("--range-pct", type=float, default=None,
                   help="平台 close range 上限 %%（預設 5）")
    p.add_argument("--vol-ratio-max", type=float, default=None,
                   help="量縮上限 vol_ratio_20（預設 1.3）")
    p.add_argument("--with-kou", action=argparse.BooleanOptionalAction, default=True,
                   help="計算扣抵值（預設開啟）")
    p.add_argument("--with-coil", action=argparse.BooleanOptionalAction, default=True,
                   help="計算均線糾纏（預設開啟）")
    p.add_argument("--debug", action="store_true",
                   help="顯示詳細診斷")
    return p.parse_args()


def _build_cfg(args: argparse.Namespace) -> dict:
    cfg = dict(DEFAULT_CFG)
    if args.platform_days is not None:
        cfg["platform_days"] = args.platform_days
    if args.high_tolerance is not None:
        cfg["high_tolerance_pct"] = args.high_tolerance
    if args.range_pct is not None:
        cfg["range_pct"] = args.range_pct
    if args.vol_ratio_max is not None:
        cfg["vol_ratio_max"] = args.vol_ratio_max
    return cfg


def main() -> None:
    from datetime import date as _date

    args = _parse_args()
    target_date = args.date or _date.today().strftime("%Y-%m-%d")
    db_path = Path(args.db)
    cfg = _build_cfg(args)

    with_kou  = getattr(args, "with_kou", True)
    with_coil = getattr(args, "with_coil", True)

    print(f"掃描日期: {target_date}")
    print(f"設定: platform_days={cfg['platform_days']} range_pct={cfg['range_pct']}% "
          f"high_tolerance={cfg['high_tolerance_pct']}% vol_ratio_max={cfg['vol_ratio_max']}")
    print()

    hits = run_scan(
        target_date=target_date,
        db_path=db_path,
        cfg=cfg,
        with_kou=with_kou,
        with_coil=with_coil,
    )

    print(_render_markdown(hits, target_date, cfg))

    if args.debug and hits:
        print("\n### Debug 詳情")
        for h in hits:
            ss = h["small_structure"]
            print(f"\n{h['ticker']} {h.get('name', '')}: close={h['close']} "
                  f"high_60={h['high_60']} platform_days={ss['platform_days']} "
                  f"range={ss['range_pct_nd']}% vol={ss['vol_ratio']} signal={ss['signal']}")


if __name__ == "__main__":
    main()
