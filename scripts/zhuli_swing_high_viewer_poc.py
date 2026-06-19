"""
主力大「反轉形態」Swing High POC 畫圖工具
=========================================
目的：校準「兩個明顯高點連線」演算法，輸出 PNG 供人工 / vision 判讀。

使用：
    python scripts/zhuli_swing_high_viewer_poc.py --ticker 6237 --end-date 2024-12-31 --window 60
    python scripts/zhuli_swing_high_viewer_poc.py --ticker 6237 --end-date 2024-12-31 --window 90 --vision

注意：禁止直接呼叫 FinMind API，必須透過 common.clients.finmind_compat。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import mplfinance as mpf
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup：import common.clients.finmind_compat
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent  # worktree root
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

try:
    from common import finmind_client as fm
except ImportError as exc:
    print(f"[ERROR] 無法 import common.clients.finmind_compat：{exc}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 輸出目錄
# ---------------------------------------------------------------------------
OUT_DIR = _REPO_ROOT / "data" / "analysis" / "zhuli" / "swing_high_poc"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 撈日 K 資料
# ---------------------------------------------------------------------------

def _load_token() -> str:
    """從環境變數讀取 FINMIND_API_TOKEN 或 FINMIND_TOKEN。"""
    return (
        os.environ.get("FINMIND_API_TOKEN", "")
        or os.environ.get("FINMIND_TOKEN", "")
    )


def fetch_daily_kbar(ticker: str, end_date: str, window: int) -> pd.DataFrame:
    """
    撈 [end_date - window*2 個日曆日, end_date] 的日 K，
    取最後 window 根交易日資料。
    使用 fm.get_price（含 throttle）。
    """
    token = _load_token()
    if not token:
        raise RuntimeError("找不到 FINMIND_API_TOKEN/FINMIND_TOKEN，請 export 環境變數")

    end_dt = date.fromisoformat(end_date)
    # window 根交易日 ≈ window * 1.5 個日曆日（含假日緩衝）
    start_dt = end_dt - timedelta(days=int(window * 1.6) + 30)
    start_str = start_dt.isoformat()

    print(f"[INFO] 撈日K：{ticker}  {start_str} ~ {end_date}")
    df = fm.get_price(ticker, start_str, end_date, token)

    if df.empty:
        raise ValueError(f"撈不到 {ticker} 的日K資料（{start_str}~{end_date}），請確認股票代號和日期。")

    # 統一欄位名稱
    df = df.rename(columns={"date": "Date", "open": "Open", "close": "Close",
                             "high": "High", "low": "Low", "Trading_Volume": "Volume",
                             "volume": "Volume"})
    # 確保有必要欄位
    required = ["Date", "Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"日K資料缺少欄位：{missing}，現有欄位：{list(df.columns)}")

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    # 取最後 window 根
    df = df.tail(window).reset_index(drop=True)
    print(f"[INFO] 取得 {len(df)} 根日K（{df['Date'].iloc[0].date()} ~ {df['Date'].iloc[-1].date()}）")
    return df


# ---------------------------------------------------------------------------
# 演算法 A：scipy.signal.find_peaks
# ---------------------------------------------------------------------------

def algo_findpeaks(df: pd.DataFrame, distance: int = 5, prominence_ratio: float = 0.02) -> list[int]:
    """
    用 scipy.signal.find_peaks 找 swing high 候選。
    - 以 high 做為訊號序列
    - prominence >= close * prominence_ratio（每根的 close * ratio 取均值作為全局門檻）
    - distance=5：相鄰高點至少間隔 5 根
    回傳 row index list。
    """
    from scipy.signal import find_peaks

    highs = df["High"].values
    # prominence 門檻：用整段平均收盤 * ratio
    avg_close = df["Close"].mean()
    prominence_threshold = avg_close * prominence_ratio

    peaks, props = find_peaks(highs, distance=distance, prominence=prominence_threshold)
    return list(peaks)


# ---------------------------------------------------------------------------
# 演算法 B：Rolling local max（window 5 / 10）
# ---------------------------------------------------------------------------

def algo_rollingmax(df: pd.DataFrame, window: int = 5) -> list[int]:
    """
    用 rolling max（center=True）找 swing high。
    high[i] == high.rolling(window, center=True, min_periods=window).max()
    回傳 row index list。
    """
    highs = df["High"]
    rolling_max = highs.rolling(window=window, center=True, min_periods=window).max()
    # 只保留「真正是局部最高」的點（避免平台重複）
    is_peak = (highs == rolling_max)
    # 去重：連續相等高點只取中間那個
    indices = []
    prev_peak = False
    peak_group_start = None
    for i, v in enumerate(is_peak):
        if v and not prev_peak:
            peak_group_start = i
        if prev_peak and not v:
            # peak_group_start ~ i-1 取中間
            mid = (peak_group_start + i - 1) // 2
            indices.append(mid)
        prev_peak = v
    if prev_peak and peak_group_start is not None:
        mid = (peak_group_start + len(is_peak) - 1) // 2
        indices.append(mid)
    return indices


# ---------------------------------------------------------------------------
# 畫圖：mplfinance + scatter overlay
# ---------------------------------------------------------------------------

MARKER_STYLE = dict(markersize=10, markeredgewidth=1.5)


def _build_addplot(df: pd.DataFrame, peak_indices: list[int], color: str, label: str):
    """在高點上方標 marker（使用 mplfinance addplot scatter）。"""
    n = len(df)
    y = np.full(n, np.nan)
    # 標在 high 上方 0.5%
    for i in peak_indices:
        y[i] = df["High"].iloc[i] * 1.005
    return mpf.make_addplot(y, type="scatter", marker="v", markersize=80,
                            color=color, panel=0, alpha=0.85)


def _draw_and_save(df: pd.DataFrame, peak_indices: list[int],
                   ticker: str, end_date: str, algo_label: str,
                   color: str, title: str) -> Path:
    """畫 K 線 + swing high markers，存 PNG，回傳 Path。"""
    df_plot = df.set_index("Date")

    addplots = []
    if peak_indices:
        addplots.append(_build_addplot(df, peak_indices, color=color, label=algo_label))

    filename = f"{ticker}_{end_date}_{algo_label}.png"
    out_path = OUT_DIR / filename

    # 標記峰值計數
    count_txt = f"  (n={len(peak_indices)} peaks)"

    # 使用 mplfinance 存圖
    mpf.plot(
        df_plot,
        type="candle",
        style="charles",
        title=f"{ticker}  {title}{count_txt}",
        ylabel="Price",
        addplot=addplots if addplots else [],
        figsize=(16, 8),
        savefig=str(out_path),
        tight_layout=True,
    )
    print(f"[INFO] 存圖：{out_path}")
    return out_path


def plot_all(df: pd.DataFrame, ticker: str, end_date: str) -> dict[str, tuple[list[int], Path]]:
    """
    跑三種演算法並各存一張 PNG。
    回傳 {algo_label: (peak_indices, png_path)}
    """
    results: dict[str, tuple[list[int], Path]] = {}

    # --- find_peaks ---
    peaks_fp = algo_findpeaks(df, distance=5, prominence_ratio=0.02)
    path_fp = _draw_and_save(df, peaks_fp, ticker, end_date,
                              "findpeaks",
                              color="#e74c3c",
                              title="Swing High (find_peaks d=5 prom=2%)")
    results["findpeaks"] = (peaks_fp, path_fp)

    # --- rolling max w5 ---
    peaks_w5 = algo_rollingmax(df, window=5)
    path_w5 = _draw_and_save(df, peaks_w5, ticker, end_date,
                              "rollingmax_w5",
                              color="#8e44ad",
                              title="Swing High (rolling max w=5)")
    results["rollingmax_w5"] = (peaks_w5, path_w5)

    # --- rolling max w10 ---
    peaks_w10 = algo_rollingmax(df, window=10)
    path_w10 = _draw_and_save(df, peaks_w10, ticker, end_date,
                               "rollingmax_w10",
                               color="#2980b9",
                               title="Swing High (rolling max w=10)")
    results["rollingmax_w10"] = (peaks_w10, path_w10)

    return results


# ---------------------------------------------------------------------------
# Step 5：Vision 判讀（需 ANTHROPIC_API_KEY）
# ---------------------------------------------------------------------------

VISION_PROMPT = """
這張日 K 線圖標出了 swing high（局部高點）候選點（倒三角形 marker）。

