"""層 1: Trigger detection unit tests.

針對核心 numpy trigger 函式做 synthetic bar fixture 測試。
每個 trigger 至少 3 cases: positive (應觸發) / negative (應不觸發) / edge (邊界)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── 路徑設定 ─────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.zhuli.intraday_stage_helper import (
    _check_trigger_1_np,
    _check_trigger_2_np,
    _check_trigger_c_np,
    _check_ch5_3_entry_np,
)


# ── 合成分 K 建構器 ───────────────────────────────────────────────────────────

def _synthetic_bars(scenario: str):
    """產生人工 5 分 K arrays，模擬不同 trigger 場景。

    回傳: (opens, highs, lows, closes, vols, times)
    times 為 HH:MM 字串 list。
    """
    # 通用基底: 09:00-13:25 共 54 根 (每 5 分鐘一根)
    # 基底價格: open=100、水平整理

    if scenario == '首攻_pass':
        # Ch5-3: 第一根紅K + 收 ≥ 前收 + 收 ≥ 開 + 實體 > 上影 + 漲幅 < 4% + 跳空 < 5%
        # 前收 = 99, open=100, close=102 (漲幅 2%) → 9:10 後過高 → confirmed
        opens  = np.array([100.0, 102.0, 102.5, 103.0])
        highs  = np.array([102.0, 103.0, 103.5, 104.0])
        lows   = np.array([ 99.5, 101.5, 102.0, 102.5])
        closes = np.array([102.0, 102.8, 103.2, 103.5])
        vols   = np.array([1000.0, 1200.0, 1100.0, 900.0])
        times  = ["09:00", "09:10", "09:15", "09:20"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '首攻_fail_not_red':
        # 第一根黑 K → 失敗
        opens  = np.array([100.0, 99.0, 99.0])
        highs  = np.array([101.0, 100.0, 100.0])
        lows   = np.array([ 98.5,  98.5,  98.0])
        closes = np.array([ 99.0,  99.5,  99.8])  # 第一根 close(99) < open(100) → 黑 K
        vols   = np.array([1000.0, 800.0, 900.0])
        times  = ["09:00", "09:10", "09:15"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '首攻_edge_gap_exactly_5pct':
        # 跳空恰好 5%: open=105, prev_close=100 → gap=5.0% → 失敗 (條件 < 5%)
        opens  = np.array([105.0, 106.0])
        highs  = np.array([107.0, 107.5])
        lows   = np.array([104.0, 105.5])
        closes = np.array([106.0, 107.0])
        vols   = np.array([1000.0, 1200.0])
        times  = ["09:00", "09:10"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '首攻_edge_rise_exactly_4pct':
        # 5K 漲幅恰好 4%: open=100, close=104 → rise_under_4 = False → 失敗
        opens  = np.array([100.0, 104.0])
        highs  = np.array([104.2, 105.0])
        lows   = np.array([ 99.5, 103.5])
        closes = np.array([104.0, 104.8])
        vols   = np.array([1000.0, 1200.0])
        times  = ["09:00", "09:10"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '首攻_weak_regime_pass':
        # 弱勢盤: 9:10-9:30 過高 (signal) → 後來回踩 MA10 守住 → confirmed
        # MA10 = 99, 第一根 open=100, high=103, close=102 (pass all conditions)
        # 9:15 過高 103 (signal), 9:20 回踩 MA10 99 (low=98.8) 並收紅 (close=100.2 > open=99)
        opens  = np.array([100.0, 102.5, 99.0,  99.0])
        highs  = np.array([103.0, 103.5, 99.5, 100.5])
        lows   = np.array([ 99.5, 102.0, 98.8,  98.5])
        closes = np.array([102.0, 103.2, 100.2, 100.5])  # close[2]=100.2 > open[2]=99 → 確認
        vols   = np.array([1000.0, 1200.0, 800.0, 900.0])
        times  = ["09:00", "09:15", "09:20", "09:25"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '續攻_pass':
        # T1: 連 2 紅K + 量增 1.5x + 距開盤 >1% + 站前波高
        # 用 n=25 根，最後 2 根紅K，量是平均 2x
        # 注意: 最後一根 close 不能太接近 day_high (≥ 1.5% 以下才不是 T1_watch)
        n = 25
        opens  = np.full(n, 100.0)
        highs  = np.full(n, 110.0)   # day_high = 110 (在前面的 bar)
        lows   = np.full(n,  99.5)
        closes = np.full(n, 100.5)
        vols   = np.full(n, 1000.0)
        times  = ["09:00"] * n
        # 設定最後 2 根為紅 K、close=102 << day_high=110 (距離 7.3% > 1.5%)
        opens[-2:]  = [99.0, 99.5]
        closes[-2:] = [101.0, 102.0]   # 紅 K，102 / 110 * 0.985 = 108.35 > 102 ✓
        highs[-2:]  = [102.5, 102.8]
        lows[-2:]   = [98.8,  99.3]
        # 量：最後一根大量
        vols[-1] = 3000.0  # 3x 均量
        # 距開盤 +2%: open_price=opens[0]=100, current_close=102 → +2% > 1%
        # 時間設定 9:48 後（避免 T1_watch 時段）
        times[-1] = "09:48"
        times[-2] = "09:43"
        return opens, highs, lows, closes, vols, times

    elif scenario == '續攻_fail_no_vol':
        # T1 條件: 連 2 紅 K 但量增不足
        n = 25
        opens  = np.full(n, 100.0)
        closes = np.full(n, 100.5)
        highs  = np.full(n, 101.0)
        lows   = np.full(n,  99.5)
        vols   = np.full(n, 1000.0)
        times  = ["09:30"] * n
        opens[-2:]  = [99.0, 99.5]
        closes[-2:] = [101.0, 102.0]
        vols[-1]    = 1100.0  # 只有 1.1x，不足 1.5x
        times[-1]   = "10:00"
        return opens, highs, lows, closes, vols, times

    elif scenario == '續攻_edge_at_9:45_watch':
        # T1 時間 9:30 (在 9:15-9:45 拉高出貨時段) → T1_watch
        n = 25
        opens  = np.full(n, 100.0)
        closes = np.full(n, 100.5)
        highs  = np.full(n, 101.0)
        lows   = np.full(n,  99.5)
        vols   = np.full(n, 1000.0)
        times  = ["09:00"] * n
        opens[-2:]  = [99.0, 99.5]
        closes[-2:] = [101.0, 102.0]
        highs[-2:]  = [102.0, 103.0]
        vols[-1]    = 3000.0
        times[-1]   = "09:30"  # 在 9:15-9:45 → T1_watch
        return opens, highs, lows, closes, vols, times

    elif scenario == '反彈_pass':
        # T2 路徑 A: 跌深 ≥ 2.5% + 連 3 紅K + 反彈 ≥ 1%
        # 日高 110 → 最低 107 (跌深 -2.73%) → 3 紅K 收在 108.2 (反彈 +1.12%)
        opens  = np.array([108.0, 110.0, 107.0, 107.1, 107.2, 107.8])
        highs  = np.array([111.0, 111.0, 108.0, 107.5, 107.8, 108.5])
        lows   = np.array([107.5, 109.5, 106.8, 106.9, 107.0, 107.5])
        closes = np.array([110.0, 110.5, 107.0, 107.3, 107.8, 108.2])
        # 後 3 根紅 K: close > open
        opens[-3:]  = [107.0, 107.2, 107.5]
        closes[-3:] = [107.3, 107.8, 108.2]
        vols   = np.array([2000.0, 3000.0, 1500.0, 1600.0, 1700.0, 1800.0])
        times  = ["09:00", "09:05", "09:30", "10:00", "10:05", "10:10"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '反彈_fail_not_deep_enough':
        # 跌深只有 -2.0%，不足 -2.5%
        opens  = np.array([100.0, 102.0, 100.5, 100.6, 100.7])
        highs  = np.array([102.0, 102.5, 101.0, 101.5, 102.0])
        lows   = np.array([ 99.5, 101.0, 100.0, 100.2, 100.5])
        closes = np.array([102.0, 102.0, 100.5, 101.0, 101.5])
        vols   = np.array([1000.0, 1500.0, 800.0, 900.0, 1000.0])
        times  = ["09:00", "09:05", "10:00", "10:05", "10:10"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '反彈_edge_exactly_2.5pct':
        # 跌深恰好 2.5%: intraday_high=100, 最低 97.5 → pullback=-2.5% 剛好觸發
        # 後 3 根紅K + 反彈 ≥ 1% (low=97.0, close=98.2 → rebound=1.24%)
        opens  = np.array([98.0, 100.0, 97.0, 97.1, 97.5, 97.8])
        highs  = np.array([100.0, 100.0, 97.6, 97.8, 98.0, 98.5])
        lows   = np.array([ 97.5,  99.5, 96.8, 96.9, 97.2, 97.5])
        closes = np.array([100.0, 100.0, 97.0, 97.3, 97.8, 98.2])
        # 後 3 根紅 K: close > open
        opens[-3:]  = [97.0, 97.2, 97.6]
        closes[-3:] = [97.3, 97.8, 98.2]
        # intraday_high = max(highs) = 100.0, last_low = lows[-1] = 97.5
        # pullback = (97.5 - 100.0) / 100.0 * 100 = -2.5%
        lows[-1] = 97.5
        vols   = np.array([1000.0, 2000.0, 800.0, 900.0, 1000.0, 1100.0])
        times  = ["09:00", "09:05", "10:00", "10:05", "10:10", "10:15"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '破底_pass':
        # TC: 跌破前波低 + 量爆 + 黑 K
        # prev_low = 98, current = 97.5 (破前波低)
        # 距 MA10 自 10 根均 closes ≈ 101 → 97.5/101-1 ≈ -3.47% ≤ -3%
        n = 15
        opens  = np.linspace(102, 101, n)
        highs  = opens + 1.0
        lows   = opens - 0.5
        closes = np.linspace(101, 100, n)
        # 最後一根: 黑 K + 量爆 + 跌破
        opens[-1]  = 99.0
        closes[-1] = 97.5   # 黑 K (97.5 < 99.0)
        highs[-1]  = 99.5
        lows[-1]   = 97.0
        vols   = np.full(n, 1000.0)
        vols[-1] = 3000.0   # 量爆 3x
        times  = ["09:30"] * n
        return opens, highs, lows, closes, vols, times

    elif scenario == '破底_fail_no_vol':
        # 跌破結構但量不足 → level="signal"，不 triggered
        n = 15
        opens  = np.linspace(102, 101, n)
        highs  = opens + 1.0
        lows   = opens - 0.5
        closes = np.linspace(101, 100, n)
        opens[-1]  = 99.0
        closes[-1] = 97.5  # 黑 K
        highs[-1]  = 99.5
        lows[-1]   = 97.0
        vols   = np.full(n, 1000.0)
        vols[-1] = 1200.0  # 量不足 1.5x
        times  = ["09:30"] * n
        return opens, highs, lows, closes, vols, times

    elif scenario == '破底_edge_dist_exactly_neg3pct':
        # 距 MA10 嚴格 ≤ -3%: 讓 MA10(last 10 closes) = 100, current close = 96.8 → dist = -3.2%
        # MA10 = 最後 10 根均，所以前 9 根都是 100，最後一根是 96.8
        # 均值 = (9*100 + 96.8) / 10 = 99.68 → dist = 96.8/99.68 - 1 = -2.85% 仍不足
        # 需要 current 更低: 前 9 根 100, last 96.0 → MA10=(9*100+96)/10=99.6, dist=96/99.6-1=-3.61%
        n = 15
        closes = np.full(n, 100.0)
        closes[-1] = 96.0  # MA10(last10) = (9*100+96)/10 = 99.6, dist = -3.61%
        opens  = np.full(n, 100.5)
        opens[-1] = 97.0  # 黑 K (96 < 97)
        highs  = opens + 0.5
        lows   = closes - 0.5
        vols   = np.full(n, 1000.0)
        vols[-1] = 2500.0  # 量爆 2.5x
        times  = ["09:30"] * n
        return opens, highs, lows, closes, vols, times

    elif scenario == '尾盤_confirmed_3of5':
        # check_closing_panel: 用 _check_closing_panel 邏輯外部測試時改用 StageTrigger
        # 這個 scenario 主要給 StageTrigger.check_closing_panel 用
        # 建立一個 DataFrame 有 3/5 條件過
        # 詳細在 test_closing_panel_3of5 中用 DataFrame 測試
        opens  = np.array([100.0])
        highs  = np.array([100.5])
        lows   = np.array([ 99.5])
        closes = np.array([100.2])
        vols   = np.array([1000.0])
        times  = ["13:10"]
        return opens, highs, lows, closes, vols, times

    elif scenario == '無訊號':
        # 平整橫盤，不觸發任何 trigger
        n = 10
        opens  = np.full(n, 100.0)
        closes = np.full(n, 100.2)
        highs  = np.full(n, 100.5)
        lows   = np.full(n,  99.8)
        vols   = np.full(n, 1000.0)
        times  = ["09:30"] * n
        return opens, highs, lows, closes, vols, times

    else:
        raise ValueError(f"未知 scenario: {scenario}")


# ── 層 1: 首攻 (Ch5-3) Tests ──────────────────────────────────────────────────

class TestCh53Entry:
    """首攻 (_check_ch5_3_entry_np) 三種 case。"""

    def test_首攻_pass_normal_regime(self):
        """正向: 第一根全 pass + 9:10 後過高 → confirmed。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('首攻_pass')
        prev_close = 99.0   # close(102) > prev_close(99) ✓
        result = _check_ch5_3_entry_np(
            opens, highs, lows, closes, vols, times,
            prev_close=prev_close, ma10=None, market_regime="normal",
        )
        assert result["triggered"] is True
        assert result["level"] == "confirmed"

    def test_首攻_fail_black_k(self):
        """負向: 第一根黑 K → level=fail、triggered=False。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('首攻_fail_not_red')
        result = _check_ch5_3_entry_np(
            opens, highs, lows, closes, vols, times,
            prev_close=98.0, ma10=None, market_regime="normal",
        )
        assert result["triggered"] is False
        assert result["level"] == "fail"
        assert "非紅K" in result["reason"]

    def test_首攻_edge_gap_exactly_5pct(self):
        """邊界: 跳空恰好 5% → gap_ok=False → fail。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('首攻_edge_gap_exactly_5pct')
        prev_close = 100.0  # open=105 → gap=(105/100-1)*100=5.0%
        result = _check_ch5_3_entry_np(
            opens, highs, lows, closes, vols, times,
            prev_close=prev_close, ma10=None, market_regime="normal",
        )
        assert result["triggered"] is False
        assert "跳空" in result["reason"]

    def test_首攻_edge_rise_exactly_4pct(self):
        """邊界: 5K 漲幅恰好 4% → rise_under_4=False → fail。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('首攻_edge_rise_exactly_4pct')
        prev_close = 99.0
        result = _check_ch5_3_entry_np(
            opens, highs, lows, closes, vols, times,
            prev_close=prev_close, ma10=None, market_regime="normal",
        )
        assert result["triggered"] is False
        assert "漲幅" in result["reason"]

    def test_首攻_weak_regime_pullback_confirmed(self):
        """弱勢盤: 過高 signal → 回踩 MA10 收紅 → confirmed。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('首攻_weak_regime_pass')
        prev_close = 99.0
        ma10 = 99.0   # MA10 設在 99，close[2]=100.2 > ma10 且 close[2] > open[2]
        result = _check_ch5_3_entry_np(
            opens, highs, lows, closes, vols, times,
            prev_close=prev_close, ma10=ma10, market_regime="weak",
        )
        # 弱勢盤需回踩 MA10 守住才 confirmed
        assert result["triggered"] is True
        assert result["level"] == "confirmed"

    def test_首攻_normal_before_0910_is_watch(self):
        """9:00 前（只有第一根、尚未 9:10）→ watch，不觸發。"""
        opens  = np.array([100.0])
        highs  = np.array([102.0])
        lows   = np.array([ 99.5])
        closes = np.array([102.0])
        vols   = np.array([1000.0])
        times  = ["09:00"]  # 只有第一根，n=1，沒有 i>=1 可過高
        prev_close = 99.0
        result = _check_ch5_3_entry_np(
            opens, highs, lows, closes, vols, times,
            prev_close=prev_close, ma10=None, market_regime="normal",
        )
        # 第一根 pass 但沒有後續 bar 可過高 → watch
        assert result["triggered"] is False
        assert result["level"] == "watch"


