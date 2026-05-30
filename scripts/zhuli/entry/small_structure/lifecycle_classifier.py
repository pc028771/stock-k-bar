"""Lifecycle Classifier — 攻擊後盤整候選的 lifecycle 標籤 (純 info、不 filter).

4 種標籤:
  consol_early       : 攻擊後剛進入整理 (1-5 天)
  consol_late        : 整理 7+ 天、即將突破 (現有 scanner 的 target)
  post_break_tail    : 突破後尾巴 (距 MA10 > +10%)
  failed_breakout    : 突破失敗 / W底反覆 (守 MA10 下方)

sub_pattern (子型):
  短週期 : 攻擊段 3-7 天、漲幅 +10-20%
  長週期 : 攻擊段 10-30 天、漲幅 +25%+
  None   : 無法判定
"""
from __future__ import annotations

import pandas as pd


def classify_lifecycle_label(
    info: dict,
    close: pd.Series | None = None,
) -> tuple[str, str | None]:
    """給定 get_post_attack_info 的 info dict，回傳 (lifecycle_label, sub_pattern).

    Parameters
    ----------
    info   : get_post_attack_info() 的回傳值
    close  : 原始 close Series (可選，用於驗證距 MA10)

    Returns
    -------
    (lifecycle_label, sub_pattern)
    """
    if info is None:
        return ('unknown', None)

    consol_days = info.get('consol_days', 0)
    dist_ma10 = info.get('dist_ma10_pct')
    attack_pct = info.get('attack_pct', 0)      # 0.xx 小數
    attack_days = info.get('attack_days', 0)
    close_last = info.get('close_last')
    attack_end_idx = info.get('attack_end_idx')
    # 計算「今日 close 相對突破高點」拉回幅度
    drawdown_from_peak_pct = None
    if close_last is not None and close is not None and attack_end_idx is not None:
        try:
            atk_end_close = float(close.iloc[attack_end_idx])
            if atk_end_close > 0:
                drawdown_from_peak_pct = (close_last - atk_end_close) / atk_end_close * 100.0
        except (IndexError, KeyError, TypeError):
            drawdown_from_peak_pct = None

    # ── sub_pattern ───────────────────────────────────────────────────────────
    if attack_days >= 10 and attack_pct >= 0.25:
        sub = '長週期'
    elif 3 <= attack_days <= 7 and attack_pct < 0.25:
        sub = '短週期'
    else:
        sub = '短週期'  # 大多數微整理都是短週期

    # ── lifecycle label ───────────────────────────────────────────────────────
    # 失敗判定 (優先)：突破後拉回 > 5% (close 從 attack_end_close 拉回) OR 守不住 MA10
    if drawdown_from_peak_pct is not None and drawdown_from_peak_pct < -5.0:
        return ('failed_breakout', sub)
    if dist_ma10 is not None and dist_ma10 < -2.0:
        return ('failed_breakout', sub)

    # 尾巴判定：距 MA10 > 10% (突破後一路漲、過熱)
    if dist_ma10 is not None and dist_ma10 > 10.0:
        return ('post_break_tail', sub)

    # 整理末期：整理 7+ 天
    if consol_days >= 7:
        return ('consol_late', sub)

    # 整理早期：1-5 天（post_attack_filter 已確保 consol_days ≤ consol_window）
    return ('consol_early', sub)


# 人讀標籤對應
LIFECYCLE_DISPLAY = {
    'consol_early': '4a 微整理',
    'consol_late': '1b 整理末期',
    'post_break_tail': '4a 尾巴',
    'failed_breakout': '5 失敗/W底',
    'unknown': '?',
}
