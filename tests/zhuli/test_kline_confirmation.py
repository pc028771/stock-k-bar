"""Tests for kline_confirmation.py (Tier-A 升等訊號 wiring).

涵蓋兩塊：
  A. apply_confirmations 的 tier boost 邏輯 (純函式、不需 DB)
  B. detect_kline_tier_a 對手做 fixture 的偵測 (整合 add_features + 3 detectors)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).parent.parent.parent
for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.kline_confirmation import (  # noqa: E402
    KLINE_TIER_A_NAMES_CN,
    KLINE_TIER_A_PATTERNS,
    apply_confirmations,
    boost_tier,
    detect_kline_tier_a,
    format_confirmation_badge,
)


# ── A. Tier boost (純邏輯) ────────────────────────────────────────────────────

def test_boost_normal_to_b():
    assert boost_tier("一般") == "⭐ Tier-B"


def test_boost_b_to_a():
    assert boost_tier("⭐ Tier-B") == "🔥 Tier-A"


def test_boost_a_stays_a():
    assert boost_tier("🔥 Tier-A") == "🔥 Tier-A"


def test_boost_add_position_stays():
    # 加碼用 tier 不參與升等
    assert boost_tier("➕ 加碼用") == "➕ 加碼用"


def test_boost_unknown_stays():
    # 未知 tier 不動 (避免亂改)
    assert boost_tier("未知") == "未知"


def test_format_badge_single():
    assert format_confirmation_badge(["attack_cost_displayed"]) == "✨攻擊成本顯現"


def test_format_badge_multiple():
    badge = format_confirmation_badge(["morning_star_island_reversal", "attack_cost_displayed"])
    assert badge == "✨晨星島反轉+攻擊成本顯現"


def test_format_badge_empty():
    assert format_confirmation_badge([]) == ""


def test_apply_confirmations_boosts_and_tags():
    hits = [
        {"ticker": "2330", "tier": "一般"},
        {"ticker": "2454", "tier": "⭐ Tier-B"},
        {"ticker": "1234", "tier": "🔥 Tier-A"},
        {"ticker": "9999", "tier": "一般"},  # 沒命中 — 不該動
    ]
    confs = {
        "2330": ["attack_cost_displayed"],
        "2454": ["morning_star_island_reversal"],
        # 已是 A、貼兩個 pattern 都應該顯示；tier 不再升等
        "1234": ["attack_cost_displayed", "morning_star_island_reversal"],
    }
    boosted = apply_confirmations(hits, confs)
    assert boosted == 2  # 2330 + 2454 升級；1234 已 A 不算升等
    assert hits[0]["tier"] == "⭐ Tier-B"
    assert hits[0]["kline_badge"] == "✨攻擊成本顯現"
    assert hits[1]["tier"] == "🔥 Tier-A"
    assert hits[1]["kline_badge"] == "✨晨星島反轉"
    assert hits[2]["tier"] == "🔥 Tier-A"  # 維持
    assert hits[2]["kline_badge"] == "✨攻擊成本顯現+晨星島反轉"  # 多 pattern 串接
    # 9999 沒命中
    assert "kline_badge" not in hits[3]
    assert hits[3]["tier"] == "一般"


def test_apply_confirmations_empty():
    hits = [{"ticker": "2330", "tier": "一般"}]
    boosted = apply_confirmations(hits, {})
    assert boosted == 0
    assert hits[0]["tier"] == "一般"
    assert "kline_badge" not in hits[0]


def test_pattern_list_matches_names_dict():
    # 中文對照表必須 cover 所有 detector
    for p in KLINE_TIER_A_PATTERNS:
        assert p in KLINE_TIER_A_NAMES_CN


# ── B. detect_kline_tier_a (整合 add_features + detector) ─────────────────────

def _make_bull_history_bars(n_history: int = 80) -> list[dict]:
    """建一段 bull history (n_history 根)、收尾 close ~高點、給 attack_cost_displayed
    + bull_exhaustion_context 用.
    """
    rows = []
    base_price = 100.0
    # 前 60 根穩定漲、製造 prior_high_60 + 攻擊背景
    for i in range(n_history):
        # 漲一陣 → 整理一陣 → 收尾平台 (給 prior_high_60 有意義的值)
        if i < 40:
            base_price *= 1.005
        # 後段微震盪
        price = base_price * (1 + (0.001 * ((i % 5) - 2)))
        rows.append({
            "open": price, "high": price * 1.005, "low": price * 0.995, "close": price,
            "volume": 1000.0,
        })
    return rows


def test_detect_empty_input():
    assert detect_kline_tier_a({}, "2026-06-11") == {}


def test_detect_no_hits_on_flat_history():
    """純橫盤 history → 三支 pattern 都不該觸發."""
    rows = _make_bull_history_bars(80)
    ticker_dfs = {"T0001": pd.DataFrame(rows)}
    ticker_dfs["T0001"]["trade_date"] = pd.date_range("2026-01-02", periods=80, freq="B")
    ticker_dfs["T0001"]["ticker"] = "T0001"
    # 補課程內基本 MA 欄位 (add_features 預期已存在於 load_bars 輸出)
    df = ticker_dfs["T0001"]
    df["ma5"] = df["close"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["close"].rolling(10, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(60, min_periods=1).mean()

    target = str(df["trade_date"].iloc[-1])[:10]
    result = detect_kline_tier_a(ticker_dfs, target)
    # 平台、無 attack、無漲停、無 gap → 應無命中
    assert result == {}


def test_detect_attack_cost_locked_limit_up():
    """構造一根 close 突破 prior_high_60 + 收漲停 + 量爆 = attack_cost_displayed."""
    # 70 根穩定 100~105 (prior_high_60 ~= 105)、最後一根 close=120 (>105) + 鎖漲停
    rows = []
    for i in range(70):
        p = 100 + (i % 5)
        rows.append({"open": p, "high": p, "low": p, "close": p, "volume": 1000.0})
    # D-0 鎖漲停：close = prev_close * 1.10、high == close、low >= prev_close
    prev_close = rows[-1]["close"]  # 104
    limit_up_close = prev_close * 1.10  # 114.4
    rows.append({
        "open": prev_close * 1.05,
        "high": limit_up_close,
        "low": prev_close,  # low 不跌回昨收
        "close": limit_up_close,
        "volume": 5000.0,
    })
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.date_range("2026-01-02", periods=len(rows), freq="B")
    df["ticker"] = "T0001"
    df["ma5"] = df["close"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["close"].rolling(10, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(60, min_periods=1).mean()

    target = str(df["trade_date"].iloc[-1])[:10]
    result = detect_kline_tier_a(
        {"T0001": df},
        target,
        patterns=["attack_cost_displayed"],
    )
    assert "T0001" in result
    assert "attack_cost_displayed" in result["T0001"]


def test_detect_returns_dict_only_for_target_date():
    """命中發生在 D-3、target_date 是 D-0 → 不該回傳."""
    rows = []
    for i in range(70):
        p = 100 + (i % 5)
        rows.append({"open": p, "high": p, "low": p, "close": p, "volume": 1000.0})
    # D-3 attack cost (限漲停)
    prev_close = rows[-1]["close"]
    limit_up = prev_close * 1.10
    rows.append({
        "open": prev_close * 1.05, "high": limit_up, "low": prev_close,
        "close": limit_up, "volume": 5000.0,
    })
    # 之後 3 根橫盤
    for _ in range(3):
        p = limit_up
        rows.append({"open": p, "high": p, "low": p, "close": p, "volume": 1000.0})

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.date_range("2026-01-02", periods=len(rows), freq="B")
    df["ticker"] = "T0001"
    df["ma5"] = df["close"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["close"].rolling(10, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(60, min_periods=1).mean()

    # target = 最後一根 (D-0)
    target = str(df["trade_date"].iloc[-1])[:10]
    result = detect_kline_tier_a({"T0001": df}, target, patterns=["attack_cost_displayed"])
    # 命中是 D-3、target 是 D-0 → 不該抓到
    assert "T0001" not in result
