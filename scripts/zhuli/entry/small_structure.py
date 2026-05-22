"""小結構整理 scanner — 偵測「N字攻擊後的高位整理末端」.

依據 5/21 老師「群創 N字上攻」教學提煉的 pattern。
群創 5/14-5/20 即經典案例：5/13 攻上 37.5 後高點橫盤 7 天，量縮 → 5/21 漲停。

## 偵測邏輯

1. **前段攻擊**：過去 10-20 個交易日有 +10% 以上的攻擊
2. **高位整理**：近 5 天收盤在 95% 高點附近橫盤（不破前高 -5%）
3. **量縮整理**：近 5 天均量比 < 1.0（窒息整理）
4. **MA 追上**：MA5/收盤 > 0.95（均線快追上來）
5. **無跌破結構**：未跌破 MA10

## 與其他 scanner 區別

- **shakeout_strong** 偵測「底部窒息 → 突破」
- **small_structure** 偵測「突破後 → 高位整理 → 第二攻準備」
- 兩者互補，shakeout 在 N 字底部，small_structure 在 N 字中段

## 用法

    from zhuli.entry.small_structure import detect

    feats = add_features(bars)
    feats['signal'] = detect(feats)
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def detect(df: pd.DataFrame) -> pd.Series:
    """小結構整理偵測.

    回傳 bool Series，True = 該日符合「小結構整理末端」條件.
    """
    c = df['close']
    h = df['high']
    vol_ratio = df.get('vol_ratio_20', pd.Series(np.nan, index=df.index))
    ma5 = df.get('ma5', pd.Series(np.nan, index=df.index))
    ma10 = df.get('ma10', pd.Series(np.nan, index=df.index))

    # 1. 前段攻擊：過去 10-20 天有 +10% 漲幅
    prior_low = c.rolling(20).min().shift(5)
    prior_attack = (c / prior_low - 1) >= 0.10

    # 2. 高位整理：近 5 天「收盤」range < 10%（用 close 不用 high-low）
    close_range_5d = (c.rolling(5).max() - c.rolling(5).min()) / c
    is_sideways = close_range_5d < 0.10

    # 3. 量縮趨勢：近 3 天均量比 < 1.4 且最後一日 < 前 3 天均
    vol_recent_3 = vol_ratio.rolling(3).mean()
    vol_decreasing = (vol_recent_3 < 1.5) & (vol_ratio < vol_recent_3.shift(2))

    # 4. MA5 追上：MA5/收盤 > 0.93（均線距離收盤 7% 內）
    ma5_close = ma5 / c > 0.93

    # 5. 未跌破 MA10 太多
    above_ma10 = c >= ma10 * 0.95

    # 6. 高位整理（收盤在近 10 天高點 88% 以上）
    high_10d = h.rolling(10).max()
    high_holding = c / high_10d >= 0.85

    signal = (
        prior_attack.fillna(False) &
        is_sideways.fillna(False) &
        vol_decreasing.fillna(False) &
        ma5_close.fillna(False) &
        above_ma10.fillna(False) &
        high_holding.fillna(False)
    )

    return signal.reindex(df.index).fillna(False)


def detect_with_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    """回傳含各條件診斷的 DataFrame（用於 debug）."""
    c = df['close']
    h = df['high']
    l = df['low']
    vol_ratio = df.get('vol_ratio_20', pd.Series(np.nan, index=df.index))
    ma5 = df.get('ma5', pd.Series(np.nan, index=df.index))
    ma10 = df.get('ma10', pd.Series(np.nan, index=df.index))

    prior_low = c.rolling(20).min().shift(5)
    close_range_5d = (c.rolling(5).max() - c.rolling(5).min()) / c
    high_10d = h.rolling(10).max()
    vol_recent_3 = vol_ratio.rolling(3).mean()

    result = pd.DataFrame({
        'date': df['date'] if 'date' in df else df.index,
        'close': c,
        'cond_prior_attack': (c / prior_low - 1) >= 0.10,
        'cond_sideways': close_range_5d < 0.10,
        'cond_vol_contracted': (vol_recent_3 < 1.5) & (vol_ratio < vol_recent_3.shift(2)),
        'cond_ma5_close': (ma5 / c > 0.93).fillna(False),
        'cond_above_ma10': (c >= ma10 * 0.95).fillna(False),
        'cond_high_holding': (c / high_10d >= 0.85).fillna(False),
        'vol_recent_3_mean': vol_recent_3,
        'close_range_5d_pct': close_range_5d * 100,
    })
    result['all_pass'] = (
        result['cond_prior_attack'] &
        result['cond_sideways'] &
        result['cond_vol_contracted'] &
        result['cond_ma5_close'] &
        result['cond_above_ma10'] &
        result['cond_high_holding']
    )
    return result