背景：台股主力大老師課程「反轉形態」——在下降趨勢中，找「兩個明顯高點」連線畫出下降趨勢線，
當一根紅K 收盤站上這條線，即為進場訊號。

請你作為技術分析助手，回答：
1. 圖中所有標記的候選點裡，你會選哪兩個點來畫「下降趨勢線」？（用圖上的大約位置或相對順序描述）
2. 你為什麼選這兩個？（考慮：高點明顯、時間間隔合理、能代表下降趨勢的頂部）
3. 有沒有哪個候選點你認為「不適合」作為反轉形態的高點？為什麼？
4. 整體而言，這個演算法標記的候選點，是否接近你對「主力大課程肉眼判斷」的預期？
"""


def run_vision(png_path: Path, ticker: str, algo_label: str) -> dict:
    """
    把 PNG 傳給 Claude vision，取得判讀結果。
    需要 ANTHROPIC_API_KEY 環境變數。
    """
    try:
        import anthropic
    except ImportError:
        print("[WARN] anthropic SDK 未安裝，跳過 vision 步驟。")
        return {}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[WARN] 未找到 ANTHROPIC_API_KEY，跳過 vision 步驟。")
        return {}

    print(f"[INFO] 呼叫 Claude vision 判讀：{png_path.name}")
    img_data = base64.standard_b64encode(png_path.read_bytes()).decode("utf-8")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_data,
                        },
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }
        ],
    )
    response_text = message.content[0].text
    result = {
        "ticker": ticker,
        "algo": algo_label,
        "png": str(png_path),
        "vision_response": response_text,
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    out_json = OUT_DIR / f"{ticker}_{png_path.stem.split('_', 2)[-1]}_vision_judgment.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[INFO] Vision 結果：{out_json}")
    return result


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="主力大反轉形態 swing high 候選點畫圖 POC"
    )
    parser.add_argument("--ticker", default="6237", help="股票代號，例：6237")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="截止日期 YYYY-MM-DD")
    parser.add_argument("--window", type=int, default=60, help="取最近幾根日K（交易日）")
    parser.add_argument("--vision", action="store_true", help="啟用 Claude vision 自動判讀（需 ANTHROPIC_API_KEY）")
    args = parser.parse_args()

    ticker = args.ticker
    end_date = args.end_date
    window = args.window

    print(f"\n=== 主力大反轉形態 Swing High POC ===")
    print(f"  標的：{ticker}  截止日：{end_date}  窗口：{window} 根")
    print()

    # 1. 撈資料
    df = fetch_daily_kbar(ticker, end_date, window)

    # 2. 畫圖（三種演算法）
    results = plot_all(df, ticker, end_date)

    # 3. 列印摘要
    print()
    print("=== Swing High 候選點數量摘要 ===")
    for algo, (peaks, path) in results.items():
        dates_str = ", ".join(df["Date"].iloc[i].strftime("%m/%d") for i in peaks)
        print(f"  {algo:20s}：{len(peaks):2d} 個  [{dates_str}]")
    print()

    # 4. Vision（選用）
    if args.vision:
        vision_results = []
        for algo, (peaks, path) in results.items():
            r = run_vision(path, ticker, algo)
            if r:
                vision_results.append(r)
        if vision_results:
            print(f"\n=== Vision 判讀完成，共 {len(vision_results)} 份結果 ===")
    else:
        print("[INFO] 未啟用 --vision，如需 vision 判讀請加上 --vision 旗標。")
        print()
        print("# TODO: vision integration")
        print("# 要執行 vision 判讀，需要：")
        print("#   1. export ANTHROPIC_API_KEY=<your_key>")
        print("#   2. 執行時加上 --vision 旗標")
        print("#   3. 結果存至 data/analysis/zhuli/swing_high_poc/*_vision_judgment.json")

    print()
    print(f"[DONE] PNG 輸出目錄：{OUT_DIR}")


if __name__ == "__main__":
    main()