# ── 層 1: 續攻 (T1) Tests ────────────────────────────────────────────────────

class TestTrigger1:
    """續攻 (_check_trigger_1_np) 三種 case。"""

    def test_續攻_pass(self):
        """正向: 連 2 紅K + 量增 + 距開盤 >1% → confirmed。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('續攻_pass')
        result = _check_trigger_1_np(
            opens, highs, lows, closes, vols, times,
            prev_high=None,
        )
        assert result["triggered"] is True
        assert result["level"] == "confirmed"

    def test_續攻_fail_insufficient_volume(self):
        """負向: 量增只有 1.1x < 1.5x → 不觸發。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('續攻_fail_no_vol')
        result = _check_trigger_1_np(
            opens, highs, lows, closes, vols, times,
            prev_high=None,
        )
        assert result["triggered"] is False
        assert "量增不足" in result["reason"]

    def test_續攻_edge_t1_watch_in_dump_window(self):
        """邊界: 9:30 在拉高出貨時段 → T1_watch、不 confirmed。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('續攻_edge_at_9:45_watch')
        result = _check_trigger_1_np(
            opens, highs, lows, closes, vols, times,
            prev_high=None,
        )
        # 應為 T1_watch
        assert result["triggered"] is False
        assert result["level"] == "T1_watch"

    def test_續攻_fail_data_insufficient(self):
        """資料不足 (<5 根) → triggered=False。"""
        opens  = np.array([100.0, 101.0])
        highs  = np.array([101.0, 102.0])
        lows   = np.array([ 99.5, 100.5])
        closes = np.array([101.0, 101.5])
        vols   = np.array([1000.0, 1200.0])
        times  = ["09:00", "09:05"]
        result = _check_trigger_1_np(opens, highs, lows, closes, vols, times, prev_high=None)
        assert result["triggered"] is False
        assert "不足" in result["reason"]


# ── 層 1: 反彈 (T2) Tests ────────────────────────────────────────────────────

class TestTrigger2:
    """反彈 (_check_trigger_2_np) 三種 case。"""

    def test_反彈_pass_path_a(self):
        """正向路徑 A: 跌深 ≥ 2.5% + 3 紅K + 反彈 ≥ 1%。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('反彈_pass')
        result = _check_trigger_2_np(opens, highs, lows, closes, vols, times)
        assert result["triggered"] is True
        assert result["level"] == "confirmed"
        assert "3 紅K" in result.get("path", "") or "3 紅K" in result["reason"]

    def test_反彈_fail_not_deep_enough(self):
        """負向: 跌深只有 2.0% < 2.5% → 不觸發。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('反彈_fail_not_deep_enough')
        result = _check_trigger_2_np(opens, highs, lows, closes, vols, times)
        assert result["triggered"] is False
        assert "未跌深" in result["reason"]

    def test_反彈_edge_exactly_2pt5pct_deep(self):
        """邊界: 跌深恰好 2.5% (從日高算) → 滿足 ≤ -2.5% 條件。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('反彈_edge_exactly_2.5pct')
        result = _check_trigger_2_np(opens, highs, lows, closes, vols, times)
        # 跌深恰好 2.5% 且後有 3 紅K → 應觸發
        assert result["triggered"] is True

    def test_反彈_fail_data_insufficient(self):
        """資料不足 (<3 根) → 不觸發。"""
        opens  = np.array([100.0, 101.0])
        highs  = np.array([101.0, 102.0])
        lows   = np.array([ 99.5, 100.5])
        closes = np.array([101.0, 101.5])
        vols   = np.array([1000.0, 1200.0])
        times  = ["09:00", "09:05"]
        result = _check_trigger_2_np(opens, highs, lows, closes, vols, times)
        assert result["triggered"] is False
        assert "不足" in result["reason"]

    def test_反彈_path_b_5m_diff_positive(self):
        """路徑 B: 5m diff 由負轉正 + 紅 K + 09:10 後。

        要求:
          - after_low_len ≥ 2 (低點不能在最後 1 根)
          - diff_prev = closes[-2] - closes[-3] < 0 (下行)
          - diff_now  = closes[-1] - closes[-2] > 0 (轉正)
          - path A all_red 要 fail (有黑K) 以確保走 path B
        """
        # 低點在第 2 根 (idx=1)，after_low_len = 7 - 1 - 1 = 5 ≥ 2
        # closes: [110.0, 106.0, 107.5, 107.2, 106.5, 108.0, 108.8]
        # 低點 idx: lows.argmin() = 1 (low=105.5)
        # diff_prev = closes[5] - closes[4] = 108.0 - 106.5 = +1.5 → not < 0 ... need different

        # Better design: low at idx=1, then sequence goes down then up
        # closes: [110, 106, 107, 106, 107, 106.5, 108]
        # diff_prev = closes[-2] - closes[-3] = 106.5 - 107 = -0.5 (負) ✓
        # diff_now  = closes[-1] - closes[-2] = 108 - 106.5 = +1.5 (正) ✓
        # path A: tail3 = closes[-3:] = [107, 106.5, 108], opens[-3:] = ?
        #   to make all_red fail: idx -3 or -2 should be black K
        n = 7
        closes_arr = np.array([110.0, 106.0, 107.0, 106.0, 107.0, 106.5, 108.0])
        opens_arr  = np.array([109.5, 107.5, 106.5, 107.0, 106.5, 107.5, 107.5])
        # idx -3: closes[4]=107.0 < opens[4]=106.5 → 紅K (107>106.5) ✓
        # idx -2: closes[5]=106.5 < opens[5]=107.5 → 黑K → all_red = False → path A fail ✓
        highs_arr  = np.array([110.5, 107.5, 107.5, 107.2, 107.5, 108.0, 109.0])
        lows_arr   = np.array([109.0, 105.5, 106.5, 105.8, 106.3, 106.0, 107.3])
        # day_high = 110.5, last_low = 107.3, pullback = (107.3-110.5)/110.5 = -2.9%
        # closes[-1]=108.0 < day_high(110.5)*0.985 = 108.84 → 不是 T2_watch ✓
        vols_arr   = np.array([2000.0, 3000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1200.0])
        times_arr  = ["09:00", "09:05", "10:00", "10:05", "10:10", "10:15", "10:20"]
        result = _check_trigger_2_np(opens_arr, highs_arr, lows_arr, closes_arr, vols_arr, times_arr)
        assert result["triggered"] is True, f"Expected triggered, got: {result}"
        assert result.get("path") == "B (5m diff)"


