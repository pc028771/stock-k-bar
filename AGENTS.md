# AGENTS.md

## Project Context

This repository is used to convert the course notes from `K線力量判斷入門` into testable stock-analysis rules, backtests, and eventually daily screening/watchlist tools.

The primary goal is not to reproduce course content. The goal is to extract strategy-relevant indicators, translate them into measurable features, validate them with market data, and document which indicators are ready for strategy prototypes versus which still need annotation or research.

The working direction is deliberately incremental:

1. Extract course-derived indicators into measurable rules.
2. Classify indicators by whether they are ready for strategy prototypes.
3. Validate one strategy family at a time.
4. Turn validated strategy families into daily scanners/watchlists.
5. Only then move into more subjective chart-pattern and pressure-zone research.

Avoid jumping directly from a course concept to a trading rule. Each rule must pass through measurable definition, backtest, interpretation, and documentation.

## Data And Backtest Policy

- Use `/Users/howard/.four_seasons/data.sqlite` as the primary local daily-K database for broad market validation, full-universe scans, and daily watchlist generation.
- Keep custom Python backtests as the main research pipeline because the course-derived rules require custom features, custom exclusions, and full-market scanning.
- Use FinMind API/DataLoader as a supplemental data source for missing data, cross-checking daily data, and fetching minute-K data when intraday validation is needed.
- FinMind backtest can be used for quick single-stock sanity checks or comparison runs, but it should not replace the local SQLite-based research pipeline.
- For minute-K cache sharing across repositories, default cache path is `~/.four_seasons/finmind_kbar_cache`; override with `FINMIND_KBAR_CACHE_DIR` when needed.

Rationale:

- The target workflow is full-market screening, not only single-stock backtesting.
- Local SQLite already contains fields needed by this project, including attention/disposition flags, liquidity fields, technical fields, and local data-quality status.
- Course concepts such as false breakdown, neckline, supply zones, box patterns, and selling-pressure gaps require custom feature engineering and annotation.
- Daily practical output should be a scanner/watchlist with ticker, signal date, key level, confirmation status, stop reference, and ranking score.

## Established Workflow

When working on this project, use the following loop:

1. Read the relevant docs first, especially:
   - `docs/K線力量判斷入門/strategy-indicators.md`
   - `docs/K線力量判斷入門/strategy-readiness.md`
   - `docs/K線力量判斷入門/strategy-validation-plan.md`
   - existing files under `docs/K線力量判斷入門/backtests/`
2. Implement or adjust a focused script under `scripts/`.
3. Write machine-readable outputs under `data/analysis/kline_course_backtest/`.
4. Write a concise Markdown report under `docs/K線力量判斷入門/backtests/`.
5. Update `strategy-readiness.md` and `strategy-validation-plan.md` when a task changes strategy status or task order.
6. Run at least a syntax check or the relevant script before claiming the work is complete.

Prefer small, sequential research steps. Do not combine market regime, stop-loss redesign, failure analysis, and scanner construction in one unreviewable change.

## Strategy Maturity Rules

Classify each indicator as one of the following:

- `entry_signal`: can directly create a candidate trade setup after validation.
- `filter`: improves or weakens another signal but should not be traded alone.
- `exit_or_risk_rule`: useful for stop, invalidation, sizing, or holding decisions.
- `position_tool`: defines a level, box, neckline, or reference area but has no standalone direction.
- `research_candidate`: still needs annotation, better data, or a stronger proxy.

Do not promote a `research_candidate` into a strategy unless the rule has:

- a measurable definition,
- a backtest or documented validation result,
- clear execution timing,
- cost/slippage assumptions,
- liquidity and attention/disposition handling,
- and a report explaining whether it is an entry, filter, exit/risk rule, or position tool.

## Current Findings

The strongest current candidate is `false_breakdown_reclaim`.

Current interpretation:

- It is a reversal strategy prototype, not an immediate intraday attack signal.
- It detects stocks that recently dropped hard, broke below an important prior low intraday, and then closed back above that key level.
- It has survived the first extra validation pass with transaction cost, liquidity, attention/disposition exclusions, next-day confirmation, and a simple stop check.
- The next useful checks are market regime, ATR/box-low stop, and failure-case analysis.

Useful current variants:

- `tradable_filter`: exclude attention/disposition stocks, low liquidity, and very low price stocks.
- `tradable_next_close_confirm`: wait for next-day close to remain above the key level, then enter on the following open.
- `tradable_close_pos_ge_0_7`: prioritize cases where the signal day closes near the high.
- `tradable_panic_drop_ge_10pct`: prioritize deeper short-term panic drops.

The following are not yet ready as standalone strategies:

