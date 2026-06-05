# k-bar-power — LLM Integration Reference

**Mission:** K 線力量課程實作 + 應變劇本層 (playbook layer)

> 本檔針對其他 repo 的 AI agent 或開發者，讓你在不 scan 整個 worktree 的情況下
> 快速理解模組、API、資料格式、與課程合規約束。

**Pipeline 總覽**

```
bars_df (OHLCV)
  → features.add_features()         # 衍生欄位（含扣抵 / attack_cost / defensive_low / merged_doji 等）
  → patterns/<slug>.detect()        # 27 個多空轉折型態 + intro 概念 (bool Series)
  → entry / exit / scoring          # 進出場偵測 + 評分
  → scenarios.advisor.analyze()     # 劇本層 (playbook layer) — 27 lights + 30 playbooks
  → scenarios.formatter             # ASCII + emoji 色碼輸出
  → AdvisorResult                   # fired_patterns / scenarios / active_lights / notes / manual_hints
```

**新整合（2026-06-05 / -06）：**
- `scripts/run_advisor.py` CLI、輸出 ASCII 色碼摘要（距 MA% / 扣抵 emoji / branch 條件人讀化）
- 27 lights + 30 playbooks（含 4 intro 新概念、4 lt_* advanced 已 wired）
- Manual-judgment hints：`defensive_stance`、`record_decline_rebound`（課程明示「交易藝術」、不寫 detect）
- `simulate_advisor_history` + `compute_branch_hit_rates` Phase 4.3 backtest infrastructure（v4: 127k branches、0 NULL、30.5% avg hit rate）
- `load_bars(tickers=...)` + mtime cache（CLI 30s → 5s warm）
- 課程資料：入門 58 + 行進ing 41 + 型態學 20 + 轉折 35 + 明日 K 線 51 = 205 篇全齊

---

## 1. 課程合規核心限制 (CLAUDE.md — 必看)

| 規則 | 說明 |
|---|---|
| 禁止自創指標 | 所有進出場條件只能用課程明確教過的邏輯 |
| 目錄物理隔離 | `scripts/kline/{entry,exit,scoring}/` = 課程內；`extras/` = 課程外 default OFF |
| 工程數字集中 | 所有量化門檻只能在 `scripts/kline/course_proxy_constants.py` 裡定義 |
| STUB 標記 | 待 user 拍板的數字標 `[STUB-NEED-USER Sn]`；不可靜默代入 |
| 禁止補完課程未說明的部分 | 若問到課程未涵蓋的細節，回答「課程沒有明確說明」 |

**`partial_exit` 特例：** ActionType 包含 `partial_exit`，但 `Action.description` 必須
引用老師原話中明示的比例（例：「先賣一半」/ 「三分之一先出」）。未引用原話則違規。

**extras 啟用方式：** 使用 `--extras name[=arg],name[=arg]` CLI 旗標。
未加 `--extras` 時所有課程外邏輯不執行。

---

## 2. 目錄結構快覽

```
scripts/
  run_advisor.py              # CLI: uv run python scripts/run_advisor.py <ticker> <date>
scripts/kline/
  bars.py                     # load_bars() — OHLCV 載入（含 tickers filter + mtime cache）
  features.py                 # add_features() — 衍生欄位
  course_proxy_constants.py   # 全部量化門檻的唯一來源
  patterns/
    __init__.py               # PATTERN_REGISTRY (27 slugs — +attack_cost_displayed +self_rescue_breakout)
    _common.py                # 共用 helpers
    <slug>.py                 # 各型態 detect(df) -> pd.Series[bool]
  entry/
    __init__.py               # ENTRY_REGISTRY (8 entries)
    <name>.py
  exit/
    __init__.py               # EXIT_REGISTRY (10+ exits)
    simulator.py              # simulate(df, entries, ...) -> trades_df
    groups.py                 # get_exit_priority(entry_name)
    reversal_k/               # 6 個 reversal K exit modules
  scoring/
    __init__.py               # SCORING_REGISTRY (7 factors)
    <factor>.py
  scenarios/
    _schema.py                # Pydantic 定義 (Playbook/Branch/Light/AdvisorResult)
    advisor.py                # analyze() 主入口
    formatter.py              # ASCII + emoji 色碼輸出（commit 08b445f）
    manual_hints.py           # defensive_stance / record_decline_rebound（commit 3346bc5）
    condition.py              # mini-DSL evaluate() / evaluate_vectorized()
    context.py                # build_context_snapshot()
    loader.py                 # load_playbooks() / load_lights()
    persistence.py            # save() / load_runs() / update_branch_outcome()
    simulator.py              # simulate_advisor_history / compute_branch_hit_rates
    playbooks/                # 30 個 *.yaml playbook 檔
    lights/                   # 27 個 *.yaml light 檔
  minute_bars.py              # get_minute_bars(ticker, date) helper（commit 245edbe）
  extras/
    __init__.py               # 3 個 registries + parse_extras_spec()
    shakeout_strong.py
    inst_direction_score.py
    ...
```

---

## 3. Data Layer

### 3.1 `kline.bars.load_bars`

```python
from scripts.kline.bars import load_bars
from pathlib import Path

df = load_bars()                              # 全市場、預設 DB
df = load_bars(tickers=["2330"])              # 單 ticker filter（CLI 用、快 ~6x）
df = load_bars(fill_from_backfill=False)      # 不 union backfill
```

**簽名：**
```python
def load_bars(
    db_path: Path = DEFAULT_DB_PATH,        # /Users/howard/.four_seasons/data.sqlite
    fill_from_backfill: bool = True,        # 自動 union pre-2022 backfill DB
    tickers: list[str] | None = None,       # SQL filter（advisor CLI 用）
) -> pd.DataFrame
```

**效能 — mtime cache（2026-06-05、commit `3b42e09`）：**
- 共用快取路徑：`/tmp/kline_bars_snapshot.sqlite`（非 per-pid，避免重複 copy）
- 每次 `load_bars` 比對 source mtime；source 未變且 cache size ≥ 50% → 直接重用
- Stale / size 不對 → mkstemp 寫入 staging + atomic `os.replace()`（race-safe）
- CLI 重跑：~30s cold → ~5s warm
- 額外 `tickers=` 參數：SQL placeholder 過濾、避免 2.1M rows × pandas overhead

**輸出 schema：**

| 欄位 | 型別 | 說明 |
|---|---|---|
| ticker | str | 股票代號 |
| trade_date | datetime64[ns] | 交易日 |
| open / high / low / close | float64 | OHLC |
| volume | float64 | 成交量 |
| ma20, ma60, ma240 | float64, 可 NaN | 移動平均線 |
| vol_ma20, vol_ratio_20 | float64 | 均量、量比 |
| is_attention_stock, is_disposition_stock | int | 注意/處置股旗標 |
| is_usable | int | 1 = 可用（query 已 filter） |

