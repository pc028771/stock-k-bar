"""WS 真實連線驗證 — 週一盤中跑一次、確認 doc 假設對真實 Fubon API。

⚠️ 只在平日盤中 (09:00-13:30) 跑才有意義 (盤後 WS 不推、snapshot 空值)。
只讀行情、不下單。

驗證項目 (對應 Opus review 的未驗點 + doc 驗證):
  1. WS 連線 ws_ok + 收不收得到 trades tick
  2. 🔴 volume 單位絕對值: get_realtime_snapshot total_volume 是不是「張」
     (跟 DB 當日 daily volume 比、應同量級;若 1000x 差 = 單位錯)
  3. 批次 get_snapshot_quotes_map: 真實欄位名 (symbol/closePrice/tradeVolume 平的?)
  4. WS push: 等幾秒看 cache 有沒有被 WS 更新 (last_update 變新)
  5. 旗標: 有沒有收到 isTrial/isLimitUp 等

Usage:
  PYTHONPATH=scripts python scripts/zhuli/verify_ws_live.py [ticker ...]
  (預設 2330 台積電 + 1303 南亞)
"""
from __future__ import annotations
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from zhuli.db import MAIN_DB


def _daily_volume(ticker: str) -> int | None:
    try:
        c = sqlite3.connect(str(MAIN_DB))
        r = c.execute("SELECT volume FROM standard_daily_bar WHERE ticker=? "
                      "ORDER BY trade_date DESC LIMIT 1", (ticker,)).fetchone()
        c.close()
        return int(r[0]) if r and r[0] else None
    except Exception:
        return None


def main():
    tickers = sys.argv[1:] or ["2330", "1303"]
    now = datetime.now()
    print(f"=== WS live 驗證 @ {now:%Y-%m-%d %H:%M:%S} ===")
    if not (now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (13, 30)):
        print("⚠️ 非盤中時段、WS/snapshot 可能無資料、結果僅供連線測試")

    from common.clients.fubon_client import FubonClient
    from zhuli.live_position_monitor import WSPriceCache

    print("[1] 建 FubonClient + 連線…")
    client = FubonClient()
    print("[2] 包 WSPriceCache + subscribe…")
    ws = WSPriceCache(client, tickers)
    print(f"    ws_ok = {ws.ws_ok}  (True=WS 連上)")

    # ── 3. 批次 snapshot 真實欄位 ──
    print("\n[3] get_snapshot_quotes_map 真實欄位 (確認 schema):")
    try:
        raw = client._reststock.snapshot.quotes(market="TSE")
        from common.clients.fubon_client import _extract_data
        rows = _extract_data(raw)
        if rows:
            print(f"    raw row keys: {sorted(rows[0].keys()) if isinstance(rows[0], dict) else dir(rows[0])}")
            print(f"    sample row: {rows[0]}")
    except Exception as e:
        print(f"    批次取樣失敗: {e}")

    # ── 4. WS push: 等 8 秒看 cache 更新 ──
    print("\n[4] 等 8 秒收 WS tick…")
    t0 = {tk: ws.last_update.get(tk, 0) for tk in tickers}
    time.sleep(8)
    for tk in tickers:
        moved = ws.last_update.get(tk, 0) > t0[tk]
        print(f"    {tk}: WS 更新={'✅' if moved else '❌ (沒收到 tick)'}")

    # ── 2. 🔴 volume 單位絕對值 ──
    print("\n[2] 🔴 volume 單位驗證 (total_volume 是不是『張』):")
    for tk in tickers:
        snap = ws.get_realtime_snapshot(tk)
        dv = _daily_volume(tk)
        if snap:
            tv = snap.get("total_volume")
            print(f"    {tk}: WS total_volume = {tv} 張?")
            if dv:
                # daily volume 是「股」、換算張 = dv/1000;盤中累積量應 ≤ 整日量
                print(f"         DB 前日 daily volume = {dv:,} 股 = {dv//1000:,} 張")
                if tv:
                    ratio = tv / (dv / 1000) if dv else 0
                    verdict = ("✅ 量級合理 (張)" if 0.01 < ratio < 3
                               else f"🔴 量級異常 ratio={ratio:.3f} (可能單位錯)")
                    print(f"         盤中量 / 前日量(張) = {ratio:.3f} → {verdict}")
            # 旗標
            flags = [k for k in ("is_trial", "limit_up", "limit_down", "is_close")
                     if snap.get(k)]
            print(f"         旗標: {flags or '(無)'} | close={snap.get('close')} "
                  f"high={snap.get('high')} low={snap.get('low')}")
        else:
            print(f"    {tk}: snap = None")

    print(f"\n[stats] WSPriceCache.stats() = {ws.stats()} (cached, stale, errors)")
    print("\n=== 驗證重點 ===")
    print("  - ws_ok=True + WS 更新✅ → WS 推播正常")
    print("  - volume ratio 合理(張) → C1 單位修正正確")
    print("  - 批次 row keys 含 symbol/closePrice/tradeVolume(平) → schema 對")
    try:
        client.disconnect()
    except Exception:
        pass


if __name__ == "__main__":
    main()
