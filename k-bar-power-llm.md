# k-bar-power — LLM Integration Reference

**Mission:** K 線力量課程實作 + 應變劇本層 (playbook layer)

> 本檔針對其他 repo 的 AI agent 或開發者，讓你在不 scan 整個 worktree 的情況下
> 快速理解模組、API、資料格式、與課程合規約束。

**Pipeline 總覽**

```
bars_df (OHLCV)
  → features.add_features()         # 衍生欄位
  → patterns/<slug>.detect()        # 26 個多空轉折型態 (bool Series)
  → entry / exit / scoring          # 進出場偵測 + 評分
  → scenarios.advisor.analyze()     # 劇本層 (playbook layer)
  → AdvisorResult                   # fired_patterns / scenarios / active_lights / notes
```

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
scripts/kline/
  bars.py                     # load_bars() — OHLCV 載入
  features.py                 # add_features() — 衍生欄位
  course_proxy_constants.py   # 全部量化門檻的唯一來源
  patterns/
    __init__.py               # PATTERN_REGISTRY (26 slugs)
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
    condition.py              # mini-DSL evaluate() / evaluate_vectorized()
    context.py                # build_context_snapshot()
    loader.py                 # load_playbooks() / load_lights()
    persistence.py            # save() / load_runs() / update_branch_outcome()
    playbooks/                # *.yaml playbook 檔
    lights/                   # *.yaml light 檔
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

df = load_bars()                           # 使用預設 DB 路徑，自動補 backfill
df = load_bars(db_path=Path("/custom/data.sqlite"), fill_from_backfill=False)
```

**簽名：**
```python
def load_bars(
    db_path: Path = DEFAULT_DB_PATH,   # 預設: /Users/howard/.four_seasons/data.sqlite
    fill_from_backfill: bool = True,   # 自動 union pre-2022 backfill DB
) -> pd.DataFrame
```

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
| pre_breakout_trend_days | 連續收盤高於 MA60 的天數（上限 20） |
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

**Cross-ticker rolling bug 已修正：**
所有「排除今日的 rolling」一律用 `.transform(lambda s: s.shift(1).rolling(N).max())` 
而非 `g["col"].shift(1).rolling(N)`（後者跨 ticker 邊界計算，為已知 bug）。

---

## 4. Pattern Detection (26 個型態)

### 4.1 通用 API

每個 pattern module 提供：
```python
def detect(df: pd.DataFrame) -> pd.Series  # bool, aligned with df.index
```

- 純函式 (pure function)，DataFrame in/out，無 side effect
- 觸發點 = pattern 完成的那根 K（True 那天可作為 entry/exit timing）
- 全部 26 個 detect 函式統一在 `PATTERN_REGISTRY`

```python
from scripts.kline.patterns import PATTERN_REGISTRY

# 批次跑所有 pattern
for name, detect_fn in PATTERN_REGISTRY.items():
    fired: pd.Series = detect_fn(enriched_df)   # enriched_df 需先 add_features
```

### 4.2 全部 26 個 slug

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

---

## 7. Scenarios — Playbook Layer

### 7.1 主入口 `advisor.analyze`

```python
from pathlib import Path
from scripts.kline.scenarios.advisor import analyze

result = analyze(
    bars_df=df,               # raw 或 features-enriched 均可（自動偵測）
    today_date="2026-06-03",  # 'YYYY-MM-DD'
    ticker="2330",
    context_overrides={       # Phase 1: broker/teacher/ch2/sector 欄位從此注入
        "broker_tier1_buy": True,
        "teacher_tier": "core",
        "ch2_warning_score": 3,
        "ma60_will_rise": True,
    },
    # playbook_dirs=[Path("my/playbooks")],  # 預設: scenarios/playbooks/
    # light_dirs=[Path("my/lights")],        # 預設: scenarios/lights/
)

print(result.fired_patterns)   # List[PatternHit]
print(result.scenarios)        # List[Scenario]
print(result.active_lights)    # List[Light] sorted critical→warn→info
print(result.notes)            # WARN 訊息清單
print(result.context_snapshot) # ContextSnapshot
```

**效能目標：** 單 ticker × 單日 < 200 ms（含 add_features）。

### 7.2 YAML Loader

```python
from scripts.kline.scenarios.loader import load_playbooks, load_lights, LoaderError

# dict[str, list[Playbook]]: pattern → playbooks
playbooks = load_playbooks([Path("scripts/kline/scenarios/playbooks")])

