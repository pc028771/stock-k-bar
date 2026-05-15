---
name: 回測方法論：必須用停損停利出場
description: 禁止用 n 日固定報酬（ret_10d 等），必須用課程定義的出場條件模擬實際出場
type: feedback
originSessionId: d7e91495-e51b-49b5-ad3a-99d9db94b659
---
禁止用 `ret_10d`、`ret_20d` 等固定 N 日報酬作為回測績效指標或相關係數目標變數。

**Why:** 固定 N 日報酬忽略中途停損/停利出場，與真實交易行為不符。課程強調出場由型態與關鍵 K 線決定。

**How to apply:**
- 回測必須模擬事件驅動出場：每日檢查課程定義的出場條件，以最先觸發者為出場點，記錄實際持有天數與報酬
- 停損停利規則必須來自課程教過的內容，不可用固定百分比

**課程定義的出場條件（CLAUDE.md & strategy-indicators.md）：**
1. 收盤跌破關鍵低點或頸線 → 停損出清（以收盤價確認，隔日開盤出場）
2. 大黑 K 完整包覆前段漲幅 → 停損訊號
3. 趨勢特徵消失（低點越來越高的規律不再成立）→ 停損出清
4. 攻擊失敗（跳空缺口當天回補失敗）→ 出場訊號

**對現有程式的影響：**
- `attack_quality_analysis.py` Spearman 目標變數要改為「課程出場後的實際報酬」
- `kline_course_backtest.py` signal summary 也應改用出場報酬
- `breakout_attack_strategy_check.py` 已有 `stop_price_breakout` 概念可參考，但仍有固定期限問題
