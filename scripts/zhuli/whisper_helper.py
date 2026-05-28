"""
whisper_helper.py — mlx-whisper 台股主力大課程轉錄輔助模組

功能:
  1. build_initial_prompt()  → 組裝 --initial-prompt 字串（≤ 224 tokens）
  2. apply_post_process_dict() → 高頻誤譯字典替換 + 替換 log

來源: 5/19 當沖復盤實戰課解讀 + broker_aliases memory
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# 字典檔預設位置（相對專案根目錄）
_DEFAULT_DICT_PATH = Path(__file__).parent / "data" / "whisper_replacements.json"


# ---------------------------------------------------------------------------
# Part 1: build_initial_prompt
# ---------------------------------------------------------------------------

def build_initial_prompt(
    holdings_path: Path | str = Path("docs/主力大課程/holdings.json"),
    extra_terms: list[str] | None = None,
    max_tokens: int = 200,
) -> str:
    """組裝 mlx-whisper --initial-prompt 用的中文提示。

    結構:
        繁體中文台股。常見個股: [holdings 名+ticker] [watchlist 名+ticker]
        分點: 凱基-站前 元大-館前 ...
        術語: 突破 跌破 漲停 跌停 V反 缺口 缺口回補 ...

    Parameters
    ----------
    holdings_path:
        holdings.json 路徑（可為絕對或相對於 cwd 的相對路徑）。
        若檔案不存在，跳過 holdings/watchlist 段落、只保留術語段。
    extra_terms:
        額外要放入 prompt 的術語清單（字串 list）。
    max_tokens:
        prompt token 數上限（whisper 上限 224，保守取 200）。
        超過時從最後截斷。

    Returns
    -------
    str
        prompt string（UTF-8，含換行）
    """
    holdings_path = Path(holdings_path)

    # --- 1. 持倉 + 觀察名單 ---
    stock_terms: list[str] = []
    if holdings_path.exists():
        data = json.loads(holdings_path.read_text(encoding="utf-8"))
        for ticker, info in data.get("holdings", {}).items():
            name = info.get("name", "")
            if name:
                stock_terms.append(f"{name}{ticker}")
        for ticker, info in data.get("watchlist", {}).items():
            name = info.get("name", "")
            if name:
                stock_terms.append(f"{name}{ticker}")
        # 排除清單的公司名仍放進去讓 whisper 認識
        for ticker, info in data.get("exclusion_list", {}).items():
            name = info.get("name", "")
            if name:
                stock_terms.append(f"{name}{ticker}")

    # --- 2. 常見熱門族群代表股 ---
    sector_tickers = [
        # 被動元件
        "國巨2327", "華新1605", "佳邦6284", "鉅祥2476",
        # 矽晶圓/半導體
        "世界先進5347", "聯電2303", "新唐4919", "強茂2481", "文曄3036",
        # 光通/面板
        "群創3481", "正達3149",
        # 其他常見
        "奇鋐3017", "晶豪科3006",
    ]

    # --- 3. 分點別名 ---
    broker_terms = [
        "凱基-站前", "站前哥",
        "元大-館前", "館前哥",
        "永豐金-惠利", "惠利哥",
        "凱基-松山",
        "玉山-中山",
    ]

    # --- 4. 主力大術語 ---
    trading_terms = [
        "漲停", "跌停", "V反", "缺口", "缺口回補",
        "均價線", "江波圖", "動能仔", "周轉率",
        "主力", "分點", "籌碼", "外資", "投信", "自營",
        "突破", "跌破", "壓力", "支撐", "頸線",
        "5分K", "日K", "月線", "季線",
        "掉人線", "吊人線", "吞噬",
        "扣抵值", "MA5", "MA10", "MA20",
        "漲停後的那一天", "昨日收盤價",
        "族群共識", "主力大",
    ]

    if extra_terms:
        trading_terms.extend(extra_terms)

    # --- 組裝 prompt ---
    all_stock = " ".join(dict.fromkeys(stock_terms + sector_tickers))  # 去重保序
    broker_str = " ".join(broker_terms)
    terms_str = " ".join(trading_terms)

    prompt = (
        f"繁體中文台股課程。\n"
        f"常見個股: {all_stock}\n"
        f"分點: {broker_str}\n"
        f"術語: {terms_str}"
    )

    # --- 簡易 token 估算（中文字 ≈ 1.5 token，英數 ≈ 0.25 token）---
    def _rough_tokens(s: str) -> int:
        cjk = sum(1 for c in s if "一" <= c <= "鿿")
        rest = len(s) - cjk
        return int(cjk * 1.5 + rest * 0.25)

    # 超過 max_tokens 時從術語段截斷（優先保住股名與分點）
    if _rough_tokens(prompt) > max_tokens:
        # 逐步縮短 trading_terms
        while trading_terms and _rough_tokens(prompt) > max_tokens:
            trading_terms.pop()
            terms_str = " ".join(trading_terms)
            prompt = (
                f"繁體中文台股課程。\n"
                f"常見個股: {all_stock}\n"
                f"分點: {broker_str}\n"
                f"術語: {terms_str}"
            )

    return prompt


# ---------------------------------------------------------------------------
# Part 2: apply_post_process_dict
# ---------------------------------------------------------------------------

def apply_post_process_dict(
    raw_text: str,
    dict_path: Path | str = _DEFAULT_DICT_PATH,
) -> tuple[str, list[dict]]:
    """套用高頻誤譯字典替換，回傳 (cleaned_text, replacement_log)。

    Parameters
    ----------
    raw_text:
        原始 whisper 輸出文字（可含換行）。
    dict_path:
        whisper_replacements.json 路徑。

    Returns
    -------
    cleaned : str
        替換後文字。
    log : list[dict]
        每條替換紀錄，格式:
        {
            "original": str,
            "replaced_with": str,
            "count": int,
            "line_numbers": list[int]   # 1-based
        }
    """
    dict_path = Path(dict_path)
    if not dict_path.exists():
        raise FileNotFoundError(f"替換字典不存在: {dict_path}")

    raw_dict: dict[str, str] = json.loads(dict_path.read_text(encoding="utf-8"))

    # 過濾掉 _meta 鍵與 TODO 值（TODO 保留原文）
    replacements = {
        k: v
        for k, v in raw_dict.items()
        if not k.startswith("_") and not v.startswith("TODO")
    }

    lines = raw_text.splitlines(keepends=True)
    log: list[dict] = []

    for wrong, correct in replacements.items():
        hit_lines: list[int] = []
        count = 0
        for i, line in enumerate(lines, start=1):
            occurrences = line.count(wrong)
            if occurrences:
                lines[i - 1] = line.replace(wrong, correct)
                count += occurrences
                hit_lines.append(i)
        if count > 0:
            log.append(
                {
                    "original": wrong,
                    "replaced_with": correct,
                    "count": count,
                    "line_numbers": hit_lines,
                }
            )

    cleaned = "".join(lines)
    # 依替換次數降冪排序 log
    log.sort(key=lambda x: x["count"], reverse=True)
    return cleaned, log


# ---------------------------------------------------------------------------
# CLI 快速測試
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("=== build_initial_prompt (前 500 chars) ===")
    # 嘗試從專案根目錄找 holdings.json
    project_root = Path(__file__).parents[2]
    holdings = project_root / "docs" / "主力大課程" / "holdings.json"
    prompt = build_initial_prompt(holdings_path=holdings)
    print(prompt[:500])
    print(f"\n全長: {len(prompt)} 字元")

    print("\n=== apply_post_process_dict ===")
    test_input = "連店今天漲停，强貌也不錯，管錢哥在金豪科大買。"
    cleaned, log = apply_post_process_dict(test_input)
    print(f"原文: {test_input}")
    print(f"替換後: {cleaned}")
    print(f"替換 log: {log}")