**重要注意：**
- DB 以 `is_usable=1` 過濾，OHLCV 必須非 null 且 > 0
- 自動複製 DB 到 `/tmp/kline_bars_snapshot_{pid}.sqlite` 避免 iCloud I/O 問題
- 操作結束後 `finally: tmp.unlink()` 清除暫存（舊版 bug 曾留 91 個副本共 91 GB）
- `trade_date` 統一為 `datetime64[ns]`（pandas 3.x 預設 us，強制轉 ns）

### 3.2 `kline.features.add_features`

```python
from scripts.kline.features import add_features

enriched = add_features(df)   # 純函式，回傳新 DataFrame，不修改輸入
```

**簽名：**
```python
def add_features(df: pd.DataFrame) -> pd.DataFrame
```

**新增的衍生欄位（主要）：**

| 欄位 | 說明 |
|---|---|
| prev_close / prev_open / prev_high / prev_low | 前日 OHLC |
| prior_high_60 / prior_high_20 | shift(1) 後 rolling max（60/20 日） |
| prior_low_60 / prior_low_20 | shift(1) 後 rolling min |
| avg_volume_20, volume_ratio | 20 日均量（排除今日）、量比 |
| range_pct, body_pct, body_abs | K 棒範圍 / 實體比例 |
| upper_shadow, lower_shadow, upper_shadow_ratio, lower_shadow_ratio | 上下影線 |
| close_pos | 收盤在 (high-low) 的位置比 |
| is_red, is_black, is_doji | 顏色旗標、十字線（body_pct ≤ 0.6% AND range_pct ≥ 1.5%） |
| ma60_slope_5d | MA60 五日斜率 |
| ma60_rolling_off_close | 60 日前收盤（扣抵預測用） |
| pre_breakout_trend_days | **過去 20 日內**收盤高於 MA60 的**天數總和** (rolling sum，非連續) |
| overhead_supply_layer | 過去 240 日 swing-high peak 數（高於今日收盤） |
| unfilled_gap_down_count_240d | 過去 240 日未回補向下跳空缺口數 |
| is_in_breakdown_pattern | 破底型態旗標（60 日 ≥2 次新低 AND MA60 下滑） |
| is_pattern_breakout | 5 條件 AND：低點墊高 + 上緣穩定 + 上方無套牢 + 突破前高 + MA60 多頭 |
| attack_intensity | 攻擊強度 0-4（0=無、1=波動前進、2=推升、3=跳空、4=日出） |
| prev_bar_had_attack_meaning | 前日是否有攻擊意義 |
| is_first_breakout_above_level | 是否為 60 日窗內第一次突破 |
| is_attack_bar | 攻擊確認棒（紅K續攻 / 跳空 / 創新高，三選一） |
| is_sunset_bar | 日落棒（high < prev_high AND low < prev_low） |
| is_harami | 孕線（今日高低完全在前日內） |
| midpoint | K 棒中值 (open+close)/2 |
| is_gap_up_today / is_gap_down_today | 嚴格跳空定義 |
| attack_intent_zone_high / attack_intent_zone_low | 攻擊意圖區上/下緣 |
| intent_zone_break | 今日收盤跌回攻擊意圖區 |
| is_just_broke_high | 剛創 60 日新高（今日或前 1~2 日） |
| is_limit_up_locked | 漲停鎖住（無上影線 + 全天不破昨收） |
| is_anomalous_volume | 異常放量 [STUB-NEED-USER S1] |
| is_just_broke_high_intraday | 盤中觸及新高（即使收盤收回）— 入門新概念 |
| at_pressure_retest | 觸及前高壓力但未過 — §08 壓力相遇 |
| merged_high / merged_low | 合併十字線上下緣（forward-fill **1 日**，commit `b87537e` 從 5 → 1） |
| attack_cost | 攻擊成本價（§20、state-machine forward-fill **60 日**）— 漲停鎖住 + 突破創新高觸發 |
| defensive_low | 防守低點（§26、6 日 rolling、單純 K 棒最低） |
| ma5_kou / ma10_kou / ma20_kou / ma60_kou | N 日前收盤（扣抵值原理） |
| ma5_will_rise / ma10_will_rise / ma20_will_rise / ma60_will_rise | 明日 MA 是否上揚（close > ma_kou） |
| low_price_flag | 低價股旗標（close < `LOW_PRICE_THRESHOLD` 預設 30、入門§09） |
| same_level_red_count_5d | 同價位反覆紅 K 次數（入門新概念） |
| taiex_down_today | 大盤跌日（外部 taiex DB 注入）— `taiex_down_stock_new_high` light |
| is_after_negative_news_taiex | 利空大跌後（self_rescue_breakout 用） |

**新衍生欄位（2026-06-05/-06）課程出處：**
- `attack_cost` — 轉折§20「攻擊成本」+ `attack_cost_state_machine_v1.md` state-machine 設計
- `defensive_low` — 明日 K 線§26「防守姿態」+ `defensive_low_break` light
- `merged_high/low` — 明日 K 線§24「合併十字線」+ commit `296504d` forward-fill UX 標示
- `ma*_kou / ma*_will_rise` — 入門「扣抵值原理」（兩課程明示）
- `at_pressure_retest` — 明日 K 線§08「壓力相遇」未化解
- `is_just_broke_high_intraday` — 入門 § `just_high_doji_attack` light（盤中創新高但收回）
- `same_level_red_count_5d` — 入門 § `same_level_red_then_black` light
- `taiex_down_today` — 入門 §「大盤跌個股創新高」相對強勢

**Cross-ticker rolling bug 已修正：**
所有「排除今日的 rolling」一律用 `.transform(lambda s: s.shift(1).rolling(N).max())` 
而非 `g["col"].shift(1).rolling(N)`（後者跨 ticker 邊界計算，為已知 bug）。

---

## 4. Pattern Detection (27 個型態)

### 4.1 通用 API

每個 pattern module 提供：
```python
def detect(df: pd.DataFrame) -> pd.Series  # bool, aligned with df.index
```

- 純函式 (pure function)，DataFrame in/out，無 side effect
- 觸發點 = pattern 完成的那根 K（True 那天可作為 entry/exit timing）
- 全部 27 個 detect 函式統一在 `PATTERN_REGISTRY`（加入 `attack_cost_displayed` 與 `self_rescue_breakout`）