# ── 層 1: 破底 (TC) Tests ─────────────────────────────────────────────────────

class TestTriggerC:
    """破底 (_check_trigger_c_np) 三種 case。"""

    def test_破底_pass(self):
        """正向: 跌破前波低 + 量爆 + 黑 K → confirmed。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('破底_pass')
        prev_low = 98.0  # current(97.5) < prev_low(98) → 跌破
        result = _check_trigger_c_np(opens, highs, lows, closes, vols, times, prev_low)
        assert result["triggered"] is True
        assert result["level"] == "confirmed"
        assert "跌破前波低" in result["reason"]

    def test_破底_fail_no_volume(self):
        """負向: 跌破結構但量不足 → level=signal、triggered=False。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('破底_fail_no_vol')
        prev_low = 98.0
        result = _check_trigger_c_np(opens, highs, lows, closes, vols, times, prev_low)
        assert result["triggered"] is False
        assert result["level"] == "signal"

    def test_破底_edge_dist_ma10_exactly_neg3pct(self):
        """邊界: 距 MA10 恰好 -3% → broken_structure=True。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('破底_edge_dist_exactly_neg3pct')
        # 不傳 prev_low，依賴距 MA10 條件
        result = _check_trigger_c_np(opens, highs, lows, closes, vols, times, prev_low=None)
        # 距 MA10 ≤ -3% → broken_structure=True，且量爆 → confirmed
        assert result["triggered"] is True

    def test_破底_no_signal_when_structure_intact(self):
        """結構未破壞 → 不觸發。"""
        opens, highs, lows, closes, vols, times = _synthetic_bars('無訊號')
        result = _check_trigger_c_np(opens, highs, lows, closes, vols, times, prev_low=None)
        assert result["triggered"] is False
        assert "未破壞" in result["reason"]

    def test_破底_data_insufficient(self):
        """資料不足 (<5 根) → 不觸發。"""
        opens  = np.array([100.0, 99.0])
        highs  = np.array([100.5, 99.5])
        lows   = np.array([ 99.5, 98.5])
        closes = np.array([ 99.5, 98.8])
        vols   = np.array([1000.0, 1500.0])
        times  = ["09:00", "09:05"]
        result = _check_trigger_c_np(opens, highs, lows, closes, vols, times, prev_low=90.0)
        assert result["triggered"] is False
        assert "不足" in result["reason"]



# ── 層 1: 尾盤 (Closing) Tests ────────────────────────────────────────────────

class TestClosingPanel:
    """StageTrigger.check_closing_panel 尾盤 confirmed / overheated / skip / not_in_window。"""

    def _make_base_df(self) -> pd.DataFrame:
        """建立 09:00-13:25 共 54 根 5 分 K，所有 close=101, MA10=100。

        預設 5 個條件全 pass:
          cond1 structure_hold: close(101) > MA10(100) ✓
          cond2 kill_test:      after_12 low(100) < morning_high(103)*0.98(100.94) ✓
          cond3 rebound:        13:00 後 2 紅K ✓
          cond4 volume_calm:    尾盤量(1000) < 早盤量均(1000)*1.2 ✓
          cond5 not_chasing:    close(101) vs day_high(103) → (103-101)/103=1.94%≥1.5% ✓
        """
        # 09:00 → 13:25 共 54 根 (每 5 分鐘一根)
        times_pd = pd.date_range("2026-01-02 09:00", "2026-01-02 13:25", freq="5min")
        times_list = list(times_pd)
        idx = pd.DatetimeIndex(times_list)
        n = len(idx)

        opens  = np.full(n, 100.5)
        highs  = np.full(n, 103.0)
        lows   = np.full(n, 100.0)   # 12:00 後 low=100 < 103*0.98=100.94 → cond2 pass
        closes = np.full(n, 101.0)   # close(101) > MA10(100) → cond1 pass
        vols   = np.full(n, 1000.0)

        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
            index=idx,
        )

        # 13:00 後確保 2 根紅 K (cond3)
        ts_strs = [t.strftime("%H:%M") for t in times_list]
        idx_13 = [i for i, s in enumerate(ts_strs) if s >= "13:00"]
        for i in idx_13[:3]:
            df.iloc[i, df.columns.get_loc("open")]  = 100.5
            df.iloc[i, df.columns.get_loc("close")] = 101.5  # 紅 K

        return df

    def test_尾盤_confirmed_4of5(self):
        """4/5 條件通過 → triggered=True, level=confirmed。

        讓 kill_test (cond2) fail (after_12 low 抬到 102 > morning_high*0.98=100.94)。
        其餘 4 個條件 pass → pass_count=4 → confirmed。
        """
        from scripts.zhuli.intraday_stage_helper import StageTrigger
        df = self._make_base_df()
        ts_strs = [t.strftime("%H:%M") for t in df.index]
        for i, s in enumerate(ts_strs):
            if s >= "12:00":
                df.iloc[i, df.columns.get_loc("low")] = 102.0  # cond2 fail

        st = StageTrigger()
        result = st.check_closing_panel(
            ticker="TEST", k5=df, ma10=100.0, _now_override="13:10",
        )
        assert result["level"] == "confirmed", (
            f"Expected confirmed, got {result['level']} pass_count={result.get('pass_count')} "
            f"scores={result.get('scores')}"
        )
        assert result["triggered"] is True

    def test_尾盤_過熱_5of5(self):
        """5/5 條件通過 → triggered=False, level=overheated。"""
        from scripts.zhuli.intraday_stage_helper import StageTrigger
        df = self._make_base_df()
        # base_df 已是 5/5 pass: close=101, day_high=103 → (103-101)/103=1.94% ≥ 1.5% ✓
        st = StageTrigger()
        result = st.check_closing_panel(
            ticker="TEST", k5=df, ma10=100.0, _now_override="13:10",
        )
        assert result["level"] == "overheated", (
            f"Expected overheated, got {result['level']} pass_count={result.get('pass_count')} "
            f"scores={result.get('scores')}"
        )
        assert result["triggered"] is False

    def test_尾盤_skip_2of5(self):
        """2/5 條件通過 → triggered=False, level=skip。

        讓 3 個條件 fail → pass_count ≤ 2 → skip:
          cond1 structure_hold: ✓ close(101) > MA10(100)
          cond2 kill_test:      ✗ after_12 low 抬高到 102 > 100.94
          cond3 rebound:        ✗ 13:00 後設黑 K
          cond4 volume_calm:    ✓ 均等量
          cond5 not_chasing:    ✗ close(102) 接近 day_high(103) → 0.97% < 1.5%
        → pass_count = cond1 + cond4 = 2 → skip
        """
        from scripts.zhuli.intraday_stage_helper import StageTrigger
        df = self._make_base_df()
        ts_strs = [t.strftime("%H:%M") for t in df.index]
        idx_13 = [i for i, s in enumerate(ts_strs) if s >= "13:00"]

        # cond5 fail: 先把全部 close 拉到 102 (接近 day_high=103)
        df["close"] = 102.0
        df["high"]  = 103.0

        # cond2 fail: after_12 low 抬到 102 (> 103*0.98=100.94)
        for i, s in enumerate(ts_strs):
            if s >= "12:00":
                df.iloc[i, df.columns.get_loc("low")] = 102.0

        # cond3 fail: 所有 13:00+ 設黑 K (open=103 > close=102)
        for i in idx_13:
            df.iloc[i, df.columns.get_loc("open")]  = 103.0
            df.iloc[i, df.columns.get_loc("close")] = 102.0  # 黑 K (open > close)

        st = StageTrigger()
        result = st.check_closing_panel(
            ticker="TEST", k5=df, ma10=100.0, _now_override="13:10",
        )
        assert result["level"] == "skip", (
            f"Expected skip, got {result['level']} pass_count={result.get('pass_count')} "
            f"scores={result.get('scores')}"
        )
        assert result["triggered"] is False

    def test_尾盤_not_in_window(self):
        """不在 13:05-13:25 時段 → level=not_in_window。"""
        from scripts.zhuli.intraday_stage_helper import StageTrigger
        times = pd.date_range("2026-01-02 09:00", periods=10, freq="5min")
        df = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 1000.0},
            index=times,
        )
        st = StageTrigger()
        result = st.check_closing_panel(
            ticker="TEST", k5=df, ma10=100.0,
            _now_override="12:50",
        )
        assert result["level"] == "not_in_window"
        assert result["triggered"] is False

    def test_尾盤_結構失敗必skip_即使3of5pass(self):
        """🔴 Regression (2026-06-10 bug 6ca1638):
        結構守住 (close < MA10) 失敗時、即使其他 3/4 條件通過、必須 level='skip'、
        絕不可標 'confirmed'。

        Repro 案例: 8064 東捷 6/9 13:09、close=141 / MA10 ~146 (結構❌) /
        反彈❌、但殺盤✓+量縮✓+未追高✓ = 3/5 → 此前實作標「最佳進場 Win 82%」
        嚴重誤導 user。
        """
        from scripts.zhuli.intraday_stage_helper import StageTrigger
        df = self._make_base_df()
        # cond1 fail: close 設 < MA10 (98 < 100)
        df["close"] = 98.0
        df["open"]  = 98.0
        df["high"]  = 99.0
        df["low"]   = 97.0
        # 其他 3 條保持 pass (kill_test/volume_calm/not_chasing)
        # 反彈 cond3 在 13:00+ 已是黑K (close=98 = open=98 平盤、不算紅K) → fail
        # 總和: cond1 ❌ cond2 ✓ cond3 ❌ cond4 ✓ cond5 ✓ = 3/5
        st = StageTrigger()
        result = st.check_closing_panel(
            ticker="TEST", k5=df, ma10=100.0, _now_override="13:10",
        )
        scores = result.get("scores", {})
        # 重點: 結構必失敗 (precondition for this regression)
        assert scores.get("structure_hold") is False, (
            f"precondition fail: structure_hold should be False, got {scores}"
        )
        # 核心斷言: 結構失敗 → 永遠 skip、不論 pass_count
        assert result["level"] == "skip", (
            f"Expected skip when structure_hold=False, got {result['level']} "
            f"pass_count={result.get('pass_count')} scores={scores}. "
            f"BUG: 破底股不可標最佳進場 (8064 教訓)"
        )
        assert result["triggered"] is False
