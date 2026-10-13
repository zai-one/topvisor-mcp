---
name: topvisor-competitor-tracking
description: Track competitors with Topvisor data - AI-tracker competitor visibility/sentiment vs own brand and keywords lost from TOP-10. Use for "конкуренты в Topvisor", "AI visibility vs competitors", "кто забрал запросы".
license: LicenseRef-ZAI-ONE
compatibility: Requires topvisor-mcp; keysso-mcp optional for domain-level research.
metadata:
  service: topvisor
---
# Competitor tracking

Free reads only. Background: [references/competitors.md](references/competitors.md).

## Steps
1. Resolve project (`topvisor_list_projects`).
2. AI visibility: `topvisor_ai_tracker_settings(project_id, show_available_models=true)` → model keys and
   competitor IDs. For own brand and each competitor (≤5): `topvisor_ai_tracker_summary(project_id,
   model_key, dates, competitor_id)`. Table: entity × mentions / visibility / sentiment, Δ between dates.
3. Lost queries: `topvisor_rank_changes` for the two dates; list keywords that left TOP-10 or changed URL.
4. Summarise: who gains in AI answers, which queries were lost, 3 suggested actions.
5. Optional: if keysso-mcp is connected, hand the competitor domains to skill `keysso-competitor-research`.

## Guardrails
- Do not request `response`/`metadata` history fields unless the user asks (large texts).
- Never launch paid checks here; refer to `topvisor-rank-check-safe`.