```python
from scripts.kline.patterns import PATTERN_REGISTRY

# 批次跑所有 pattern
for name, detect_fn in PATTERN_REGISTRY.items():
    fired: pd.Series = detect_fn(enriched_df)   # enriched_df 需先 add_features
```

### 4.2 全部 27 個 slug

| slug | 說明 |
|---|---|
| `bear_engulfing` | 空頭吞噬（P02）大黑 K 包覆前日紅 K，多方力竭背景 |
| `bull_engulfing` | 多頭吞噬（P03）大紅 K 包覆前日黑 K，空方力竭背景 |
| `morning_star_harami` | 早晨之星（P04/P06）孕線＋紅 K 突破，空方力竭背景 |
| `high_hanging_man` | 高檔吊人（P05）長下影線 + 日落棒，多方力竭背景 |
| `three_red_dadi_dangqian` | 大敵當前（P07）三紅拉不開距離，多方力竭背景 |
| `dark_double_star_anye` | 暗夜雙星（P08）兩根並排相似 K 線，多方力竭背景 |
| `gap_under_pressure_reversal` | 壓力下跳空（P08b）向下跳空後反轉，空方力竭背景 |
| `gap_reversal` | 缺口反轉（P09）跳空後當日拉回反轉 |
| `two_crow_gap` | 兩烏鴉跳空（P10）跳空後連兩黑，多方力竭背景 |
| `breakout_double_star` | 突破雙星（P11）突破前高 + 並排雙星，攻擊強度 ≥ 2 |
| `evening_star_abandoned` | 棄嬰晚星（P12）跳空後十字 + 黑 K，多方力竭背景 |
| `evening_star_island_reversal` | 晚星島狀反轉（P13）雙側跳空島形，多方力竭背景 |
| `morning_star_island_reversal` | 早晨島狀反轉（P14）雙側跳空島形，空方力竭背景 |
| `merged_doji` | 合併十字（P— / 明日 K 線）當日或合併後形成十字 |
| `outside_three_black` | 三外黑 K（P15）大黑 K 三連，包覆前段紅 K |
| `outside_three_black_like` | 三外黑 K 變形（P15 alike）寬鬆版門檻 |
| `piercing_line` | 刺穿線（P20）前黑後紅，紅 K 中點超過前黑中點，空方力竭背景 |
| `neutral_engulfing` | 中性吞噬（P19）紅 K 回包黑 K，無趨勢偏向 |
| `embracing` | 懷抱型態（P21）大 K 線包覆小 K 線孕線 |
| `meeting` | 遭遇型態（P22）收盤相近但方向相反 |
| `rebound` | 反撲型態（P23）前期高/低後出現逆向量能 K |
| `trapped` | 套牢型態（P24）狹幅整理後跌破，空方力竭背景 |
| `biting` | 咬定型態（P25）多日狹幅 + 今日力量棒突破 |
| `rising_falling` | 升降型態（P26）整理後向上/向下突破 |
| `gap_fill_up` | 向上缺口回補（P27）向上跳空被回補 |
| `gap_fill_down` | 向下缺口回補（P27）向下跳空被回補 |
| `attack_cost_displayed` | 攻擊成本顯現（§20）— 漲停鎖住 + 突破創新高、state-machine 標記攻擊成本價、forward-fill 60 日（commit `245edbe`） |
| `self_rescue_breakout` | 自救型突破（入門 §34）— 利空大跌後量縮回升、突破前高、commit `1a20d8e` |

**課程注意：** 轉折組合是「多單出場」/「空單回補」訊號，**非反向進場訊號**。
失效條件（如隔日創新高使空頭吞噬失效）由上層 simulator / advisor 判斷，不在 detect 內。

### 4.3 共用 Helpers (`scripts/kline/patterns/_common.py`)

```python
from scripts.kline.patterns._common import (
    is_power_bar,
    is_narrow_consolidation,
    in_trend,
    is_similar_bars,
    bull_exhaustion_context,
    bear_exhaustion_context,
)

# 力量型 K 線
is_power_bar(df, direction="bull", body_pct_min=0.03)  # -> pd.Series[bool]
# direction: 'bull' / 'bear' / 'either'

# 狹幅整理（回傳 DataFrame 含多個欄位）
result = is_narrow_consolidation(df, n_bars=3, max_range_pct=0.03, use_close=True)
# result.columns: narrow (bool), past_close_max, past_close_min, past_high_max, past_low_min

# 略顯趨勢背景
in_trend(df, direction="bull", method="close_vs_ma20", threshold=0.005)  # -> pd.Series[bool]
# method: 'close_vs_ma20' (推薦) / 'ma60_slope' (嚴格)

# 並排相似（暗夜雙星用）
is_similar_bars(df, lookback1=1, lookback2=2, tolerance_pct=0.035)  # -> pd.Series[bool]

# 多方力竭背景（3 條件 AND：攻擊強度 + 近期突破 + 高檔位置）
bull_exhaustion_context(df)  # -> pd.Series[bool]

# 空方力竭背景（3 條件 AND：破底型態 + 漫長崩跌 + 賣壓中空 ≥ 30% 跌幅）
bear_exhaustion_context(df)  # -> pd.Series[bool]
```

---

## 5. Entry / Exit / Scoring

### 5.1 Entry

```python
from scripts.kline.entry import ENTRY_REGISTRY

# 8 個 entry detect 函式，全部 detect(df) -> pd.Series[bool]
ENTRY_REGISTRY = {
    "breakout_attack": ...,          # 突破攻擊（第一次或確認後）
    "pattern_breakout_only": ...,    # 純型態突破（無攻擊強度要求）
    "tweezer_top_breakout": ...,     # 鑷形頂突破
    "tweezer_top_breakout_strict": ...,  # 鑷形頂突破（嚴格版）
    "shoulder_gap_up_pullback": ..., # 墊肩跳空回測
    "trend_reversal": ...,           # 趨勢反轉
    "sunrise_attack": ...,           # 日出攻擊
    "combined_pattern_or_tweezer": ...,  # 複合型態 OR 鑷形
}
```

### 5.2 Exit