# dict[str, Light]: light_id → Light
lights = load_lights([Path("scripts/kline/scenarios/lights")])
# 重複 (pattern, setup.name) 或 light_id → ValueError (fail loud)
```

### 7.3 Condition DSL

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
| `context.*` | `context.broker_tier1_buy` / `context.ma60_will_rise` / `context.teacher_tier` |
| top-level | `prev_high_60` / `attack_cost` / `attack_intent_zone_high` / `defensive_low` |

**DSL 約束：**
- RHS 禁止算式（如 `volume * 1.5`）— 嚴格 reject UnknownTokenError
- 嵌套深度最多 2 層（`all` / `any` / `not`）
- `context.teacher_tier == "core"` 這種字串比較用 `==` / `!=`

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

### 7.4 Context Snapshot 建構

```python
from scripts.kline.scenarios.context import build_context_snapshot

snapshot, warn_notes = build_context_snapshot(
    bars_df=enriched_df,
    today_date="2026-06-03",
    ticker="2330",
    overrides={"broker_tier1_buy": True},
)
# warn_notes 含每個 None 欄位的 "WARN:" 訊息 (fail-loud, 不靜默補值)
```

### 7.5 Persistence

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

## 8. Pydantic Schema 速查

所有 schema 定義在 `scripts/kline/scenarios/_schema.py`。

### AdvisorResult
```python
class AdvisorResult(BaseModel):
    fired_patterns: list[PatternHit]   # pattern, fired_at, confidence
    scenarios: list[Scenario]          # pattern_hit, playbook_name, enabled_branches
    active_lights: list[Light]         # sorted critical→warn→info
    notes: list[str]                   # WARN 訊息 + D-class 觀念提醒
    context_snapshot: Optional[ContextSnapshot]
```

### ContextSnapshot（欄位說明）

| 欄位 | 型別 | 來源 | 說明 |
|---|---|---|---|
| broker_tier1_buy | bool | overrides | 主力一線券商淨買超 |
| teacher_tier | str | overrides | "core" / "strong" / "mention" / "context" |
| broker_concentration | float | overrides | 集中度 |
| ch2_warning_score | int | overrides | 0~6，Ch2 警示累積分 |
| sector_consensus_direction | str | overrides | "bull" / "bear" / "mixed" |
| ma5/10/20/60_will_rise | bool | overrides / features | 明日 MA 是否上揚（扣抵值） |
| attack_cost | float | features | 攻擊成本（突破 K 的 close） |
| defensive_low | float | features | 防守低點 |
| attack_intent_zone_high | float | features | 攻擊意圖區上緣（C03） |
| attack_intent_zone_low | float | features | 攻擊意圖區下緣（C03，STUB S6） |
| is_just_broke_high | bool | features | 剛創 60 日新高（C04） |
| is_limit_up_locked | bool | features | 漲停鎖住（C05） |
| is_anomalous_volume | bool | features | 異常放量（C07，STUB S1） |

**注意：** broker / teacher / ch2 / sector 四類欄位為 Phase 1 = overrides only；
Phase 4 才會 wire 真實資料源。不提供時 ContextSnapshot 欄位為 None，advisor 會在 notes 警告。

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

## 9. DB 路徑

| DB | 路徑 | 說明 |
|---|---|---|
| 主 OHLCV | `/Users/howard/.four_seasons/data.sqlite` | 多 repo 共用，四季專案管理，table: `standard_daily_bar` |
| Backfill | `/Users/howard/Repository/stock-k-bar/.claude/worktrees/k-bar-power/data/analysis/kline_patterns/historical_backfill.sqlite` | k-bar-power 抓 FinMind 補的 pre-2022 歷史，`fill_from_backfill=True` 時自動 union |
| Advisor history | `data/advisor_history.db`（相對 repo root） | advisor 跑過的歷史，persistence.py 管理 |

---

## 10. 典型整合範例

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

# 從外部系統取得 broker / teacher context（Phase 1 用 overrides）
overrides = {
    "broker_tier1_buy": True,
    "teacher_tier": "core",
    "ch2_warning_score": 4,
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

## 11. 約束 + 邊界

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

## 12. 常見 Pitfalls

| 問題 | 正確做法 |
|---|---|
| Rolling 跨 ticker 邊界計算 | 一律用 `.transform(lambda s: s.shift(N).rolling(M))` |
| SQLite 連線不關閉（91 GB bug） | `bars.py` 已在 `finally: tmp.unlink()` 清除；自己的 DB 操作用 `with sqlite3.connect() as conn` |
| DSL RHS 算式（`volume * 1.5`）| condition.py 嚴格 reject `UnknownTokenError`，改用靜態常數 |
| datetime parse 格式不一致 | v4 格式 vs v2 `corrected_approx_date` 用 `pd.to_datetime(..., errors="coerce")` |
| 直接 import extras 當課程邏輯用 | extras/ 的東西不可搬進 entry/ exit/ scoring/；需要升格先提給 user 審閱 |
| 跑 all-ticker scan 不加 ticker filter | pattern detect 接收全市場 df 是正確的（需 lookback），但要在結果上過濾今日行 |

---

## 13. 重要 Spec / Plan 參考

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

---

*最後更新：2026-06-03*
