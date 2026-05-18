#!/usr/bin/env python3
"""
POC：反推主力大口中「大量/爆量」的真實倍數閾值

做法：
1. 文字探勘 26 份講稿，找「日期 + 股票代號/名稱 + 大量/爆量/出量/巨量/爆出/攻擊量」
2. 補充手工驗證案例（講稿明確點名日期+標的的案例）
3. 用 FinMind client 撈日 K，算 volume_ratio
4. 統計分布，輸出報告

用法：
    python scripts/zhuli_large_volume_threshold_poc.py            # 完整執行
    python scripts/zhuli_large_volume_threshold_poc.py --dry-run  # 只做文字探勘，不呼叫 API
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
WORKTREE_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR   = Path("/Users/howard/Repository/stock-analysis-system/docs/scripts")
ANALYSIS_DIR  = WORKTREE_ROOT / "data" / "analysis" / "zhuli"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

FINMIND_SYS = Path("/Users/howard/Repository/stock-analysis-system")

OUT_CASES  = ANALYSIS_DIR / "large_volume_cases.csv"
OUT_RATIOS = ANALYSIS_DIR / "large_volume_ratios.csv"
OUT_REPORT = ANALYSIS_DIR / "large_volume_threshold_report.md"

# ── 關鍵字分組 ────────────────────────────────────────────────────────────────
KW_BREAKOUT = ["爆量", "巨量", "爆出"]
KW_LARGE    = ["大量", "出量", "攻擊量"]
ALL_KW      = KW_BREAKOUT + KW_LARGE

# ── 公司名稱 → 代號映射（從講稿中明確提及的）────────────────────────────────
NAME_TO_TICKER = {
    "泰銘":  "9927",
    "圓剛":  "2417",
    "嘉澤":  "3533",
    "南茂":  "8150",
    "佳邦":  "6284",
    "光罩":  "2338",
    "亞德克": "1590",
    "春源":  "2010",
    "宏泰":  "1612",
    "技嘉":  "2376",
    "宏捷科": "8086",
    "漢磊":  "3707",
    "群創":  "3481",
    "中鋼":  "2002",
    "中鴻":  "2014",
    "華訊":  "6237",
    "友達":  "2409",
    "彩晶":  "6116",
}

# ── 手工驗證案例（講稿中有明確日期 + 代號 + 量詞事件）────────────────────────
# 記錄格式：(ticker, date, keyword, event_type, notes, script_file, source_image)
# event_type: "breakout" = 那天是大量突破日; "choke" = 那天是窒息量日（前面有大量）
# source_image: 對應 PDF 圖檔名稱（空字串表示來自講稿文字）
MANUAL_CASES = [
    # ── 原有講稿案例（ex1-3 章節）──
    # 2338 光罩：2021-02-17 拉漲停 = 年假首日大量攻擊
    ("2338", "2021-02-17", "大量", "breakout", "光罩 年假首日拉漲停出量攻擊", "ex1-3.txt", ""),
    # 3533 嘉澤：2020-12-30 窒息量（大量是之前的 20 日最高量）
    ("3533", "2020-12-30", "窒息量", "choke", "嘉澤 去年12月30號窒息量 前有大量", "ex1-3.txt", ""),
    # 8150 南茂：2021-03-10 窒息量
    ("8150", "2021-03-10", "窒息量", "choke", "南茂 今年3月10號窒息量", "ex1-3.txt", ""),
    # 6284 佳邦：2021-01-22 窒息量
    ("6284", "2021-01-22", "窒息量", "choke", "佳邦 1月22日窒息量", "ex1-3.txt", ""),
    # 1590 亞德克：2020-12-24 窒息量
    ("1590", "2020-12-24", "窒息量", "choke", "亞德克 2020/12/24 窒息量 前有大量", "ex1-3.txt", ""),

    # ── PDF 圖檔新增案例（pdf_extracted_parameters.md 抽取）──
    # 6441 廣鍵：2020-09-16 漲9.87% 反轉形態出量
    ("6441", "2020-09-16", "大量", "breakout", "廣鍵 2020/09/16 漲9.87% 反轉形態出量", "pdf_p107", "_page_107_Figure_0.jpeg"),
    # 6441 廣鍵：2020-08-30 均線切入前大量
    ("6441", "2020-08-30", "大量", "breakout", "廣鍵 2020/08/30 均線切入前大量", "pdf_p107", "_page_107_Figure_0.jpeg"),
    # 1904 正隆：2020-08-06 反轉形態出量
    ("1904", "2020-08-06", "大量", "breakout", "正隆 2020/08/06 反轉形態出量", "pdf_p102", "_page_102_Figure_0.jpeg"),
    # 1904 正隆：2020-08-10 後旗型形態
    ("1904", "2020-08-10", "大量", "breakout", "正隆 2020/08/10 後旗型形態出量", "pdf_p103", "_page_103_Figure_0.jpeg"),
    # 6672 iBASE：2021-05-28 漲5.5% 布林上軌出量
    ("6672", "2021-05-28", "大量", "breakout", "iBASE 2021/05/28 漲5.5% 布林上軌出量", "pdf_p118", "_page_118_Figure_1.jpeg"),
    # 2351 順德：2021-01-13 布林回測大量
    ("2351", "2021-01-13", "大量", "breakout", "順德 2021/01/13 布林回測大量", "pdf_p129", "_page_129_Figure_0.jpeg"),
    # 2351 順德：2021-01-20 布林回測後出量
    ("2351", "2021-01-20", "大量", "breakout", "順德 2021/01/20 布林回測後出量", "pdf_p130", "_page_130_Figure_0.jpeg"),
    # 5425 台半：2020-10-16 布林回測大量
    ("5425", "2020-10-16", "大量", "breakout", "台半 2020/10/16 布林回測大量", "pdf_p130", "_page_130_Figure_0.jpeg"),
    # 3042 晶技：2021-01-08 策略綜合應用出量
    ("3042", "2021-01-08", "大量", "breakout", "晶技 2021/01/08 策略綜合應用出量", "pdf_p142", "_page_142_Figure_1.jpeg"),
    # 2492 華新科：2019-12-24 漲9.19% 投信基因案例
    ("2492", "2019-12-24", "大量", "breakout", "華新科 2019/12/24 漲9.19% 投信基因截圖案例", "pdf_p86", "_page_86_Figure_0.jpeg"),
    # 2883 開發金：2021-03-09 波段關鍵因素出量
    ("2883", "2021-03-09", "大量", "breakout", "開發金 2021/03/09 波段關鍵因素出量", "pdf_p74", "_page_74_Figure_1.jpeg"),
    # 2002 中鋼：2021-05-13 波段月線出場大量
    ("2002", "2021-05-13", "大量", "breakout", "中鋼 2021/05/13 波段月線出場大量", "pdf_p77", "_page_77_Figure_1.jpeg"),
    # 3481 群創：2021-03-11 窒息量（前有大量峰值）
    ("3481", "2021-03-11", "窒息量", "choke", "群創 2021/03/11 出現窒息量（前有大量峰值）", "pdf_p79", "_page_79_Figure_1.jpeg"),
]

# ── 多格式日期 regex ──────────────────────────────────────────────────────────
TICKER_RE = re.compile(r'\b([1-9]\d{3})\b')
KW_RE     = re.compile('|'.join(ALL_KW))

DATE_RES = [
    (re.compile(r'(20\d{2})[/\-年](\d{1,2})[/\-月](\d{1,2})[日號]?'), 'ymd'),
    (re.compile(r'(\d{1,2})月(\d{1,2})[日號]'), 'md'),
]


def scan_scripts() -> pd.DataFrame:
    """Phase 1: Text mining — find volume keyword mentions with tickers and dates."""
    scripts = sorted(SCRIPTS_DIR.glob("*.txt"))
    scripts = [s for s in scripts if s.name != "full_scripts.txt"]
    print(f"[scan] Processing {len(scripts)} script files...")

    rows = []
    for script in scripts:
        lines = script.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            kw_match = KW_RE.search(line)
            if not kw_match:
                continue

            keyword = kw_match.group(0)
            ctx_start = max(0, i - 15)
            ctx_end   = min(len(lines), i + 16)
            window    = lines[ctx_start:ctx_end]
            window_text = '\n'.join(window)

            # Find tickers (by number or company name)
            tickers = set()
            for m in TICKER_RE.finditer(window_text):
                t = m.group(1)
                v = int(t)
                # Filter years (2016-2026) and obvious prices/volumes
                if 2015 <= v <= 2026:
                    continue
                if v < 1100:
                    continue
                tickers.add(t)
            for name, code in NAME_TO_TICKER.items():
                if name in window_text:
                    tickers.add(code)

            # Find dates
            dates_found = []
            for dr, dtype in DATE_RES:
                for m in dr.finditer(window_text):
                    if dtype == 'ymd':
                        try:
                            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                            if 2015 <= d.year <= 2026:
                                dates_found.append(d.isoformat())
                        except ValueError:
                            pass
                    elif dtype == 'md':
                        dates_found.append(f"????-{int(m.group(1)):02d}-{int(m.group(2)):02d}")

            parsed_date = next((d for d in dates_found if '????' not in d), None)
            partial_date = next((d for d in dates_found if '????' in d), None) if not parsed_date else None

            context_200 = window_text[:200].replace('\n', ' ')

            for ticker in (tickers if tickers else [None]):
                rows.append({
                    "script_file":   script.name,
                    "line_no":       i + 1,
                    "raw_text":      line.strip(),
                    "parsed_date":   parsed_date,
                    "partial_date":  partial_date,
                    "parsed_ticker": ticker,
                    "keyword":       keyword,
                    "context_50char": context_200[:200],
                    "source":        "auto",
                })

    df = pd.DataFrame(rows)
    print(f"[scan] Found {len(df)} raw mentions, {df['parsed_ticker'].notna().sum()} with ticker, "
          f"{df['parsed_date'].notna().sum()} with full date")
    return df


def add_manual_cases(df: pd.DataFrame) -> pd.DataFrame:
    """Add manually verified cases from lecture review and PDF image extraction."""
    manual_rows = []
    for entry in MANUAL_CASES:
        # Support both old format (6 fields) and new format (7 fields with source_image)
        if len(entry) == 7:
            ticker, dt, kw, etype, notes, script, source_image = entry
        else:
            ticker, dt, kw, etype, notes, script = entry
            source_image = ""
        manual_rows.append({
            "script_file":    script,
            "line_no":        0,
            "raw_text":       notes,
            "parsed_date":    dt,
            "partial_date":   None,
            "parsed_ticker":  ticker,
            "keyword":        kw,
            "context_50char": notes,
            "source":         "manual",
            "event_type":     etype,
            "source_image":   source_image,
        })
    manual_df = pd.DataFrame(manual_rows)
    combined = pd.concat([df, manual_df], ignore_index=True)
    # Also ensure auto cases have source_image column
    if "source_image" not in combined.columns:
        combined["source_image"] = ""
    else:
        combined["source_image"] = combined["source_image"].fillna("")
    print(f"[cases] Added {len(manual_rows)} manual cases → total rows: {len(combined)}")
    return combined


def build_cases(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to actionable cases: must have BOTH ticker AND full date."""
    cases = df[
        df["parsed_ticker"].notna() &
        df["parsed_date"].notna()
    ].copy()
    # Deduplicate by (date, ticker, source) keeping first
    cases = cases.drop_duplicates(subset=["parsed_date", "parsed_ticker", "source"])
    print(f"[cases] {len(cases)} unique actionable (date, ticker) pairs")
    return cases