```python
from scripts.kline.exit import EXIT_REGISTRY
from scripts.kline.exit.simulator import simulate

# EXIT_REGISTRY: mark(df, entries) -> pd.Series[bool]
EXIT_REGISTRY = {
    "breakout_price_break": ...,     # 收盤跌破突破價（突破後 2 日窗內）
    "breakout_low_break": ...,       # 收盤跌破突破 K 最低點
    "trailing_stop": ...,            # 追蹤停損
    "trend_change": ...,             # 趨勢特徵消失（低點不再墊高）
    "prev_day_low_break": ...,       # 收盤跌破前日低點（攻擊意義前提）
    "gap_attack_filled": ...,        # 跳空缺口被回補（攻擊失敗）
    "sunrise_attack_end": ...,       # 日出攻擊結束
    "high_long_black": ...,          # 高檔長黑 K（body ≥ 4%）
    "supply_zone_reach": ...,        # 到達供給區（賣壓回補）
    "ma60_neckline": ...,            # MA60 頸線跌破
    "reversal_k.bearish_engulfing": ...,  # 空頭吞噬 exit
    "reversal_k.dark_double_star": ...,
    "reversal_k.enemy_at_gate": ...,
    "reversal_k.evening_star": ...,
    "reversal_k.gap_reversal": ...,
    "reversal_k.two_crows": ...,
}

# 模擬出場
trades_df = simulate(
    df=enriched_df,
    entries=entry_series,    # pd.Series[bool] aligned with df
    entry_name="breakout_attack",   # 決定課程對應的 exit priority
    # exit_priority=[...]           # 或手動指定
)
```

**禁止事項：** simulator 禁止計算 EV / PnL / `ret_Nd`（必須走課程 exit 模擬）。

### 5.3 Scoring

```python
from scripts.kline.scoring import SCORING_REGISTRY

# 7 個 score(df) -> pd.Series[float]
SCORING_REGISTRY = {
    "overhead_supply": ...,                  # 套牢層數懲罰（-5 / -15）
    "ma60_rolloff": ...,                     # MA60 扣抵分數
    "shadow_position": ...,                  # 影線位置分數
    "pattern_breakout": ...,                 # 型態突破加分
    "attack_intensity": ...,                 # 攻擊強度加分
    "high_zone_narrow_consolidation": ...,   # 高檔狹幅醞釀加分（+8）
    "trend_continuation": ...,              # 趨勢延續加分（+25，閾值 17 天）
}
```

---

## 6. Extras（課程外，預設 OFF）

```python
from scripts.kline.extras import (
    ENTRY_FILTER_REGISTRY,   # intensity_floor / strict_breakout
    EXIT_REGISTRY,           # hold_days_cap / gap_fill_excess_market_adjusted /
                             # neckline_break_crude_proxy / consolidation_breakdown
    SCORING_REGISTRY,        # attack_quality_anti_course_penalties / inst_direction_score
    ENTRY_STRATEGY_REGISTRY, # shakeout_strong (完整策略，非 filter)
    resolve_extras,
    parse_extras_spec,
)

# 從 CLI spec 解析
extras = resolve_extras("intensity_floor=2,hold_days_cap=20")
# -> {"entry_filters": [...], "exits": [...], "scoring": [...]}
```

| extras 名稱 | 類型 | 說明 |
|---|---|---|
| `intensity_floor` | entry filter | 要求 attack_intensity ≥ N |
| `strict_breakout` | entry filter | 嚴格突破條件 |
| `hold_days_cap` | exit | 限制最大持倉天數 |
| `gap_fill_excess_market_adjusted` | exit | 市場調整後缺口過度回補 |
| `neckline_break_crude_proxy` | exit | 粗略頸線跌破 |
| `consolidation_breakdown` | exit | 整理型態跌破 |
| `attack_quality_anti_course_penalties` | scoring | 量比 / body / 收盤位置三項懲罰 |
| `inst_direction_score` | scoring | 法人方向分數（tiebreaker） |
| `shakeout_strong` | entry strategy | Shakeout Strong 完整策略（user-defined） |
| `bear_single_day_reversal` | pattern (extras) | 空方單日反轉 — 課程明示「最微弱」(P16) |
| `bull_single_day_reversal` | pattern (extras) | 多方單日反轉 — 課程明示「最微弱」(P17) |
| `scenarios/playbooks/bullish_reversal_long_bear.yaml` | playbook (extras) | B08 — 多方逆轉長空頭 (需基本面、user override) |

**註：** `LOW_PRICE` 已搬回 `course_proxy_constants.py`（`LOW_PRICE_THRESHOLD = 30.0` [STUB-NEED-USER]），不再是 extra（commit `1a20d8e`）。

---

## 7. Scenario Advisor — Playbook Layer 主入口

```python
from scripts.kline.bars import load_bars
from scripts.kline.scenarios.advisor import analyze
from scripts.kline.scenarios.formatter import format_advisor_result

bars = load_bars(tickers=["1605"])      # CLI 模式：mtime cache + ticker filter
result = analyze(bars, today_date="2026-06-03", ticker="1605")
print(format_advisor_result(result, ticker="1605", today_date="2026-06-03", bars=bars))
```

**`analyze` 簽名：**
```python
def analyze(
    bars_df: pd.DataFrame,
    today_date: str,                          # "YYYY-MM-DD"
    ticker: str,
    context_overrides: dict | None = None,    # K線力量 fields override
    playbook_dirs: list[Path] | None = None,
    light_dirs: list[Path] | None = None,
) -> AdvisorResult
```

**Sentinel 偵測：** `bars_df` 含 `prev_close` 欄 → 已 enriched、不重跑 `add_features`。
**效能：** 單 ticker × 單日 < 200 ms（不含 add_features）。
**Fail-loud：** 缺欄位 → `warn_notes` + `field=None`、絕不靜默補值。

**AdvisorResult 欄位：**
- `fired_patterns: list[PatternHit]` — `PatternHit` 是 `@dataclass(slots=True)`、無 `.model_dump()`、用 `dataclasses.asdict()`
- `scenarios: list[Scenario]` — `pattern_hit + playbook_name + enabled_branches`
- `active_lights: list[Light]` — sorted critical → warn → info
- `notes: list[str]` — WARN + D-class 觀念
- `context_snapshot: Optional[ContextSnapshot]`

---

## 8. Lights System — 27 個 lights

Lights 是「橫向觀念警示」（與 pattern 無關、依 context 觸發、附課程引用），存 `scripts/kline/scenarios/lights/*.yaml`、由 `loader.load_lights()` 載入。

### 8.1 Light Fire Rates（Phase 4.3 v4 — `phase4_report.md`、115,182 ticker-days）

