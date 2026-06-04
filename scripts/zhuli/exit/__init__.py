"""出場 detector 模組 — Phase 1。

提供 4 個基於課程規則的出場訊號偵測器:
  check_umbrella_exit         🌂 掀傘 (連 2-3 根不創高 + 量縮)
  check_high_long_black       🦘 高檔長黑 K (≥2 種攻擊結束意義)
  check_profit_milestone      💰 分批停利里程碑 (+10/20/30%)
  check_gap_down_emergency    📉 隔日跳空大跌 (開盤 -5%)
"""
from .detectors import (
    check_umbrella_exit,
    check_high_long_black,
    check_profit_milestone,
    check_gap_down_emergency,
)

__all__ = [
    "check_umbrella_exit",
    "check_high_long_black",
    "check_profit_milestone",
    "check_gap_down_emergency",
]
