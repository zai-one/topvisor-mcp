---
name: topvisor-weekly-report
description: Weekly SEO ranking report from saved Topvisor positions (free, no paid checks) - TOP-3/10/30, movers, URL changes. Use for "отчёт по позициям", "weekly rankings", "что с позициями за неделю".
license: LicenseRef-ZAI-ONE
compatibility: Requires the topvisor-mcp server (tools topvisor_*).
metadata:
  service: topvisor
---
# Topvisor weekly report

Uses only saved data. Never call `topvisor_check_launch` in this skill.

## Steps
1. `topvisor_list_projects` → pick the project (ask if ambiguous).
2. `topvisor_get_project_setup(project_id)` → list searchers/regions; use every `region_index` the user
   cares about (default: all, max 10).
3. Dates: default last two saved check dates ≈ 7 days apart (ask or use `topvisor_positions_history`
   with `format="matrix"` over the last 14 days to see which dates have data).
4. For each region: `topvisor_rank_changes(project_id, region_index, before_date, after_date)`;
   page with `offset` when `limit` (≤250) is reached.
5. Compute per region: count in TOP-3/10/30 for both dates, Δ, average of ranked positions,
   10 best/worst movers (Δ = before − after), keywords with changed URL.
6. Fill [templates/report-template.md](templates/report-template.md). Markdown tables, no raw JSON.
7. If data is stale, offer skill `topvisor-rank-check-safe` (paid) — do not run it unasked.

## Guardrails
- Not ranked = missing / 0 / >100; exclude from averages, count separately.
- Do not invent numbers; state the dates used.
- Errors: see [references/errors.md](references/errors.md).