| light_id | severity | n_fires | fire_rate |
|---|---|---|---|
| `zhongshu_recency_bias` | info | 27,369 | 23.8% |
| `lt_attack_intent_zone_breakdown` | warn | 10,741 | 9.3% |
| `lt_attack_cost_breakdown` | critical | 8,952 | **7.8%** |
| `gap_down_falling_three` | warn | 5,762 | 5.0% |
| `new_high_next_day_attack_required` | info | 5,051 | 4.4% |
| `just_high_upper_shadow` | info | 4,699 | 4.1% |
| `pressure_layer_no_support` | warn | 3,974 | **3.5%**（v3 38.9% → v4 fix） |
| `pressure_meeting_unresolved` | warn | 3,974 | 3.5% |
| `pessimistic_stock_structural` | warn | 3,060 | 2.7% |
| `mountain_descent_four_types` | warn | 2,960 | 2.6% |
| `top_formation_three_criteria` | critical | 2,901 | 2.5% |
| `lt_defensive_low_break` | critical | 2,347 | 2.0% |
| `limit_up_next_day_stats` | info | 1,136 | 1.0% |
| `sunrise_vs_rising_three_boundary` | info | 784 | 0.7% |
| `manipulator_distribution_warning` | warn | 696 | 0.6% |
| `weak_bull_trendline_only` | info | 476 | 0.4% |
| `lowprice_first_pull_exit` | warn | 426 | 0.4% |
| `high_black_k_warning` | warn | 274 | 0.2% |
| `lack_of_power_distinction` | info | 148 | 0.1% |
| `lt_merged_doji_low_break` | warn | 87 | **0.1%**（v3 0.6% → v4 carry 5→1 fix） |
| `lt_merged_doji_high_break` | info | 82 | **0.1%**（v3 0.5% → v4 carry 5→1 fix） |
| `selling_pressure_dissolution_required` | info | 57 | 0.0% |

**未列出 5 lights**（無 phase4_report 數據 — v4 後新增 / 無 fires）：
- `bottom_break_struggle`
- `high_pushup_next_step`
- `just_high_doji_attack` — 入門新概念（commit `1a20d8e`）
- `same_level_red_then_black` — 入門新概念（commit `1a20d8e`）
- `taiex_down_stock_new_high` — 入門新概念（commit `1a20d8e`）

### 8.2 4 個 `lt_*` advanced lights（已 wired，commit `c937c03`）

| light_id | 依賴 feature | Forward-fill 窗口 |
|---|---|---|
| `lt_attack_cost_breakdown` | `attack_cost` | 60 日 state-machine |
| `lt_attack_intent_zone_breakdown` | `attack_intent_zone_high/low` | 1 日（最新值）|
| `lt_defensive_low_break` | `defensive_low` | 6 日 rolling |
| `lt_merged_doji_high_break` / `lt_merged_doji_low_break` | `merged_high` / `merged_low` | **1 日**（commit `b87537e` 從 5 → 1）|

Formatter 對這 4 個自動加 forward-fill UX 標示（`_FORWARD_FILL_NOTES`、commit `296504d`）。

### 8.3 Light schema

```yaml
light_id: pressure_layer_no_support
severity: warn   # critical / warn / info
trigger_condition:                      # 同 Branch.when 的 mini-DSL
  all:
    - today.high: ">= prev_high_60"
    - today.close: "< prev_high_60"
course_citation:
  source: "明日 K 線 §08 壓力相遇"
  quote: "..."
recommendation_text: "建議..."
```

---

## 9. Playbooks — 30 個應變劇本

存 `scripts/kline/scenarios/playbooks/*.yaml`、每個 playbook 綁一個 PATTERN_REGISTRY pattern、含 1+ branches。

### 9.1 全部 30 個 playbooks

`attack_cost_displayed` / `bear_engulfing` / `biting` / `breakout_double_star` / `bull_engulfing` / `dark_double_star_anye` / `defensive_stance` / `embracing` / `evening_star_abandoned` / `evening_star_island_reversal` / `gap_fill_down` / `gap_fill_up` / `gap_reversal` / `gap_under_pressure_reversal` / `high_hanging_man` / `meeting` / `merged_doji_attack` / `morning_star_harami` / `morning_star_island_reversal` / `neutral_engulfing` / `no_attack_after_breakout` / `outside_three_black` / `piercing_line` / `rebound` / `record_decline_rebound` / `rising_falling` / `self_rescue_breakout` / `three_red_dadi_dangqian` / `trapped` / `two_crow_gap`

### 9.2 高命中 branches Top 3（Phase 4.3 v4、`phase4_report.md`）

| pattern | branch_id | n_runs | hit_rate |
|---|---|---|---|
| `morning_star_island_reversal` | `B2_next_day_gap_filled` | 288 | **88.5%** |
| `gap_under_pressure_reversal` | `B1_next_day_gap_fills_up` | 3,997 | **82.0%** |
| `gap_reversal` | `B2_next_day_gap_filled` | 2,512 | **81.7%** |

中信心 branches（50–80%、9 個）：`attack_cost_displayed.B3_gap_attack` 78.2% / `breakout_double_star.B1_gap_up_holds` 66.7% / `morning_star_island.B3_overhead_supply` 66.0% / `attack_cost_displayed.B4_push_attack` 57.0% / `merged_doji.B1_gap_up_attack` 53.5% / `morning_star_harami.B1_gap_up_attack` 51.9% / `merged_doji.B4_consolidation_wait` 51.8% / `piercing_line.B3_stalls` 51.1% / `bear_engulfing.B3_consolidation` 51.1%。

完整表：`data/analysis/kline_patterns/phase4_branch_hit_rates.csv`（69 pairs ≥ 10 runs）。

### 9.3 Branch action_type 色碼

| ActionType | Emoji |
|---|---|
| `entry_signal` | 🟢 |
| `watch_only` / `context_only_signal` | 🟡 |
| `exhaust_invalid` | ⚪ （**事後標籤、非進場訊號**）|
| `stop_loss_trigger` / `partial_exit` / `exit_signal` | 🔴 |

`partial_exit` 仍受課程紀律約束：`Action.description` 必須引用老師原話比例。

---

## 10. Manual-judgment Hints

存 `scripts/kline/scenarios/manual_hints.py`。課程明示「交易藝術」的情境**不寫 detect**、改回傳 hint dict 讓 user 自行判斷：

| Hint | 觸發 | 課程出處 |
|---|---|---|
| `check_defensive_stance_hint` | `taiex_recent_weak AND defensive_low != None`（**AND**、2026-06-05 收緊、原本 OR 觸發過頻）| 明日 K 線 §26「防守姿態」`EF7308E2336BF7BCE94142944DB580B1` |
| `check_record_decline_rebound_hint` | 加權跌點/跌幅/跌停家數任一創歷史新高（context.taiex_record_*）| 明日 K 線 §30「創紀錄的跌點之後」`77DC434EC71DB04553752A44C9354680` |

