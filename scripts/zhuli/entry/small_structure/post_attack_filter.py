"""攻擊後盤整過濾器 — post_attack_consol tier.

過去 attack_window 天有攻擊 +10%+ 且最近 consol_window 天進入盤整。
輸出供人眼辨識 + 問老師用。

過濾條件:
1. 過去 attack_window + consol_window 天有攻擊段 ≥ +10%
2. 最近 1-consol_window 天 close range < consol_range_pct (進入盤整)
3. 量比降下來：整理段均量比 < 攻擊段均量比
4. close 還在 MA10 上 (整理沒崩)

判斷流程:
  1. 找「最近 attack_window+consol_window 天內的最高收盤日」→ 攻擊終點
  2. 整理段 = 攻擊終點+1 到最後
  3. 驗證整理段長度 1~consol_window 且 range < threshold
"""
from __future__ import annotations

import pandas as pd


def get_post_attack_info(
    df: pd.DataFrame,
    attack_window: int = 15,
    consol_window: int = 5,
    min_attack_pct: float = 0.10,
    consol_range_pct: float = 0.10,
) -> dict | None:
    """攻擊後盤整資訊 dict，不符合回傳 None.

    Parameters
    ----------
    df              : 單 ticker DataFrame，需含 close, ma10, vol_ratio_20
    attack_window   : 在整理段之前最多往前看幾天找攻擊起點 (預設 15 天)
    consol_window   : 盤整天數上限 (預設 5 天)
    min_attack_pct  : 最小攻擊幅 (預設 10%)
    consol_range_pct: 盤整 range 門檻 (預設 5%)

    Returns
    -------
    None 或 dict:
      attack_start_date, attack_end_date,
      attack_pct          : float (0.xx)
      attack_days         : int
      consol_days         : int
      consol_range_pct    : float (0.xx)
      vol_contraction_ratio : float | None
      dist_ma10_pct       : float | None
      close_last          : float
    """
    if df is None or len(df) < 20:
        return None

    date_col = 'trade_date' if 'trade_date' in df.columns else 'date'
    close = df['close'].reset_index(drop=True)
    n = len(close)

    vol_ratio = df.get('vol_ratio_20', pd.Series(dtype=float)).reset_index(drop=True)
    ma10 = df.get('ma10', pd.Series(dtype=float)).reset_index(drop=True)
    dates = df[date_col].reset_index(drop=True) if date_col in df.columns else None

    # ── MA10 純當參考 (user 5/30 校正、不過濾) ────────────────────────────────
    close_last = float(close.iloc[-1])
    dist_ma10 = None
    if not ma10.empty and len(ma10) == n and pd.notna(ma10.iloc[-1]):
        ma10_last = float(ma10.iloc[-1])
        dist_ma10 = (close_last - ma10_last) / ma10_last * 100.0

    # ── 步驟 1: 找攻擊終點 ─────────────────────────────────────────────────────
    # 搜尋範圍：確保終點後至少 1 根整理、最多 consol_window 根整理
    # 攻擊終點候選範圍 = [n - attack_window - consol_window, n - 1 - 1]
    # 但整理段長度 = n - 1 - atk_end，必須在 [1, consol_window]
    # 即 atk_end 必須在 [n - 1 - consol_window, n - 2]
    atk_end_lo = max(0, n - 1 - consol_window)  # 整理最多 consol_window 天
    atk_end_hi = n - 2                           # 整理至少 1 天

    if atk_end_lo >= n or atk_end_hi < 1 or atk_end_lo > atk_end_hi:
        return None

    # 在 [atk_end_lo, atk_end_hi] 找最高收盤作為攻擊終點
    candidate_close = close.iloc[atk_end_lo: atk_end_hi + 1]
    atk_end = int(candidate_close.idxmax())

    # ── 步驟 2: 計算整理段 ────────────────────────────────────────────────────
    consol_slice = close.iloc[atk_end + 1:]
    consol_days = len(consol_slice)

    # 整理天數超出範圍 → 排除（理論上不會發生，因為 atk_end 限制在範圍內）
    if consol_days < 1 or consol_days > consol_window:
        return None

    # ── 條件 2: 整理段 range < consol_range_pct ──────────────────────────────
    atk_end_close = float(close.iloc[atk_end])
    if consol_days == 1:
        # 用「收盤回撤 = (atk_end_close - last_close) / atk_end_close」代替 range
        # 整理 1 天不應大幅回落（> consol_range_pct）
        pullback = (atk_end_close - close_last) / atk_end_close if atk_end_close > 0 else 0.0
        rng_pct = max(pullback, 0.0)
    else:
        rng_val = consol_slice.max() - consol_slice.min()
        rng_pct = rng_val / consol_slice.mean() if consol_slice.mean() > 0 else 999.0

    if rng_pct >= consol_range_pct:
        return None

    # ── 條件 1: 攻擊段 ≥ min_attack_pct ────────────────────────────────────────
    atk_high = float(close.iloc[atk_end])
    search_start = max(0, atk_end - attack_window)
    prior_slice = close.iloc[search_start: atk_end]

    if prior_slice.empty:
        return None

    atk_low_val = float(prior_slice.min())
    atk_low_idx = int(prior_slice.idxmin())
    if atk_low_val <= 0:
        return None

    attack_pct = atk_high / atk_low_val - 1.0
    if attack_pct < min_attack_pct:
        return None

    attack_days = atk_end - atk_low_idx

    # ── 條件 3: 量比降下來 ────────────────────────────────────────────────────
    vol_contraction_ratio = None
    if not vol_ratio.empty and len(vol_ratio) == n:
        atk_vol_slice = vol_ratio.iloc[atk_low_idx: atk_end + 1]
        consol_vol_slice = vol_ratio.iloc[atk_end + 1:]
        if len(atk_vol_slice) > 0 and len(consol_vol_slice) > 0:
            atk_vol_mean = float(atk_vol_slice.mean())
            consol_vol_mean = float(consol_vol_slice.mean())
            if atk_vol_mean > 0:
                vol_contraction_ratio = consol_vol_mean / atk_vol_mean
                if vol_contraction_ratio >= 1.0:
                    return None

    # ── 取日期 ────────────────────────────────────────────────────────────────
    atk_start_date = str(dates.iloc[atk_low_idx]) if dates is not None else None
    atk_end_date = str(dates.iloc[atk_end]) if dates is not None else None

    return {
        'attack_start_idx': atk_low_idx,
        'attack_end_idx': atk_end,
        'attack_start_date': atk_start_date,
        'attack_end_date': atk_end_date,
        'attack_pct': attack_pct,
        'attack_days': attack_days,
        'consol_days': consol_days,
        'consol_range_pct': rng_pct,
        'vol_contraction_ratio': vol_contraction_ratio,
        'dist_ma10_pct': dist_ma10,
        'close_last': close_last,
    }


def is_post_attack_consolidating(
    df: pd.DataFrame,
    attack_window: int = 15,
    consol_window: int = 5,
    min_attack_pct: float = 0.10,
    consol_range_pct: float = 0.05,
) -> bool:
    """攻擊後盤整判定（單 ticker df，回傳 bool）."""
    return get_post_attack_info(
        df,
        attack_window=attack_window,
        consol_window=consol_window,
        min_attack_pct=min_attack_pct,
        consol_range_pct=consol_range_pct,
    ) is not None
