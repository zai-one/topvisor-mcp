"""Topvisor agent profile: router, compact descriptions, toolsets and prompts."""

from __future__ import annotations

from zai_topvisor.agent_layer import Profile, Prompt

ROUTER = """Topvisor MCP: saved SEO rankings, keyword inventory, AI-tracker and guarded paid rank checks.
Toolsets: meta, positions, ai_tracker, checks, setup_write (see topvisor://toolsets).
Start: topvisor_list_projects -> topvisor_get_project_setup for project_id/region_index. Never guess IDs.
Reads are free and use saved data. Fresh rank checks cost money: topvisor_balance -> topvisor_check_quote \
-> show price to user -> topvisor_check_launch(quote) only after explicit OK -> topvisor_check_status.
Writes are dry-run by default; re-run with apply=true only after the user confirms the preview.
Reports: positions_history(format="matrix") or rank_changes (two dates) keep output small.
Playbooks: skills topvisor-weekly-report, topvisor-rank-check-safe, topvisor-competitor-tracking, \
seo-weekly-client-report; or topvisor://playbook, topvisor://guide/{pricing,report-template,errors}.
Errors: retry only when the error says retryable; follow its hint."""

DESCRIPTIONS = {
    "topvisor_balance": "Read the account balance. Use before any paid check; for a check price use "
    "`topvisor_check_quote`. Cost: free. Returns balance_all/personal/bonus/plan.",
    "topvisor_list_projects": "List projects with IDs and URLs. Use first to resolve project_id; for one "
    "project's engines/regions use `topvisor_get_project_setup`. Cost: free. Paged by limit/offset.",
    "topvisor_get_project_setup": "Read one project's searchers and regions (region_index). Use before "
    "positions or quotes; to find new regions use `topvisor_search_regions`. Cost: free.",
    "topvisor_list_keywords": "List keyword metadata for a project. Use for inventory; for rankings use "
    "`topvisor_positions_history`. Cost: free; never runs checks. Paged by limit/offset.",
    "topvisor_list_folders": "List keyword folders of a project. Use before imports; for groups use "
    "`topvisor_list_groups`. Cost: free.",
    "topvisor_list_groups": "List keyword groups of a project. Use before imports; for folders use "
    "`topvisor_list_folders`. Cost: free.",
    "topvisor_search_regions": "Search the region catalog for a search engine. Use before add/import "
    "regions; for regions already in a project use `topvisor_get_project_setup`. Cost: free.",
    "topvisor_positions_history": "Read saved positions for 1-31 dates. Use for trends; for a two-date "
    'diff use `topvisor_rank_changes`. Cost: free. format="matrix" returns a compact keyword x date grid; '
    "page keywords with next_offset.",
    "topvisor_rank_changes": "Compare saved ranks and URLs between two dates. Use for weekly reports; for "
    "many dates use `topvisor_positions_history`. Cost: free. Returns rows with delta and URL summary.",
    "topvisor_ai_tracker_settings": "Read AI-tracker settings and model keys. Use before AI summary/history. "
    "Cost: free.",
    "topvisor_ai_tracker_summary": "Read saved AI-answer mentions, visibility and sentiment for one model. "
    "Use for brand visibility in LLMs; per prompt use `topvisor_ai_tracker_history`. Cost: free.",
    "topvisor_ai_tracker_history": "Read saved AI-tracker results per prompt. Use for detail after the "
    "summary; response/metadata fields are large, request only if needed. Cost: free.",
    "topvisor_check_quote": "Get a 5-minute price quote for a fresh rank check. Use before "
    "`topvisor_check_launch`; show the price to the user. Cost: free, no dispatch.",
    "topvisor_check_launch": "Launch a quoted paid rank check once. Use only after the user approved the "
    "quote price; then poll `topvisor_check_status`. Cost: spends account balance (quote amount).",
    "topvisor_check_status": "Read the local receipt and project check status. Use after a launch; when "
    "done read `topvisor_rank_changes`. Cost: free.",
    "topvisor_create_project": "Create a project (dry-run default). Use for onboarding; apply=true only "
    "after user confirms the preview. Writes: idempotent.",
    "topvisor_create_folder": "Create a keyword folder (dry-run default). Use before imports; apply=true "
    "after confirmation. Writes: idempotent.",
    "topvisor_create_groups": "Create missing groups in a folder (dry-run default). apply=true after "
    "confirmation. Writes: idempotent.",
    "topvisor_import_keywords": "Import up to 1,000 missing keywords with targets/folders/groups (dry-run "
    "default). Prefer over `topvisor_add_keywords`. Writes: apply=true after confirmation.",
    "topvisor_add_keywords": "Legacy: import keywords under one folder path. Prefer "
    "`topvisor_import_keywords`. Writes: dry-run default.",
    "topvisor_set_keyword_target": "Set one keyword's target URL (dry-run default; overwrites). "
    "Writes: apply=true after confirmation.",
    "topvisor_set_keyword_tags": "Set/add/remove color tags 1..10 on a keyword (dry-run default). "
    "Writes: apply=true after confirmation.",
    "topvisor_add_searcher": "Add a search engine to a project (dry-run default). Then add regions with "
    "`topvisor_add_region`. Writes: apply=true after confirmation.",
    "topvisor_add_region": "Add one region/depth to a project searcher (dry-run default). For many use "
    "`topvisor_import_regions`. Writes: apply=true after confirmation.",
    "topvisor_import_regions": "Import searcher/region rows in bulk (dry-run default). Find keys with "
    "`topvisor_search_regions`. Writes: apply=true after confirmation.",
    "topvisor_apply": "Legacy single keyword/group write. Prefer the typed dry-run tools. "
    "Writes: dry-run default.",
    "topvisor_check_update": "Check for a newer server release; never installs. Cost: free, 24h cache.",
}

