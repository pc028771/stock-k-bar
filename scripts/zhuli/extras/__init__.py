# scripts/zhuli/extras/ — 課程外輔助資料源（預設 OFF，透過 --enable-* 啟用）
#
# 注意：此目錄放的是「資料源 + heuristic 判處置」邏輯（課程外）。
# 老師框架本身（A/B/C 分型）在 scripts/zhuli/disposal_framework.py。
#
# 其他老師方法亦放此處，獨立 module（如 macd_diff_huangda = 黃大方法）。
# 紀律：永不升格主力大課程 spec、永遠標 extras. 前綴。詳見 README.md。

from __future__ import annotations

# ── Registry hooks（給 monitor / scanner 使用）─────────────────────────────────

ENTRY_FILTER_REGISTRY: dict = {}
EXIT_REGISTRY: dict = {}
SCORING_REGISTRY: dict = {}


def register_macd_diff_huangda():
    """註冊黃大 MACD DIF 三個 hook（lazy import 避免啟動成本）。

    呼叫方：monitor 或 scanner 在 --extras macd_diff_huangda 啟用時呼叫一次。
    """
    from . import macd_diff_huangda as mh

    ENTRY_FILTER_REGISTRY["extras.macd_diff_huangda.bear_resonance"] = (
        mh.bear_resonance_filter
    )
    EXIT_REGISTRY["extras.macd_diff_huangda.h1_flip_long"] = (
        mh.h1_flip_long_exit
    )
    SCORING_REGISTRY["extras.macd_diff_huangda.bull_resonance"] = (
        mh.bull_resonance_score
    )
