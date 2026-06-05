"""自救型突破 — bull, entry candidate (入門 §34).

Course source: K線力量入門 第 34 篇《第二次突破型態的延伸運用之「自救型突破」》
  9E84C6271EAF67C173279994BF7BFA0C

老師原話（逐字）:
  - 「通常在大盤本來是多方趨勢，檯面上有很多個股在拉抬的階段，突然遇到了重大的利空使大盤
     下跌，資金根本來不及從容離開，就會採取防守的做法來暫時先護住股價，但是漸漸的股價又
     往上推升來到前高位置，這個背景是必要條件。」
  - 「隨著利空的逐漸鈍化，股價又突破了前高。此時成交量卻出現了比前高萎縮的跡象，一般技術
     分析的教學會判斷這種型態叫做『價量背離』，其實完全不是如此。」
  - 「自救型後的跳空是很重要的研判要點」
  - 「如果這次突破比上次量增，那就不列為自救型突破的範圍了」

定義（features.py is_self_rescue_breakout）:
  1. 今日 close > prior_high_60（突破前高）
  2. 過去 60 日內存在一次前次突破（close > 當時 prior_high_60）
  3. 今日成交量 < 上次突破當日量 × SELF_RESCUE_VOL_RATIO_MAX = 0.95（量縮）
  4. 多頭背景：close > ma60

利空背景條件（playbook required_context）:
  is_after_negative_news_taiex — 近 N 日大盤曾單日跌幅 ≥ proxy（context.py 提供）

Playbook: scripts/kline/scenarios/playbooks/self_rescue_breakout.yaml
  - B1: 隔日跳空 → entry_signal（最強攻擊確認）
  - B2: 隔日無跳空但持續走高 → watch_only / context_only
  - B3: 隔日無攻擊（open ≤ today.close 且 close 不創新高）→ exhaust_invalid
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """偵測自救型突破當日（features.py 已預計算 is_self_rescue_breakout）。

    僅 wrap features.py 預計算欄位以對齊 PATTERN_REGISTRY 介面。
    """
    if "is_self_rescue_breakout" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["is_self_rescue_breakout"].fillna(False).astype(bool)
