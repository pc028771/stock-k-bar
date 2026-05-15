from __future__ import annotations

import pandas as pd


def build_vp_from_kbar(kbar: pd.DataFrame, tick_size: float = 0.01) -> pd.DataFrame:
    """把 1分K OHLCV 聚合成分價量表 [price, volume]。

    每根 bar 的 volume 均勻分配到 high-low 之間的 tick 格子。
    tick_size 預設 0.01 元（台股最小跳動單位）。
    """
    if kbar.empty:
        return pd.DataFrame(columns=["price", "volume"])

    buckets: dict[float, float] = {}
    for _, row in kbar.iterrows():
        lo = _snap(float(row["low"]), tick_size)
        hi = _snap(float(row["high"]), tick_size)
        vol = float(row["volume"])
        if lo >= hi:
            buckets[lo] = buckets.get(lo, 0.0) + vol
        else:
            ticks = round((hi - lo) / tick_size) + 1
            vol_per = vol / ticks
            p = lo
            for _ in range(ticks):
                rp = _snap(p, tick_size)
                buckets[rp] = buckets.get(rp, 0.0) + vol_per
                p += tick_size

    return pd.DataFrame(sorted(buckets.items()), columns=["price", "volume"])


def _snap(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 10)


def compute_vp_features(
    vp: pd.DataFrame,
    current_close: float,
    band_pct: float = 0.10,
    dense_quantile: float = 0.80,
) -> dict[str, float | bool]:
    """從分價量表計算壓力區特徵。

    Args:
        vp:             [price, volume] DataFrame
        current_close:  今日收盤價
        band_pct:       觀察帶寬，現價上方 0% ~ band_pct（預設 10%）
        dense_quantile: 密集定義門檻：該帶有 bucket 超過全體第 dense_quantile 分位（預設 80th）

    Returns dict keys:
        vp_overhead_pct           — 現價以上成交量佔全日總量比率（0–1）
        vp_dense_above            — 現價上方 band 內有密集成交區
        vp_supply_vacuum          — 現價上方 band 內無密集區（賣壓中空）
        vp_nearest_resistance_pct — 最近密集成交區距現價距離（%），無則 NaN
    """
    nan_result: dict[str, float | bool] = {
        "vp_overhead_pct": float("nan"),
        "vp_dense_above": False,
        "vp_supply_vacuum": False,
        "vp_nearest_resistance_pct": float("nan"),
    }
    if vp.empty or current_close <= 0:
        return nan_result

    total_vol = float(vp["volume"].sum())
    if total_vol == 0:
        return nan_result

    band_high = current_close * (1 + band_pct)
    above = vp[vp["price"] > current_close]
    in_band = vp[(vp["price"] > current_close) & (vp["price"] <= band_high)]

    vp_overhead_pct = float(above["volume"].sum() / total_vol)

    dense_threshold = float(vp["volume"].quantile(dense_quantile))
    vacuum_threshold = float(vp["volume"].quantile(0.20))

    if in_band.empty:
        vp_dense_above = False
        vp_supply_vacuum = True
    else:
        vp_dense_above = bool((in_band["volume"] >= dense_threshold).any())
        vp_supply_vacuum = bool(float(in_band["volume"].max()) < vacuum_threshold)

    if above.empty:
        vp_nearest_resistance_pct = float("nan")
    else:
        dense_above = above[above["volume"] >= dense_threshold]
        if dense_above.empty:
            vp_nearest_resistance_pct = float("nan")
        else:
            nearest = float(dense_above["price"].min())
            vp_nearest_resistance_pct = round((nearest / current_close - 1) * 100, 2)

    return {
        "vp_overhead_pct": round(vp_overhead_pct, 4),
        "vp_dense_above": vp_dense_above,
        "vp_supply_vacuum": vp_supply_vacuum,
        "vp_nearest_resistance_pct": vp_nearest_resistance_pct,
    }


if __name__ == "__main__":
    import pandas as pd

    kbar = pd.DataFrame({
        "open":   [10.0, 10.5],
        "high":   [10.5, 11.0],
        "low":    [10.0, 10.5],
        "close":  [10.4, 10.9],
        "volume": [1000, 2000],
    })
    vp = build_vp_from_kbar(kbar)
    assert not vp.empty, "VP should not be empty"
    assert list(vp.columns) == ["price", "volume"], "Wrong columns"
    assert abs(vp["volume"].sum() - 3000) < 1, f"Volume sum mismatch: {vp['volume'].sum()}"

    feats = compute_vp_features(vp, current_close=10.4)
    assert "vp_overhead_pct" in feats
    assert 0 <= feats["vp_overhead_pct"] <= 1
    assert isinstance(feats["vp_dense_above"], bool)
    assert isinstance(feats["vp_supply_vacuum"], bool)

    # edge case: empty vp
    empty_feats = compute_vp_features(pd.DataFrame(columns=["price", "volume"]), 10.0)
    import math
    assert math.isnan(empty_feats["vp_overhead_pct"])

    print("volume_profile.py: all assertions passed")
    print(feats)
