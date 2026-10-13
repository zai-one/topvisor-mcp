# Changelog

## Unreleased

- Agent layer: router `instructions` (≤1200 chars), compact template descriptions (when to use / neighbour tool / cost) and titles on every tool.
- Toolsets `meta`, `positions`, `ai_tracker`, `checks`, `setup_write` via `TOPVISOR_TOOLSETS`, `TOPVISOR_TOOLS`, `TOPVISOR_DISABLED_TOOLS`, `TOPVISOR_READ_ONLY=1`; resource `topvisor://toolsets`.
- Resources `topvisor://playbook`, `topvisor://guide/{topic}` (pricing, report-template, errors); prompts `weekly_report`, `check_positions`.
- Self-contained skills: `topvisor-weekly-report`, `topvisor-rank-check-safe`, `topvisor-competitor-tracking`, cross-service `seo-weekly-client-report`; Claude Code plugin manifest, Cursor rule, `.agents/skills`.
- New read-only `topvisor_balance` (`bank_2/info`); `topvisor_positions_history(format="matrix")` compact keyword × date grid with `limit`/`offset`/`next_offset` paging and the same rank parsing as `topvisor_rank_changes` (`"--"` = not in depth, `null` = no data).
- `scripts/token_budget.py` + tests gate instructions, description and SKILL.md sizes.

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
