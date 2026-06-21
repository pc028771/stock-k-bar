"""WS 路徑驗證 — WebSocket 接收 + HTTP fallback (不打爆 rate limit)。

驗證 WS-1/WS-2:
  - WS tick (trades channel 格式) → WSPriceCache cache 正確更新 (close/high/low/vol)
  - WS stale → 批次 HTTP fallback 補 cache (1-2 req、節流、不逐檔打爆)

Usage: PYTHONPATH=scripts python -m zhuli.mock.ws_tests
"""
from __future__ import annotations
import logging
import sys
from datetime import time
from pathlib import Path

REPO = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
logging.disable(logging.CRITICAL)

from zhuli.mock import DataProvider, MockFubonClient
from zhuli.live_position_monitor import WSPriceCache


def _ws(date="2026-06-18", tickers=("2330", "1303")):
    dp = DataProvider()
    client = MockFubonClient(dp, date)
    client.set_clock(time(13, 30))                 # 全日資料、warm 有值
    ws = WSPriceCache(client, list(tickers))
    return dp, client, ws


def test_ws_receive():
    dp, client, ws = _ws()
    try:
        # 推一筆 trades tick → cache 應更新
        client.emit_ws_trade("2330", price=999.0, volume_shares=5_000_000,
                             bid=998.0, ask=999.0)
        snap = ws.get_realtime_snapshot("2330")
        assert snap and snap["close"] == 999.0, f"close 未更新: {snap}"
        assert snap["high"] >= 999.0, "high 未維護"
        assert snap["total_volume"] == 5000, f"量單位錯 (應 5M//1000=5000): {snap['total_volume']}"
        # 再推更高價 → high 跟上、close 更新
        client.emit_ws_trade("2330", price=1010.0, volume_shares=5_100_000)
        snap2 = ws.get_realtime_snapshot("2330")
        assert snap2["close"] == 1010.0 and snap2["high"] >= 1010.0, "第二筆未更新"
        print("WS 接收: ✅ (trades tick → close/high/low/量 正確)")
    finally:
        dp.close()


def test_ws_fallback_batch():
    dp, client, ws = _ws()
    try:
        client._batch_calls = 0
        # 強制全 cache stale (WS 全掛模擬)
        with ws.lock:
            for tk in ws.tickers:
                ws.last_update[tk] = 0.0
        # 股票 stale → 走批次 fallback (不逐檔)
        snap = ws.get_realtime_snapshot("2330")
        assert client._batch_calls == 1, f"應走批次 1 次、實際 {client._batch_calls}"
        assert snap is not None, "批次 fallback 應補到值"
        # 節流: 8s 內第二次 stale 不該再 batch (防打爆)
        with ws.lock:
            ws.last_update["1303"] = 0.0
        ws.get_realtime_snapshot("1303")
        assert client._batch_calls == 1, f"節流失效、batch 被多打 {client._batch_calls} 次"
        print("WS fallback: ✅ (批次 1 req 補全 / 節流防打爆、非逐檔)")
    finally:
        dp.close()


def test_multitf_bars():
    """WS-4: tick → 2分/3分 K 聚合正確 + 分桶錨定 09:00。"""
    from datetime import datetime, date as _D
    from zhuli.live_position_monitor import MultiTFBarBuilder
    b = MultiTFBarBuilder(timeframes=(2, 3))
    d = _D(2026, 6, 18)
    # 09:00, 09:01 → 同 2分桶(09:00) 同 3分桶(09:00)；09:02 → 新 2分桶、仍同 3分桶
    b.add_tick("2330", 100.0, 1000, datetime.combine(d, time(9, 0)))
    b.add_tick("2330", 105.0, 1500, datetime.combine(d, time(9, 1)))   # 同桶、high=105
    b.add_tick("2330", 102.0, 2000, datetime.combine(d, time(9, 2)))   # 2分新桶 / 3分同桶
    bars2 = b.get_bars("2330", 2)
    bars3 = b.get_bars("2330", 3)
    # 2分K: 09:00 桶 (O100 H105 L100 C105 量 500=1500-1000)、09:02 桶
    assert len(bars2) == 2, f"2分K 應 2 桶: {bars2}"
    assert bars2[0]["ts"] == "09:00" and bars2[0]["high"] == 105.0, bars2[0]
    assert bars2[0]["volume"] == 500, f"量 delta 錯: {bars2[0]['volume']}"
    assert bars2[1]["ts"] == "09:02", bars2[1]
    # 3分K: 三筆全在 09:00 桶 (H105 C102 量 1000)
    assert len(bars3) == 1 and bars3[0]["ts"] == "09:00", bars3
    assert bars3[0]["high"] == 105.0 and bars3[0]["close"] == 102.0, bars3[0]
    assert bars3[0]["volume"] == 1000, f"3分量 delta 錯: {bars3[0]['volume']}"
    print("WS-4 2分/3分K: ✅ (分桶錨定09:00 / OHLC / 量delta 正確)")


def test_snap_parse_both_schemas():
    """富邦官方 schema: 單檔 total.tradeVolume(巢狀) vs 批次 tradeVolume(平的)、都要吃。"""
    from common.clients.fubon_client import _snap_from_quote
    nested = {"closePrice": 100.0, "openPrice": 99.0, "highPrice": 101.0,
              "lowPrice": 98.0, "total": {"tradeVolume": 5_000_000, "tradeValue": 5e8}}
    flat = {"symbol": "2330", "closePrice": 100.0, "openPrice": 99.0,
            "highPrice": 101.0, "lowPrice": 98.0,
            "tradeVolume": 5_000_000, "tradeValue": 5e8}     # snapshot/quotes 形狀
    sn, sf = _snap_from_quote(nested), _snap_from_quote(flat)
    assert sn["total_volume"] == 5000, f"巢狀量錯: {sn}"
    assert sf["total_volume"] == 5000, f"平的量錯 (批次 bug): {sf}"
    assert sf["close"] == 100.0 and sf["open"] == 99.0, sf
    print("snap 雙 schema: ✅ (巢狀 total + 批次平 tradeVolume 都正確、富邦 doc 驗證)")


def test_ws_trades_doc_envelope():
    """富邦官方 trades doc example 原樣餵 _on_message、確認 envelope+欄位解析無 drift。"""
    dp, client, ws = _ws()
    try:
        # 富邦 doc Receive data 範例 (symbol/price/volume/bid/ask)
        doc_msg = {"event": "data", "data": {
            "symbol": "2330", "type": "EQUITY", "exchange": "TWSE", "market": "TSE",
            "bid": 567, "ask": 568, "price": 568, "size": 4778, "volume": 54538,
            "isClose": True, "time": 1685338200000000, "serial": 6652422},
            "id": "X", "channel": "trades"}
        ws._on_message(doc_msg)
        snap = ws.get_realtime_snapshot("2330")
        assert snap["close"] == 568, f"price→close 解析錯: {snap}"
        assert snap["total_volume"] == 54, f"volume 54538股//1000=54張、得 {snap['total_volume']}"
        assert snap.get("bid") == 567 and snap.get("ask") == 568, snap
        # 非 data event 應略過
        ws._on_message({"event": "pong"})
        print("WS trades doc envelope: ✅ (官方 example 原樣解析正確、無 drift)")
    finally:
        dp.close()


def main():
    test_ws_receive()
    test_ws_fallback_batch()
    test_multitf_bars()
    test_snap_parse_both_schemas()
    test_ws_trades_doc_envelope()
    print("WS tests: 全通過")


if __name__ == "__main__":
    main()