def fetch_volume_ratios(cases: pd.DataFrame) -> pd.DataFrame:
    """Phase 2: Fetch volume data and compute volume_ratio."""
    sys.path.insert(0, str(FINMIND_SYS))

    try:
        from dotenv import load_dotenv
        load_dotenv(FINMIND_SYS / ".env")
    except ImportError:
        pass

    from clients.finmind_client import get_price

    token = os.environ.get("FINMIND_API_TOKEN", "")
    if not token:
        print("[ERROR] FINMIND_API_TOKEN not set")
        return pd.DataFrame()

    results = []

    for idx, row in cases.iterrows():
        ticker        = row["parsed_ticker"]
        case_date_str = row["parsed_date"]
        event_type    = row.get("event_type", "breakout")  # default to breakout

        try:
            case_date = datetime.strptime(case_date_str, "%Y-%m-%d").date()
        except ValueError:
            print(f"  [{ticker} {case_date_str}] SKIP — invalid date")
            continue

        # For choke cases: we need the MAX volume in 60 days BEFORE the choke date
        # For breakout cases: we need that day's volume vs MA20 before it
        lookback_days = 90  # fetch 90 calendar days to get ~60 trading days
        start_date = (case_date - timedelta(days=lookback_days)).isoformat()
        end_date   = case_date.isoformat()

        print(f"  [{ticker} {case_date_str} {event_type}] fetching {start_date}→{end_date}...", end=" ", flush=True)

        try:
            df = get_price(ticker, start_date, end_date, token)

            if df is None or df.empty:
                print("SKIP — empty data")
                results.append({**row, "raw_volume": None, "ma20_volume": None,
                                 "max20_volume": None, "volume_ratio": None,
                                 "fetch_status": "empty"})
                continue

            # Normalize columns
            df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
            df = df.sort_values("date").reset_index(drop=True)

            # Detect volume column
            vol_col = None
            for c in ["Trading_Volume", "volume", "vol", "Volume"]:
                if c in df.columns:
                    vol_col = c
                    break
            if vol_col is None:
                print(f"SKIP — no volume column (cols: {list(df.columns)})")
                results.append({**row, "raw_volume": None, "ma20_volume": None,
                                 "max20_volume": None, "volume_ratio": None,
                                 "fetch_status": "no_vol_col"})
                continue

            if event_type == "choke":
                # For 窒息量 cases:
                # Find the peak (大量) day within the 20-60 trading days before the choke date
                # The 大量 is what the 窒息量 is being compared to (20-day max)
                choke_idx = df[df["date"] == case_date_str].index
                if len(choke_idx) == 0:
                    print("SKIP — choke date not in data (non-trading day?)")
                    results.append({**row, "raw_volume": None, "ma20_volume": None,
                                     "max20_volume": None, "volume_ratio": None,
                                     "fetch_status": "non_trading_choke"})
                    continue
                choke_idx = choke_idx[0]

                # Get the 20-60 trading days before the choke date
                prior_window_start = max(0, choke_idx - 60)
                prior_window = df.loc[prior_window_start:choke_idx - 1]

                if len(prior_window) < 5:
                    print(f"SKIP — insufficient history ({len(prior_window)} rows)")
                    results.append({**row, "raw_volume": None, "ma20_volume": None,
                                     "max20_volume": None, "volume_ratio": None,
                                     "fetch_status": "insufficient_history"})
                    continue

                choke_volume = float(df.loc[choke_idx, vol_col])
                max20_volume = float(prior_window[vol_col].max())
                ma20_volume  = float(prior_window[vol_col].tail(20).mean())

                # Peak day (大量 day)
                peak_idx  = prior_window[vol_col].idxmax()
                peak_date = df.loc[peak_idx, "date"]
                peak_vol  = float(df.loc[peak_idx, vol_col])

                # Volume ratio: 大量 (peak) vs MA20 before the peak
                # This tells us how big the 大量 was relative to normal trading
                peak_pos = prior_window.index.get_loc(peak_idx)
                pre_peak  = prior_window.iloc[max(0, peak_pos - 20):peak_pos]
                if len(pre_peak) >= 5:
                    pre_peak_ma20 = float(pre_peak[vol_col].mean())
                    ratio_breakout = peak_vol / pre_peak_ma20 if pre_peak_ma20 > 0 else None
                else:
                    pre_peak_ma20 = ma20_volume
                    ratio_breakout = peak_vol / ma20_volume if ma20_volume > 0 else None

                choke_ratio = choke_volume / max20_volume if max20_volume > 0 else None

                print(f"OK — choke_vol={choke_volume:,.0f}, "
                      f"peak_vol={peak_vol:,.0f} ({peak_date}), "
                      f"MA20={ma20_volume:,.0f}, "
                      f"大量ratio={ratio_breakout:.2f}x" if ratio_breakout else "OK")

                results.append({
                    **row,
                    "raw_volume":     peak_vol,         # 大量 = peak volume
                    "ma20_volume":    pre_peak_ma20,
                    "max20_volume":   max20_volume,
                    "volume_ratio":   ratio_breakout,   # peak / pre-peak MA20
                    "choke_volume":   choke_volume,
                    "choke_ratio":    choke_ratio,       # choke / 20-day max
                    "peak_date":      peak_date,
                    "fetch_status":   "ok",
                })

            else:  # breakout case
                if case_date_str not in df["date"].values:
                    print("SKIP — date not in data (non-trading day?)")
                    results.append({**row, "raw_volume": None, "ma20_volume": None,
                                     "max20_volume": None, "volume_ratio": None,
                                     "fetch_status": "non_trading"})
                    continue

                case_idx = df[df["date"] == case_date_str].index[0]

                if case_idx < 10:
                    print(f"SKIP — only {case_idx} prior rows")
                    results.append({**row, "raw_volume": None, "ma20_volume": None,
                                     "max20_volume": None, "volume_ratio": None,
                                     "fetch_status": "insufficient_history"})
                    continue

                case_volume = float(df.loc[case_idx, vol_col])
                prior_20    = df.loc[max(0, case_idx - 20):case_idx - 1]
                ma20_volume = float(prior_20[vol_col].mean())
                max20_volume = float(prior_20[vol_col].max())

                ratio = case_volume / ma20_volume if ma20_volume > 0 else None
                print(f"OK — vol={case_volume:,.0f}, MA20={ma20_volume:,.0f}, ratio={ratio:.2f}x" if ratio else "OK")

                results.append({
                    **row,
                    "raw_volume":    case_volume,
                    "ma20_volume":   ma20_volume,
                    "max20_volume":  max20_volume,
                    "volume_ratio":  ratio,
                    "choke_volume":  None,
                    "choke_ratio":   None,
                    "peak_date":     case_date_str,
                    "fetch_status":  "ok",
                })

        except RuntimeError as e:
            if "配額" in str(e):
                print("ABORT — FinMind quota exhausted")
                break
            print(f"ERROR — {e}")
            results.append({**row, "raw_volume": None, "ma20_volume": None,
                             "max20_volume": None, "volume_ratio": None,
                             "fetch_status": f"error:{e}"})
        except Exception as e:
            print(f"ERROR — {e}")
            results.append({**row, "raw_volume": None, "ma20_volume": None,
                             "max20_volume": None, "volume_ratio": None,
                             "fetch_status": f"error:{e}"})

    return pd.DataFrame(results)