Hint 回傳 schema：
```python
{
    "name": "defensive_stance",
    "course_source": "明日 K 線 §26",
    "trigger_reason": "...",
    "manual_checks": ["...", "..."],     # user 自行判斷項目
    "course_quotes": ["..."],            # 逐字引用
}
```

---

## 11. Formatter + CLI

### 11.1 `scripts/run_advisor.py`

```bash
uv run python scripts/run_advisor.py 1605 2026-06-03
uv run python scripts/run_advisor.py 6285 2026-06-03 --raw   # raw JSON
```

**輸出包含：**
- 🟢🟡🔴⚪⚫ ActionType emoji（見 §9.3）
- 🔴🟡⚪ Severity emoji（critical/warn/info）
- MA5/10/20/60 扣抵狀態（🟢 will rise / 🔴 will fall / 🟡 borderline diff < 1% / — None）
- 距 MA% — 今日 close 距 ma5/10/20/60 的百分比
- Branch when-condition 人讀化（`_humanize_when`）
- Forward-fill UX 標示（`lt_merged_doji_*` / `lt_attack_cost_*` / `lt_defensive_*`）
- Manual-judgment hints（如觸發）
- Citation 逐字「老師原話」段落

### 11.2 `scripts/kline/scenarios/formatter.py`

```python
from scripts.kline.scenarios.formatter import format_advisor_result

text = format_advisor_result(result, ticker="2330", today_date="2026-06-03", bars=bars)
```

純 presentation 層、不改 advisor 邏輯或 schema。

---

## 12. Phase 4.3 Backtest Infrastructure

存 `scripts/kline/scenarios/simulator.py`。

### 12.1 主入口

```python
from scripts.kline.scenarios.simulator import simulate_advisor_history, compute_branch_hit_rates

simulate_advisor_history(
    tickers=["2330", ...],
    start_date="2024-01-01",
    end_date="2026-06-30",
    db_path=Path("data/analysis/kline_patterns/phase4_advisor_history.db"),
)

hit_rates_df = compute_branch_hit_rates(
    db_path=Path("data/analysis/kline_patterns/phase4_advisor_history.db"),
    min_runs=10,
)
```

### 12.2 Schema 改動（commit `62f21dd`）

`advisor_branches` table 新增 `pattern_name TEXT NOT NULL DEFAULT ''`。`save()` 從 `scenario.pattern_hit.pattern` 取值。`compute_branch_hit_rates` 改用 `COALESCE(NULLIF(pattern_name, ''), action_type, 'unknown')` 分組（向下相容舊 DB）。

### 12.3 Phase 4.3 v4 統計（`phase4_report.md`、commit `a7380cc`）

| 指標 | 數值 |
|---|---|
| Tickers | 200 |
| Date range | 2024-01-01 → 2026-06-30 |
| Trading dates | 585 |
| Ticker-days | 115,182 |
| Advisor runs saved | 115,182 |
| Branches total | 127,513 |
| Branches NULL（未評估）| **0** |
| 平均 hit rate | 30.5% |
| (pattern × branch) pairs ≥10 runs | 69 |
| Elapsed | 97.0 min |

### 12.4 v3 → v4 4 個 STUB fix（commit `4c9ba79`）

| Fix | 影響 |
|---|---|
| 1. `merged_*` carry 5 → 1 日 | `lt_merged_doji_*` 0.5%~0.6% → 0.1% |
| 2. `attack_cost` lookback 20 → 60 日 | `lt_attack_cost_breakdown` 3.8% → 7.8% |
| 3. `pressure_layer` 二元觸及條件 | `pressure_layer_no_support` 38.9% → 3.5% |
| 4. 純檔案組織（無行為變動）| — |

### 12.5 `minute_bars.py` helper

`scripts/kline/minute_bars.py`（commit `245edbe`）— `get_minute_bars(ticker, date)` 從主 DB `minute_bars` table 讀分 K（先 copy 到 /tmp、避 iCloud 衝突）。`attack_cost_displayed` 偵測時可選用。

---
---

## 13. Scenarios — Internals (DSL / Loader / Context / Persistence)

主入口 API 見 §7。本章覆蓋 DSL、YAML loader、context snapshot 構建、persistence。

### 13.1 YAML Loader

```python
from scripts.kline.scenarios.loader import load_playbooks, load_lights, LoaderError

# dict[str, list[Playbook]]: pattern → playbooks
playbooks = load_playbooks([Path("scripts/kline/scenarios/playbooks")])

# dict[str, Light]: light_id → Light
lights = load_lights([Path("scripts/kline/scenarios/lights")])
# 重複 (pattern, setup.name) 或 light_id → ValueError (fail loud)
```

### 13.2 Condition DSL

```python
from scripts.kline.scenarios.condition import evaluate, evaluate_vectorized, UnknownTokenError

# Scalar — advisor 用
result = evaluate(
    when={"today.close": "> prev_high_60"},
    row=today_series,
    ctx=ctx_snapshot,
    next_day_n=1,
)
# 回傳: True / False / None（None = pending，next_day.* 明日值未知）

# Vectorized — backtest / simulator 用
bool_series = evaluate_vectorized(
    when={"all": [
        {"today.close": "> prev_high_60"},
        {"context.ma60_will_rise": True},
    ]},
    df=enriched_df,
    ctx_df=context_df,
    next_day_n=1,
)  # -> pd.Series[bool]
```

**DSL 允許的欄位命名空間：**

| namespace | 範例 |
|---|---|
| `today.*` | `today.open` / `today.high` / `today.low` / `today.close` / `today.volume` |
| `prev.*` | `prev.open` / `prev.high` / `prev.low` / `prev.close` |
| `next_day.*` | `next_day.open` / `next_day.high` / `next_day.gap_up` / `next_day.fills_gap` |
| `context.*` | `context.ma5/10/20/60_will_rise` / `context.taiex_record_any_criterion` |
| top-level | `prev_high_60` / `attack_cost` / `attack_intent_zone_high` / `defensive_low` |

**DSL 約束：**
- RHS 禁止算式（如 `volume * 1.5`）— 嚴格 reject UnknownTokenError
- 嵌套深度最多 2 層（`all` / `any` / `not`）
- `context.taiex_record_any_criterion == true` 這種布林比較直接用 `true` / `false`

```yaml
# YAML 範例：playbook branch when-condition
when:
  all:
    - today.close: "> prev_high_60"
    - context.ma60_will_rise: true
    - any:
        - next_day.gap_up: true
        - next_day.close: "> today.high"
```

### 13.3 Context Snapshot 建構

