"""W 底起漲 scanner — 偵測「大跌 → 反彈未過前高 → 二次拉回守住 → 準備突破」模式.

依據 4958 臻鼎-KY 2026/03/23 起漲前形態提煉（老師 5/22 強調「完美複製 4958 起漲前長相」，案例 6239 力成 5/22 漲停）。

## 模式核心

```
高點 H1 ───────╗
              ╲                  反彈高 H2 (≤ H1)
               ╲                ╱
                ╲     ╱╲      ╱
                 ╲   ╱  ╲    ╱
                  ╲ ╱    ╲  ╱
                   ╳      ╲╱   ← 二次拉回（不破 L1）
                  低點 L1
                              起漲前位置（檢測日）
```

## 條件

1. **大跌主跌**：過去 60 天高點 → 30 天內最低點，跌幅 ≥ 20%
2. **反彈高足夠**：反彈最高 H2 ≥ H1 × 0.85（漲回前高至少 85%）
3. **W 底成立**：二次拉回低點 > 第一次低點 × 0.95（不破第一次低點）
4. **接近反彈高**：當日收盤 ≥ H2 × 0.90（準備突破反彈高）
5. **量縮**：近 5 日均量比 < 1.5（整理中）
6. **未破 MA20**：close ≥ ma20 × 0.95（中期趨勢未破）

## 與其他 scanner 區別

- **shakeout_strong**：底部窒息突破（無前高參考）
- **small_structure**：高位整理末端（N 字中段）
- **w_bottom_launch**：W 底完成、準備從反彈高突破起漲（**最大波段潛力**）

## 案例

- 4958 臻鼎-KY 3/23 觸發 → 噴到 432（+125% 在 28 天）
- 6239 力成 5/20-5/21 觸發 → 5/22 漲停（短期確認）
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from kline.features import REQUIRED_FEATURES_W_BOTTOM as REQUIRED_FEATURES  # noqa: F401


def detect(df: pd.DataFrame) -> pd.Series:
    """W 底起漲偵測.

    回傳 bool Series，True = 該日符合 W 底起漲前條件.
    """
    c = df['close']
    h = df['high']
    l = df['low']
    vol_ratio = df.get('vol_ratio_20', pd.Series(np.nan, index=df.index))
    ma20 = df.get('ma20', pd.Series(np.nan, index=df.index))

    # 1. 大跌主跌：過去 60 天 H1 → 過去 30 天 L1，跌幅 ≥ 20%
    h1 = h.rolling(90, min_periods=40).max().shift(20)  # 60-90 天前的高
    l1 = l.rolling(40, min_periods=20).min().shift(10)   # 30-40 天內低
    big_drop = (l1 / h1 - 1) <= -0.20

    # 2. 反彈高足夠：H2 = 過去 20 天高 ≥ H1 × 0.85
    h2 = h.rolling(20).max()
    valid_bounce = h2 >= h1 * 0.85

    # 3. W 底成立：近 10 天低 > L1 × 0.95
    second_low = l.rolling(10).min()
    w_bottom = second_low > l1 * 0.95

    # 4. 接近反彈高：close ≥ H2 × 0.88（更寬鬆，允許還在二次拉回中）
    near_h2 = c / h2 >= 0.88

    # 5. 量縮：近 5 日均量比 < 1.5
    vol_contracted = vol_ratio.rolling(5).mean() < 1.5

    # 6. 未跌破 MA20 太多
    above_ma20 = c >= ma20 * 0.95

    signal = (
        big_drop.fillna(False) &
        valid_bounce.fillna(False) &
        w_bottom.fillna(False) &
        near_h2.fillna(False) &
        vol_contracted.fillna(False) &
        above_ma20.fillna(False)
    )

    return signal.reindex(df.index).fillna(False)


def detect_with_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    """回傳含各條件診斷的 DataFrame."""
    c = df['close']
    h = df['high']
    l = df['low']
    vol_ratio = df.get('vol_ratio_20', pd.Series(np.nan, index=df.index))
    ma20 = df.get('ma20', pd.Series(np.nan, index=df.index))

    h1 = h.rolling(90, min_periods=40).max().shift(20)
    l1 = l.rolling(40, min_periods=20).min().shift(10)
    h2 = h.rolling(20).max()
    second_low = l.rolling(10).min()

    result = pd.DataFrame({
        'date': df['date'] if 'date' in df else df.index,
        'close': c,
        'H1_prior_high': h1,
        'L1_main_low': l1,
        'drop_pct': (l1 / h1 - 1) * 100,
        'H2_bounce_high': h2,
        'bounce_ratio': h2 / h1,
        'second_low': second_low,
        'w_bottom_ratio': second_low / l1,
        'close_to_h2': c / h2,
        'vol_5d_avg': vol_ratio.rolling(5).mean(),
        'cond_big_drop': ((l1 / h1 - 1) <= -0.20).fillna(False),
        'cond_valid_bounce': (h2 >= h1 * 0.85).fillna(False),
        'cond_w_bottom': (second_low > l1 * 0.95).fillna(False),
        'cond_near_h2': (c / h2 >= 0.88).fillna(False),
        'cond_vol_contracted': (vol_ratio.rolling(5).mean() < 1.5).fillna(False),
        'cond_above_ma20': (c >= ma20 * 0.95).fillna(False),
    })
    result['all_pass'] = (
        result['cond_big_drop'] & result['cond_valid_bounce'] & result['cond_w_bottom'] &
        result['cond_near_h2'] & result['cond_vol_contracted'] & result['cond_above_ma20']
    )
    return result
