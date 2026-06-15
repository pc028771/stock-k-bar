/**
 * Backtest Grid Search Workflow 範本
 *
 * 用於對 detector / setup 做多變體 grid search、依方法論篩選。
 *
 * 使用方式: 拿這個 template 改 detector 名 + variant grid 條件、用 Workflow tool 跑。
 *
 * 強制紀律 (from references/methodology.md):
 * - 樣本小是 feature、不扣分
 * - 三條過濾: WR≥65% (任一窗口) AND 跨股≥5 AND 跨月≥2
 * - 物理意義講不清楚 = 過擬合、不選
 * - 反向訊號 (WR≤35% + n≥10 + 跨股≥5) 也要列
 * - N 日報酬作 ranking、實際出場用 C6 Rule A
 */

export const meta = {
  name: 'detector-grid-search-template',
  description: '依 backtest 方法論做 detector 變體 grid search',
  phases: [
    { title: 'Grid', detail: '12-15 變體、寬鬆 → 嚴格 stack' },
    { title: 'Backtest', detail: '每變體跑 2026 YTD、5d/10d/20d windows' },
    { title: 'Filter', detail: '三條過濾: WR≥65% / 跨股≥5 / 跨月≥2' },
    { title: 'Pick', detail: 'top 3-5 + 反向訊號' },
  ],
}

// ── Schema (固定、不可改) ────────────────────────────────────────────────

const VARIANT_SCHEMA = {
  type: 'object',
  required: ['variants'],
  properties: {
    variants: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'description', 'conditions'],
        properties: {
          id: { type: 'string' },
          description: { type: 'string', description: '一句白話: 物理意義、講不清楚 = 過擬合' },
          conditions: { type: 'object' },  // detector-specific
        },
      },
    },
  },
}

const BT_SCHEMA = {
  type: 'object',
  required: [
    'variant_id', 'n_hits', 'n_unique_tickers', 'n_unique_months',
    'fwd5_wr', 'fwd5_avg', 'fwd10_wr', 'fwd10_avg', 'fwd20_wr', 'fwd20_avg',
    'passes_methodology', 'reason',
  ],
  properties: {
    variant_id: { type: 'string' },
    n_hits: { type: 'integer' },
    n_unique_tickers: { type: 'integer' },
    n_unique_months: { type: 'integer' },
    fwd5_wr: { type: 'number' },
    fwd5_avg: { type: 'number' },
    fwd10_wr: { type: 'number' },
    fwd10_avg: { type: 'number' },
    fwd20_wr: { type: 'number' },
    fwd20_avg: { type: 'number' },
    passes_methodology: { type: 'boolean' },  // WR≥65% (任一) AND tickers≥5 AND months≥2
    reason: { type: 'string' },
    top_5_hits: { type: 'array', items: { type: 'object' } },
  },
}

const PICK_SCHEMA = {
  type: 'object',
  required: ['recommendation_zh', 'top_variants', 'counter_examples', 'reverse_signals', 'next_steps'],
  properties: {
    recommendation_zh: { type: 'string', description: '白話一句、不要 jargon' },
    top_variants: {
      type: 'array',
      items: {
        type: 'object',
        required: [
          'rank', 'variant_id', 'physical_meaning', 'why_top',
          'fwd5_wr', 'fwd5_avg', 'fwd20_wr', 'fwd20_avg',
          'n_hits', 'unique_tickers', 'unique_months', 'sample_size_judgement',
        ],
      },
    },
    counter_examples: { type: 'array', items: { type: 'string' } },
    reverse_signals: { type: 'array', items: { type: 'string' } },  // WR≤35% 也是訊號
    next_steps: { type: 'string' },
  },
}

// ── Workflow body ────────────────────────────────────────────────

phase('Grid')
const grid = await agent(`
你是 detector 變體設計者。依 methodology.md 三鐵則設計 12-15 個變體。

🔴 從寬鬆 baseline → 中等 stack → 重 stack → 極端 stack (n<10 也 OK)
🔴 每個變體 description 寫物理意義 (一句白話)
🔴 條件互斥前 sanity check (避免 n=0)
🔴 [detector-specific conditions 在這裡描述]

回 schema。
`, { schema: VARIANT_SCHEMA, model: 'opus' })

log(`設計 ${grid.variants.length} 個變體`)

phase('Backtest')
const results = await pipeline(
  grid.variants,
  (v) => agent(`
跑 [detector_name] 變體 ${v.id} 的 2026 YTD backtest。

🔴 樣本小是 feature、不扣分
🔴 passes_methodology 三條 hard rule: WR≥65% (任一窗口) AND tickers≥5 AND months≥2
🔴 N 日報酬只作 ranking、實際出場用 C6 Rule A

寫 Python script + 跑 + CSV 寫到 /tmp/variant_${v.id}.csv

回 schema。
  `, {
    label: `bt:${v.id}`,
    phase: 'Backtest',
    schema: BT_SCHEMA,
    model: 'sonnet',
  }),
)

const valid = results.filter(Boolean)
const passing = valid.filter(r => r.passes_methodology)
log(`${passing.length}/${valid.length} 過方法論`)

phase('Pick')
const pick = await agent(`
從 ${valid.length} 個變體挑 top 3-5。

🔴 樣本小不扣分 (n=10-30 是 feature)
🔴 嚴格 stack 優先
🔴 物理意義講不清楚的 skip
🔴 也找 2-3 個反向訊號 (WR≤35% + n≥10)

passing: ${passing.map(r => `${r.variant_id} n=${r.n_hits} fwd20_wr=${r.fwd20_wr}%`).join('\n')}

回 schema。
`, { schema: PICK_SCHEMA, model: 'opus' })

return {
  variants_tested: valid.length,
  variants_passing: passing.length,
  ...pick,
}
