"""持股集中度警示模組 — 主力大課程輔助資訊.

公開 API:
    concentration_warnings(db_path, ticker) -> (score, warning_lines)

注意：course 未明說「集中 = 利多」，故只警示「分散/散戶接手」出貨方向。
集中訊息只當資訊不計分，避免誤導加碼。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# ── 實際 FinMind TaiwanStockHoldingSharesPer 回傳的 level 名稱 ──
_LARGE_LEVELS = {
    "100,001-200,000",
    "200,001-400,000",
    "400,001-600,000",
    "600,001-800,000",
    "800,001-1,000,000",
    "more than 1,000,001",
}
_MID_LEVELS = {
    "10,001-15,000",
    "15,001-20,000",
    "20,001-30,000",
    "30,001-40,000",
    "40,001-50,000",
    "50,001-100,000",
}
_SMALL_LEVELS = {
    "1-999",
    "1,000-5,000",
    "5,001-10,000",
}

# 過濾掉非有意義列
_SKIP_LEVELS = {"total", "差異數調整（說明4）"}


def concentration_warnings(
    db_path: Path, ticker: str
) -> tuple[int, list[str]]:
    """回傳 (score, warning_lines).

    從 stock_holding_shares_per 抓最近 ~6 週資料
    聚合三檔：
      大戶 = sum(percent where level in _LARGE_LEVELS)
      中戶 = sum(percent where level in _MID_LEVELS)
      散戶 = sum(percent where level in _SMALL_LEVELS)

    警示規則（每條疊加）：
      1. 大戶 4 週內下降 > 1.0%  → 籌碼分散（主力出貨）— +2 分
      2. 散戶 4 週內上升 > 1.5%  → 散戶接手（出貨末段）— +1 分
      3. 大戶最新 < 4 週前 1.5%  → 強烈出貨警示        — +1 分（可與 1 疊加）
      4. 大戶 4 週內上升 > 1.0%  → 籌碼集中（主力進貨）— +0 分（資訊用）

    若資料不足（少於 2 週）返回 (0, ['  ? 集中度資料不足']).
    """
    try:
        with sqlite3.connect(str(db_path), timeout=15) as conn:
            rows = conn.execute(
                """
                SELECT date, level, percent
                FROM stock_holding_shares_per
                WHERE stock_id = ?
                ORDER BY date DESC
                LIMIT 102
                """,
                (ticker,),
            ).fetchall()
    except Exception as exc:
        return 0, [f"  ? 集中度 DB 查詢錯誤: {exc}"]

    if not rows:
        return 0, ["  ? 集中度資料不足"]

    # 按日期分組
    by_date: dict[str, dict[str, float]] = {}
    for date, level, percent in rows:
        if level in _SKIP_LEVELS:
            continue
        if date not in by_date:
            by_date[date] = {}
        by_date[date][level] = percent or 0.0

    dates = sorted(by_date.keys(), reverse=True)  # 最新在前

    if len(dates) < 2:
        return 0, ["  ? 集中度資料不足"]

    def agg(level_map: dict[str, float], level_set: set[str]) -> float:
        return sum(level_map.get(lv, 0.0) for lv in level_set)

    # 最新週
    latest_map = by_date[dates[0]]
    latest_large = agg(latest_map, _LARGE_LEVELS)
    latest_mid = agg(latest_map, _MID_LEVELS)
    latest_small = agg(latest_map, _SMALL_LEVELS)

    # 4 週前（取 index=4 若有，否則最舊）
    ref_idx = min(4, len(dates) - 1)
    ref_map = by_date[dates[ref_idx]]
    ref_large = agg(ref_map, _LARGE_LEVELS)
    ref_small = agg(ref_map, _SMALL_LEVELS)

    large_delta = latest_large - ref_large   # 正 = 集中，負 = 分散
    small_delta = latest_small - ref_small   # 正 = 散戶增，負 = 散戶減

    score = 0
    triggers: list[str] = []

    # 規則 1+3：大戶分散
    if large_delta < -1.0:
        score += 2
        triggers.append(
            f"      [2分] 大戶 4 週減 {large_delta:+.1f}% → 籌碼分散"
        )
        if large_delta < -1.5:
            score += 1
            triggers.append(
                f"      [1分] 大戶降幅 > 1.5%（{large_delta:+.1f}%）→ 強烈出貨警示"
            )

    # 規則 2：散戶接手
    if small_delta > 1.5:
        score += 1
        triggers.append(
            f"      [1分] 散戶 4 週增 +{small_delta:.1f}% → 散戶接手（出貨末段）"
        )

    # 資訊：大戶集中（不計分）
    info_lines: list[str] = []
    if large_delta > 1.0:
        info_lines.append(
            f"      [info] 大戶 4 週增 +{large_delta:.1f}% → 籌碼集中（主力進貨）"
        )

    # 基礎資訊行
    info_lines.append(
        f"      [info] 大戶 {latest_large:.1f}% / 中戶 {latest_mid:.1f}% / 散戶 {latest_small:.1f}%"
        f"  （{dates[0]} 最新）"
    )

    lines: list[str] = []
    if triggers:
        lines.extend(triggers)
    lines.extend(info_lines)

    return score, lines
