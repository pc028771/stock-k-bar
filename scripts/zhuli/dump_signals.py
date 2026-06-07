"""持倉拉高出貨即時訊號評估 (v2 helper).

從 holdings_dump_monitor.py 移植 6 個出貨訊號:
  1. 跌破停損 (stop_loss vs current)
  2. 開盤跳空 +3% 拉低 ≤ 0% (主力倒貨)
  3. 上影 5%+ 出貨 (高檔)
  4. 破 MA5 / 跌破 MA10 (依部位 size 分級)
  5. 12 點殺盤未恢復 (12:30+)
  6. 出貨 A/B/C (量比 + 方向)

設計:
  - DumpStateTracker: per-ticker open/day_high/day_low/vol_minute、thread-safe (Lock)
  - evaluate_dump_signals(): 純函式、回傳 warning list[str]
  - State persisted to /tmp/dump_signals_state.json (date check、重啟保留量比)

不依賴 textual、可在 background refresh thread 直接呼叫。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

STATE_FILE = Path("/tmp/dump_signals_state.json")

# Position size threshold: 張數 × cost × 1000 ≥ 300_000 → 中大部位 (老師 5/28「破 MA5」規則)
_POSITION_VALUE_THRESHOLD = 300_000


def get_spike_threshold(now: datetime | None = None) -> tuple[float | None, str]:
    """依時段回 (spike threshold 倍數, 時段名). 回 (None, name) = 該時段忽略量比."""
    now = now or datetime.now()
    hm = now.hour * 100 + now.minute
    if 900 <= hm < 910:
        return None, "開盤"
    if 910 <= hm < 930:
        return 2.5, "早盤"
    if 930 <= hm < 1130:
        return 2.0, "中盤"
    if 1130 <= hm < 1230:
        return 1.8, "午盤"
    if 1230 <= hm < 1300:
        return 2.0, "殺盤窗"
    if 1300 <= hm < 1325:
        return 3.0, "尾盤"
    if 1325 <= hm < 1330:
        return None, "試撮"
    return 2.0, "盤外"


class DumpStateTracker:
    """Per-ticker intraday state (open / day_high / day_low / cumulative vol /
    vol_minute history). Thread-safe via internal Lock。

    Usage:
        tracker = DumpStateTracker(tickers=['1234', '5678'])
        tracker.update_tick('1234', price=39.5, cum_volume=1234567)
        state = tracker.get_state('1234')   # dict snapshot
        warnings = evaluate_dump_signals('1234', state, item, baseline)
    """

    def __init__(self, tickers: list[str] | None = None):
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}
        self._last_save: float = 0.0
        self._last_cum_volume: dict[str, float] = {}

        # Load persisted state (only if same date)
        prev: dict = {}
        today = datetime.now().strftime("%Y-%m-%d")
        if STATE_FILE.exists():
            try:
                saved = json.loads(STATE_FILE.read_text())
                if saved.get("date") == today:
                    prev = saved.get("state", {}) or {}
            except Exception:
                prev = {}

        if tickers:
            for t in tickers:
                self._state[t] = prev.get(t) or self._empty_state()
        else:
            self._state.update({k: v for k, v in prev.items()})

    @staticmethod
    def _empty_state() -> dict:
        return {
            "open": None,
            "day_high": None,
            "day_low": None,
            "last_price": None,
            "last_update": None,
            "vol_minute": {},  # "YYYY-MM-DD HH:MM" -> volume delta (shares)
        }

    def ensure(self, ticker: str) -> None:
        """確保 ticker 有 state entry (lazy init)。"""
        with self._lock:
            if ticker not in self._state:
                self._state[ticker] = self._empty_state()

    def update_tick(
        self,
        ticker: str,
        price: float | None,
        cum_volume: float | None = None,
        now: datetime | None = None,
    ) -> None:
        """更新 ticker 的當日 high/low + 分鐘量。

        cum_volume = 當日累計量 (snap 回傳的 total_volume)、內部會算 delta。
        若 price 為 None / 0 直接跳過。
        """
        if not price:
            return
        now = now or datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")

        with self._lock:
            s = self._state.get(ticker)
            if s is None:
                s = self._empty_state()
                self._state[ticker] = s

            if s.get("open") is None:
                s["open"] = price
            hi = s.get("day_high")
            lo = s.get("day_low")
            s["day_high"] = price if hi is None else max(hi, price)
            s["day_low"] = price if lo is None else min(lo, price)
            s["last_price"] = price
            s["last_update"] = now.strftime("%H:%M:%S")

            # Volume delta from cumulative (per-ticker)
            if cum_volume is not None:
                prev_cum = self._last_cum_volume.get(ticker)
                delta = 0
                if prev_cum is not None and cum_volume >= prev_cum:
                    delta = int(cum_volume - prev_cum)
                self._last_cum_volume[ticker] = cum_volume
                if delta > 0:
                    vm = s.setdefault("vol_minute", {})
                    vm[minute_key] = vm.get(minute_key, 0) + delta
                    # cap memory: keep last 30 minutes
                    if len(vm) > 30:
                        oldest = sorted(vm.keys())[:-30]
                        for k in oldest:
                            del vm[k]

        self._maybe_save()

    def get_state(self, ticker: str) -> dict:
        """回傳該 ticker state 的 shallow copy (snapshot)。沒資料回 empty dict。"""
        with self._lock:
            s = self._state.get(ticker)
            if s is None:
                return self._empty_state()
            return {
                "open": s.get("open"),
                "day_high": s.get("day_high"),
                "day_low": s.get("day_low"),
                "last_price": s.get("last_price"),
                "last_update": s.get("last_update"),
                "vol_minute": dict(s.get("vol_minute", {})),
            }

    def get_volume_spike(self, ticker: str) -> tuple[int, float, float]:
        """回傳 (本分鐘量, 過去 10 分鐘平均量, 倍數)。資料不足回 (0, 0, 0)。"""
        with self._lock:
            s = self._state.get(ticker)
            if s is None:
                return 0, 0.0, 0.0
            vm = dict(s.get("vol_minute", {}))
        if len(vm) < 2:
            return 0, 0.0, 0.0
        sorted_keys = sorted(vm.keys())
        current_key = sorted_keys[-1]
        prev_keys = sorted_keys[-11:-1]
        cur_vol = vm[current_key]
        if not prev_keys:
            return cur_vol, 0.0, 0.0
        avg_vol = sum(vm[k] for k in prev_keys) / len(prev_keys)
        ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0
        return cur_vol, avg_vol, ratio

    def _maybe_save(self) -> None:
        """Throttled save (every 5s)。"""
        now = time.time()
        if now - self._last_save < 5:
            return
        try:
            with self._lock:
                snapshot = {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "state": {k: v for k, v in self._state.items()},
                }
            STATE_FILE.write_text(json.dumps(snapshot))
            self._last_save = now
        except Exception:
            pass


def evaluate_dump_signals(
    ticker: str,
    state: dict,
    item: dict,
    baseline: dict,
    current_close: float | None = None,
    volume_spike: tuple[int, float, float] | None = None,
    now: datetime | None = None,
) -> list[str]:
    """評估該檔當前出貨訊號、回傳警示 list[str]。

    Args:
        ticker: stock code
        state:  tracker.get_state(ticker) 的回傳 (open/day_high/day_low/vol_minute)
        item:   held item dict (要有 stop / shares / cost)
        baseline: {ticker: {yesterday_close, ma5, ma10, ...}} 從 baseline_snapshot.json
        current_close: 現價 (若 None、用 state['last_price'])
        volume_spike: (cur_vol, avg_vol, ratio) — 由 caller 從 tracker 取
        now: 用於 12 點殺盤判定 + spike threshold band

    Returns:
        list[str] of warnings。若無訊號回 []。
    """
    warnings: list[str] = []
    now = now or datetime.now()

    cur = current_close if current_close is not None else state.get("last_price")
    if not cur:
        return warnings

    b = baseline.get(ticker, {}) if baseline else {}
    yc = b.get("yesterday_close", 0) or 0
    ma5 = b.get("ma5", 0) or 0
    ma10 = b.get("ma10", 0) or 0

    op = state.get("open")
    hi = state.get("day_high")
    lo = state.get("day_low")

    stop = item.get("stop")
    if stop is None:
        stop = item.get("stop_loss")

    # 1. 跌破停損
    if stop and isinstance(stop, (int, float)) and cur < stop:
        warnings.append(f"🚨 跌破停損 ${stop}")

    # 2. 開盤跳空 +3% 拉低 ≤ 0%
    if op and yc:
        gap_pct = (op - yc) / yc * 100
        cur_vs_yc = (cur - yc) / yc * 100
        if gap_pct >= 3 and cur_vs_yc <= 0:
            warnings.append(f"🚨 跳空 +{gap_pct:.1f}% 拉回 {cur_vs_yc:+.1f}% (主力倒貨)")
        elif gap_pct >= 5:
            warnings.append(f"⚠️ 跳空 +{gap_pct:.1f}% (注意拉回)")

    # 3. 上影 5%+ (高檔出貨)
    if op and hi:
        upper_shadow_pct = (hi - cur) / op * 100
        if upper_shadow_pct >= 5:
            warnings.append(f"⚠️ 上影 {upper_shadow_pct:.1f}% (高檔出貨)")

    # 4a. 破 MA5 (老師 5/28: 中大部位汰弱、小部位不用動)
    if ma5 and cur < ma5:
        shares = item.get("shares", 0) or 0
        cost = item.get("cost", 0) or 0
        position_value = shares * cost * 1000
        if position_value >= _POSITION_VALUE_THRESHOLD:
            warnings.append(f"⚠️ 破 MA5 ${ma5:.2f} (中大部位、汰弱?)")
        else:
            warnings.append(f"📌 破 MA5 ${ma5:.2f} (小部位、老師說不用動)")

    # 4b. 跌破 MA10
    if ma10 and cur < ma10:
        warnings.append(f"⚠️ 現價 < MA10 ${ma10:.2f}")

    # 5. 12 點殺盤未恢復 (12:30+)
    if now.hour == 12 and now.minute >= 30:
        if lo and op:
            dip = (op - lo) / op * 100
            recovery = (cur - lo) / lo * 100 if lo > 0 else 0
            if dip >= 1.5 and recovery < 0.5:
                warnings.append(f"⚠️ 12 點殺 {dip:.1f}% 未恢復")

    # 6. 出貨 A/B/C (量比 + 方向)
    if volume_spike is not None:
        _cur_vol, _avg_vol, ratio = volume_spike
        threshold, band = get_spike_threshold(now)
        if threshold is not None and op and hi and ratio > 0:
            move_pct = (cur - op) / op * 100
            high_dist = (hi - cur) / op * 100

            if ratio >= threshold and move_pct <= -1:
                warnings.append(f"🚨 出貨A: {band}急量 {ratio:.1f}x + 跌 {move_pct:+.1f}%")
            elif ratio >= threshold and high_dist >= 2:
                warnings.append(
                    f"🚨 出貨B: {band}急量 {ratio:.1f}x、衝高 ${hi:.2f} 回吐 -{high_dist:.1f}%"
                )
            elif band == "尾盤" and ratio >= 1.5 and move_pct <= -0.5:
                warnings.append(f"🚨 出貨C: 尾盤殺量 {ratio:.1f}x + 跌 {move_pct:+.1f}%")
            elif ratio >= threshold:
                warnings.append(f"⚠️ {band}量放 {ratio:.1f}x (觀察方向)")

    return warnings


def load_baseline(baseline_path: Path) -> dict[str, dict[str, Any]]:
    """讀 baseline_snapshot.json、回傳 {ticker: {yesterday_close, ma5, ma10, ...}}.

    缺檔回 {} (caller 自行降級處理、不會 raise)。
    """
    if not baseline_path.exists():
        return {}
    try:
        snap = json.loads(baseline_path.read_text())
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for t, d in (snap.get("tickers") or {}).items():
        out[t] = {
            "yesterday_date": d.get("yesterday_date"),
            "yesterday_close": d.get("yesterday_close"),
            "yesterday_high": d.get("yesterday_high"),
            "yesterday_low": d.get("yesterday_low"),
            "ma5": d.get("ma5"),
            "ma10": d.get("ma10"),
        }
    return out
