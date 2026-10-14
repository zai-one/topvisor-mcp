# Topvisor semantics: collect -> frequencies -> clusters -> positions

Opt-in toolsets: `TOPVISOR_TOOLSETS=default,semantics,analytics` (or `all`).

| Step | Tool | Notes |
|---|---|---|
| Collect phrases | `topvisor_semantics_price(kind="collect", project_id, keywords=seeds, searcher, region_key, group_id)` -> `topvisor_semantics_launch(..., approved_cost, confirm_cost=true)` | searcher: yandex, google, bing, yandex_hints, google_hints, youtube_hints, bing_hints; `minus_keywords`, `depth` 1–10 |
| Frequencies | `kind="volumes"`, `volume_types` base/phrase/exact/ordered/exact_ordered, optional `group_id` | yandex or google only |
| Dedupe | `topvisor_semantics_tools(action="deduplicate", keywords)` | free; ignores word order / stop words |
| Clusters | Topvisor clustering runs in the UI (Ядро → Кластеризация); `topvisor_semantics_tools(action="cluster_progress", project_id)` reads %; result = keyword groups (`topvisor_list_groups`, `topvisor_list_keywords`) | API has no public start method |
| Organise | `topvisor_create_folder`, `topvisor_create_groups`, `topvisor_import_keywords` (dry-run -> apply=true) | targets per cluster with `topvisor_set_keyword_target` |
| Positions | `topvisor_check_quote` -> OK -> `topvisor_check_launch` -> `topvisor_check_status` -> `topvisor_rank_changes` | paid |
| Summary | `topvisor_report(report="positions_summary", project_id, region_index)` | tops, avg, visibility, dynamics |
| Tasks | `topvisor_report(report="tasks", project_id)` | progress of collect/volumes |

Paid launches need the operator gate: `TOPVISOR_WRITE_ENABLED=true`, the project in
`TOPVISOR_CHECK_PROJECTS`, cost ≤ `TOPVISOR_CHECK_MAX_COST`, and `approved_cost` equal to a fresh price.
Other `topvisor_report` values: summary_chart, snapshots_history, snapshots_competitors, competitors,
audit_summary, indexing_summary, watcher_summary, search_updates (apometr: region_index + date1), bank_history. Summary, chart and snapshot reports need date1 and date2.