TOOLSETS = {
    "meta": ("topvisor_check_update", "topvisor_balance"),
    "positions": (
        "topvisor_list_projects",
        "topvisor_get_project_setup",
        "topvisor_list_keywords",
        "topvisor_list_folders",
        "topvisor_list_groups",
        "topvisor_search_regions",
        "topvisor_positions_history",
        "topvisor_rank_changes",
    ),
    "ai_tracker": (
        "topvisor_ai_tracker_settings",
        "topvisor_ai_tracker_summary",
        "topvisor_ai_tracker_history",
    ),
    "checks": ("topvisor_check_quote", "topvisor_check_launch", "topvisor_check_status"),
    "setup_write": (
        "topvisor_create_project",
        "topvisor_create_folder",
        "topvisor_create_groups",
        "topvisor_import_keywords",
        "topvisor_add_keywords",
        "topvisor_set_keyword_target",
        "topvisor_set_keyword_tags",
        "topvisor_add_searcher",
        "topvisor_add_region",
        "topvisor_import_regions",
        "topvisor_apply",
    ),
}

PROMPTS = (
    Prompt(
        "weekly_report",
        "Weekly ranking report for one Topvisor project from saved data (free).",
        ("project", "before_date", "after_date"),
        "Build a weekly SEO ranking report for Topvisor project {project} comparing {before_date} and "
        "{after_date}. Follow skill topvisor-weekly-report (or read topvisor://guide/report-template): "
        "resolve IDs, use topvisor_rank_changes per region, compute TOP-3/10/30 and movers. "
        "Do not launch paid checks.",
    ),
    Prompt(
        "check_positions",
        "Run a fresh paid rank check safely: balance, quote, confirm, launch, poll.",
        ("project",),
        "Refresh rankings for Topvisor project {project}. Follow skill topvisor-rank-check-safe: "
        "topvisor_balance, topvisor_check_quote, show the price and wait for my explicit OK, then "
        "topvisor_check_launch once and poll topvisor_check_status. Never launch without my OK.",
    ),
)

PROFILE = Profile(
    service="topvisor",
    package="zai_topvisor",
    router=ROUTER,
    descriptions=DESCRIPTIONS,
    toolsets=TOOLSETS,
    prompts=PROMPTS,
)
