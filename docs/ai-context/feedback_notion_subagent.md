---
name: Notion 操作用 Haiku subagent
description: Notion MCP 操作（建頁、更新內容）應開 Haiku subagent 執行，不要佔用主 context
type: feedback
originSessionId: 11bb64c1-84ac-40bb-8bfb-182cbbdde4a3
---
Notion 的建頁與更新操作（create-pages、update-page）應開 Haiku subagent 執行。

**Why:** 這類操作是機械性的格式轉換，不需要深度推理，用 Haiku 最省 token。使用者明確要求「開 haiku subagent」。

**How to apply:** 每次要操作 Notion（建頁、更新 draft、寫分析結果）時，準備好 markdown 內容後，spawn `model="haiku"` 的 subagent 去執行 MCP 呼叫。