def write_report(ratios_df: pd.DataFrame, all_cases_df: pd.DataFrame) -> None:
    """Phase 3: Distribution analysis and markdown report."""
    today = date.today().isoformat()

    ok = pd.DataFrame()
    if not ratios_df.empty and "fetch_status" in ratios_df.columns:
        ok = ratios_df[ratios_df["fetch_status"] == "ok"].copy()

    def kw_group(kw: str) -> str:
        if kw in KW_BREAKOUT:
            return "爆量"
        return "大量"

    if not ok.empty:
        ok["kw_group"] = ok["keyword"].apply(kw_group)

    total_scan  = len(all_cases_df[all_cases_df.get("source", pd.Series(dtype=str)) != "manual"]) if not all_cases_df.empty else 0
    total_manual = len(all_cases_df[all_cases_df.get("source", pd.Series(dtype=str)) == "manual"]) if not all_cases_df.empty else 0
    total_cases = len(ratios_df)
    ok_count    = len(ok)
    fail_count  = total_cases - ok_count

    lines = [
        "# 主力大「大量/爆量」閾值反推報告",
        "",
        f"> 生成日期：{today}",
        f"> 分析目標：透過講稿案例反推「大量」「爆量」的 volume_ratio（case 當日量 / 前 20 日均量）",
        "",
        "## 背景說明",
        "",
        "### 課程中「大量」的定義框架",
        "",
        "從講稿挖掘，主力大用「大量」的語境有兩種：",
        "",
        "1. **窒息量策略的「大量」**（ex1-2, ex1-3）：",
        "   - 定義：「20 日內最大量」= MAX(過去 20 個交易日的成交量)",
        "   - 窒息量條件：當日成交量 < 大量 × 10%",
        "   - 此處「大量」是一個歷史高峰值，不是 MA20",
        "",
        "2. **出量/攻擊量**（ch2-4, ch7-1）：",
        "   - 定義：相對於前一根 K 棒「放大」，且至少 > 前一根的 50%（量縮定義的反面）",
        "   - 沒有絕對數字，是相對比較",
        "",
        "**本報告的 volume_ratio = 大量案例當日成交量 / 前 20 日均量（MA20）**",
        "用於量化「主力大說的大量，相對於平常交易量放大了幾倍」",
        "",
        "## 樣本概況",
        "",
        f"- 自動文字探勘結果（有完整日期+代號）：**{total_scan}** 筆",
        f"- 手工驗證案例（講稿明確點名日期+標的）：**{total_manual}** 筆",
        f"- 成功撈量：**{ok_count}** 筆",
        f"- 失敗/跳過：**{fail_count}** 筆",
        "",
    ]

    if ok_count == 0:
        lines.append("⚠️ 沒有成功案例，無法進行統計分析。")
        OUT_REPORT.write_text('\n'.join(lines), encoding="utf-8")
        print(f"[report] Written → {OUT_REPORT}")
        return

    lines += [
        "## 整體 volume_ratio 分布（所有成功案例）",
        "",
        f"| 統計量 | 值 |",
        f"|--------|-----|",
        f"| N | {ok_count} |",
        f"| Min | {ok['volume_ratio'].min():.2f}x |",
        f"| P25 | {ok['volume_ratio'].quantile(0.25):.2f}x |",
        f"| Median | {ok['volume_ratio'].median():.2f}x |",
        f"| P75 | {ok['volume_ratio'].quantile(0.75):.2f}x |",
        f"| Max | {ok['volume_ratio'].max():.2f}x |",
        f"| Mean | {ok['volume_ratio'].mean():.2f}x |",
        "",
    ]

    # By event type
    for etype, label in [("breakout", "出量/攻擊量（突破當日）"), ("choke", "大量（窒息量策略前的高峰）")]:
        grp = ok[ok.get("event_type", pd.Series()) == etype] if "event_type" in ok.columns else pd.DataFrame()
        if grp.empty:
            continue
        lines += [
            f"## 「{label}」案例 volume_ratio（N={len(grp)}）",
            "",
            f"| 統計量 | 值 |",
            f"|--------|-----|",
            f"| N | {len(grp)} |",
            f"| Min | {grp['volume_ratio'].min():.2f}x |",
            f"| P25 | {grp['volume_ratio'].quantile(0.25):.2f}x |",
            f"| Median | {grp['volume_ratio'].median():.2f}x |",
            f"| P75 | {grp['volume_ratio'].quantile(0.75):.2f}x |",
            f"| Max | {grp['volume_ratio'].max():.2f}x |",
            f"| Mean | {grp['volume_ratio'].mean():.2f}x |",
            "",
        ]

    # Suggested thresholds
    lines += [
        "## 建議閾值",
        "",
        "| 閾值層次 | 說明 | 建議值 |",
        "|----------|------|--------|",
    ]

    breakout_grp = ok[ok.get("event_type", pd.Series()) == "breakout"] if "event_type" in ok.columns else pd.DataFrame()
    choke_grp    = ok[ok.get("event_type", pd.Series()) == "choke"] if "event_type" in ok.columns else pd.DataFrame()

    if not breakout_grp.empty:
        p25 = breakout_grp["volume_ratio"].quantile(0.25)
        med = breakout_grp["volume_ratio"].median()
        lines += [
            f"| 出量/攻擊量（保守） | P25，最低門檻 | **{p25:.1f}x** |",
            f"| 出量/攻擊量（標準） | Median | **{med:.1f}x** |",
        ]
    if not choke_grp.empty:
        p25 = choke_grp["volume_ratio"].quantile(0.25)
        med = choke_grp["volume_ratio"].median()
        lines += [
            f"| 窒息量策略大量（保守） | P25，峰值 vs MA20 | **{p25:.1f}x** |",
            f"| 窒息量策略大量（標準） | Median | **{med:.1f}x** |",
        ]

    if len(ok) >= 3:
        overall_p25 = ok["volume_ratio"].quantile(0.25)
        overall_med = ok["volume_ratio"].median()
        lines += [
            f"| 整體保守 | P25 | **{overall_p25:.1f}x** |",
            f"| 整體標準 | Median | **{overall_med:.1f}x** |",
        ]

    lines += [
        "",
        "## 注意事項",
        "",
        "1. **樣本稀少**：26 份講稿中，具備「明確完整日期 + 4 位代號 + 量詞」的三合一案例僅 5 筆。",
        "   閾值為初步參考，不建議直接用於生產策略。",
        "2. **日期推斷**：講稿多數只提「月/日」無年份，需根據錄製年份（ex1-3 系列約 2021 年）推斷。",
        "3. **課程定義的「大量」有兩層意義**：",
        "   - 窒息量策略：20 日最大量（MAX，不是均量）",
        "   - 出量/攻擊量：視覺上相對放大，至少超過前一根的 50%",
        "4. **樣本偏誤**：老師在課程選取的是效果特別明顯的教學案例，反推閾值偏高屬正常。",
        "5. **窒息量案例的 volume_ratio** 是峰值大量 vs 峰值前的 MA20，",
        "   代表「那個 20 日最大量到底有多大」。",
        "",
        "## 明細案例",
        "",
        "| 日期 | 代號 | 關鍵字 | 事件類型 | 來源 | 當日量 | MA20 量 | 比值 | 狀態 |",
        "|------|------|--------|----------|------|--------|---------|------|------|",
    ]

    if not ratios_df.empty:
        for _, r in ratios_df.sort_values(["parsed_date", "parsed_ticker"]).iterrows():
            vol    = f"{r['raw_volume']:,.0f}" if pd.notna(r.get("raw_volume")) else "-"
            ma20   = f"{r['ma20_volume']:,.0f}" if pd.notna(r.get("ma20_volume")) else "-"
            ratio  = f"{r['volume_ratio']:.2f}x" if pd.notna(r.get("volume_ratio")) else "-"
            etype  = r.get("event_type", "-")
            src    = r.get("source", "-")
            status = r.get("fetch_status", "-")
            lines.append(
                f"| {r['parsed_date']} | {r['parsed_ticker']} | {r['keyword']} "
                f"| {etype} | {src} | {vol} | {ma20} | {ratio} | {status} |"
            )

    OUT_REPORT.write_text('\n'.join(lines), encoding="utf-8")
    print(f"[report] Written → {OUT_REPORT}")


