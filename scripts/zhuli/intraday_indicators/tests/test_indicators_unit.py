"""合成資料 unit test — 驗證 Ch5 補強 indicator 的觸發條件正確。

歷史日實測（強茂 5/19、3037 5/22 等）case 大多太「淡」、無法 exercise B5-1 /
紅線 #9 / 均線發散 等指標。本 unit test 用合成資料明確構造「應觸發」場景、
確認 indicator 邏輯正確。

跑法:
    PYTHONPATH=scripts python -m zhuli.intraday_indicators.tests.test_indicators_unit
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).parent
_REPO = _HERE.parent.parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _build_1m(start: datetime, prices: list[float]) -> pd.DataFrame:
    """合成 1m K（close = open = high = low、量固定）。"""
    times = [start + timedelta(minutes=i) for i in range(len(prices))]
    return pd.DataFrame({
        "datetime": times,
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": [100] * len(prices),
    }).set_index("datetime")


def _build_5m(opens_closes: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """合成 5m K from list of (open, high, low, close)。"""
    start = datetime(2026, 6, 4, 9, 0)
    rows = []
    for i, (o, h, l, c) in enumerate(opens_closes):
        rows.append({
            "datetime": start + timedelta(minutes=i*5),
            "open": o, "high": h, "low": l, "close": c, "volume": 1000,
        })
    return pd.DataFrame(rows).set_index("datetime")


# ── 測試 ──────────────────────────────────────────────────────────────────────


def test_first5min_skip_fires_at_6pct():
    from zhuli.intraday_indicators import check_first5min_skip
    # 開盤 100、前 5 分鐘高 106 → +6%、應 fire
    k1m = _build_1m(datetime(2026, 6, 4, 9, 0),
                    [100, 102, 104, 105, 106, 105.5, 105, 104.5])
    r = check_first5min_skip(k1m)
    assert r["triggered"], f"應 fire 但沒、reason={r['reason']}"
    assert r["level"] == "skip"
    print(f"✅ 紅線 #9：開盤 100 → 前 5 分 high 106 → fire ({r['reason']})")


def test_first5min_skip_not_fire_at_3pct():
    from zhuli.intraday_indicators import check_first5min_skip
    k1m = _build_1m(datetime(2026, 6, 4, 9, 0),
                    [100, 101, 102, 102.5, 103, 103.2])
    r = check_first5min_skip(k1m)
    assert not r["triggered"], f"不該 fire 但 fire 了、reason={r['reason']}"
    print(f"✅ 紅線 #9：開盤 100 → 前 5 分 high 103 → 不 fire ({r['reason']})")


def test_b5_1_stop_profit_fires_at_5pct_5m():
    from zhuli.intraday_indicators import check_b5_1_stop_profit
    # 5K 開 100 收 105.5 → +5.5%、應 fire
    k5 = _build_5m([(100, 105.8, 100, 105.5)])
    r = check_b5_1_stop_profit(k5, timeframe="5m")
    assert r["triggered"], f"應 fire 但沒、reason={r['reason']}"
    assert r["level"] == "exit"
    print(f"✅ B5-1 5m：開 100 收 105.5 (+5.5%) → fire ({r['reason']})")


def test_b5_1_stop_profit_2m_threshold_3pct():
    from zhuli.intraday_indicators import check_b5_1_stop_profit
    # 2K 開 100 收 103.5 → +3.5%、2m timeframe 應 fire
    k2 = _build_5m([(100, 103.5, 100, 103.5)])  # 借用 5m 結構、邏輯只看 open/close
    r = check_b5_1_stop_profit(k2, timeframe="2m")
    assert r["triggered"], f"應 fire、reason={r['reason']}"
    print(f"✅ B5-1 2m：開 100 收 103.5 (+3.5%) → fire ({r['reason']})")


def test_b5_2_a_type():
    from zhuli.intraday_indicators import check_b5_2_limit_up_pattern
    # 昨收 100、昨日漲停 → 今開 101 (跳空 +1%) 第 1 根、第 2 根 close 101.5
    # 跳空 < 2% + 第 2 根守 ≥ 第 1 根開 → A 型
    k5 = _build_5m([
        (101, 102, 100.5, 101.5),  # 第 1 根
        (101.5, 102, 101, 101.8),  # 第 2 根（守住開 101）
    ])
    r = check_b5_2_limit_up_pattern(k5, prev_close=100.0, prev_was_limit_up=True)
    assert r["triggered"] and r["level"] == "A", f"應為 A 型、got level={r['level']}"
    print(f"✅ B5-2 A 型：昨漲停 + 今跳 +1% + 第 2 根守 → A ({r['reason']})")


def test_b5_2_b_type():
    from zhuli.intraday_indicators import check_b5_2_limit_up_pattern
    # 昨收 100、昨日漲停 → 今跳 +4% (104)、第 1 根衝高 110 但收回 104 (大上影)
    # 跳空 ≥ 3% + 第 1 根上影遠 > body → B 型
    k5 = _build_5m([
        (104, 110, 103.5, 104),    # 第 1 根：跳空 +4%、衝高大上影
        (104, 105, 102, 103),
    ])
    r = check_b5_2_limit_up_pattern(k5, prev_close=100.0, prev_was_limit_up=True)
    assert r["triggered"] and r["level"] == "B", f"應為 B 型、got level={r['level']}"
    print(f"✅ B5-2 B 型：昨漲停 + 今跳 +4% + 大上影 → B ({r['reason']})")


def test_b5_3_ma60_uptrend_fires():
    from zhuli.intraday_indicators import check_b5_3_quarterly_ma_short_filter
    # 日 K 一路上漲、MA60 應為上揚
    closes = pd.Series([100 + i * 0.5 for i in range(80)])
    r = check_b5_3_quarterly_ma_short_filter(closes)
    assert r["triggered"], f"應 fire、reason={r['reason']}"
    print(f"✅ B5-3：日 K 上漲 80 日 → MA60 上揚 fire ({r['reason']})")


def test_b5_3_ma60_downtrend_not_fire():
    from zhuli.intraday_indicators import check_b5_3_quarterly_ma_short_filter
    # 日 K 一路下跌
    closes = pd.Series([200 - i * 0.5 for i in range(80)])
    r = check_b5_3_quarterly_ma_short_filter(closes)
    assert not r["triggered"], f"不該 fire、reason={r['reason']}"
    print(f"✅ B5-3：日 K 下跌 80 日 → MA60 下行不 fire ({r['reason']})")


def test_ma_divergence_fires():
    from zhuli.intraday_indicators import check_ma_divergence
    # 構造 5K 走勢：前 15 根低、後 5 根爆衝 → MA5/10/20 拉開
    closes = [100] * 15 + [110, 112, 114, 116, 118]
    rows = [(c, c, c, c) for c in closes]
    k5 = _build_5m(rows)
    r = check_ma_divergence(k5, divergence_threshold_pct=3.0)
    assert r["triggered"], f"應 fire、reason={r['reason']}"
    print(f"✅ 均線發散：前低後爆衝 → spread > 3% fire ({r['reason']})")


def test_ma_divergence_not_fire():
    from zhuli.intraday_indicators import check_ma_divergence
    # 平穩走勢、MA 應糾結
    closes = [100 + i * 0.05 for i in range(25)]
    rows = [(c, c, c, c) for c in closes]
    k5 = _build_5m(rows)
    r = check_ma_divergence(k5)
    assert not r["triggered"], f"不該 fire、reason={r['reason']}"
    print(f"✅ 均線發散：平穩走勢 → spread < 3% 不 fire ({r['reason']})")


def main():
    tests = [
        test_first5min_skip_fires_at_6pct,
        test_first5min_skip_not_fire_at_3pct,
        test_b5_1_stop_profit_fires_at_5pct_5m,
        test_b5_1_stop_profit_2m_threshold_3pct,
        test_b5_2_a_type,
        test_b5_2_b_type,
        test_b5_3_ma60_uptrend_fires,
        test_b5_3_ma60_downtrend_not_fire,
        test_ma_divergence_fires,
        test_ma_divergence_not_fire,
    ]
    failed = 0
    print("=== Ch5 補強 indicator unit test ===\n")
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"💥 {t.__name__}: 例外 {e}")
            failed += 1

    print()
    print(f"=== 結果: {len(tests) - failed}/{len(tests)} 通過 ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