```python
from scripts.kline.scenarios.context import build_context_snapshot

snapshot, warn_notes = build_context_snapshot(
    bars_df=enriched_df,  # features-enriched df
    today_date="2026-06-03",
    ticker="2330",
    overrides={"ma5_will_rise": True},
)
# warn_notes 含每個 None 欄位的 "WARN:" 訊息 (fail-loud, 不靜默補值)
```

### 13.4 Persistence

```python
from scripts.kline.scenarios.persistence import save, load_runs, update_branch_outcome
from pathlib import Path

# 儲存一次 advisor 結果
run_id = save(result, ticker="2330", trade_date="2026-06-03")
run_id = save(result, ticker="2330", trade_date="2026-06-03",
              db_path=Path("data/advisor_history.db"))

# 查詢歷史
runs = load_runs("2330", start_date="2026-01-01", end_date="2026-06-30")
# -> list[dict] (run_id, ticker, trade_date, fired_pattern_count, scenario_count, created_at)

# Simulator 回填 branch 結果
update_branch_outcome(
    run_id=42,
    scenario_idx=0,
    branch_id="B1_明日續強",
    matched_after_n_days=2,
)
```

---

## 14. Pydantic Schema 速查

所有 schema 定義在 `scripts/kline/scenarios/_schema.py`。

### AdvisorResult
```python
class AdvisorResult(BaseModel):
    fired_patterns: list[PatternHit]   # pattern, fired_at, confidence
                                       # NOTE: PatternHit 是 @dataclass(slots=True)
                                       # **不是** Pydantic BaseModel，沒有 .model_dump()
                                       # 用 dataclasses.asdict(hit) 或直接 .pattern / .fired_at
    scenarios: list[Scenario]          # pattern_hit, playbook_name, enabled_branches
    active_lights: list[Light]         # sorted critical→warn→info
    notes: list[str]                   # WARN 訊息 + D-class 觀念提醒
    context_snapshot: Optional[ContextSnapshot]
```

### ContextSnapshot（欄位說明）

**K線力量課程專用 schema — 不含主力大欄位（broker/teacher/ch2/sector 移至 ZhuliContextSnapshot）。**

| 欄位 | 型別 | 來源 | 說明 |
|---|---|---|---|
| ma5/10/20/60_will_rise | bool | features / overrides | 明日 MA 是否上揚（扣抵值） |
| attack_cost | float | features | 攻擊成本（突破 K 的 close） |
| defensive_low | float | features | 防守低點 |
| attack_intent_zone_high | float | features | 攻擊意圖區上緣（C03） |
| attack_intent_zone_low | float | features | 攻擊意圖區下緣（C03，STUB S6） |
| is_just_broke_high | bool | features | 剛創 60 日新高（C04） |
| is_limit_up_locked | bool | features | 漲停鎖住（C05） |
| is_anomalous_volume | bool | features | 異常放量（C07，STUB S1） |
| taiex_record_drop_point | bool | taiex DB | 今日加權跌點創歷史新高 |
| taiex_record_drop_pct | bool | taiex DB | 今日加權跌幅創歷史新高 |
| taiex_record_limit_down_count | bool | limit_down DB | 跌停家數創歷史新高 |
| taiex_record_any_criterion | bool | computed | 上述三項任一成立（OR） |
| taiex_no_new_low_next_day | bool | taiex DB | 隔日加權不再創新低（進場確認） |

### Playbook / Branch / Action / Light

```python
class Playbook(BaseModel):
    pattern: str                    # 對應 PATTERN_REGISTRY key
    setup: PlaybookSetup            # name, required_context 清單
    branches: list[Branch]         # 應變分支
    course_sources: list[CourseCitation]
    relevant_lights: list[str]     # 配套燈號 light_id 清單

class Branch(BaseModel):
    id: str                         # 唯一 id，例："B1_明日續強"
    when: dict                      # mini-DSL 條件 dict
    confirm_at: ConfirmAt           # "today_close" / "next_open" / "next_close" / ...
    next_day_n: int                 # 1~3，next_day.* 對應 shift(-N)
    action: Action
    next_branch_ids: list[str]

class Action(BaseModel):
    type: ActionType                # entry_signal / exit_signal / stop_loss_trigger /
                                    # watch_only / partial_exit / ...
    description: str
    course_citation: CourseCitation  # 必填，source min_length=5
    notes: list[str]

class Light(BaseModel):
    light_id: str
    trigger_condition: dict         # 同 Branch.when 的 DSL
    course_citation: CourseCitation
    recommendation_text: str
    severity: Literal["info", "warn", "critical"]
```

---

## 15. DB 路徑

| DB | 路徑 | 說明 |
|---|---|---|
| 主 OHLCV | `/Users/howard/.four_seasons/data.sqlite` | 多 repo 共用，四季專案管理，table: `standard_daily_bar` |
| Backfill | `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/historical_backfill.sqlite` | k-bar-power 抓 FinMind 補的 pre-2022 歷史，`fill_from_backfill=True` 時自動 union |
| Advisor history | `data/advisor_history.db`（相對 repo root） | advisor 跑過的歷史，persistence.py 管理（schema 含 `pattern_name` 欄、commit `62f21dd`）|
| Phase 4.3 backtest | `data/analysis/kline_patterns/phase4_advisor_history.db` | 200 ticker × 583 trading days、127k branches |
| Minute bars | 主 OHLCV 同 DB、table: `minute_bars` | `scripts/kline/minute_bars.py` helper、attack_cost_displayed 用（commit `245edbe`）|
| TAIEX history | `data/analysis/kline_patterns/taiex_history.sqlite` | 2000–2023 補完（commit `246f995`）、`taiex_record_*` context |
| Limit-down history | `data/analysis/kline_patterns/limit_down_history.sqlite` | 跌停家數歷史、`taiex_record_limit_down_count` context |

---

## 16. 典型整合範例

### stock-analysis-system — Pattern Screening

```python
from scripts.kline.bars import load_bars
from scripts.kline.features import add_features
from scripts.kline.patterns import PATTERN_REGISTRY

df = load_bars()
enriched = add_features(df)

# 只取最新一日，對全市場跑所有 pattern
latest_date = enriched["trade_date"].max()
today = enriched[enriched["trade_date"] == latest_date].copy()

hits = {}
for name, detect_fn in PATTERN_REGISTRY.items():
    fired = detect_fn(enriched)   # 全部歷史（需要 lookback）
    today_fired = fired[fired.index.isin(today.index)]
    tickers = today.loc[today_fired[today_fired].index, "ticker"].tolist()
    if tickers:
        hits[name] = tickers

print(hits)
```

### four-seasons-investment — 日盤前 Advisor

