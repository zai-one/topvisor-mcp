# Changelog

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