- doji direction rules,
- real breakdown after range,
- lower-shadow support,
- supply/selling-pressure zones,
- neckline/head/bottom pattern rules,
- short-selling and cover rules,
- jump-gap/limit-up rules without event and tradability handling.

## Backtest Conventions

For course-derived daily-K strategy checks:

- Signal is assumed known after the signal day close.
- Default execution is next trading day open unless the variant explicitly waits for confirmation.
- Use 5/10/20 trading-day horizons for initial comparison.
- Report both gross and net returns when a strategy is close to trading use.
- Apply a round-trip cost assumption before calling a result strategy-ready. The current prototype uses `0.585%` as a conservative approximation.
- Exclude or separately report attention stocks and disposition stocks for tradable strategies.
- Include liquidity filters before treating results as practical.
- Use daily-low stop checks only as a rough approximation; document that daily bars cannot know exact intraday fill quality.
- Treat FinMind minute-K checks as validation samples unless a task explicitly expands them into a broader data pipeline.

Required report elements:

- sample range,
- data source,
- signal definition,
- execution timing,
- cost and exclusion assumptions,
- core result table,
- interpretation,
- limitations,
- next step.

## Output Locations

Use these paths consistently:

- Scripts: `scripts/*.py`
- Backtest reports: `docs/K線力量判斷入門/backtests/*.md`
- Strategy overview: `docs/K線力量判斷入門/strategy-indicators.md`
- Strategy readiness: `docs/K線力量判斷入門/strategy-readiness.md`
- Task/model plan: `docs/K線力量判斷入門/strategy-validation-plan.md`
- Optional visual task board: `docs/K線力量判斷入門/strategy-validation-plan.html`
- CSV outputs: `data/analysis/kline_course_backtest/*.csv`

Do not write generated analysis files outside this structure unless the user asks for a different destination.

## Current Strategy Priority

Follow `docs/K線力量判斷入門/strategy-validation-plan.md` for task order and model choice.

Current priority:

1. Continue breakout-attack validation after the first tradable-version backtest.
2. Treat `breakout_next_not_low_open` as a conditional quality filter candidate, not a universal trade filter.
3. Focus next on using breakout intraday-quality signals for watchlist ranking rather than hard entry gating.

Only after Phase 1 is stable should agents move to breakout-attack strategy validation.

## Task Execution Direction

Near-term sequence:

1. Maintain and iterate the first breakout watchlist version (`scripts/breakout_daily_scanner.py` and related CSV/report outputs).
2. Expand FinMind-supported intraday sampling only after validating whether the watchlist ranking improves practical selection quality.

For each task, preserve the distinction between:

- research validation,
- strategy prototype,
- and practical daily scanner.

Do not make claims about live trading readiness from a single backtest table.

## Model Selection Guidance

- Use `gpt-5.3-codex` for clear coding/data tasks: Python, SQLite, CSV, backtests, scanner scripts, and report generation.
- Use `gpt-5.4` for mixed research and engineering tasks: failed-case analysis, intraday-quality interpretation, and rule refinement.
- Use `gpt-5.5` for high-level strategy interpretation: translating course semantics, chart patterns, pressure zones, neckline/box definitions, and other subjective rules into measurable specifications.

## Documentation Outputs

When adding or changing validation work, update the relevant documents:

- `docs/K線力量判斷入門/strategy-readiness.md`
- `docs/K線力量判斷入門/strategy-validation-plan.md`
- `docs/K線力量判斷入門/backtests/*.md`

Keep reports concise and focused on whether a rule can become:

- an entry signal,
- a filter,
- an exit/risk rule,
- or only a labeling/research candidate.

When a plan changes, update both:

- `strategy-validation-plan.md`
- `AGENTS.md` if the change affects project-level direction or workflow.

## Shared Intraday Cache Warmup

- Use `scripts/warmup_finemind_intraday_cache.py` for nightly prefetch of minute-K data.
- The script writes shared cache files to `~/.four_seasons/finmind_kbar_cache` (or `FINMIND_KBAR_CACHE_DIR` if set).
- Candidate universe follows breakout scanner hard filters: TWSE/TPEx only, construction-related exclusions, active DB exclusion list, tradability constraints.
- Recommended nightly run pattern:
  - `--days-back 90`
  - `--max-per-date 30`
  - `--max-requests 5000`
  - `--sleep-seconds 0.2`
- Run the daily scanner after warmup so ranking can reuse cached intraday data with minimal daytime API load.

## Copyright And Course Content

Do not reproduce paid course articles verbatim. Store only summaries, derived rules, indicators, metadata, and analysis outputs needed for personal strategy research.