```python
from scripts.kline.bars import load_bars
from scripts.kline.scenarios.advisor import analyze
from scripts.kline.scenarios.persistence import save

df = load_bars()
today = "2026-06-03"

# K線力量 context fields（ma*_will_rise 可透過 overrides 注入；taiex 欄位自動從 DB 讀）
overrides = {
    "ma5_will_rise": True,
    "ma60_will_rise": True,
}

for ticker in ["2330", "6121"]:
    result = analyze(df, today_date=today, ticker=ticker,
                     context_overrides=overrides)
    run_id = save(result, ticker=ticker, trade_date=today)
    if result.active_lights:
        print(f"{ticker}: {[l.light_id for l in result.active_lights]}")
    if result.scenarios:
        print(f"{ticker}: {[s.playbook_name for s in result.scenarios]}")
```

### stock-research — ETF Holdings × Patterns

```python
from scripts.kline.bars import load_bars
from scripts.kline.features import add_features
from scripts.kline.patterns import PATTERN_REGISTRY

df = load_bars()
enriched = add_features(df)
latest_date = enriched["trade_date"].max()

# 假設已有 ETF holdings list
etf_tickers = ["2330", "2454", "3231"]

etf_df = enriched[enriched["ticker"].isin(etf_tickers)]
for name, detect_fn in PATTERN_REGISTRY.items():
    fired = detect_fn(etf_df)
    today_mask = etf_df["trade_date"] == latest_date
    if fired[today_mask].any():
        hit_tickers = etf_df.loc[today_mask & fired, "ticker"].tolist()
        print(f"{name}: {hit_tickers}")
```

---

## 17. 約束 + 邊界

1. **不准自創指標：** branch.when 內只能用 DSL 白名單欄位，RHS 不允許算式。

2. **broker / teacher / sector 只進 context + notes + lights：**
   不可進 `Branch.when`（那是課程邏輯層）。外部訊號透過 `context_overrides` 注入，
   由 playbook `required_context` 決定是否啟用對應劇本。

3. **simulator 禁止算 EV / PnL / ret_Nd：** 必須走課程 exit 模擬（`simulate()`），
   不能直接用 N 日後報酬替代。

4. **partial_exit 必須引用老師原話比例：**
   `action.description` 必須含老師明示的比例（「先賣一半」/ 「三分之一先出」），
   loader 不自動校驗，靠 code review + grep 確認。

5. **缺資料禁止靜默補值：** features 欄位為 None / NaN 時，
   `build_context_snapshot` 加到 `warn_notes`，不推算替代值。

---

## 18. 常見 Pitfalls

| 問題 | 正確做法 |
|---|---|
| Rolling 跨 ticker 邊界計算 | 一律用 `.transform(lambda s: s.shift(N).rolling(M))` |
| SQLite 連線不關閉（91 GB bug） | `bars.py` 已在 `finally: tmp.unlink()` 清除；自己的 DB 操作用 `with sqlite3.connect() as conn` |
| DSL RHS 算式（`volume * 1.5`）| condition.py 嚴格 reject `UnknownTokenError`，改用靜態常數 |
| datetime parse 格式不一致 | v4 格式 vs v2 `corrected_approx_date` 用 `pd.to_datetime(..., errors="coerce")` |
| 直接 import extras 當課程邏輯用 | extras/ 的東西不可搬進 entry/ exit/ scoring/；需要升格先提給 user 審閱 |
| 跑 all-ticker scan 不加 ticker filter | pattern detect 接收全市場 df 是正確的（需 lookback），但要在結果上過濾今日行 |

---

## 19. 重要 Spec / Plan 參考

| 文件 | 路徑 |
|---|---|
| Playbook Layer 設計 | `docs/superpowers/specs/2026-06-03-playbook-layer-design.md` |
| Playbook Phase 1 計劃 | `docs/superpowers/plans/2026-06-03-playbook-layer-phase1-plan.md` |
| Playbook Phase 3 計劃 | `docs/superpowers/plans/2026-06-03-playbook-layer-phase3-plan.md` |
| Shared Data Layer 設計 | `docs/superpowers/specs/2026-05-27-shared-data-layer-design.md` |
| 課程合規 Audit | `docs/kline_course/COMPLIANCE_AUDIT_2026-06-03.md` |
| Pattern Inventory | `docs/kline_course/long_short_turning_point/PATTERN_INVENTORY.md` |
| Pattern Definitions | `docs/kline_course/long_short_turning_point/PATTERN_DEFINITIONS.md` |
| 明日 K 線 Inventory | `docs/kline_course/mingri_kline/INVENTORY.md` |
| Phase 4.3 v4 報告 | `data/analysis/kline_patterns/phase4_report.md`（commit `a7380cc`、127k branches）|
| Phase 4.3 v3 報告 | `data/analysis/kline_patterns/phase4_v3_report.md`（含 v2 對比 + regression 紀錄）|
| Branch hit rates CSV | `data/analysis/kline_patterns/phase4_branch_hit_rates.csv`（69 pairs ≥ 10 runs）|
| 入門 58 篇全抓報告 | `docs/kline_course/notes/kline_intro_extraction_report.md`（commit `4c9ba79`）|
| 入門 4 新概念實作 | `docs/kline_course/notes/intro_concepts_impl_2026-06-05.md`（commit `1a20d8e`）|
| Lights audit | `docs/kline_course/notes/lights_audit_2026-06-04.md`（commit `0db266d`）|
| Lights fix batch | `docs/kline_course/notes/lights_fix_batch_2026-06-04.md` |
| New advanced lights | `docs/kline_course/notes/lights_new_advanced_2026-06-04.md`（4 `lt_*` wiring）|
| STUB fix batch | `docs/kline_course/notes/stub_fix_batch_2026-06-05.md` |
| Attack cost state-machine | `docs/kline_course/notes/attack_cost_state_machine_v1.md` |

### 5 課程資料夾完備度

| 課程 | 路徑 | 篇數 |
|---|---|---|
| K 線力量判斷入門 | `docs/K線力量判斷入門/articles/` | 58 ✅（commit `4c9ba79` 全抓）|
| K 線行進ing | `docs/K線行進ing/` | 41 ✅ |
| 型態學 | `docs/型態學/` | 20 ✅ |
| 多空轉折組合 | `docs/kline_course/long_short_turning_point/` | 35 ✅ |
| 明日 K 線 | `docs/kline_course/mingri_kline/` | 51 ✅ |

---

*最後更新：2026-06-06（49 commits since 2026-06-03，覆蓋 Phase 3.E + 4.3 + advisor formatter + CLI + 4 新 intro 概念 + lights audit 修正 + STUB fix）*
