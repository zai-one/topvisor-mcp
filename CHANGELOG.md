# Changelog

## Unreleased

- Follow the [single-competitor add contract](https://topvisor.com/ru/api/projects-2/competitors/add/) before 1 November 2026: `topvisor_competitors_write(action="add")` sends scalar `url`, optional `name` and `brand_name`; supports `service_name` (`positions` / `aiTracker`) and `brand_aliases`.
- Migration: use `url="example.org", name="Example"` instead of `urls=[...], names=[...]`. Deprecated `urls`/`names` remain single-item local aliases; multiple items, conflicting scalar/array arguments and unsupported `brand_names` are rejected before approval or dispatch. Bulk adds are never split into multiple requests; stray add arguments previously ignored are now refused. Other competitor actions are unchanged.
- Approvals and idempotency bind the normalized scalar request, including brand/service fields. Prepare a fresh approval after upgrading. Matching pending single-item adds from the old journal block the new request across actors/keys within the configured account, including a transactional re-check before reservation. Matching uses normalized URL plus optional name; a changed/omitted name is a different request. Reconcile pending legacy bulk adds before upgrading: the old journal retains hashes, so their individual items cannot be inferred. Old completed receipts keep their old identities; do not replay completed adds as fresh writes. No generic write-reconciliation CLI is introduced.

## 0.6.0 — Semantics and analytics coverage, router eval

- Upgrade note: `TOPVISOR_TOOLSETS=all` now also enables the new opt-in `semantics`, `analytics` and `competitors_write` toolsets (paid launches and writes still behind operator approval and the daily budget). Unset or `default` keeps the 0.5.0 surface; list toolsets explicitly if you relied on `all` meaning the previous set.
- Optional lazy tool loading (`TOPVISOR_TOOL_LOADING=eager|lazy`, default `eager` = unchanged): lazy lists a small core plus `topvisor_enable_toolsets` (toolsets with one-line description and token cost); enabling registers the tools at runtime and sends `notifications/tools/list_changed`. Allowlists, read-only mode and approval gates still apply. Setup wizard asks eager vs lazy. Startup tokens (tools/list + instructions, ≈chars/4): eager ≈5561, lazy ≈1196. Scope: enablement is per MCP session (FastMCP session visibility), so one client's enabled toolsets never appear for another. The HTTP transport here is stateless (every request is its own session), so enabled toolsets do not persist there: for shared HTTP use `eager` or `TOPVISOR_TOOLSETS`. README lazy section lists verified `tools/list_changed` client support with sources.
- Paid tasks `relevants` and `indexing` (projects_2/tasks) in `topvisor_semantics_price` / `_launch`; every paid `topvisor_semantics_launch` now also needs an operator-accepted, request-bound approval (`topvisor-approval`). Paid semantics launches reserve their estimate against `TOPVISOR_CHECK_DAILY_BUDGET` (shared with paid rank checks; an unknown dispatch outcome stays counted). Approvals are bound to the preparing actor.
- `topvisor_competitors_write` (opt-in toolset `competitors_write`): add/del/import, edit name/brand/on/move, approval-gated.
- Security (review fixes): approvals now live in the SQLite state database (durable commit, no shared `topvisor-approvals.json`) and are bound to `account_id`, the Topvisor user ID, the caller and the exact request including `project_id` (relevants/indexing payloads did not carry it), so an approval prepared for one account or project cannot authorise another. `operator_command` includes the absolute `--path` of the server's state database; `topvisor-approval` also accepts `--config`.
- Fix: a paid semantics launch uses its approval ID as a stable task ID, consumed in the same transaction as the budget reservation; an unknown dispatch outcome fences further paid tasks for the project until `topvisor-check-reconcile --check-id TASK_ID`, and a replay returns the stored receipt. `topvisor_competitors_write` goes through the persistent idempotency ledger with a competitor-list readback (new optional `idempotency_key`), so a lost reply is never resubmitted by a fresh approval.
- Snapshots no longer send or require `region_index` (not in the OpenAPI for snapshots_2); positions summaries still require it.

- Review fixes (topvisor-openapi): `search_updates` sends required `region_index` + `date`; summary/chart/snapshot reports require `date1`+`date2`; keyword collection into a group sends `in_one_group=true` with `to_group_id`.

- API re-check against topvisor-openapi (2026-10): positions summary/chart, snapshots, project competitors, tasks, audit/indexing/watcher summaries, apometr updates, bank history, keyword collection, frequency checks, deduplication and clustering progress were missing.
- New opt-in toolset `analytics` (off by default; default tools and token budget unchanged): `topvisor_report` over a fixed read allowlist.
- New opt-in toolset `semantics`: `topvisor_semantics_tools` (free deduplicate, cluster_progress), `topvisor_semantics_price` (collect / volumes price) and `topvisor_semantics_launch` (paid; same operator gate as paid rank checks: write enabled, project allowlisted, cost ≤ TOPVISOR_CHECK_MAX_COST, `approved_cost` equals a fresh price, `confirm_cost=true`).
- Skill `topvisor-semantic-core` (self-contained semantics -> clusters -> positions), guide `topvisor://guide/semantics`, prompt `semantic_core`.
- Router: one line per intent (RU/EN -> first tool; skill; guide) with `topvisor://playbook` and the generated `topvisor://guide/tool-map` as fallbacks; `TOPVISOR_TOOLSETS=default|all`.
- `tests/test_routing_eval.py` + `tests/evals/routing_cases.json` (20 RU/EN requests incl. paraphrases and negative cases): fails if any tool, skill or guide is unreachable.

## 0.5.0

- License: LicenseRef-ZAI-ONE 2.0 (source-available). Free install and use for yourself and your organisation, including commercial work; issues and pull requests welcome; copying code into other projects, redistribution, embedding and competing hosted services need written permission. Earlier releases keep their LicenseRef-ZAI-ONE 1.0 terms (see NOTICE). README first screen: one-line scope, why this MCP, maintenance and update check.

- Agent layer: router `instructions` (≤1200 chars), compact template descriptions (when to use / neighbour tool / cost) and titles on every tool.
- Toolsets `meta`, `positions`, `ai_tracker`, `checks`, `setup_write` via `TOPVISOR_TOOLSETS`, `TOPVISOR_TOOLS`, `TOPVISOR_DISABLED_TOOLS`, `TOPVISOR_READ_ONLY=1`; resource `topvisor://toolsets`. All toolsets stay enabled by default, so existing setups keep every tool.
- Resources `topvisor://playbook`, `topvisor://guide/{topic}` (pricing, report-template, errors); prompts `weekly_report`, `check_positions`.
- Self-contained skills: `topvisor-weekly-report`, `topvisor-rank-check-safe`, `topvisor-competitor-tracking`, cross-service `seo-weekly-client-report`; Claude Code plugin manifest, Cursor rule, `.agents/skills`.
- New read-only `topvisor_balance` (`bank_2/info`); `topvisor_positions_history(format="matrix")` compact keyword × date grid with `limit`/`offset`/`next_offset` paging and the same rank parsing as `topvisor_rank_changes` (`"--"` = not in depth, `null` = no data). The matrix returns one page at a time: keep requesting with `offset=next_offset` until it is `null`, or a large project shows only its first page. The default `format="raw"` is unchanged.
- `scripts/token_budget.py` + tests gate instructions, description and SKILL.md sizes.
- Install snippets in the Claude Code plugin manifest and README pin `git+https://github.com/zai-one/topvisor-mcp@v0.5.0` instead of the moving default branch.

## 0.4.0

- `topvisor_positions_history` accepts `serp_features` (`filter_by_serp_features`: `aiOverviewExists`, `images`, `video`, `knowledge`, `maps`), added to the Topvisor OpenAPI on 2026-10-08.
- Read-only AI tracker tools over `aiTracker_2`: `topvisor_ai_tracker_settings`, `topvisor_ai_tracker_summary`, `topvisor_ai_tracker_history`. Paid `checker/go` and `del/history` stay unavailable.
- `topvisor_check_update`: suggests an update from the latest GitHub release (24h cache, offline-safe, never installs); cached startup hint; opt out with `TOPVISOR_DISABLE_UPDATE_CHECK=1`.
- MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`) on every tool.
- Update check hardening: only plain numeric release tags are accepted; a failed attempt pauses checks for 30 minutes and `force_refresh` works at most once a minute; `topvisor_check_update` runs through the standard runtime (actor check, audit record, deadline) without spending Topvisor quota; the opt-out is documented in `.env.example`, `INSTALL.md` and `docs/RUNTIME.md`.

## 0.3.0

- Installable setup wizard and JSON/TOML client snippets that work outside the checkout.
- English and Russian agency information, integration contact and package installation guide.
- Saved-ranking comparison by relevant URL, with explicit missing/out-of-depth states and bounded JSON/CSV export.
- Five-minute price quotes and explicitly confirmed paid checks under an operator project allowlist and estimate budgets. Durable project fences block replay after uncertain outcomes; local reconciliation is required.
- Aggregate check status is shown separately from the launch receipt; it is not proof that a particular check completed.

## 0.2.0

- Explicit config-file startup and offline configuration doctor.
- Install/client guide, local setup wizard and clean-wheel validation.
- Read saved positions with topvisor_positions_history; region_indexes are indexes from project setup, not geographic region codes. Paid position checks are not exposed.
- LicenseRef-ZAI-ONE and Issues-based feedback policy.
