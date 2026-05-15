---
name: K-Line Power Judgment Course - Source of Truth
description: Complete course rules + immutable principles + naming conventions + review checklist (single source, must review after every change)
type: reference
originSessionId: d7e91495-e51b-49b5-ad3a-99d9db94b659
---
## Source
PressPlay course "Lin Jia-yang | K-Line Power" → "K-Line Power Judgment Intro" subcategory (58 articles)
Project ID: `55DE90EBFBB634BE864F75703AB654DE`

Human-readable Chinese mirror: `docs/K線力量判斷入門/course_principles.md`

## When to Use
**After ANY of these actions, review against this document:**
- Add/modify entry conditions
- Add/modify exit conditions
- Add/modify ranking scores
- Add/modify backtest logic
- Add new extension toggle (`extras`)

---

# Part 1: Complete Course Rules

## Three Entry Types → Three Stop-Loss Types

Source: 【買點賣點】多方操作的出場點邏輯

| Entry Type | Stop-Loss | Current Proxy Status |
|---|---|---|
| Buy at trend change (post-bear) | **Bottom break** (back to bear trend) | ✗ Not implemented |
| Buy at neckline breakout (consolidation) | **Drop below prior breakout (neckline)** | ⚠ E3 uses prior_low_20 (crude proxy) |
| Buy at attack (bull market) | **Attack failure** (e.g., attack gap filled) | ✓ E1 gap fill |

Strict neckline definition:
- **Long-side entry**: "prior high **after** the quarterly MA turns up" (季線上揚後的前一個高點)
- **Short-side exit**: "prior low **after** the quarterly MA turns down" (季線下彎後的前一個低點)

---

## Take-Profit (Swing vs Short-term)

### Swing Trading

**(A) Reversal K-line patterns** (any one triggers exit):