def main():
    parser = argparse.ArgumentParser(description="反推主力大「大量/爆量」量化閾值 POC")
    parser.add_argument("--dry-run", action="store_true", help="只做文字探勘，不呼叫 FinMind API")
    args = parser.parse_args()

    # Phase 1: text mining
    print("=== Phase 1: 文字探勘 ===")
    raw_df = scan_scripts()

    # Add manual cases
    all_df = add_manual_cases(raw_df)
    all_df.to_csv(OUT_CASES, index=False, encoding="utf-8-sig")
    print(f"[scan] Saved → {OUT_CASES}")

    cases = build_cases(all_df)

    if args.dry_run:
        print("\n[dry-run] 跳過 API 撈量")
        print("\n=== 可行案例（有完整日期+代號）===")
        cols_show = ["script_file", "line_no", "parsed_date", "parsed_ticker", "keyword", "source", "raw_text"]
        show_cols = [c for c in cols_show if c in cases.columns]
        print(cases[show_cols].to_string(index=False) if not cases.empty else "（無案例）")
        return

    if cases.empty:
        print("[warn] No actionable cases — cannot fetch volume data")
        return

    # Phase 2: fetch volumes
    print(f"\n=== Phase 2: 撈 FinMind 量價資料 ({len(cases)} cases) ===")
    ratios_df = fetch_volume_ratios(cases)

    if not ratios_df.empty:
        save_cols = ["script_file", "line_no", "parsed_date", "parsed_ticker", "keyword",
                     "event_type", "source", "source_image", "raw_volume", "ma20_volume",
                     "max20_volume", "volume_ratio", "choke_volume", "choke_ratio",
                     "peak_date", "fetch_status"]
        save_cols_exist = [c for c in save_cols if c in ratios_df.columns]
        ratios_df[save_cols_exist].to_csv(OUT_RATIOS, index=False, encoding="utf-8-sig")
        print(f"[ratios] Saved → {OUT_RATIOS}")

    # Phase 3: report
    print("\n=== Phase 3: 分布分析 ===")
    write_report(ratios_df, all_df)

    # Summary
    ok_df = ratios_df[ratios_df.get("fetch_status", pd.Series(dtype=str)) == "ok"] if not ratios_df.empty else pd.DataFrame()
    ok_count   = len(ok_df)
    fail_count = len(ratios_df) - ok_count if not ratios_df.empty else 0
    print(f"\n完成：{ok_count} 成功 / {fail_count} 失敗")
    if not ok_df.empty and "volume_ratio" in ok_df.columns:
        print(f"volume_ratio 統計：min={ok_df['volume_ratio'].min():.2f}x, "
              f"median={ok_df['volume_ratio'].median():.2f}x, "
              f"max={ok_df['volume_ratio'].max():.2f}x")


if __name__ == "__main__":
    main()
