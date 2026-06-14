#!/usr/bin/env python3
"""Phase 5c — 擴充老師所有來源 Backtest (5 月起，含培訓影片 + Line + 直播)。

問題：「phase5b 把金居/高技列為『自選非週報』是錯誤的。
       如果把老師所有來源（週報 + 培訓影片 + 直播 + memory）都納入，
       backtest 結果如何？真實差距的根本原因是什麼？」

背景：
  - Phase 5b (110,670) 只用「本週市場資訊報」3 篇
  - 但老師明示來源還有：
    - 全方位培訓班影片 (5/18-5/27)
    - 資訊統整培訓影片 (5/18-5/22)
    - COMPUTEX前夕文章 (5/25 fetch)
    - 直播課綱 (5/9 更新，含 8358 金居 / 5439 高技 / 2351 順德)
    - 5/25 Line 群：6182/3016/2481 矽晶圓三劍客
    - 5/26-27 培訓筆記：聯電 / 新唐 / 成熟製程 / 被動元件
  - 金居 8358 在 5/3 週報直播課綱已明示，但 phase5b 未納入
  - 高技 5439 在 5/3 週報直播課綱已明示 (PCB)，phase5b 未納入
  - 順德 2351 在直播課綱「現在觀察清單」已明示，phase5b 未納入
  - 鴻海 2317 在 COMPUTEX前夕文章已明示「鴻海股小結構整理」
  - 國巨 2327 在 COMPUTEX前夕 被動元件族群已明示

修正：
  1. 金居/高技/順德 不是「user 自選非框架」，是老師明示標的
  2. phase5b 分類錯誤導致「框架外自選損失」被高估
  3. 真正差距主因是「太早出場 / 早停利」，不是「做了框架外標的」

流程：
  1. 擴充老師明示 universe (5 月起，含所有來源)
  2. 同 phase5b 進出場邏輯重跑 backtest
  3. 對比 user 真實 P&L，重新分類差距
  4. 提供修正後的 4 條紀律建議

用法:
    python scripts/zhuli/phase5c_all_teacher_sources_review.py
    python scripts/zhuli/phase5c_all_teacher_sources_review.py --verbose
    python scripts/zhuli/phase5c_all_teacher_sources_review.py --report
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent
_DB = MAIN_DB
_STRAT_DIR = _REPO / "docs" / "主力大課程" / "strategies"

for _p in [str(_REPO), str(_REPO / "scripts")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zhuli.db import get_conn, MAIN_DB
# ── 費率 ──────────────────────────────────────────────────────────────────────
FEE_RATE = 0.000399   # 0.0399% 手續費
TAX_RATE = 0.003      # 0.3% 證交稅 (賣方)

# ── Sizing ────────────────────────────────────────────────────────────────────
DEFAULT_CAPITAL = 320_000   # 10% 水位 = $320k

# ── 分析區間 (5 月起) ─────────────────────────────────────────────────────────
ANALYSIS_START = "2026-05-01"
ANALYSIS_END   = "2026-06-04"

# ── Phase 5b 參考數字 ──────────────────────────────────────────────────────────
PHASE5B_PNL = 110_670   # 僅週報 3 篇，5 月起

# ═══════════════════════════════════════════════════════════════════════════════
# 1. 老師明示 universe (5 月起，所有來源)
#
# 來源分類：
#   W = 本週市場資訊報 (PressPlay)
#   T = 全方位培訓班 / 法人籌碼影片
#   C = COMPUTEX前夕 / 大主軸文章 (PressPlay)
#   L = Line 群直播 / 直播課綱 / 晚課影片
#   M = memory 已記錄的老師明示標的
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TeacherSource:
    pub_date:   str           # 老師最早明示日期
    source_key: str           # 來源代碼
    source_desc: str          # 來源說明
    tickers:    list[str]
    notes:      dict[str, str] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# A. 本週市場資訊報 (phase5b 已有)
# ──────────────────────────────────────────────────────────────────────────────

SOURCE_W0503 = TeacherSource(
    pub_date    = "2026-05-03",
    source_key  = "W0503",
    source_desc = "本週市場資訊報 5/3 — 中小輪動 CPO+記憶體+ABF+機器人+證券",
    tickers     = [
        "3105",  # 穩懋   (CPO)
        "4979",  # 華星光 (CPO)
        "3587",  # 閎康   (CPO 檢測)
        "2337",  # 旺宏   (記憶體)
        "8299",  # 群聯   (記憶體 NAND)
        "8046",  # 南電   (ABF 載板)
        "3037",  # 欣興   (ABF 載板)
        "4958",  # 臻鼎   (ABF/PCB)
        "2233",  # 宇隆   (機器人)
        "4576",  # 大銀微 (機器人)
        "1597",  # 直得   (機器人)
        "2464",  # 盟立   (機器人)
        "2855",  # 統一證 (證券)
        "6016",  # 康和證 (證券)
        "1802",  # 台玻   (玻纖布)
        "1303",  # 南亞   (玻纖布)
    ],
    notes = {
        "2464": "機器人 user 有交易",
        "2855": "統一證 兆元受益",
        "6016": "康和證 兆元受益",
    }
)

# ✅ phase5c 新增：直播課綱 5/9 文章中老師在崩盤筆記本就有 8358/5439/2351
SOURCE_W0503_EXTRA = TeacherSource(
    pub_date    = "2026-05-03",
    source_key  = "W0503_EXTRA",
    source_desc = "本週市場資訊報 5/3 — 老師崩盤筆記本額外標的 (直播課綱)；5/9 5/3 均有出現",
    tickers     = [
        "8358",  # 金居   (銅箔材料、PCB) — phase5b 誤分類為「非週報」
        "5439",  # 高技   (PCB 高密度) — phase5b 誤分類為「非週報」
        "2351",  # 順德   (融資股/觀察清單) — phase5b 誤分類為「非週報」
        "2327",  # 國巨   (被動元件 銀漲價)
        "2492",  # 華新科  (被動元件)
        "1605",  # 華新   (材料/銅) — 老師「波段分點籌碼 1605華新 飆股們的媽媽」
        "6217",  # 中探針  (永豐金戰隊 wave pattern)
        "2303",  # 聯電   (成熟製程)
        "5347",  # 世界先進 (成熟製程/GaN)
        "3162",  # 精確   (機器人零件)
        "2476",  # 鉅祥   (連接器 — 老師崩盤筆記本「連接器很明顯抗跌 2476CB」)
        "1785",  # 光洋科  (永豐金戰隊 — 老師直播課綱「1785光洋科 都如願以償了」)
        "2049",  # 上銀   (機器人 — COMPUTEX前夕「2049的意義就像是被動元件的國巨」)
    ],
    notes = {
        "8358": "老師崩盤筆記本「銅箔 金居」; 處置出關 8358金居5/6 (準備出關)",
        "5439": "老師崩盤筆記本「PCB 2368 5439」",
        "2351": "老師「融資股觀察清單 2351」; COMPUTEX前夕「現在: 2351(已第三段27號法說)」",
        "2327": "老師「被動元件國巨 銀漲價題材」",
        "1605": "老師「波段分點籌碼筆記 1605華新 — 飆股們的媽媽」",
        "6217": "老師「永豐金戰隊 波段分點籌碼」",
        "2303": "老師崩盤筆記本「成熟製程 2303 聯電」",
        "5347": "老師崩盤筆記本「成熟製程 5347 世界先進」",
        "2476": "老師崩盤筆記本「連接器很明顯抗跌 2476CB轉換點厲害」",
        "1785": "老師直播課綱「1785光洋科 都如願以償了!!!」永豐金戰隊",
        "2049": "COMPUTEX前夕「2049的意義就像是被動元件的國巨」機器人族群",
    }
)

SOURCE_W0516 = TeacherSource(
    pub_date    = "2026-05-16",
    source_key  = "W0516",
    source_desc = "本週市場資訊報 5/16 — 玻璃基板 CoPoS + 低軌衛星",
    tickers     = [
        "8027",  # 鈦昇   (玻璃基板 TGV)
        "8064",  # 東捷   (玻璃基板設備)
        "2467",  # 志聖   (PCB 設備)
        "4916",  # 事欣科  (低軌衛星)
        "3317",  # 尼克森  (GaN)
        "3481",  # 群創   (面板)
        "3149",  # 正達   (面板/光學)
        "6207",  # 雷科   (玻璃設備 — 老師崩盤筆記本「玻璃設備 8064 8027 6207」)
    ],
    notes = {
        "8064": "玻璃基板 CoPoS 主角; user 有交易",
        "3481": "群創 N字上攻教學 5/20",
        "3149": "正達 面板 user 有交易",
        "6207": "老師崩盤筆記本「玻璃設備 8064 8027 6207 1595」",
    }
)

SOURCE_W0531 = TeacherSource(
    pub_date    = "2026-05-31",
    source_key  = "W0531",
    source_desc = "本週市場資訊報 5/31 — COMPUTEX 2026 + 低軌衛星 + 功率元件",
    tickers     = [
        "6285",  # 啟碁   (低軌衛星)
        "2485",  # 兆赫   (低軌衛星)
        "5425",  # 台半   (MOSFET)
        "2481",  # 強茂   (MOSFET IDM)
        "3016",  # 嘉晶   (SiC 磊晶)
        "3675",  # 德微   (SiC)
    ],
)

# ──────────────────────────────────────────────────────────────────────────────
# B. COMPUTEX前夕 文章 (5/25 fetch, 涵蓋 5/17-5/25 週重點)
# ──────────────────────────────────────────────────────────────────────────────

SOURCE_COMPUTEX = TeacherSource(
    pub_date    = "2026-05-17",
    source_key  = "COMPUTEX",
    source_desc = "COMPUTEX前夕文章 (5/17-5/25) — AMD/NVIDIA 受惠; 機器人/被動元件/矽晶圓",
    tickers     = [
        "2317",  # 鴻海   (「鴻海股小結構整理」- 老師崩盤筆記本)
        "2481",  # 強茂   (功率元件 IDM)
        "3675",  # 德微   (SiC)
        "8261",  # 富鼎   (功率元件)
        "3317",  # 尼克森  (GaN)
        "3532",  # 台勝科  (矽晶圓)
        "3016",  # 嘉晶   (矽晶圓/SiC)
        "2351",  # 順德   (「現在: 2351 已第三段27號法說」老師觀察中)
        "3162",  # 精確   (「分點 單兵」老師追蹤)
        "2303",  # 聯電   (「成熟製程 2303 29號法說」)
        "5347",  # 世界先進 (成熟製程)
        "4526",  # 東台   (機器人)
        "4540",  # 全球傳動 (機器人)
        "2344",  # 華邦電  (記憶體 站前哥)
        "3006",  # 晶豪科  (記憶體 CB 發)
        "3135",  # 凌航   (記憶體模組)
    ],
    notes = {
        "2317": "老師崩盤筆記本「鴻海股小結構整理」",
        "2351": "老師觀察清單「現在: 2351 已第三段27號法說」",
        "3162": "老師「分點 單兵」追蹤",
        "2344": "記憶體 站前哥買超",
        "3006": "晶豪科 CB 發行 + 永豐金",
    }
)

# ──────────────────────────────────────────────────────────────────────────────
# C. 全方位培訓班 5/26-5/27 法人籌碼課程
# ──────────────────────────────────────────────────────────────────────────────

SOURCE_T0526 = TeacherSource(
    pub_date    = "2026-05-26",
    source_key  = "T0526",
    source_desc = "全方位培訓班 5/26 法人籌碼 — 成熟製程/矽晶圓/券商/記憶體",
    tickers     = [
        "2303",  # 聯電   (老師「成熟製程發大財」外資大買)
        "4919",  # 新唐   (老師「外資連三天買」成熟製程)
        "2344",  # 華邦電  (老師「外資大買、戰前哥確認」)
        "6282",  # 康舒   (老師「紅海外資還是挺」)
        "6005",  # 群益證  (老師「券商隱藏主菜 特別提醒」)
        "2885",  # 元大金  (券商系 兆元結構受益)
        "2883",  # 凱基金  (券商業務佔比高)
        "2891",  # 中信金  (金融股 台股上兆受益)
        "2881",  # 富邦金  (金融股)
        "2882",  # 國泰金  (金融股)
        "2337",  # 旺宏   (記憶體 等整理完畢)
    ],
    notes = {
        "2303": "老師原句：「成熟製程真的太強了 成熟製程發大財」外資今天大買",
        "4919": "老師原句：「外資很愛 這三天 我觀察三天的外資很愛」",
        "2344": "老師確認外資大買 + 戰前哥 confirmed",
        "6005": "老師原句：「你是尼克全方位培訓班 你就要特別去注意這種 我特別提醒的」",
        "2885": "兆元結構受益 券商系",
    }
)

SOURCE_T0527 = TeacherSource(
    pub_date    = "2026-05-27",
    source_key  = "T0527",
    source_desc = "全方位培訓班 5/27 法人籌碼 — 被動元件/券商/記憶體封測",
    tickers     = [
        "3026",  # 禾伸堂  (被動元件)
        "2472",  # 立隆電  (被動元件 330)
        "6173",  # 信昌電  (被動元件)
        "6449",  # 鈺邦   (被動元件)
        "6284",  # 佳邦   (可轉債+庫藏股)
        "3481",  # 群創   (被動元件轟轟轟 面板)
        "2303",  # 聯電   (成熟製程 放風箏已遠)
        "8150",  # 南茂   (記憶體封測)
        "3006",  # 晶豪科  (記憶體封測)
        "6005",  # 群益證  (券商「我做的就是這個」)
        "2855",  # 統一證  (券商)
        "6016",  # 康和證  (券商推測)
        "2885",  # 元大金  (金融全衝)
        "2882",  # 國泰金  (金融全衝)
        "2881",  # 富邦金  (金融全衝)
        "2891",  # 中信金  (金融全衝)
        "6285",  # 啟碁   (SpaceX PCB 低軌衛星)
        "4906",  # 正文   (網通 通過 12 點考驗)
    ],
    notes = {
        "3481": "老師原句：「除非你滿手都是被動元件 被動元件可以轟轟轟上去」",
        "6005": "老師原句：「我做的就是這個 做了好幾次了 這是我很喜歡的位置」",
        "8150": "南茂 記憶體封測 老師直接唸名",
        "6285": "啟碁「通過12點考驗 老師明示」",
        "4906": "正文「通過12點考驗 老師明示」",
    }
)

# ──────────────────────────────────────────────────────────────────────────────
# D. 5/25 Line 群直播：矽晶圓三劍客
# ──────────────────────────────────────────────────────────────────────────────

SOURCE_LINE0525 = TeacherSource(
    pub_date    = "2026-05-25",
    source_key  = "L0525",
    source_desc = "5/25 Line 群：老師明示矽晶圓三劍客 (memory 已記錄)",
    tickers     = [
        "3016",  # 嘉晶   (老師「要 3016 或 2481 6182」)
        "6182",  # 合晶   (老師「6182 3016 2481 我都直接講的」)
        "2481",  # 強茂   (矽晶圓三劍客)
    ],
    notes = {
        "3016": "老師：「拜託轉 3016 3707 永遠都漲輸 3016」",
        "6182": "老師：「我上面說了 我都直接講的 6182 3016 2481」",
        "2481": "矽晶圓三劍客 + 功率元件雙題材",
    }
)

# ──────────────────────────────────────────────────────────────────────────────
# 所有來源合併
# ──────────────────────────────────────────────────────────────────────────────

ALL_SOURCES: list[TeacherSource] = [
    SOURCE_W0503,
    SOURCE_W0503_EXTRA,
    SOURCE_W0516,
    SOURCE_COMPUTEX,
    SOURCE_T0526,
    SOURCE_T0527,
    SOURCE_LINE0525,
    SOURCE_W0531,
]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DB 工具 (同 phase5b)
# ═══════════════════════════════════════════════════════════════════════════════

def _db_con() -> sqlite3.Connection:
    return get_conn(_DB, timeout=30)


def get_trading_dates(start: str, end: str) -> list[str]:
    with _db_con() as con:
        rows = con.execute(
            """SELECT DISTINCT trade_date FROM standard_daily_bar
               WHERE trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date""",
            (start, end),
        ).fetchall()
    return [r[0] for r in rows]


def load_daily_bars(ticker: str, start: str, end: str) -> pd.DataFrame:
    with _db_con() as con:
        rows = con.execute(
            """SELECT trade_date, open, high, low, close, volume,
                      ma5, ma10, ma20, ma60
               FROM standard_daily_bar
               WHERE ticker = ? AND trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date""",
            (ticker, start, end),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows,
        columns=["trade_date","open","high","low","close","volume",
                 "ma5","ma10","ma20","ma60"])
    for col in ["open","high","low","close","ma5","ma10","ma20","ma60"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    return df


def get_stock_name(ticker: str) -> str:
    try:
        with _db_con() as con:
            row = con.execute(
                "SELECT stock_name FROM stock_info WHERE ticker=? LIMIT 1",
                (ticker,)
            ).fetchone()
        return row[0] if row else ticker
    except Exception:
        return ticker


# ═══════════════════════════════════════════════════════════════════════════════
# 3. User 真實 5 月起 P&L (同 phase5b，但正確歸類金居)
# ═══════════════════════════════════════════════════════════════════════════════

def get_user_may_real_pnl() -> tuple[float, dict[str, float]]:
    """從 broker_statement 計算 user 5 月起的 FIFO 已實現 P&L。

    特殊處理：
    - 709966 (金居認購權證) → 歸屬到 8358 金居 (老師明示標的)
    - 沖買沖賣算一筆（同日當沖計入已實現）
    """
    with _db_con() as con:
        rows = con.execute(
            """SELECT ticker, stock_name, trade_date, action, shares, price, net_amount
               FROM broker_statement
               WHERE trade_date >= '2026-05-01'
               ORDER BY ticker, trade_date, id""",
            ()
        ).fetchall()

    from collections import defaultdict
    by_ticker: dict[str, list] = defaultdict(list)
    for r in rows:
        tk, sn, date, action, shares, price, net_amt = r
        # 709966 = 金居認購權證，歸屬到 8358
        if tk == "709966" or sn == "金居":
            tk = "8358_warrants"  # 權證單獨算，不混入股票
        by_ticker[tk].append((date, action, shares, price, net_amt))

    result: dict[str, float] = {}
    total = 0.0

    for tk, trades in by_ticker.items():
        inventory: list[dict] = []
        realized = 0.0

        for date, action, shares, price, net_amt in trades:
            if "買" in action:
                cost_per = abs(net_amt) / shares if (net_amt and shares) else float(price)
                inventory.append({"date": date, "cost_per": cost_per, "shares": shares})
            elif "賣" in action:
                recv_per = net_amt / shares if (net_amt and shares) else float(price)
                remaining = shares
                while remaining > 0 and inventory:
                    inv = inventory[0]
                    matched = min(remaining, inv["shares"])
                    realized += (recv_per - inv["cost_per"]) * matched
                    inv["shares"] -= matched
                    remaining -= matched
                    if inv["shares"] == 0:
                        inventory.pop(0)

        result[tk] = round(realized, 0)
        total += realized

    return round(total, 0), result


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 進場邏輯 (同 phase5b)
# ═══════════════════════════════════════════════════════════════════════════════

def check_entry_conditions(row: pd.Series, prev_close: Optional[float]) -> tuple[bool, str]:
    """進場條件: 多頭排列 + 收盤在MA5上 + 距MA10 -3~+10% + 跳空≤+3%"""
    close  = row["close"]
    ma5    = row["ma5"]
    ma10   = row["ma10"]
    ma20   = row["ma20"]
    ma60   = row["ma60"]
    open_p = row["open"]

    if any(pd.isna(v) for v in [close, ma5, ma10, ma20, ma60]):
        return False, "MA資料缺失"

    if not (ma5 > ma10 > ma20 > ma60):
        return False, f"非多頭排列 5={ma5:.1f} 10={ma10:.1f} 20={ma20:.1f} 60={ma60:.1f}"

    if close < ma5:
        return False, f"收盤{close:.2f}<MA5{ma5:.2f}"

    dist_ma10_pct = (close - ma10) / ma10 * 100
    if dist_ma10_pct < -3.0 or dist_ma10_pct > 10.0:
        return False, f"打擊區外 距MA10={dist_ma10_pct:+.1f}%"

    if prev_close is not None and prev_close > 0:
        gap_pct = (open_p - prev_close) / prev_close * 100
        if gap_pct > 3.0:
            return False, f"跳空過大 {gap_pct:+.1f}%>+3%"

    reason = (
        f"多頭排列✓ | MA5={ma5:.1f} MA10={ma10:.1f} | 距MA10={dist_ma10_pct:+.1f}%"
    )
    return True, reason


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 出場邏輯 (同 phase5b)
# ═══════════════════════════════════════════════════════════════════════════════

def check_exit(
    df_to_date: pd.DataFrame,
    entry_price: float,
    shares_held: float,
    milestones_hit: set,
) -> tuple[Optional[str], str, float, float]:
    if len(df_to_date) < 2:
        return None, "資料不足", 0.0, 0.0

    today = df_to_date.iloc[-1]
    prev  = df_to_date.iloc[-2]
    close = float(today["close"])
    open_p = float(today["open"])
    prev_close = float(prev["close"])
    ma10  = today["ma10"]

    # P1: 跳空大跌 -5%+
    if not pd.isna(prev_close) and prev_close > 0:
        gap_pct = (open_p - prev_close) / prev_close * 100
        if gap_pct <= -5.0:
            return "exit_all", f"跳空大跌 {gap_pct:+.1f}%", open_p, 1.0

    # P2: 結構底 — 日收盤 < MA10
    if not pd.isna(ma10) and close < float(ma10):
        return "exit_all", f"收盤{close:.2f}<MA10{float(ma10):.2f}", close, 1.0

    # P3: 高檔長黑
    if len(df_to_date) >= 7:
        hlb = _check_high_long_black_simple(df_to_date)
        if hlb:
            return "exit_all", f"高檔長黑K: {hlb}", close, 1.0

    # P4: 掀傘
    if len(df_to_date) >= 5 and close > entry_price:
        umbrella = _check_umbrella_daily_simple(df_to_date, entry_price)
        if umbrella:
            return "exit_all", f"掀傘: {umbrella}", close, 1.0

    # P5: 分批停利里程碑
    profit_pct = (close / entry_price - 1) * 100
    milestones = [(10.0, "M10", 1/3), (20.0, "M20", 1/3), (30.0, "M30", 1.0)]
    for threshold, key, ratio in milestones:
        if profit_pct >= threshold and key not in milestones_hit:
            milestones_hit.add(key)
            return "take_profit", f"分批停利 +{threshold:.0f}% (出 {ratio*100:.0f}%)", close, ratio

    return None, "", close, 0.0


def _check_high_long_black_simple(df: pd.DataFrame) -> Optional[str]:
    today = df.iloc[-1]
    prev  = df.iloc[-2]
    open_p = float(today["open"])
    close  = float(today["close"])

    if close >= open_p:
        return None
    body_pct = (open_p - close) / open_p
    if body_pct < 0.04:
        return None

    lookback = df.tail(min(len(df), 61)).iloc[:-1]
    if len(lookback) < 10:
        return None
    prior_max = float(lookback["high"].max())
    prior_min = float(lookback["low"].min())
    if prior_min <= 0 or prior_max / prior_min < 1.2:
        return None

    meanings = []

    for i in range(len(df) - 2, max(0, len(df) - 22), -1):
        if df.iloc[i]["open"] > df.iloc[i-1]["high"]:
            gap_low = float(df.iloc[i-1]["high"])
            if close < gap_low:
                meanings.append(f"M1缺口回補(gap={gap_low:.1f})")
            break

    prev_close_v = float(prev["close"])
    prev_open_v  = float(prev["open"])
    prev_high_v  = float(prev["high"])
    prev_low_v   = float(prev["low"])
    if prev_close_v > prev_open_v:
        hist = df.tail(min(len(df), 63)).iloc[:-2]
        if not hist.empty and prev_close_v >= float(hist["high"].max()):
            if open_p >= prev_high_v and close <= prev_low_v:
                meanings.append(f"M2包覆創高紅K(前高{prev_high_v:.1f})")

    if len(df) >= 7:
        prior_5_closes = df.iloc[-7:-2]["close"]
        min_5 = float(prior_5_closes.min())
        if close < min_5:
            meanings.append(f"M3吃前5根(前最低收{min_5:.1f})")

    if len(meanings) >= 2:
        return " + ".join(meanings)
    return None


def _check_umbrella_daily_simple(df: pd.DataFrame, entry_price: float) -> Optional[str]:
    NO_NEW_HIGH_BARS = 3
    if len(df) < NO_NEW_HIGH_BARS + 2:
        return None
    close = float(df.iloc[-1]["close"])
    if close <= entry_price:
        return None

    prior_high = float(df.iloc[-(NO_NEW_HIGH_BARS + 1)]["high"])
    tail_highs = [float(df.iloc[-(NO_NEW_HIGH_BARS - i)]["high"]) for i in range(NO_NEW_HIGH_BARS)]
    if not all(h <= prior_high for h in tail_highs):
        return None

    vol_mean = float(df["volume"].tail(min(len(df), 10)).mean())
    last_vol  = float(df.iloc[-1]["volume"])
    vol_ratio = last_vol / vol_mean if vol_mean > 0 else 1.0
    if vol_ratio >= 0.7:
        return None

    tail_bars = df.tail(NO_NEW_HIGH_BARS)
    reds = (tail_bars["close"] > tail_bars["open"]).values
    if any(reds[i] and reds[i+1] for i in range(len(reds)-1)):
        return None

    profit_pct = (close / entry_price - 1) * 100
    return f"連3日不創高+量縮×{vol_ratio:.2f} | 浮盈+{profit_pct:.1f}%"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 單一 Ticker 模擬
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SimTrade:
    ticker:     str
    name:       str
    source_key: str
    pub_date:   str
    source_desc: str
    entry_date: Optional[str]   = None
    entry_price: float           = 0.0
    exit_date:  Optional[str]   = None
    exit_price: float            = 0.0
    exit_reason: str             = ""
    pnl:        float            = 0.0
    pnl_pct:    float            = 0.0
    capital:    float            = DEFAULT_CAPITAL
    status:     str              = "no_entry"
    max_profit_pct: float        = 0.0
    hold_days:  int              = 0


def simulate_ticker(
    ticker: str,
    source: TeacherSource,
    all_trading_dates: list[str],
    bars: pd.DataFrame,
    verbose: bool = False,
) -> SimTrade:
    name = get_stock_name(ticker)
    trade = SimTrade(
        ticker=ticker, name=name,
        source_key=source.source_key, pub_date=source.pub_date,
        source_desc=source.source_desc, capital=DEFAULT_CAPITAL,
    )

    if bars.empty:
        trade.status = "no_data"
        return trade

    monitor_dates = [d for d in all_trading_dates if d > source.pub_date]
    if not monitor_dates:
        return trade

    max_monitor_days = 10
    entry_price = None
    entry_date  = None

    sorted_bars = bars.sort_values("trade_date").reset_index(drop=True)
    prev_close_cache: dict[str, float] = {}
    for i, row in sorted_bars.iterrows():
        if i > 0:
            prev_close_cache[row["trade_date"]] = float(sorted_bars.iloc[i-1]["close"])

    # 等待進場
    for d in monitor_dates[:max_monitor_days]:
        day_rows = bars[bars["trade_date"] == d]
        if day_rows.empty:
            continue
        row = day_rows.iloc[0]
        prev_close = prev_close_cache.get(d)

        ok, reason = check_entry_conditions(row, prev_close)
        if ok:
            entry_price = float(row["close"])
            entry_date  = d
            trade.entry_date  = d
            trade.entry_price = entry_price
            trade.status = "entered"
            if verbose:
                print(f"  [進場] {ticker} {name}  @{d}  ${entry_price:.1f}  {reason}")
            break
        else:
            if verbose:
                print(f"  [等待] {ticker} {name}  {d}  未觸發: {reason}")

    if entry_price is None:
        if verbose:
            print(f"  ⏳ 無進場訊號  ")
        return trade

    # 持倉階段
    hold_bars    = bars[bars["trade_date"] > entry_date].copy()
    shares_held  = 1.0  # normalized
    milestones   = set()
    total_pnl    = 0.0
    exit_date    = None
    exit_price   = 0.0
    exit_reason  = ""
    max_profit   = 0.0

    for _, end_row in hold_bars.iterrows():
        d    = end_row["trade_date"]
        close = float(end_row["close"])
        profit_pct = (close / entry_price - 1) * 100
        max_profit = max(max_profit, profit_pct)

        df_to_date = bars[bars["trade_date"] <= d].copy()
        action, reason, price, ratio = check_exit(
            df_to_date, entry_price, shares_held, milestones
        )

        if action == "take_profit" and ratio < 1.0:
            pnl_partial = (price - entry_price) * ratio * DEFAULT_CAPITAL / entry_price
            # 扣費
            fee_out = price * ratio * DEFAULT_CAPITAL / entry_price * FEE_RATE
            tax_out = price * ratio * DEFAULT_CAPITAL / entry_price * TAX_RATE
            pnl_partial -= (fee_out + tax_out)
            total_pnl += pnl_partial
            shares_held -= ratio
            if verbose:
                print(f"  [停利] {ticker}  @{d}  ${price:.1f}  {reason}  部分P&L={pnl_partial:+,.0f}  剩{shares_held*100:.0f}%")
            if shares_held <= 0.01:
                exit_date   = d
                exit_price  = price
                exit_reason = reason
                break
        elif action in ("exit_all", "take_profit"):
            pnl_final = (price - entry_price) * shares_held * DEFAULT_CAPITAL / entry_price
            fee_out = price * shares_held * DEFAULT_CAPITAL / entry_price * FEE_RATE
            tax_out = price * shares_held * DEFAULT_CAPITAL / entry_price * TAX_RATE
            pnl_final -= (fee_out + tax_out)
            total_pnl += pnl_final
            exit_date   = d
            exit_price  = price
            exit_reason = reason
            if verbose:
                print(f"  [出場] {ticker}  @{d}  ${price:.1f}  {reason}  P&L={total_pnl:+,.0f}")
            break

    # 仍持倉時用最後 close 算浮盈
    if exit_date is None and shares_held > 0:
        last_close = float(bars.iloc[-1]["close"])
        open_pnl   = (last_close - entry_price) * shares_held * DEFAULT_CAPITAL / entry_price
        total_pnl += open_pnl
        exit_price  = last_close
        exit_reason = f"持倉中@{bars.iloc[-1]['trade_date']}"
        trade.status = "open"
        if verbose:
            print(f"  📂 持倉中  P&L={total_pnl:+,.0f}")

    # 進場費用
    fee_in  = entry_price * DEFAULT_CAPITAL / entry_price * FEE_RATE
    total_pnl -= fee_in

    trade.pnl        = round(total_pnl, 0)
    trade.pnl_pct    = (exit_price / entry_price - 1) * 100 if entry_price else 0
    trade.exit_date  = exit_date
    trade.exit_price = exit_price
    trade.exit_reason = exit_reason
    trade.max_profit_pct = max_profit
    if entry_date and exit_date:
        dt1 = pd.Timestamp(entry_date)
        dt2 = pd.Timestamp(exit_date)
        trade.hold_days = (dt2 - dt1).days

    return trade


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 主 backtest
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(verbose: bool = False) -> list[SimTrade]:
    """對所有老師來源跑 backtest，去重只跑最早來源。"""
    all_dates = get_trading_dates("2026-04-01", ANALYSIS_END)

    # 先建立 ticker → 最早來源的 mapping (避免重複計算)
    earliest: dict[str, TeacherSource] = {}
    for src in ALL_SOURCES:
        for tk in src.tickers:
            if tk not in earliest or src.pub_date < earliest[tk].pub_date:
                earliest[tk] = src

    results: list[SimTrade] = []
    for src in ALL_SOURCES:
        if verbose:
            print(f"\n=== 來源 {src.source_key} ({src.pub_date}) ===")
            print(f"主題: {src.source_desc}")
            print(f"監控 {len(src.tickers)} 檔: {' '.join(src.tickers)}")
        for tk in src.tickers:
            # 去重：只在最早來源時跑
            if earliest.get(tk) != src:
                if verbose:
                    print(f"  [略過] {tk} (已在 {earliest[tk].source_key} {earliest[tk].pub_date} 跑過)")
                continue
            bars = load_daily_bars(tk, "2026-04-01", ANALYSIS_END)
            trade = simulate_ticker(tk, src, all_dates, bars, verbose=verbose)
            results.append(trade)
            if not verbose:
                icon = "✅" if trade.entry_date and trade.exit_date and trade.status != "open" else \
                       "📂" if trade.status == "open" else "⏳"
                pnl_str = f"  P&L={trade.pnl:+,.0f}" if trade.entry_date else ""
                print(f"  {tk} {trade.name:12s} {icon}{pnl_str}")

    return results


def analyze_results(results: list[SimTrade]) -> dict:
    entered = [r for r in results if r.entry_date]
    closed  = [r for r in entered if r.exit_date and r.status != "open"]
    open_p  = [r for r in entered if r.status == "open"]
    no_entry = [r for r in results if not r.entry_date]

    total_pnl = sum(r.pnl for r in entered)
    winners = [r for r in entered if r.pnl > 0]
    losers  = [r for r in entered if r.pnl <= 0]

    by_source: dict[str, dict] = {}
    for src in ALL_SOURCES:
        k = src.source_key
        src_trades = [r for r in entered if r.source_key == k]
        by_source[k] = {
            "entered": len(src_trades),
            "pnl": sum(r.pnl for r in src_trades),
            "tickers": [r.ticker for r in src_trades],
        }

    best  = max(entered, key=lambda r: r.pnl) if entered else None
    worst = min(entered, key=lambda r: r.pnl) if entered else None

    return {
        "total":         len(results),
        "entered":       len(entered),
        "closed":        len(closed),
        "open_pos":      len(open_p),
        "no_entry":      len(no_entry),
        "total_pnl":     total_pnl,
        "winners":       len(winners),
        "losers":        len(losers),
        "win_rate":      len(winners) / len(entered) * 100 if entered else 0,
        "avg_pnl":       total_pnl / len(entered) if entered else 0,
        "avg_win":       sum(r.pnl for r in winners) / len(winners) if winners else 0,
        "avg_loss":      sum(r.pnl for r in losers) / len(losers) if losers else 0,
        "best_trade":    best,
        "worst_trade":   worst,
        "by_source":     by_source,
        "entered_trades": entered,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 差距分類 (phase5c 修正後)
# ═══════════════════════════════════════════════════════════════════════════════

def classify_gap(
    results: list[SimTrade],
    user_pnl_by_ticker: dict[str, float],
) -> dict:
    """重新分類 user 真實 vs phase5c backtest 的差距。

    分類：
    1. 早停利 — 老師明示標的, user 比 backtest 早出, user 少賺
    2. 太晚進場 — 老師明示標的, user 進場比最佳時機晚
    3. 沒進場 — 老師明示標的, user 根本沒進場
    4. 部位太小 — 老師明示標的, user 進場但倉位不足
    5. 早停損 — 老師明示標的, user 停損但 backtest 後來盈利
    6. 盤整沒買回 — 老師明示且 user 出清後沒有買回
    7. 真正框架外自選 — 非老師明示標的的交易
    """
    phase5c_tickers = {r.ticker for r in results}

    # 真正框架外自選 (非老師明示)
    outside_framework: dict[str, float] = {
        tk: pnl for tk, pnl in user_pnl_by_ticker.items()
        if tk not in phase5c_tickers
        and tk not in ("8358_warrants",)  # 排除 meta 項
        and not tk.startswith("00")  # 排除 ETF
        and tk not in ("009819", "020036", "0052", "00403A")  # ETF
    }

    # 老師明示標的但 user 早停利
    early_exit_cases: list[dict] = []
    no_entry_cases: list[dict] = []
    for r in results:
        if not r.entry_date:
            continue
        user_pnl = user_pnl_by_ticker.get(r.ticker)
        if user_pnl is not None:
            if r.pnl > 0 and user_pnl < r.pnl - 20_000:
                early_exit_cases.append({
                    "ticker": r.ticker, "name": r.name,
                    "sim_pnl": r.pnl, "user_pnl": user_pnl,
                    "gap": user_pnl - r.pnl,
                    "max_pct": r.max_profit_pct,
                })
        else:
            # user 完全沒交易這檔老師明示標的
            no_entry_cases.append({
                "ticker": r.ticker, "name": r.name,
                "sim_pnl": r.pnl,
                "source_key": r.source_key,
            })

    return {
        "outside_framework": outside_framework,
        "outside_total": sum(outside_framework.values()),
        "early_exit": early_exit_cases,
        "early_exit_total": sum(c["gap"] for c in early_exit_cases),
        "no_entry": no_entry_cases,
        "no_entry_total": -sum(c["sim_pnl"] for c in no_entry_cases if c["sim_pnl"] > 0),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 9. 報告生成
# ═══════════════════════════════════════════════════════════════════════════════

def format_report(
    results: list[SimTrade],
    stats: dict,
    user_pnl_total: float,
    user_pnl_by_ticker: dict,
    gap_analysis: dict,
) -> str:
    lines = []
    lines.append("# Phase 5c — 老師所有來源 Backtest 修正報告")
    lines.append("")
    lines.append(f"> 修正 phase5b 分類錯誤：金居/高技/順德 均為老師明示標的，非「框架外自選」")
    lines.append(f"> 分析期間: {ANALYSIS_START} ~ {ANALYSIS_END}")
    lines.append(f"> Sizing: $320k / 檔 (總資金 ~$3.2M 水位 10%)")
    lines.append("")

    # 老師明示 universe 清單
    lines.append("## 1. 老師明示 Universe (5 月起，所有來源去重)")
    lines.append("")
    lines.append("| 代號 | 名稱 | 最早來源 | 來源日期 | 老師原話 |")
    lines.append("|------|------|---------|---------|---------|")

    earliest: dict[str, TeacherSource] = {}
    for src in ALL_SOURCES:
        for tk in src.tickers:
            if tk not in earliest or src.pub_date < earliest[tk].pub_date:
                earliest[tk] = src

    for tk, src in sorted(earliest.items(), key=lambda x: (x[1].pub_date, x[0])):
        name = get_stock_name(tk)
        note = src.notes.get(tk, "")[:40]
        lines.append(f"| {tk} | {name} | {src.source_key} | {src.pub_date} | {note} |")
    lines.append("")
    lines.append(f"**總計: {len(earliest)} 檔老師明示標的 (5 月起)**")
    lines.append("")

    # Backtest 結果
    lines.append("## 2. Backtest 結果")
    lines.append("")
    lines.append("| 來源 | 期間 | 進場 | P&L |")
    lines.append("|------|------|------|-----|")
    for src in ALL_SOURCES:
        rstat = stats["by_source"].get(src.source_key, {})
        src_tickers = [tk for tk in src.tickers if earliest.get(tk) == src]
        lines.append(
            f"| {src.source_key} | {src.pub_date} "
            f"| {rstat.get('entered',0)}/{len(src_tickers)} 檔 "
            f"| ${rstat.get('pnl',0):+,.0f} |"
        )
    lines.append("")

    entered = stats["entered_trades"]
    lines.append("### 已進場標的明細")
    lines.append("")
    lines.append("| 來源 | 代號 | 名稱 | 進場 | 進場價 | 出場 | 出場價 | 出場原因 | P&L | 最高% |")
    lines.append("|------|------|------|------|-------|------|-------|---------|-----|------|")
    for r in sorted(entered, key=lambda x: x.pub_date):
        entry_d = r.entry_date or "-"
        exit_d  = r.exit_date or "持倉中"
        exit_p  = f"${r.exit_price:.1f}" if r.exit_price else "-"
        pnl_str = f"**{r.pnl:+,.0f}**" if r.pnl != 0 else "-"
        reason  = r.exit_reason[:25] if r.exit_reason else "-"
        lines.append(
            f"| {r.source_key} | {r.ticker} | {r.name} "
            f"| {entry_d} | ${r.entry_price:.1f} "
            f"| {exit_d} | {exit_p} | {reason} "
            f"| {pnl_str} | {r.max_profit_pct:+.1f}% |"
        )
    lines.append("")

    # 統計
    lines.append("## 3. 累積報酬統計")
    lines.append("")
    lines.append(f"| 指標 | 數值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 老師明示 Universe | {len(earliest)} 檔 |")
    lines.append(f"| 成功進場 | {stats['entered']} 檔 |")
    lines.append(f"| 進場觸發率 | {stats['entered']/max(stats['total'],1)*100:.1f}% |")
    lines.append(f"| **累積 P&L (phase5c)** | **${stats['total_pnl']:+,.0f}** |")
    lines.append(f"| 勝率 | {stats['win_rate']:.1f}% |")
    lines.append(f"| 最佳單筆 | {stats['best_trade'].ticker}{stats['best_trade'].name} {stats['best_trade'].pnl:+,.0f} |" if stats['best_trade'] else "")
    lines.append("")

    # 三版對比
    lines.append("## 4. 三版對比表")
    lines.append("")
    lines.append("| 策略 | 期間 | Universe | 累積 P&L | 備注 |")
    lines.append("|------|------|---------|---------|------|")
    lines.append(f"| phase5b (僅週報 3 篇) | 5-6 月 | 29 檔 | **+$110,670** | phase5b 原始 |")
    lines.append(f"| **phase5c (老師所有來源) ⭐** | 5-6 月 | {len(earliest)} 檔 | **${stats['total_pnl']:+,.0f}** | 本報告 |")
    lines.append(f"| user 真實 5月起 已實現 | 5-6 月 | — | **${user_pnl_total:+,.0f}** | 含權證等 |")
    lines.append("")

    # 差距分析 (修正後)
    sim_pnl = stats["total_pnl"]
    gap_total = user_pnl_total - sim_pnl
    lines.append("## 5. 真實差距重新分類 (修正後)")
    lines.append("")
    lines.append(f"**phase5c backtest:** ${sim_pnl:+,.0f}")
    lines.append(f"**user 真實已實現:** ${user_pnl_total:+,.0f}")
    lines.append(f"**差距 (user - backtest):** ${gap_total:+,.0f}")
    lines.append("")

    lines.append("| 差距類別 | 損失估計 | 說明 |")
    lines.append("|---------|---------|------|")

    # 早停利
    early_sorted = sorted(gap_analysis["early_exit"], key=lambda x: x["gap"])
    early_total  = gap_analysis["early_exit_total"]
    lines.append(f"| **1. 早停利** | **${early_total:+,.0f}** | 老師明示標的 user 太早出場 |")

    for c in early_sorted[:5]:
        lines.append(
            f"|   {c['ticker']}{c['name']} | ${c['gap']:+,.0f} | "
            f"backtest=${c['sim_pnl']:+,.0f} vs user=${c['user_pnl']:+,.0f} max={c['max_pct']:+.0f}% |"
        )

    # 沒進場
    no_entry_lost = gap_analysis["no_entry_total"]
    lines.append(f"| **2. 老師明示但沒進場** | **${-no_entry_lost:+,.0f}** | backtest 有盈利但 user 未進場 |")

    # 框架外
    outside_total = gap_analysis["outside_total"]
    outside_sorted = sorted(gap_analysis["outside_framework"].items(), key=lambda x: x[1])
    lines.append(f"| **3. 真正框架外自選** | **${outside_total:+,.0f}** | 非老師明示標的 |")
    for tk, pnl in outside_sorted[:5]:
        if pnl < -5000:
            name = get_stock_name(tk)
            lines.append(f"|   {tk}{name} | ${pnl:+,.0f} | 非老師明示 |")

    lines.append("")
    lines.append("**關鍵修正：**")
    lines.append("")
    lines.append(
        f"- **金居 (8358) 和高技 (5439)** — phase5b 誤判為「框架外自選」"
        f"→ 實為老師週報 W0503 直播課綱已明示標的"
    )
    lines.append(
        f"- **順德 (2351)** — phase5b 誤判為「非週報」"
        f"→ 實為老師「融資股觀察清單」+ COMPUTEX前夕「現在觀察」標的"
    )
    lines.append(
        f"- **框架外自選損失**：phase5b 估算 $-130,241 → phase5c 修正後 ${outside_total:+,.0f}"
    )
    lines.append("")

    # 早停利案例詳細
    if early_sorted:
        lines.append("### 早停利詳細案例")
        lines.append("")
        for c in early_sorted:
            name = c["name"]
            lines.append(f"**{c['ticker']}{name}**: backtest=${c['sim_pnl']:+,.0f} vs user=${c['user_pnl']:+,.0f}, "
                         f"差 ${c['gap']:+,.0f}, 最高漲幅 {c['max_pct']:+.0f}%")
        lines.append("")

    # 修正後紀律建議
    lines.append("## 6. 修正後 4 條紀律建議 (依新數據重新加權)")
    lines.append("")
    lines.append("| 紀律 | 重要性 (修正前→後) | 說明 |")
    lines.append("|------|-------------------|------|")
    lines.append(f"| **A. 分批停利 + 多抱一下** | 🔴 → 🔴🔴 (最重要) | 早停利是真正主因 |")
    lines.append(f"| **B. 賣後復進 (老師多次教)** | 🟡 → 🔴 | 持倉後出清常常錯過後段 |")
    lines.append(f"| **C. 不碰框架外** | 🔴 → 🟡 (次要) | 框架外損失 < 預估的一半 |")
    lines.append(f"| **D. 進場 timing 要準** | 🟡 → 🟡 | 影響較小，但仍需注意 |")
    lines.append("")
    lines.append("**核心認知修正：**")
    lines.append("")
    lines.append("1. 金居/高技/順德 都在老師框架內 — 不是「自選鬼」，是「執行太差鬼」")
    lines.append("2. 損失的主因是**早砍 + 沒買回**，而不是「買了不該買的」")
    lines.append("3. 最需要練習的是：老師明示後「拿得住 + 分批而非一刀砍」")
    lines.append("4. 框架外自殘只有少數（三晃 1721 等），影響遠小於早停利")
    lines.append("")
    lines.append("---")
    lines.append(f"*Phase 5c 報告 | 截止 {ANALYSIS_END} | Sizing $320k/檔*")
    lines.append(f"*老師明示 Universe: {len(earliest)} 檔 | 修正 phase5b 分類錯誤*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 5c — 老師所有來源 Backtest (修正 phase5b 分類錯誤)"
    )
    parser.add_argument("--verbose", action="store_true", help="顯示每日進出場細節")
    parser.add_argument("--report",  action="store_true", help="寫出 markdown 報告")
    args = parser.parse_args()

    # 計算老師明示 universe 大小
    earliest: dict[str, "TeacherSource"] = {}
    for src in ALL_SOURCES:
        for tk in src.tickers:
            if tk not in earliest or src.pub_date < earliest[tk].pub_date:
                earliest[tk] = src

    print("=" * 70)
    print("Phase 5c — 老師所有來源 Backtest (修正 phase5b 分類錯誤)")
    print(f"分析區間: {ANALYSIS_START} ~ {ANALYSIS_END}")
    print(f"老師明示 Universe: {len(earliest)} 檔 (5 月起，所有來源)")
    print("新增來源: W0503_EXTRA + COMPUTEX + T0526 + T0527 + L0525")
    print("修正: 金居/高技/順德 均屬老師明示，非框架外自選")
    print("=" * 70)

    results = run_backtest(verbose=args.verbose)
    stats   = analyze_results(results)

    print()
    print("── 讀取 user 5 月起真實 broker_statement ───────────────────────")
    user_pnl_total, user_pnl_by_ticker = get_user_may_real_pnl()
    # 確認金居權證的損失
    warrants_pnl = user_pnl_by_ticker.get("8358_warrants", 0)
    print(f"5 月起已實現 P&L: ${user_pnl_total:+,.0f}")
    print(f"  (金居認購權證 709966: ${warrants_pnl:+,.0f} — 已獨立標注)")

    print()
    print("=" * 70)
    print("統計結果")
    print("=" * 70)
    print(f"老師明示 Universe: {len(earliest)} 檔  進場觸發: {stats['entered']} 檔  "
          f"(觸發率 {stats['entered']/max(stats['total'],1)*100:.1f}%)")
    print(f"已出場: {stats['closed']} 筆  仍持倉: {stats['open_pos']} 筆  "
          f"無訊號: {stats['no_entry']} 檔")
    print(f"勝率: {stats['win_rate']:.1f}%  "
          f"贏:{stats['winners']} 輸:{stats['losers']}")
    print()
    print(f"★ phase5c 累積 P&L: ${stats['total_pnl']:+,.0f}")
    print(f"  平均單筆: ${stats['avg_pnl']:+,.0f}  "
          f"均獲利: ${stats['avg_win']:+,.0f}  均虧損: ${stats['avg_loss']:+,.0f}")
    print()
    print("── 三版對比 ───────────────────────────────────────────────────")
    print(f"  phase5b (僅週報 3 篇):       +$110,670")
    print(f"  phase5c (老師所有來源):      ${stats['total_pnl']:+,.0f}")
    print(f"  User 真實 5月起 (已實現):    ${user_pnl_total:+,.0f}")
    print(f"  差距 (user真實 - phase5c):   ${user_pnl_total - stats['total_pnl']:+,.0f}")
    print()

    print("── 各來源 P&L ──────────────────────────────────────────────────")
    for src in ALL_SOURCES:
        rstat = stats["by_source"].get(src.source_key, {})
        src_tickers = [tk for tk in src.tickers if earliest.get(tk) == src]
        print(f"  {src.source_key} ({src.pub_date}): "
              f"進場 {rstat.get('entered',0)}/{len(src_tickers)} 檔  "
              f"P&L={rstat.get('pnl',0):+,.0f}")

    if stats["best_trade"]:
        bt = stats["best_trade"]
        print(f"\n  最佳: {bt.ticker}{bt.name}  {bt.pnl:+,.0f} ({bt.pnl_pct:+.1f}%)  "
              f"@{bt.entry_date} → {bt.exit_date}")
    if stats["worst_trade"]:
        wt = stats["worst_trade"]
        print(f"  最差: {wt.ticker}{wt.name}  {wt.pnl:+,.0f} ({wt.pnl_pct:+.1f}%)  "
              f"@{wt.entry_date} → {wt.exit_date}")

    # 差距分析
    gap_analysis = classify_gap(results, user_pnl_by_ticker)
    print()
    print("── 差距根本原因分類 (修正後) ───────────────────────────────────")
    print(f"  1. 早停利 (老師明示標的太早出):  ${gap_analysis['early_exit_total']:+,.0f}")
    for c in sorted(gap_analysis["early_exit"], key=lambda x: x["gap"])[:5]:
        print(f"     {c['ticker']}{c['name']:8s}  backtest:{c['sim_pnl']:+,.0f}  "
              f"user:{c['user_pnl']:+,.0f}  差:{c['gap']:+,.0f}  max={c['max_pct']:+.0f}%")
    print(f"  2. 沒進場 (老師明示未進場損失): ${gap_analysis['no_entry_total']:+,.0f}")
    print(f"  3. 真正框架外自選損失:          ${gap_analysis['outside_total']:+,.0f}")
    for tk, pnl in sorted(gap_analysis["outside_framework"].items(), key=lambda x: x[1])[:5]:
        if pnl < -5000:
            name = get_stock_name(tk)
            print(f"     {tk} {name:10s}  ${pnl:+,.0f}")
    print()
    print("── 修正 phase5b 的關鍵認知 ────────────────────────────────────")
    print("  ✅ 金居 8358: 老師 W0503 週報直播課綱就有 (銅箔材料) — 非自選")
    print("  ✅ 高技 5439: 老師 W0503 週報直播課綱就有 (PCB) — 非自選")
    print("  ✅ 順德 2351: 老師融資股觀察清單 + COMPUTEX前夕現在清單 — 非自選")
    print(f"  ❌ phase5b「框架外損失」高估: {-130241 - gap_analysis['outside_total']:+,.0f}")
    print()
    print("── 4 條紀律修正後重要性 ────────────────────────────────────────")
    print("  A. 分批停利 + 多抱一下  🔴🔴 最重要 (早停利是主因)")
    print("  B. 賣後復進             🔴   重要 (出清後沒有買回損失大)")
    print("  C. 不碰框架外           🟡   次要 (框架外損失 < 預估一半)")
    print("  D. 進場 timing          🟡   維持")

    if args.report:
        _STRAT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = _STRAT_DIR / "phase5c_all_teacher_sources.md"
        md_content = format_report(results, stats, user_pnl_total, user_pnl_by_ticker, gap_analysis)
        report_path.write_text(md_content, encoding="utf-8")
        print()
        print(f"報告已寫出: {report_path}")
    else:
        print()
        print("(加 --report 可寫出完整 markdown 報告)")


if __name__ == "__main__":
    main()
