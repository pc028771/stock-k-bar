"""小結構整理 scanner — module 入口.

偵測「N字攻擊後的高位整理末端」pattern。
依據 5/21 老師「群創 N字上攻」教學提煉，5/22 驗證 77% 上漲率。

## 公開 API

    from zhuli.entry.small_structure import detect
    from zhuli.entry.small_structure import detect_with_diagnostics
    from zhuli.entry.small_structure import run_scan
    from zhuli.entry.small_structure import run_watchlist

## 向後相容

原 import 路徑 `from zhuli.entry.small_structure import detect` 維持不變。

## 用法

    feats = add_features(bars)
    feats['signal'] = detect(feats)

## CLI

    python -m zhuli.entry.small_structure --date 2026-05-29
    python -m zhuli.entry.small_structure --date 2026-05-29 --watchlist
    python -m zhuli.entry.small_structure --date 2026-05-29 --watchlist --universe sector_week
"""
from zhuli.entry.small_structure.detector import detect, detect_with_diagnostics
from zhuli.entry.small_structure.watchlist import run_watchlist, run_post_attack_watchlist, format_post_attack_report
from zhuli.entry.small_structure.post_attack_filter import is_post_attack_consolidating, get_post_attack_info
from zhuli.entry.small_structure.lifecycle_classifier import classify_lifecycle_label, LIFECYCLE_DISPLAY

__all__ = [
    "detect",
    "detect_with_diagnostics",
    "run_watchlist",
    "run_post_attack_watchlist",
    "format_post_attack_report",
    "is_post_attack_consolidating",
    "get_post_attack_info",
    "classify_lifecycle_label",
    "LIFECYCLE_DISPLAY",
    "run_scan",
]


def run_scan(
    df,
    target_date: str | None = None,
    watchlist_mode: bool = False,
    universe: str = "all",
):
    """統一 scan 入口.

    Parameters
    ----------
    df           : 單一 ticker 的 DataFrame（含必要欄位）
    target_date  : 目標日期（用於 watchlist + sector_week universe）
    watchlist_mode : True = 回傳 watchlist DataFrame；False = 回傳 bool Series
    universe     : 'all' | 'sector_all' | 'sector_week'

    Returns
    -------
    watchlist_mode=False: bool Series
    watchlist_mode=True:  DataFrame
    """
    if watchlist_mode:
        return run_watchlist(df, universe=universe, target_date=target_date)
    return detect(df)
