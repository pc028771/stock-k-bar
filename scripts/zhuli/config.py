"""Default parameters for zhuli course strategies.

All values are CALIBRATABLE — see calibration.py for the update interface.

Course source: 主力大全方位操盤教戰守則 (林家洋)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path
from typing import Any


@dataclass
class SuffocationConfig:
    """Parameters for H 窒息量策略 (zhuli_suffocation).

    Fields are grouped into:
      - Hard rules: spec-defined constants from course, generally not tunable.
      - Soft margins: calibratable via CLI or JSON override file.
      - Liquidity filters: operational filters (course-neutral defaults).
      - Boost score conditions: ideal conditions for signal quality scoring.
    """

    # === Hard rules from course (spec-defined, generally not tunable) ===
    # Source: strategy-indicators.md §H — 「當日成交量 < 20 日內最大量的 10%」
    max20_volume_ratio: float = 0.10  # vol < max(vol_20d) * 0.10
    # Source: course_principles.md §16 — 「必要：月線上彎」
    require_ma20_slope_up: bool = True  # 月線 (20MA) 上彎為必要

    # === Soft margins (calibratable) ===
    # 往前 N 日找窒息量 K；候選窒息量必須在出量 K 的前一根
    # Spec: Ex1-3 05:00 SOP 投影片 — 「等下一根出量 K」，i.e., lookback=1
    lookback_days: int = 1  # 候選窒息量 = 昨天；今天 = 出量 K

    # 出量 K 量增門檻（spec 只說「比前一根多」，未定具體倍數）
    # Source: strategy-indicators.md §H — 「next_bar.volume > suffocation_bar.volume」
    breakout_volume_multiplier: float = 1.0  # 1.0 = 嚴格按 spec「比前一根多」

    # === Liquidity filters (course-neutral operational defaults) ===
    # 流動性過濾，沿用 main 慣例；可透過 CLI 覆寫
    min_avg_volume_20: int = 200   # 千股 (vol_ma20 單位)
    min_close: float = 10.0        # 元

    # === Boost score conditions (ideal 多頭排列) ===
    # Source: strategy-indicators.md §H — 「理想（最高勝率）：5/10/20/60ma 排列正確且皆上彎」
    # 若 True = 必要條件（會過濾掉不符合的）；若 False = 只加分、不過濾
    ideal_ma_alignment_required: bool = False  # 預設加分不過濾

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SuffocationConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> "SuffocationConfig":
        """Load config overrides from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def apply_overrides(self, overrides: dict[str, str]) -> "SuffocationConfig":
        """Apply KEY=VALUE string overrides (from CLI --config-override).

        Values are coerced to the correct Python type based on the field's
        current default type (bool, int, float).

        Example:
            cfg.apply_overrides({"min_close": "15.0", "lookback_days": "2"})
        """
        d = self.to_dict()
        for key, raw_val in overrides.items():
            if key not in d:
                raise ValueError(
                    f"Unknown SuffocationConfig key: '{key}'. "
                    f"Valid keys: {list(d.keys())}"
                )
            original = d[key]
            if isinstance(original, bool):
                d[key] = raw_val.lower() in ("1", "true", "yes")
            elif isinstance(original, int):
                d[key] = int(raw_val)
            elif isinstance(original, float):
                d[key] = float(raw_val)
            else:
                d[key] = raw_val
        return SuffocationConfig.from_dict(d)
