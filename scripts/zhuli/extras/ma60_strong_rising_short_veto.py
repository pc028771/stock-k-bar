"""extras.ma60_strong_rising_short_veto — 季線強力上揚時擋 SHORT_SETUP。

⚠️ 課程外條件 — 預設 OFF、必須 --extras ma60_strong_rising_short_veto 明確啟用。

## 課程立場（2026-06-29 §5.3）

老師原話：「季線只要一沒有往上揚、開始變成走平的話、它就會形成土石流」

課程**定性**說明：
  - 季線「強力上揚」→ 做空謹慎（怕被主力自救拉起）
  - 季線「走平/走下」→ 土石流條件符合、可空

課程**未給**量化斜率數字。這個 extra 將「強力上揚」數值化為一個可調門檻
（MA60_STRONG_RISE_PCT_THRESH），是課程外自訂參數、待回測校準。

## 主力大課程主邏輯對應

`live_intraday_monitor.py` 的 SHORT_SETUP 邏輯中：
  - 季線方向已用「informational note」標示（⚠️ 上揚 / ✓ 走平走下）
  - 本 extra 啟用後才真正擋 SHORT_SETUP（季線強力上揚 → block）

## 為什麼是課程外

老師只說「強力上揚」定性描述，從未給出斜率數值（如 N 天漲 X%）。
把「強力上揚」硬編進主邏輯當 hard gate = 自創量化條件。
→ 必須放 extras/、預設 OFF、標「待回測校準」。

## 參數

MA60_STRONG_RISE_PCT_THRESH: float = 0.5
    過去 3 個交易日 MA60 漲幅（%）超過此值 = 「強力上揚」→ 擋 SHORT。
    0.5% 為初始估計、待回測校準。

## 使用方式

live_intraday_monitor 端（呼叫方 check）：

    from scripts.zhuli.extras.ma60_strong_rising_short_veto import (
        is_ma60_strongly_rising,
        MA60_STRONG_RISE_PCT_THRESH,
    )

    if is_ma60_strongly_rising(st.ma60, st.ma60_3d_ago):
        # 擋 SHORT_SETUP
        pass

或透過 --extras 旗標動態載入（若 monitor 整合 extras registry）。
"""
from __future__ import annotations

# ── 課程外參數 ─────────────────────────────────────────────────────────────────

# 季線「強力上揚」斜率門檻：過去約3個交易日 MA60 漲幅 > 此值 = 強力上揚 → 擋 SHORT
# ⚠️ 課程外自訂、非老師原話、待回測校準
MA60_STRONG_RISE_PCT_THRESH: float = 0.5   # %；可調


# ── 判斷函式 ──────────────────────────────────────────────────────────────────

def is_ma60_strongly_rising(
    ma60_current: float | None,
    ma60_3d_ago: float | None,
    thresh_pct: float = MA60_STRONG_RISE_PCT_THRESH,
) -> bool:
    """季線是否「強力上揚」（課程外量化門檻、預設 OFF）。

    Args:
        ma60_current: 昨日 MA60（日線）
        ma60_3d_ago:  約三個交易日前的 MA60（load_static_for_ticker rows[3]）
        thresh_pct:   強力上揚門檻（%）、預設 MA60_STRONG_RISE_PCT_THRESH=0.5

    Returns:
        True = 季線強力上揚 → 建議擋 SHORT（課程「怕被自救拉起」）
        False = 走平/走下 or 資料不足

    課程出處: §5.3 「季線只要一沒有往上揚、開始變成走平的話、它就會形成土石流」
    ⚠️ thresh_pct 數值 = 課程外自訂、非老師原話、待回測校準
    """
    if ma60_current is None or ma60_3d_ago is None or ma60_3d_ago <= 0:
        return False  # 資料不足 → 不擋（保守、避免漏警）
    rise_pct = (ma60_current / ma60_3d_ago - 1) * 100
    return rise_pct > thresh_pct


# ── 快速 self-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 驗證：MA60 從 100 漲到 100.6 (+0.6%) → True (超過 0.5%)
    assert is_ma60_strongly_rising(100.6, 100.0) is True
    # MA60 走平 (+0.3%) → False
    assert is_ma60_strongly_rising(100.3, 100.0) is False
    # MA60 走下 (-0.2%) → False
    assert is_ma60_strongly_rising(99.8, 100.0) is False
    # 資料缺失 → False
    assert is_ma60_strongly_rising(None, 100.0) is False
    print("extras.ma60_strong_rising_short_veto self-test PASS")