| Name (CN) | Course Definition | Code Name | Status |
|---|---|---|---|
| 空頭吞噬 (Bearish Engulfing) | Red K at new high, followed on the **next day** by long black K that fully engulfs | `bearish_engulfing` | ✗ |
| 暗夜雙星 (Dark Double Star) | Long black K breaks below two parallel K bars (even when it doesn't make new high and opens below prior low — that variant is also valid) | `dark_double_star` | ✓ E2 |
| 大敵當前 (Enemy at Gate) | ⚠ **No structural definition in K-line judgment intro**. Only mentioned by name + 藍天 example. Detailed definition likely in separate "多空轉折組合K線" (26 articles) subcategory. Course-precise implementation not possible without that source. | `enemy_at_gate` | ✗ Cannot implement precisely |
| 雙鴉躍空 (Two Crows) | "前波壓力區域，紅K後接兩根短黑K，然後向下跳空" (from 提前部署文章) | `two_crows` | ✗ |
| 夜星棄嬰 (Abandoned Evening Star) | ⚠ **No structural definition in K-line judgment intro**. Definition likely in 多空轉折組合K線 subcategory. | `evening_star_abandoned` | ✗ Cannot implement precisely |
| 跳空反轉 (Gap Reversal) | "紅K後接黑K再向下跳空" (from 進出場決策序篇 hint) | `gap_reversal` | ✗ |

**(B) Trend Change** (when no reversal K appears):

| Name (CN) | Course Definition | Code Name | Status |
|---|---|---|---|
| 末升低跌破 (Last Rally Low Break) | Most recent rising-low in bull swing broken | `last_rally_low_break` | ✗ |
| 上升趨勢線跌破 (Rising Trendline Break) | Multi-point trendline broken | `rising_trendline_break` | ✗ |

**Take the higher of the three as the standard** (last_rally_low, rising_trendline, MA60-turn-down — course says "三者取其一" with "哪個價位高就採用哪個").

### Short-term Trading

| Name (CN) | Course Quote | Code Name | Status |
|---|---|---|---|
| 前一天低點跌破 (Prev Day Low Break) | "If yesterday's low is broken, attack stops" | `prev_day_low_break` | ✗ |
| 跳空缺口被回補 (Attack Gap Fill) | (See below) | `attack_gap_fill` | ✓ E1 |

> **Cross-reference:** Swing/short-term split is one dimension. For complete exit mapping by rally type (四大上漲類型 + 賣壓區到達情境), see "Four Rally Types Exit Strategy Matrix" in Part 6.5.

### Position-independent (Supply Zone)

Source: 【買點賣點】出場點的各種依據-下一個買點

| Name (CN) | Course Quote | Code Name | Status |
|---|---|---|---|
| 遇壓先出（化解再進）(Reaching Supply Zone) | "應該先出場，等到股價越過了這個壓力區段，再考慮還有沒有買回的意義" | `supply_zone_reached_exit` | ⚠ Partial (VP scoring exists, but no explicit exit trigger) |

Note: We have `vp_overhead_pct` and `vp_dense_above` in scanner_score for ENTRY-side filtering, but NO course-aligned EXIT trigger when an open position reaches a known overhead supply zone. Course explicitly says exit and re-enter after resolution.

### Trailing Stop (Slow Push Type)

Source: 【買點賣點】出場點的各種依據(二)

| Name (CN) | Course Quote | Code Name | Status |
|---|---|---|---|
| 移動停利 (Trailing Stop) | "移動停利是一個必備的操作模式，主要用來應對緩慢推升型" | `trailing_stop_rolling_low` | ✗ |

**Implementation note:** Mechanism = `prev_day_low_break` rolling forward. As price makes new highs, the "previous low" reference updates. Same machinery as short-term stop but applied to slow-push rallies (longer hold).

### Compound Strategy (Abnormal Character Type)

Source: 【買點賣點】出場點的各種依據(二)

| Name (CN) | Course Quote | Code Name | Status |
|---|---|---|---|
| 兩段操作 (Two-Stage Exit) | "第一段的初期飆升採取攻擊結束的方式出場，如果有第二段...採取趨勢型的出場" | `two_stage_exit` | ✗ |

**This is a META-strategy, not a single indicator.**
- Stage 1: Use `breakout_bar_low_break` / `prev_day_low_break` / reversal-K
- Between stages: Wait for new breakout (new high) to re-enter
- Stage 2: Switch to `trend_change_exit` (MA60 / last_rally_low / trendline)

---

## Breakout Bar Low Break (Critical)

Source: 【單一K線】紅色誤解：連續紅K的判斷要點

> "The red K of a breakout must be assumed as an attack... **If the breakout K is broken, our assumption is invalidated**, the price was not really attacking."

Code name: `breakout_bar_low_break`
Status: ✓ E4 implemented

---

## Attack Authenticity Check (Consecutive Red Ks)

Source: 【單一K線】紅色誤解：連續紅K的判斷要點

Core principle: "The theoretical foundation of attack: once started, no turning back, **cannot give many opportunities for low-buying**"

- Post-breakout **repeated low-open then rally** red Ks = lacks attack intent (case: 華電網)
- True attack = **rapid sequential upward push**, no low-buy opportunity (case: 加高)
- Quantitative proxy: `low_open_count_after_breakout`
- Status: ✗ Not implemented

---

## Stop-Loss Conceptual Principles

Source: 【停損】停損位置的設定準則(一)(二)

- **No percentage stop-loss** ("there is no such percentage stop-loss setting mode")
- Stop = Take-profit (same standard, different naming based on P&L)
- Decided by K-line position, not entry cost
- Four stop-loss logic categories: stock character, cost principle, bull-bear power change, attack power evaluation

---

# Part 2: Immutable Core Principles

## 🔴 Entry Side

1. **Entry = Attack Assumption**
   - Red K breaking prior high must be assumed as attack
   - If assumption invalidated (breakout K low broken) → exit immediately
   - Cannot change basis after entry (e.g., losing trade → "long-term investment")

2. **Strict Neckline Definition**
   - **Long-side**: "Prior high **after** quarterly MA turns up" (季線上揚後的前一個高點)
   - **Short-side**: "Prior low **after** quarterly MA turns down" (季線下彎後的前一個低點)
   - NOT prior_low_20, prior_high_60, etc. (those are crude proxies)
   - Any proxy must be labeled as "non-course approximation"

## 🔴 Exit Side

3. **No Percentage Stop-Loss**
   - Course explicitly: "no percentage stop-loss setting mode"
   - Stops decided by **K-line position and pattern**, not entry cost
   - Cannot use "stop at -X%" / "take profit at +X%" rules

4. **Stop = Take-Profit**
   - Same standard, only difference is P&L direction
   - Cannot relax stop because "already profitable"

5. **Close-Price Confirmation Principle**
   - All break/reclaim/breakout confirmed by **close price**
   - Not intraday price
   - Next-day open is execution point

## 🔴 Power Judgment

6. **Attack Should Not Give Low-Buy Opportunities**
   - True attack = rapid sequential upward, no low-buy chance for retail
   - Post-breakout **repeated low-open** red Ks = attack lacks intent

7. **K-line Meaning > Shape**
   - Same shape K has different meanings in different positions (new high / pressure zone / consolidation)
   - Red K ≠ rising, shadow ≠ support/resistance
   - Position must be considered in scoring

8. **Gap Meaning**
   - Gap = "buying or selling at any price" (urgency)
   - **Attack gap** = new high + no trades on left side of gap
   - **General gap** = has prior trapped supply above, less meaningful
   - Cannot conflate the two

## 🔴 Trend and Pattern

9. **Quarterly MA Direction = Mid-term Trend Core**
   - MA60 rising → bull background
   - MA60 turning down → don't buy
   - Neckline and last_rally_low are built on MA60 judgment

10. **Last Rally Low / Rising Trendline / MA60 Turn-Down → Three options, take the highest**

---

# Part 3: Naming & Source Traceability

**Every strategy indicator and entry/exit condition MUST have clear course source.**

## Naming Rules

1. **Map to named reversal K patterns** (use English names from tables above)

2. **Map to course concepts** (use English translation of course terminology)

3. **No mapping name?** Must comment with **course article title** in source code:
   ```python
   # Source: 【單一K線】紅色誤解：連續紅K的判斷要點
   low_open_count_after_breakout = ...
   ```

## Code Comment Format

Each course concept implementation must have docstring with source:

```python
def detect_bearish_engulfing(...):
    """Bearish Engulfing: Red K at new high followed by long black K that fully engulfs.

    Course sources:
      - 【買點賣點】出場點(二)轉折組合K線運用出場
      - 【停損】停損位置的設定準則(二)

    Course definition: "Red K making new high, next day long black K fully engulfs"
    """
```

## Extension (non-course) Labeling

```python
# === EXTRA: Non-course content ===
# Custom logic: [why we added it]
# Course stance: [whether course mentioned anything, direction consistency]
def extra_xxx(...):
    ...
```

---

# Part 4: Required Disclosure for Quantitative Proxies

| Course Concept | Our Proxy | Limitation |
|---|---|---|
| Neckline (prior high before MA60 turns up) | `prior_low_20` | Crude proxy, ignores MA direction |
| Attack gap (no trades on left of gap) | `gap_open` | Doesn't verify left side absence |
| Layered supply (層層套牢) | `overhead_supply_layer` peak-count | Not real cost zone (needs price-volume table) |
| Last rally low | (not implemented) | Needs swing low detection |
| Rising trendline | (not implemented) | Needs multi-point fitting |

---

# Part 5: Extensions Must Be Toggles

Any logic **not in course** must:
1. Name with `extra_` prefix, must have toggle
2. Default to closeable
3. Comment with `# === EXTRA: Non-course content ===`
4. Provide backtest comparison (on/off effect)

Known extensions:
- Excess gap (market-adjusted)
- close_pos / body_pct / volume_ratio backtest-derived penalties
- market_regime using equal-weighted (not actual index)
- rolloff_pressure (MA carry-off)
- overhead_supply_layer OHLCV peak-count

---

# Part 6: Review Checklist

After every change, check each item:

## Course Compliance
- [ ] Does entry condition match one of three buy types?
- [ ] Is corresponding stop-loss correct?
- [ ] Any percentage stop-loss used? (Forbidden!)
- [ ] Close-price confirmed, next-day open executed?
- [ ] Does K-line judgment consider "position"?
- [ ] Does "attack" judgment follow "no low-buy" principle?

## Naming & Source
- [ ] Each function/variable maps to reversal K name or course concept?
- [ ] No mapping → labeled with course article title in comment?
- [ ] Course content has docstring with source citation?

## Proxies & Extensions
- [ ] Are proxies labeled with limitations?
- [ ] Non-course extensions made into `extra_` toggles?
- [ ] Extensions document "course stance" comparison?

## Scoring Logic
- [ ] Do weights reflect course direction (not pure backtest)?
- [ ] Penalties against course direction labeled as EXTRA and toggleable?

---

# Part 6.5: Additional Critical Findings (from full course reading)

## Breakout (突破) Definition Refinement

Source: 【突破跌破】突破意義的釐清

> "對於K線圖來說，**價格才是最重要的事情，不需要加上成交量**"
> "與這一根突破的K線是否**長紅、有沒有上影線都無關**，研判的重點在於關鍵價位"

**Critical implications:**
- **Volume is NOT required** for breakout entry (course explicitly says so)
- **Red K is NOT required** for breakout (course explicitly says so)
- **close_pos threshold is NOT required**
- Our current `breakout_attack` is OVER-RESTRICTED (强制紅K + volume_ratio≥1.2 + close_pos≥0.7)
- These should be either removed OR moved to `extra_` toggles

## First Breakout vs Re-Breakout

Source: 【突破跌破】突破意義的釐清

- **Re-breakout** (already not first time): Must wait for **NEXT-DAY attack confirmation** (課程明確)
- **First breakout** (after first creating new high): May enter on breakout day
  - ⚠ **Low confidence** — course only explicitly addresses re-breakout case. The "first-breakout same-day entry" is inferred from negation, not explicitly stated.
- Quantitative: Track if stock has had prior breakout above the same level

## Attack (攻擊) — Multiple Forms

Source: 【買點賣點】股價的買點決策(三)多頭買在攻擊

Attack K-line types (not just long red K!):
1. **跳空** (gap up at new high)
2. **長紅** (long red K at new high)
3. **創新高上影線** (new high with upper shadow) — often overlooked
4. **創新高十字線** (new high doji) — often overlooked

Attack indicators (post-breakout):
- "真正有心攻擊的股票不會拉回再給人有更低價的買進機會"
- 「透過高點是否有持續創新高來做為攻擊延續與否的判斷」
- Next-day open should NOT be flat or down (price weakness signal)

## Attack Continuity Criterion (Short-term)

Source: 【買點賣點】買點與攻擊研判

> "攻擊力量的持續與否，可以使用每根K線的低點來作為判斷，如果創新高之後股價雖然沒有不斷的大漲，但是每一根低點卻是越來越高，表示這個力道依然存在"
> "短線操作的停利點可以設定在**昨天的低點**"

**Implementation guidance:**
- Short-term trailing stop = `prev_day_low_break`
- Attack continuity = each day's low > prior day's low (higher lows)

## Five Types of Rally Patterns

Source: 【買點賣點】出場點的各種依據(一)

Categorization of price rallies for exit logic:
1. **強勢攻擊型** (Strong attack) → 出場：轉折組合K線
2. **趨勢改變型** (Trend change) → 出場：季線、末升低、趨勢線
3. **緩慢推升型** (Slow push) → 出場：移動停利
4. **異常體質型** (Abnormal character) → 出場：兩段操作

**Note:** Course's 出場點(一) opening says "五大類型... 分為三篇探討". After reading all three (一)(二)(下一個買點), only 4 distinct rally types appear. The "fifth" was a 賣壓區到達情境 (supply zone reached), which is an independent scenario applicable to ALL types — not a separate rally type.

## Trend Change Exit (Swing Trading)

Source: 【買點賣點】出場點的各種依據(一)

For swing traders without reversal K signals:
- 上升趨勢線跌破 (rising trendline break)
- 季線下彎 (MA60 turns down)
- 末升低跌破 (last rally low break)

**Take the highest of the three as the stop point.** (取較高者)

Note: NOT suitable for short-term traders (too far from peak)

## Key K-Line (關鍵K線) Definition

> "一根K線的前與後，趨勢不一樣"

Trend transition types:
- 多空互換 (bull-bear swap)
- 盤整轉多頭 (consolidation → bull)
- 多頭變為盤整 (bull → consolidation)
- 盤整變為空頭 (consolidation → bear)
- 空頭變成整理 (bear → consolidation)

## "Just-Created-New-High Upper Shadow" Stop-Loss

Source: 【買點賣點】股價的買點決策(三)多頭買在攻擊

> "「剛」創新高的上影線低點作為短線交易者的停損位置"

This is similar to but distinct from `breakout_bar_low_break`:
- `breakout_bar_low_break` = low of the K that broke above prior_high_60
- `first_new_high_upper_shadow_low_break` = low of the K that has upper shadow at new high

## Four Rally Types + 1 Standalone Scenario → Exit Strategy Matrix

Source: 【買點賣點】出場點的各種依據(一)(二)(下一個買點)

| Rally Type | Exit Strategy | Code Name |
|---|---|---|
| 強勢攻擊型 (Strong Attack) | 轉折組合K線 (any reversal K) | `reversal_k_exit` |
| 趨勢改變型 (Trend Change) | 季線下彎 / 末升低 / 趨勢線 三者取較高者 | `trend_change_exit` |
| 緩慢推升型 (Slow Push) | 移動停利 (trailing stop) | `trailing_stop_exit` |
| 異常體質型 (Abnormal Character) | 兩段操作（先攻擊結束，後趨勢出場）| `two_stage_exit` |

**Standalone scenario (applies to ALL rally types):**

| Scenario | Exit Strategy | Code Name |
|---|---|---|
| 賣壓區到達 (Supply Zone Reached) | 遇壓先出，化解再進 | `supply_zone_exit` |

## Trailing Stop Definition

Source: 【賣壓化解】K線圖的第一個研判要點 + 【買點賣點】出場點的各種依據(二)

> "前一日低點當作是停利點，有過昨高都算是攻擊持續"
> "類似移動停利的模式作為判斷標準"

**Implementation:**
- For each held position, track the most recent low
- Exit when close < previous K-line's low
- If a new high is made, update the "previous low" to the new K's low

## Supply Zone Concept (賣壓化解)

Source: 【賣壓化解】K線圖的第一個研判要點

**The first research point for any K-line chart = previous supply zone**

- Stocks need to "resolve" overhead supply (賣壓化解) before continuing higher
- Reaching a known supply zone = potential exit signal
- Course recommends volume-by-price (分價量表) for precise identification
- High-volume zones in past (2-3x normal volume) = primary resistance

## Key K-Line (關鍵K線) - Foundational Concept

Source: 【關鍵K線】關鍵K線的意義與用途

> "在這一根K線之前與之後，趨勢不同了"

**Types of trend transitions (all are key K-lines):**
- 盤整 → 多頭 (consolidation → bull) — usually a breakout entry point
- 盤整 → 空頭 (consolidation → bear) — neckline break exit
- 多頭 → 整理 (bull → consolidation)
- 多頭 → 空頭 (bull → bear)
- 空頭 → 整理 (bear → consolidation)

**Use cases:**
- Multi-side: Key red K (breakout) = entry; broken = exit
- Short-side: Key black K (breakdown) = entry
- 多方走勢的關鍵K線 = 進場買點
- 「攻擊型的關鍵紅K線被跌破，代表著攻擊的結束」

## MA60 (季線) Direction via Carry-Off (扣抵)

Source: 【移動平均】季線與K線高低點

**MA60 Definition:**
- Rolling 60-day average of close prices
- "扣抵位置" = the day that will roll off next
- Compare new day's close vs the roll-off day's close to predict MA60 direction

**Direction Rules:**
- new_close > roll_off_close → MA60 turns up tomorrow
- new_close < roll_off_close → MA60 turns down tomorrow

**Course warning against indicator-heavy approach:**
- "均線反而模糊了一根K線能夠表現出來的真正意義"
- Don't use Golden/Death Cross
- Don't draw too many MA lines

## Breakout Type Quality (Critical for Entry)

Source: 【買點賣點】進出場決策要點-序篇

| Breakout Type | Quality | Required Confirmation |
|---|---|---|
| 突破跳空 (gap on day+1 after breakout) | Stronger | Less needed |
| 跳空突破 (gap = breakout, on same day) | Weaker | Day-after follow-through critical |

Course only contrasts these two types in 進出場決策要點-序篇. "Flat-open breakout" was previously inferred but not stated by course — removed.

**For 跳空突破 (weak gap-breakout):** Course explicitly says "隔天是關鍵的走勢"
- Day after must continue attacking → OK
- Day after fails to attack → must exit

---

# Part 6.6: Additional Findings from Complete 58-Article Read

## Tweezer Top/Bottom (鑷頂/鑷底)

Source: 【型態判斷】鑷頂三篇

- **鑷頂**: 2-3 consecutive K bars with **same high**, **rising lows** → consolidating for breakout. Only meaningful at new-high zones. Breakout of the rest (高) signals progression; break of the last low signals failure.
- **鑷底**: 2-3 consecutive K bars with **same low**, **falling highs** → no rebound force. Only meaningful at new-low zones.

Code names: `tweezer_top`, `tweezer_bottom`

## Range Consolidation Trap (區間整理)

Source: 【型態判斷】區間整理走勢應有的認知

**Critical anti-pattern:** "Buy at box bottom, sell at box top" is WRONG.
- No market force exists to buy from you at box bottom and sell back at box top
- Wait for breakout/breakdown to determine direction
- Range is often a head pattern in disguise

## Head/Bottom Pattern Behavior (頭部底部)

Source: 【型態判斷】頭部底部合併要點(一)(二)

Two principles:
1. **成本原理** (cost/holding/attack costs)
2. **多空力量原理** (force change/patterns)

Critical asymmetry:
- 頭部 (head) > 底部 (bottom) importance — heads are real (trapped supply exists), bottoms might be just dip-buyers (no attack force)
- Bottom pattern complete ≠ attack guaranteed

Neckline break has two paths:
- A: Reclaim → range (MA60 direction loses meaning)
- B: Normal trend flip → bear (proper head completed)

## Bottoming Process (築底)

Source: 【型態判斷】築底的應對與實務意義

- Definition: After bear trend's significant drop, horizontal sideways with no rally desire and no aggressive selling
- NOT just any consolidation — needs bear-market context
- Can only be confirmed retrospectively
- For value/yield investing, NOT attack strategy

## False Breakdown Follow-up (假性跌破之後)

Source: 【突破跌破】整理趨勢進入型態判斷的關鍵-假性跌破之後

- After 假性跌破 (sudden break-then-reclaim), price may break again
- Second break (after recovery) without急跌 background = REAL breakdown, not false
- Background condition for 假性跌破: rapid/急 decline (not gradual)

## Advance Deployment vs Delayed Entry (提前部署 vs 延後進場)

Source: 【突破跌破】提前部署與延後進場

**提前部署 (Advance):**
- Condition: Current volume already exceeds past overhead-supply volume (price hasn't broken yet)
- Suits: stocks where breakout often retraces, not-first-time breakouts, market with rotating leadership
- Pro: Lower cost
- Con: No clean stop if breakout doesn't happen

**延後進場 (Delayed):**
- Wait until breakout + check no 雙鴉躍空 (Two Crows: red K → 2 short black Ks → gap down)
- Pro: Clear stop position
- Con: Higher entry cost

**Strong signal:** Stock making new high on a day when market is DOWN
- "退潮之下才知道誰在裸泳"
- "只有大盤不佳才能辨別誰真心想要攻擊"

## Self-Rescue Breakout (自救型突破)

Source: 【突破跌破】第二次突破型態的延伸運用之「自救型突破」

- Background: Was bull, hit news shock, defended, climbed back to prior high
- Re-breakout with LOWER volume than first breakout = self-rescue (NOT "價量背離")
- Reason: Original attackers still hold; no need to sell to themselves
- Decisive signal: NEXT-DAY gap-up attack
- Code: `self_rescue_breakout`

## Two Crows (雙鴉躍空) Definition

Source: 【突破跌破】提前部署與延後進場

> "遇到了前波壓力區域，紅K之後接續兩根短黑K，然後再出現一個向下跳空而成"

The DOWN-GAP is the deciding element for confirmation.
Code: `two_crows`

## Right-Top-Corner Concept (右上角的觀念)

Source: 【突破跌破】右上角的觀念

- Breakout new-high always appears at **upper-right corner** of K-chart
- Don't fear "buying high" — that's where attacks start
- People avoid right-side because they want to buy low (right-bottom)
- Crucial mental shift for breakout strategy

## Three Types of Selling Pressure (三種賣壓)

Source: 【突破跌破】研判阻礙上漲的力量

1. 獲利了結賣壓 (profit-taking)
2. 套牢賣壓 (trapped supply)
3. 恐慌性賣壓 (panic selling)

**判斷profit-taking method:**
- Look for reversal-K (黑K吞噬)
- Or repeated "red K → next-day black K" at same price level (multiple times → real supply)

## Volume Real Use (成交量真正用途)

Source: 【價量關係】成交量的實務意義(上)(下)

**核心結論：** "成交量的主要功能，是幫助判斷過去的套牢賣壓所在位置"

- NOT for "價漲量增/價跌量縮/價量背離" - those are WRONG
- USE分價量表 to find largest-volume zone = primary resistance
- Volume can be manufactured; don't trust volume increase alone
- Volume ONLY matters for identifying supply zones

## Black K Special Cases (黑K特殊位置)

Source: 【單一K線】黑K能告訴我們的事、高檔區域的長黑K

**高檔長黑** carries up to 3 meanings simultaneously:
1. Recent attack gap filled
2. Long black engulfs prior new-high red
3. One black K consumes 5 prior bars

When any 2-3 of these align in a single black K, attack is over.

**Same-price 紅K→黑K** repeated multiple times = real supply zone

## Doji Position-Based Interpretation

Source: 【單一K線】十字線在新高處 / 遇壓處 / 攻擊階段(上)(下)

**Three positions for doji:**

1. **At new high (剛創新高 doji)**:
   - Don't analyze shape — only watch for next K making new high
   - If next K makes new high → attack continues
   - If next K is black → exit consideration

2. **At pressure zone (遇壓 doji)**:
   - Position dominates, not shape
   - Supply zone is the deciding factor
   - Even breakout above doji may not be attack

3. **In attack phase**:
   - Short doji = both sides observing → next-day direction critical
   - Long doji = active battle → check for power continuation

**Multi-doji区间**:
- Consecutive dojis form a range
- Use range high/low as decision boundary

## Consecutive Red K Analysis (連續紅K)

Source: 【單一K線】紅色誤解：連續紅K的判斷要點 (already known)

Additional indicators of 「沒攻擊意圖」:
- Next-day open BELOW prior close = first warning
- New-high red K's close = max during day, but next day still opens low = second warning
- Reverse pattern: opens low → rallies = 紅三兵紅K but lacks attack
- Correct attack: rapid sequential upward, no low-buy opportunities

## Limit-Up One-Line (跳空漲停一條線)

Source: 【單一K線】跳空漲停一條線

Three types:
1. News-driven (人們以為的利多): May not have follow-through
2. Post-crash rebound: Weak, accidental
3. Attack-phase strength: Most meaningful for short-term traders

**典型攻擊型** vs **非典型**:
- 典型: Heavy prior accumulation, sustained
- 非典型: Low prior volume, sudden push (often fades quickly)

## Short Selling Difficulty (放空)

Source: 【買點賣點】放空與回補的要點講解

**為何放空困難:**
- 紅K needs追高 buyers; 黑K only needs no buyers
- Easy to short — hard to know when to cover
- Bull-market shorting risks short-squeeze
- "Multi-side judgment is easy but profit hard (psychology); short-side profit easy but judgment hard"

**Short entry standard:** 頸線跌破 (neckline break, MA60 down)
**Short cover:** 急殺 (急跌) cover, OR new low broken keeps holding short
**For long strategy:** Skip short side entirely

## Operation Style (操作屬性)

Source: 【買點賣點】先了解你的操作屬性

| Style | Entry | Stop | Hold |
|---|---|---|---|
| 波段 (Swing) | 突破買進 | 跌破突破點 | Days-weeks |
| 短線 (Short-term) | 攻擊才進場 | 攻擊跡象消失 | 1-5 days |
| 當沖 | Intra-day attack only | Intra-day fail | Same day |
| 隔日沖 | Strong close + gap-up next | Gap fill | Overnight |

For our system, we should choose ONE style — mixing without clear rules creates confusion.

## Five Key Principles (Consolidated)

After full read, the immutable core boils down to:

1. **Attack assumption**: All entries assume attack until proven otherwise
2. **No-percentage stops**: Pure pattern-based
3. **Position context**: Same K means different things in different positions
4. **Quarterly MA + Neckline**: Foundation for trend judgment
5. **Volume = supply zone identifier**: Not entry/exit signal


---

# Part 7: Past Mistakes (Documented for Memory)

1. **Mistakenly judged E4 as custom-added** — Course "紅色誤解：連續紅K的判斷要點" explicitly teaches "breakout K low break = stop"
2. **Used ret_10d as backtest metric** — Course requires actual exit conditions, not fixed N days
3. **Conflated gap_open with course's "gap"** — Course distinguishes attack gap vs general gap, very different meanings
4. **Over-trusted Spearman results** — close_pos is positive in course (buying strength), but negative in backtest. This means "our exit mechanism is too sensitive", not "course is wrong"
5. **Only implemented 1 of many reversal K patterns** — Course lists 5+ (空頭吞噬, 大敵當前, 雙鴉躍空, 夜星棄嬰, 暗夜雙星, 跳空反轉), we only did 暗夜雙星

---

# Part 8: Future Implementation Roadmap (Other Subcategories)

The K-line judgment intro (58 articles) is the foundation. Two other subcategories provide critical detail needed for full implementation. Reading priority is established here for future sessions.

## 多空轉折組合K線進階教學 (26 articles)

**Purpose:** Provides STRUCTURAL DEFINITIONS for all reversal-K patterns referenced (but not defined) in the judgment-intro subcategory. This is the missing source of truth for K-line pattern detection.

**TOC URL:** `articles/C99F5AC7CA9FED14A557A7A4A5592AA5`

### 多空轉折篇 (16 articles)

| Article | Key Pattern | Implementation Priority |
|---|---|---|
| 多空轉折組合的觀念與關鍵K線前言篇 | Foundation | Read first |
| 包覆線在轉折組合中的運用：空頭吞噬與多頭吞噬 | `bearish_engulfing`, `bullish_engulfing` | HIGH (we cite engulfing in exit rules) |
| 孕線在轉折組合中的運用：母子晨星 | `harami`, `morning_star_harami` | MEDIUM |
| 高檔下影線與低檔上影線：高檔吊首 | `hanging_man_high` | MEDIUM |
| 三根K線連續判斷多方力量意義：母子雙星 | `harami_two_stars` | LOW |
| **三根K線連續判斷阻礙力量出現：大敵當前** | `enemy_at_gate` | **HIGH (currently undefined!)** |
| 三根K線連續判斷阻礙力量的行動：暗夜雙星 | `dark_double_star` | HIGH (confirm our current definition) |
| 向下跳空出現的影響：跳空反轉與延伸解說 | `gap_reversal` | HIGH |
| 向下跳空形成的壓力：雙鴉躍空與延伸解說 | `two_crows` | HIGH (currently partial) |
| 三根K線連續判斷突破整理區間的力量：突破雙星 | `breakout_two_stars` | MEDIUM |
| **三根K線連續判斷在十字線之後：夜星棄嬰** | `evening_star_abandoned` | **HIGH (currently undefined!)** |
| 三根K線連續判斷十字線之後：夜星與島狀反轉 | `evening_star_island` | MEDIUM |
| 三根K線連續判斷十字線之後：晨星與島狀反轉 | `morning_star_island` | LOW |
| 黑三兵與外側三黑的組合判斷 | `three_black_crows`, `three_outside_blacks` | MEDIUM |
| 空方單日反轉的定義與日出日落 | `single_day_reversal_bear` | LOW |
| 多方單日反轉的實務意義 | `single_day_reversal_bull` | LOW |

### 非轉折組合補充篇 (10 articles)

Continuation patterns (mostly not directly used in our breakout strategy):
- 前言與K線的類別
- 包覆型態組合的意義
- 貫穿型態組合的力量
- 懷抱型態組合的分類
- 遭遇型態組合的變化
- 反撲型態組合的辨別
- 內困型態組合的要點
- 咬定型態組合的波動
- 升降組合型態的應用
- 上下缺回補型態組合的輔助

**Recommended reading order:** Foundation → 大敵當前 → 夜星棄嬰 → 空頭吞噬 → 跳空反轉 → 雙鴉躍空 → others as needed.

---

## K線行進ing (40 articles)

**Purpose:** Sequential K-line behavior — how K-lines combine over multiple days to express attack/failure. Bridges 入門 (single K) and 多空轉折 (pattern combinations).

**TOC URL:** `articles/291BAA04A7E19EE866699C3ADD3E68C3`

### 關鍵K線延伸篇 (4 articles)

| Article | Topic | Priority |
|---|---|---|
| 關鍵K線的定義與使用目的 | Re-statement (already covered) | LOW |
| 關鍵K線與型態學的連結判斷 | Pattern integration | MEDIUM |
| 關鍵K線與移動平均線的連結判斷 | MA60 integration | HIGH (precise neckline) |
| 關鍵K線與轉折K線的連結判斷 | Reversal integration | MEDIUM |

### 行進判斷 (26 articles) - Sequential K-line analysis

**紅K篇 (8 articles):**
| Article | Concept | Code Implementation |
|---|---|---|
| (一)定義與三連紅 | 紅三兵 baseline | `red_three_soldiers` |
| (二)紅K接著十字線、上影線 | After-red doji/upper-shadow | Already partially covered |
| (三)上升三法的成功與失敗 | `rising_three_methods` | HIGH for entry validation |
| (四)跳空漲停板一條線 | Already covered | Confirm details |
| (五)黑K接續出現 | Red→Black sequence | MEDIUM |
| (六)隨機漫步 | Non-attack noise | LOW |
| (七)日出攻擊 | `sunrise_attack` | **HIGH** (sunrise = key attack pattern) |
| (八)低檔紅K | Low-position red | LOW (not our strategy) |

**黑K篇 (7 articles):**
| Article | Concept | Code |
|---|---|---|
| (一)定義黑K | Foundation | LOW |
| (二)高檔長黑 | Already covered | Confirm |
| (三)一般頸線跌破 | Standard neckline break | HIGH for E3 refinement |
| (四)假性跌破 | Already covered | Confirm |
| (五)破底之後的黑K觀察要點 | Post-breakdown analysis | LOW |
| (六)賣壓中空的認知 | Supply vacuum (already covered) | Confirm |
| (七)低檔黑K的注意事項 | Low-position black | LOW |

**跳空篇 (5 articles):**
| Article | Concept | Code |
|---|---|---|
| (一)跳空的定義 | Foundation (mostly covered) | Confirm |
| (二)一般跳空的行進判斷 | General gap behavior | MEDIUM |
| (三)攻擊跳空的行進判斷 | `attack_gap_behavior` | **HIGH** (precise attack gap definition) |
| (四)轉折組合裡的跳空 | Gap in reversal patterns | MEDIUM |
| (五)空方趨勢的向下跳空 | Down-gap in bear | LOW (not main strategy) |

**影線篇 (3 articles):**
| Article | Concept | Code |
|---|---|---|
| 上影線(一)位置與定義的關聯 | Position-based interpretation | HIGH (refines our shadow scoring) |
| 上影線(二)不同位置的上影線 | Position variations | HIGH |
| 下影線與人們的想像不同 | Lower shadow myths | MEDIUM |

### K線事件判斷 (10 articles) - Event-driven K-line analysis

| Article | Concept | Priority |
|---|---|---|
| (一)利空界定與大盤大跌當日的股價低點 | Market-shock context | MEDIUM |
| (二)攻擊股價並非隨機漫步：高檔長黑、利空逆勢 | Attack vs random | HIGH |
| (三)享有高本益比的股票特質 | Premium stock traits | LOW |
| (四)利多利空出現的上漲 | News-driven rallies | MEDIUM |
| (五)非主流個股的K線走勢 | Non-mainstream stocks | LOW |
| (六)缺乏基本面支持的個股多方趨勢 | No-fundamentals rallies | LOW |
| (七)中期持有的挑戰 | Mid-term hold challenges | LOW |
| (八)攻擊階段的大小事件 | Attack-phase events | MEDIUM |
| (九)壓力現象的呈現 | Pressure manifestation | MEDIUM |
| (十)操作的開始與結束 | Operation lifecycle | LOW |

---

## Implementation Roadmap (Cross-Subcategory)

### Phase A: Core (Current — based on 判斷入門 only)
- ✓ Entry: `breakout_attack` (over-restricted, need refinement)
- ✓ Exit: E1 gap fill, E2 dark double star, E3 prior_low_20 proxy, E4 breakout-K low break
- ⚠ Score: scanner_score with extras

### Phase B: 多空轉折 Integration (Next session — read 多空轉折 first)
Required reads:
1. 大敵當前 (currently undefined — must read to implement `enemy_at_gate`)
2. 夜星棄嬰 (currently undefined — must read to implement `evening_star_abandoned`)
3. 空頭吞噬 detail (verify our definition)
4. 跳空反轉 detail
5. 雙鴉躍空 detail (already have partial)

Implementation targets after reading:
- Complete all 6+ reversal-K exits
- Precise neckline via 關鍵K線與移動平均線連結判斷

### Phase C: 行進ing Integration
Required reads:
1. 紅K篇(七)日出攻擊 — `sunrise_attack` entry pattern
2. 紅K篇(三)上升三法 — entry confirmation
3. 跳空篇(三)攻擊跳空 — precise attack gap
4. 上影線(一)(二) — position-based shadow scoring
5. 關鍵K線與移動平均線 — precise neckline via MA60

Implementation targets:
- Refine entry to include all 4 attack types (跳空/長紅/上影線/十字線 new high)
- Add `sunrise_attack` as score booster
- Add 上升三法 confirmation for re-breakouts

### Phase D: Final Polish
- Replace `prior_low_20` neckline proxy with precise MA60-based definition
- Replace `overhead_supply_layer` peak-count with proper volume profile
- Add position-aware shadow scoring (new-high / pressure / consolidation)
- Calibrate weights via re-run of attack_quality_analysis

---

# Appendix: Course Article Index

K線力量判斷入門 has 58 articles, organized:

- **單一K線** (13): red/black K basics, doji, shadows, gaps, limit-up line, high-level long black, black K, doji at new high/pressure, doji & upper shadow in attack stage, red misconception (consecutive red K)
- **移動平均** (2): MA60 with K-line H/L, MA prediction meaning
- **關鍵K線** (2): meaning and use, trend change key K
- **型態判斷** (6): head-bottom combined (1)(2), bottom building, range consolidation, tweezers top (1)(2)(3)
- **賣壓化解** (2): K research point, resolution meaning
- **突破跌破** (10): breakout meaning, strength start, top-right concept, blocking force, post-breakout traps, next-step thinking, false breakdown, self-rescue breakout, advance/delay entry, after false breakdown
- **價量關係** (2): volume meaning (upper/lower)
- **買點賣點** (13): buy definition, attack research, operating style, exit basis (1)(2), next buy point, long-side exit logic, entry-exit preface, three buy decisions (1)(2)(3), short & cover, exit (1)(2)(3)
- **停損** (2): setting principles (1)(2)
- **成本原理** (3): layered supply, supply vacuum, evaluate supply zone
