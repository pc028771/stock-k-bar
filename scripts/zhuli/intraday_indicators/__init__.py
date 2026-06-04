"""主力大 Ch5 純當沖補強 indicator 集。

補 scripts/zhuli/intraday_stage_helper.StageTrigger 沒覆蓋的 gap：
- 紅線 #9 前 5 分鐘 > 5% skip
- 均線發散硬性過濾
- B5-1 2 分 K 3% / 5 分 K 5% 必停利
- B5-2 漲停隔日 A/B 型識別
- B5-3 季線往上不空（空方過濾）
- B5-7 等 K 棒收完才下判斷
"""
from __future__ import annotations

from .ch5_complement import (
    check_first5min_skip,
    check_ma_divergence,
    check_b5_1_stop_profit,
    check_b5_2_limit_up_pattern,
    check_b5_3_quarterly_ma_short_filter,
    is_bar_closed,
)
from .monitor_hook import (
    parse_extras,
    run_ch5_complement,
    run_huangda_if_enabled,
    compose_trigger,
)

__all__ = [
    # ch5 complement indicators
    "check_first5min_skip",
    "check_ma_divergence",
    "check_b5_1_stop_profit",
    "check_b5_2_limit_up_pattern",
    "check_b5_3_quarterly_ma_short_filter",
    "is_bar_closed",
    # monitor hook
    "parse_extras",
    "run_ch5_complement",
    "run_huangda_if_enabled",
    "compose_trigger",
]
