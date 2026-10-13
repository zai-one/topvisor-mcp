---
name: topvisor-semantic-core
description: Semantics -> clusters -> positions inside one Topvisor project - collect phrases, check frequencies, dedupe, organise clusters into groups, then a priced rank check. Use for "собери семантику в топвизоре", "частотность и кластеры", "semantic core", "позиции по кластерам".
license: LicenseRef-ZAI-ONE
compatibility: Requires topvisor-mcp with TOPVISOR_TOOLSETS=all (semantics, analytics) and operator paid limits for launches. Self-contained.
metadata:
  service: topvisor
---
# Semantic core in Topvisor

Flow and parameters: [references/semantics.md](references/semantics.md). Costs: [references/pricing.md](references/pricing.md).
Errors: [references/errors.md](references/errors.md).

## Steps
1. Resolve `project_id` and `region_index`: `topvisor_list_projects` -> `topvisor_get_project_setup`.
   Ask for seeds (≤100), searcher and region (213 Москва).
2. `topvisor_balance`. Collect: `topvisor_semantics_price(kind="collect", ...)` -> show cost -> explicit OK ->
   `topvisor_semantics_launch(..., approved_cost=<that cost>, confirm_cost=true)`.
   Poll `topvisor_report(report="tasks")`, then `topvisor_list_keywords`.
3. Frequencies: same price -> OK -> launch with `kind="volumes"` (base + exact).
4. Clean: `topvisor_semantics_tools(action="deduplicate")`; drop exact frequency < 10, foreign brands.
5. Clusters: ask the user to run Кластеризация in the UI (no API start); poll
   `topvisor_semantics_tools(action="cluster_progress")`; read groups with `topvisor_list_groups`.
   Without UI access, group by shared head words and create groups via `topvisor_create_groups`
   + `topvisor_import_keywords` (dry-run, then apply=true after OK).
6. Map each cluster to a target URL (`topvisor_set_keyword_target`, dry-run first).
7. Positions: `topvisor_check_quote` -> OK -> `topvisor_check_launch` -> `topvisor_check_status`;
   then `topvisor_report(report="positions_summary")` and `topvisor_rank_changes`.
8. Output with [templates/semantic-core.md](templates/semantic-core.md).

## Guardrails
- One approval per paid step; never reuse an old price.
- Writes are dry-run until the user confirms the preview.
