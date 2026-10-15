# Topvisor playbook

1. **Resolve IDs** — `topvisor_list_projects` → `topvisor_get_project_setup(project_id)` gives searchers and
   `region_index` values. Never guess IDs.
2. **Read saved data (free)** — `topvisor_rank_changes` for two dates (weekly report),
   `topvisor_positions_history(format="matrix")` for trends (≤31 dates), AI tracker tools for LLM visibility.
3. **Fresh check (paid)** — `topvisor_balance` → `topvisor_check_quote` → show price → explicit user OK →
   `topvisor_check_launch` once → `topvisor_check_status`. Outcome `unknown` is never retried blindly:
   run `topvisor-check-reconcile` or check the Topvisor UI.
4. **Setup writes** — every write tool previews by default; repeat with `apply=true` only after the user
   confirms the preview. Same `idempotency_key` = same write.

5. **Semantics → clusters → positions** (opt-in `semantics`) — price/launch keyword collection and
   frequency checks, dedupe, clusters as groups, then a quoted rank check: `topvisor://guide/semantics`,
   skill `topvisor-semantic-core`.
6. **Summaries** (opt-in `analytics`) — `topvisor_report`: positions summary/chart, TOP snapshots,
   competitors, tasks, audit/indexing/watcher, search-engine updates, bank history.

Skills: `topvisor-weekly-report`, `topvisor-rank-check-safe`, `topvisor-competitor-tracking`,
`seo-weekly-client-report`, `topvisor-semantic-core`. Guides: `topvisor://guide/pricing`,
`topvisor://guide/report-template`, `topvisor://guide/semantics`, `topvisor://guide/errors`,
`topvisor://guide/tool-map` (every tool by toolset), `topvisor://toolsets`.
