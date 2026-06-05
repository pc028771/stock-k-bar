# Scenario Advisor — 整體導覽

本目錄實作「應變劇本層（Playbook Layer）」，是《K 線力量判斷入門》子課程「明日 K 線」的系統化實踐。

---

## 目錄結構

```
scenarios/
├── _schema.py         — Pydantic 資料模型（Light、Playbook、Action、AdvisorResult 等）
├── advisor.py         — 主入口 analyze() → AdvisorResult
├── condition.py       — 觸發條件 mini-DSL 評估引擎（白名單欄位 + 禁止運算式 RHS）
├── context.py         — ContextSnapshot 建立（features.py + overrides）
├── loader.py          — YAML 載入器（load_playbooks / load_lights）
├── persistence.py     — AdvisorResult 持久化（Task 1.6）
├── lights/            — D 類純觀念燈號（20 個 YAML）← 本任務（Task 2.3）
└── playbooks/         — B 類進出場劇本（Task 2.1）
```

---

## Lights — D 類純觀念燈號（Task 2.3）

`lights/` 目錄收錄「明日 K 線」47 篇中屬於 **D 類（純觀念 / 心法）** 的 20 個燈號。每個燈號對應 INVENTORY 中一篇，提供情境提醒，不直接建立進出場訊號。

### 燈號清單

| 燈號 ID | 對應篇章 | Severity |
|---|---|---|
| `pressure_meeting_unresolved` | §04 遇壓狀態 | warn |
| `weak_bull_trendline_only` | §05 微弱多方趨勢 | info |
| `selling_pressure_dissolution_required` | §07 賣壓化解 | info |
| `pressure_layer_no_support` | §08 壓力的分類 | warn |
| `lowprice_first_pull_exit` | §09 低價股的處理節奏 | warn |
| `just_high_upper_shadow` | §10 剛創新高上影線高點 | info |
| `high_black_k_warning` | §11 當黑 K 出現的時候 | warn |
| `limit_up_next_day_stats` | §12 漲停板後再漲機率 | info |
| `gap_down_falling_three` | §14 出現向下跳空的下降三法 | warn |
| `high_pushup_next_step` | §15 面對高檔推升型態下一步 | info |
| `sunrise_vs_rising_three_boundary` | §16 日出攻擊結束與上升三法判斷矛盾 | info |
| `top_formation_three_criteria` | §17 頭部成型 | **critical** |
| `mountain_descent_four_types` | §19 下山 | warn |
| `bottom_break_struggle` | §22 破底股糾結 | warn |
| `pessimistic_stock_structural` | §27 明日股價不樂觀的個股 K 線 | warn |
| `manipulator_distribution_warning` | §31 主力出貨的秘密 | **critical** |
| `leading_env_reverse` | §35 領先環境出現趨勢反向 | warn |
| `lack_of_power_distinction` | §37 缺乏力量的判斷 | info |
| `new_high_next_day_attack_required` | §03 D 部分 再創新高的隔天 | info |
| `zhongshu_recency_bias` | §02 D 部分 中樞型態 | info |

### Severity 分布

- `critical` (2)：`top_formation_three_criteria`、`manipulator_distribution_warning`
- `warn` (9)：各類遇壓 / 轉弱 / 主力出貨訊號
- `info` (9)：一般情境觀察提示

---

## 未建燈號的純哲學篇章

以下三篇屬「純哲學 / 純心法」，在 INVENTORY 中明確排除實作，不建燈號：

| 篇章 | 排除原因 |
|---|---|
| §01 明日 K 線意義（沙盤推演）| 這是整個子課程的「定位原則」，不是可觸發的條件 |
| §42 人性的弱點 | 純心法，無可量化的 K 線條件 |
| §44 進場 vs 出場非對稱 | 已由 DEFINITIONS §2.12 完整文件化；不是燈號而是框架原則 |

---

## Lights YAML Schema

```yaml
light_id: <唯一 ID>
trigger_condition:
  all:                       # 或 any / not / 扁平 dict
    - "today.close": "< prev_high_60"
    - "context.ma60_will_rise": false
severity: warn               # info | warn | critical
course_citation:
  source: "明日 K 線 §XX YY"  # ≥ 5 字元
  article_id: "<PressPlay hex id>"   # 選填
  quote: "老師原話"                   # 選填
recommendation_text: "給人讀的提醒文字"
```

### DSL 欄位白名單（`condition.py` 強制）

| 命名空間 | 允許欄位 |
|---|---|
| `today.*` | `open, high, low, close, volume` |
| `prev.*` | `open, high, low, close` |
| `next_day.*` | `open, high, low, close, gap_up, gap_down, fills_gap` |
| `context.*` | `ma5/10/20/60_will_rise, taiex_record_drop_point, taiex_record_drop_pct, taiex_record_limit_down_count, taiex_record_any_criterion, taiex_no_new_low_next_day` |
| 頂層 | `prev_high_60, prior_low_60, attack_cost, attack_intent_zone_high, attack_intent_zone_low, defensive_low, merged_high, merged_low` |

**RHS 禁止運算式**（如 `prev_high_60 * 0.98`）——只接受數字常數或白名單欄位名稱。

---

## 使用方式

```python
from pathlib import Path
from scripts.kline.scenarios.advisor import analyze

result = analyze(
    bars_df=df,
    today_date="2026-06-03",
    ticker="2330",
    context_overrides={"ma60_will_rise": False},
)

for light in result.active_lights:
    print(f"[{light.severity.upper()}] {light.light_id}: {light.recommendation_text}")
```

`active_lights` 按 critical → warn → info 排序輸出。

---

## 相關文件

- `docs/kline_course/mingri_kline/INVENTORY.md` — D 類 23 篇完整分類
- `docs/kline_course/mingri_kline/DEFINITIONS.md` — 觀念定義
- `docs/superpowers/plans/2026-06-03-playbook-layer-phase1-plan.md` — 整體計畫
- `docs/superpowers/specs/2026-06-03-playbook-layer-design.md` — 燈號設計規格
