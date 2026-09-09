from __future__ import annotations

from functools import partial
from typing import Any, cast
from urllib.parse import urlsplit

from zai_topvisor.adapter import (
    ADD_FOLDER_OPERATION,
    ADD_GROUP_OPERATION,
    ADD_PROJECT_OPERATION,
    ADD_REGION_OPERATION,
    ADD_SEARCHER_OPERATION,
    IMPORT_KEYWORDS_OPERATION,
    IMPORT_REGIONS_OPERATION,
    LEGACY_WRITE_OPERATIONS,
    SET_KEYWORD_TAGS_OPERATION,
    SET_KEYWORD_TARGET_OPERATION,
    TopvisorAdapter,
    normalize_keyword,
)
from zai_topvisor.transport import ProviderError


def register_tools(server: Any, runtime: Any) -> None:
    registry = runtime
    settings = runtime
    require_scopes = runtime.require_scopes
    safe_provider_error = runtime.safe_error
    _provider_read = runtime.read
    _autonomous_write = runtime.write

    @server.tool(auth=require_scopes("topvisor:read"))
    async def topvisor_positions_history(
        project_id: int, region_indexes: list[int], dates: list[str], limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """Read saved positions by date and project region index; never starts checks."""
        adapter = registry.topvisor()
        arguments = dict(
            project_id=project_id, region_indexes=region_indexes, dates=dates, limit=limit, offset=offset
        )
        return {
            "payload": await _provider_read(
                "topvisor",
                "positions_history",
                arguments,
                lambda: adapter.positions_history(**arguments),
                validate=lambda: adapter.validate_history(**arguments),
            )
        }

    @server.tool(auth=require_scopes("topvisor:read"))
    async def topvisor_list_projects(
        limit: int = 100, offset: int = 0, include_positions_summary: bool = False
    ) -> dict[str, Any]:
        """List bounded Topvisor projects through the server-side credential."""
        adapter = registry.topvisor()
        return {
            "payload": await _provider_read(
                "topvisor",
                "projects",
                {
                    "limit": limit,
                    "offset": offset,
                    "include_positions_summary": include_positions_summary,
                },
                lambda: adapter.projects(
                    limit=limit,
                    offset=offset,
                    include_positions_summary=include_positions_summary,
                ),
                validate=lambda: TopvisorAdapter.validate_projects(limit, offset, include_positions_summary),
            )
        }

    @server.tool(auth=require_scopes("topvisor:read"))
    async def topvisor_list_keywords(
        project_id: int, limit: int = 100, offset: int = 0, show_trash: bool = False
    ) -> dict[str, Any]:
        """List bounded Topvisor keyword metadata for one project; never runs checks."""
        adapter = registry.topvisor()
        return {
            "payload": await _provider_read(
                "topvisor",
                "keywords",
                {
                    "project_id": project_id,
                    "limit": limit,
                    "offset": offset,
                    "show_trash": show_trash,
                },
                lambda: adapter.keywords(
                    project_id,
                    limit=limit,
                    offset=offset,
                    show_trash=show_trash,
                ),
                validate=lambda: TopvisorAdapter.validate_keywords(project_id, limit, offset, show_trash),
            )
        }

    @server.tool(auth=require_scopes("topvisor:read"))
    async def topvisor_get_project_setup(project_id: int) -> dict[str, Any]:
        """Read one Topvisor project with its configured searchers and regions."""
        adapter = registry.topvisor()
        return {
            "payload": await _provider_read(
                "topvisor",
                "project_setup",
                {"project_id": project_id},
                lambda: adapter.project_setup(project_id),
                validate=lambda: TopvisorAdapter.validate_project_setup(project_id),
            )
        }

    @server.tool(auth=require_scopes("topvisor:read"))
    async def topvisor_list_folders(
        project_id: int,
        limit: int = 100,
        offset: int = 0,
        show_trash: bool = False,
        view: str = "flat",
    ) -> dict[str, Any]:
        """List bounded keyword folders for one Topvisor project."""
        adapter = registry.topvisor()
        return {
            "payload": await _provider_read(
                "topvisor",
                "folders",
                {
                    "project_id": project_id,
                    "limit": limit,
                    "offset": offset,
                    "show_trash": show_trash,
                    "view": view,
                },
                lambda: adapter.folders(
                    project_id,
                    limit=limit,
                    offset=offset,
                    show_trash=show_trash,
                    view=view,
                ),
                validate=lambda: TopvisorAdapter.validate_folders(
                    project_id, limit, offset, show_trash, view
                ),
            )
        }

    @server.tool(auth=require_scopes("topvisor:read"))
    async def topvisor_list_groups(
        project_id: int,
        limit: int = 100,
        offset: int = 0,
        show_trash: bool = False,
    ) -> dict[str, Any]:
        """List bounded keyword groups for one Topvisor project."""
        adapter = registry.topvisor()
        return {
            "payload": await _provider_read(
                "topvisor",
                "groups",
                {
                    "project_id": project_id,
                    "limit": limit,
                    "offset": offset,
                    "show_trash": show_trash,
                },
                lambda: adapter.groups(project_id, limit=limit, offset=offset, show_trash=show_trash),
                validate=lambda: TopvisorAdapter.validate_groups(project_id, limit, offset, show_trash),
            )
        }

    @server.tool(auth=require_scopes("topvisor:read"))
    async def topvisor_search_regions(
        searcher_key: int | str,
        search: str,
        country_code: str | None = None,
        only_countries: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search Topvisor's region catalog for a search engine without mutation."""
        adapter = registry.topvisor()
        return {
            "payload": await _provider_read(
                "topvisor",
                "region_search",
                {
                    "searcher_key": searcher_key,
                    "search": search,
                    "country_code": country_code,
                    "only_countries": only_countries,
                    "limit": limit,
                    "offset": offset,
                },
                lambda: adapter.search_regions(
                    searcher_key,
                    search,
                    country_code=country_code,
                    only_countries=only_countries,
                    limit=limit,
                    offset=offset,
                ),
                validate=lambda: TopvisorAdapter.validate_region_search(
                    searcher_key,
                    search,
                    country_code,
                    only_countries,
                    limit,
                    offset,
                ),
            )
        }

    def _topvisor_items(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        result = payload.get("result")
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            return [result]
        return []

    async def _topvisor_all_projects() -> list[dict[str, Any]]:
        adapter = registry.topvisor()
        items: list[dict[str, Any]] = []
        for offset in range(0, 100_000, 500):
            page = await _provider_read(
                "topvisor",
                "projects_scan",
                {"limit": 500, "offset": offset},
                partial(adapter.projects, limit=500, offset=offset),
                validate=partial(TopvisorAdapter.validate_projects, 500, offset, False),
            )
            page_items = _topvisor_items(page)
            items.extend(page_items)
            if len(page_items) < 500:
                break
        return items

    async def _topvisor_all_folders(project_id: int) -> list[dict[str, Any]]:
        adapter = registry.topvisor()
        items: list[dict[str, Any]] = []
        for offset in range(0, 100_000, 500):
            page = await _provider_read(
                "topvisor",
                "folders_scan",
                {"project_id": project_id, "limit": 500, "offset": offset},
                partial(adapter.folders, project_id, limit=500, offset=offset),
                validate=partial(TopvisorAdapter.validate_folders, project_id, 500, offset, False, "flat"),
            )
            page_items = _topvisor_items(page)
            items.extend(page_items)
            if len(page_items) < 500:
                break
        return items

    async def _topvisor_all_groups(project_id: int) -> list[dict[str, Any]]:
        adapter = registry.topvisor()
        items: list[dict[str, Any]] = []
        for offset in range(0, 100_000, 500):
            page = await _provider_read(
                "topvisor",
                "groups_scan",
                {"project_id": project_id, "limit": 500, "offset": offset},
                partial(adapter.groups, project_id, limit=500, offset=offset),
                validate=partial(TopvisorAdapter.validate_groups, project_id, 500, offset, False),
            )
            page_items = _topvisor_items(page)
            items.extend(page_items)
            if len(page_items) < 500:
                break
        return items

    async def _topvisor_all_keywords(project_id: int) -> list[dict[str, Any]]:
        adapter = registry.topvisor()
        items: list[dict[str, Any]] = []
        for offset in range(0, 100_000, 500):
            page = await _provider_read(
                "topvisor",
                "keywords_scan",
                {"project_id": project_id, "limit": 500, "offset": offset},
                partial(adapter.keywords, project_id, limit=500, offset=offset),
                validate=partial(TopvisorAdapter.validate_keywords, project_id, 500, offset, False),
            )
            page_items = _topvisor_items(page)
            items.extend(page_items)
            if len(page_items) < 500:
                break
        return items

    async def _topvisor_plan_or_apply(
        tool_name: str,
        operation: tuple[str, ...],
        params: dict[str, Any],
        apply: bool,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        adapter = registry.topvisor()
        _op, validated = TopvisorAdapter.validate_write(operation, params)
        if not apply:
            return {
                "applied": False,
                "dry_run": True,
                "provider": "topvisor",
                "tool": tool_name,
                "operation": list(operation),
                "validated": True,
                "payload_fields": sorted(validated),
            }
        return cast(
            dict[str, Any],
            await _autonomous_write(
                "topvisor",
                tool_name,
                {"operation": list(operation), "params": params},
                idempotency_key,
                enabled=settings.topvisor_write_enabled,
                validate=lambda: TopvisorAdapter.validate_write(operation, params),
                apply_fn=lambda: adapter.apply_write(operation, params),
                readback_fn=lambda _result: adapter.readback(operation, params),
            ),
        )

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_create_project(
        site: str,
        name: str | None = None,
        tags: list[int] | None = None,
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create one project idempotently; dry-run is the default."""
        params: dict[str, Any] = {"url": site}
        if name is not None:
            params["name"] = name
        if tags is not None:
            params["tags"] = tags
        _op, validated = TopvisorAdapter.validate_write(ADD_PROJECT_OPERATION, params)
        projects = await _topvisor_all_projects()

        def site_key(value: object) -> str:
            text = str(value or "").strip().rstrip("/")
            parsed = urlsplit(text if "://" in text else f"https://{text}")
            host = str(parsed.hostname or "").casefold()
            port = f":{parsed.port}" if parsed.port is not None else ""
            return f"{host}{port}{parsed.path.rstrip('/').casefold()}"

        wanted_name = str(validated.get("name") or validated["url"]).strip().casefold()
        wanted_site = site_key(validated["url"])
        existing = next(
            (
                project
                for project in projects
                if str(project.get("name") or "").strip().casefold() == wanted_name
                and site_key(project.get("url")) == wanted_site
            ),
            None,
        )
        if existing is not None:
            return {
                "applied": False,
                "dry_run": not apply,
                "already_exists": True,
                "project_id": existing.get("id"),
                "project": existing,
            }
        receipt = await _topvisor_plan_or_apply(
            "topvisor_create_project",
            ADD_PROJECT_OPERATION,
            params,
            apply,
            idempotency_key,
        )
        if not apply:
            return {
                **receipt,
                "already_exists": False,
                "would_create": {"name": validated.get("name"), "site": validated["url"]},
            }
        after = await _topvisor_all_projects()
        created = next(
            (
                project
                for project in after
                if str(project.get("name") or "").strip().casefold() == wanted_name
                and site_key(project.get("url")) == wanted_site
            ),
            None,
        )
        if created is None:
            raise safe_provider_error(
                "topvisor", ProviderError("Topvisor project writeback was not confirmed")
            )
        return {
            "applied": True,
            "dry_run": False,
            "already_exists": False,
            "project_id": created.get("id"),
            "project": created,
            "write_receipt": receipt,
        }

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_create_folder(
        project_id: int,
        name: str,
        parent_folder_id: int = 0,
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create one project folder idempotently; dry-run is the default."""
        params = {
            "project_id": project_id,
            "name": name,
            "to_id": parent_folder_id,
            "to_type": "in",
        }
        _op, validated = TopvisorAdapter.validate_write(ADD_FOLDER_OPERATION, params)
        folders = await _topvisor_all_folders(project_id)
        wanted_name = str(validated["name"]).casefold()
        existing = next(
            (
                folder
                for folder in folders
                if str(folder.get("name") or "").strip().casefold() == wanted_name
                and int(folder.get("parent_id") or 0) == parent_folder_id
            ),
            None,
        )
        if existing is not None:
            return {
                "applied": False,
                "dry_run": not apply,
                "already_exists": True,
                "folder_id": existing.get("id"),
                "folder": existing,
            }
        receipt = await _topvisor_plan_or_apply(
            "topvisor_create_folder",
            ADD_FOLDER_OPERATION,
            params,
            apply,
            idempotency_key,
        )
        if not apply:
            return {**receipt, "already_exists": False, "would_create": validated}
        after = await _topvisor_all_folders(project_id)
        created = next(
            (
                folder
                for folder in after
                if str(folder.get("name") or "").strip().casefold() == wanted_name
                and int(folder.get("parent_id") or 0) == parent_folder_id
            ),
            None,
        )
        if created is None:
            raise safe_provider_error(
                "topvisor", ProviderError("Topvisor folder writeback was not confirmed")
            )
        return {
            "applied": True,
            "dry_run": False,
            "already_exists": False,
            "folder_id": created.get("id"),
            "folder": created,
            "write_receipt": receipt,
        }

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_create_groups(
        project_id: int,
        names: list[str],
        folder_id: int = 0,
        active: bool = True,
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create missing groups in one folder; dry-run is the default."""
        raw = {
            "project_id": project_id,
            "names": names,
            "to_id": folder_id,
            "to_type": "in_folder",
            "on": active,
        }
        _op, validated = TopvisorAdapter.validate_write(ADD_GROUP_OPERATION, raw)
        groups = await _topvisor_all_groups(project_id)
        existing_names = {
            str(group.get("name") or "").strip().casefold()
            for group in groups
            if int(group.get("folder_id") or 0) == folder_id
        }
        planned_names = set(existing_names)
        missing: list[str] = []
        for candidate in validated["names"]:
            key = candidate.casefold()
            if key not in planned_names:
                planned_names.add(key)
                missing.append(candidate)
        if not missing:
            return {
                "applied": False,
                "dry_run": not apply,
                "already_exists": True,
                "created": 0,
                "skipped_existing": len(validated["names"]),
            }
        params = {**raw, "names": missing}
        receipt = await _topvisor_plan_or_apply(
            "topvisor_create_groups",
            ADD_GROUP_OPERATION,
            params,
            apply,
            idempotency_key,
        )
        if not apply:
            return {
                **receipt,
                "already_exists": False,
                "would_create": missing,
                "skipped_existing": len(validated["names"]) - len(missing),
            }
        after = await _topvisor_all_groups(project_id)
        after_names = {
            str(group.get("name") or "").strip().casefold()
            for group in after
            if int(group.get("folder_id") or 0) == folder_id
        }
        confirmed = [name for name in missing if name.casefold() in after_names]
        if len(confirmed) != len(missing):
            raise safe_provider_error(
                "topvisor", ProviderError("Topvisor group writeback was only partially confirmed")
            )
        return {
            "applied": True,
            "dry_run": False,
            "already_exists": False,
            "created": len(confirmed),
            "skipped_existing": len(validated["names"]) - len(missing),
            "write_receipt": receipt,
        }

    async def _topvisor_import_keywords_impl(
        tool_name: str,
        project_id: int,
        keywords: list[dict[str, Any]],
        apply: bool,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        _payload, normalized = TopvisorAdapter.prepare_keyword_import(project_id, keywords)
        before = await _topvisor_all_keywords(project_id)

        def scope_key(item: dict[str, Any]) -> tuple[str, str]:
            return (
                str(item.get("group_folder_path") or "").strip().casefold(),
                str(item.get("group_name") or "").strip().casefold(),
            )

        target_scopes = {scope_key(item) for item in normalized}
        scope_total_before = sum(1 for item in before if scope_key(item) in target_scopes)
        existing_names = {
            normalize_keyword(item["name"])
            for item in before
            if isinstance(item.get("name"), str) and str(item["name"]).strip()
        }
        batch_names: set[str] = set()
        missing: list[dict[str, Any]] = []
        skipped_existing = 0
        skipped_batch_duplicates = 0
        for raw, item in zip(keywords, normalized, strict=True):
            phrase = str(item["normalized_query"])
            if phrase in existing_names:
                skipped_existing += 1
            elif phrase in batch_names:
                skipped_batch_duplicates += 1
            else:
                batch_names.add(phrase)
                missing.append(raw)
        if not missing:
            return {
                "applied": False,
                "dry_run": not apply,
                "already_exists": True,
                "added": 0,
                "would_add": 0,
                "skipped_existing": skipped_existing,
                "skipped_batch_duplicates": skipped_batch_duplicates,
                "total_after": scope_total_before,
                "project_total_after": len(before),
            }
        params = {"project_id": project_id, "keywords": missing}
        receipt = await _topvisor_plan_or_apply(
            tool_name,
            IMPORT_KEYWORDS_OPERATION,
            params,
            apply,
            idempotency_key,
        )
        if not apply:
            return {
                **receipt,
                "already_exists": False,
                "added": 0,
                "would_add": len(missing),
                "skipped_existing": skipped_existing,
                "skipped_batch_duplicates": skipped_batch_duplicates,
                "total_before": len(before),
                "scope_total_before": scope_total_before,
                "total_after": scope_total_before,
                "project_total_after": len(before),
                "preview": normalized[:10],
            }
        after = await _topvisor_all_keywords(project_id)
        after_names = {
            normalize_keyword(item["name"])
            for item in after
            if isinstance(item.get("name"), str) and str(item["name"]).strip()
        }
        planned_names = {normalize_keyword(item["query"]) for item in missing}
        confirmed = planned_names & (after_names - existing_names)
        if len(confirmed) != len(planned_names):
            raise safe_provider_error(
                "topvisor", ProviderError("Topvisor keyword import writeback was only partially confirmed")
            )
        scope_total_after = sum(1 for item in after if scope_key(item) in target_scopes)
        return {
            "applied": True,
            "dry_run": False,
            "already_exists": False,
            "added": len(confirmed),
            "would_add": 0,
            "skipped_existing": skipped_existing,
            "skipped_batch_duplicates": skipped_batch_duplicates,
            "total_before": scope_total_before,
            "total_after": scope_total_after,
            "project_total_before": len(before),
            "project_total_after": len(after),
            "write_receipt": receipt,
        }

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_import_keywords(
        project_id: int,
        keywords: list[dict[str, Any]],
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Import at most 1,000 missing keywords with targets/folders/groups; dry-run by default."""
        return await _topvisor_import_keywords_impl(
            "topvisor_import_keywords", project_id, keywords, apply, idempotency_key
        )

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_add_keywords(
        project_id: int,
        folder_path: str,
        keywords: list[dict[str, Any]],
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility workflow: import missing keywords under one explicit folder path."""
        path = folder_path.strip()
        if not path or len(path) > 2_040:
            raise ValueError("folder_path must be between 1 and 2040 characters")
        scoped: list[dict[str, Any]] = []
        for index, keyword in enumerate(keywords):
            existing = keyword.get("group_folder_path")
            if existing is not None and str(existing).strip() != path:
                raise ValueError(f"keywords[{index}].group_folder_path conflicts with folder_path")
            scoped.append({**keyword, "group_folder_path": path})
        return await _topvisor_import_keywords_impl(
            "topvisor_add_keywords", project_id, scoped, apply, idempotency_key
        )

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_set_keyword_target(
        project_id: int,
        keyword_id: int,
        target_url: str,
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Set one keyword target URL; dry-run is the default."""
        return await _topvisor_plan_or_apply(
            "topvisor_set_keyword_target",
            SET_KEYWORD_TARGET_OPERATION,
            {"project_id": project_id, "id": keyword_id, "target": target_url},
            apply,
            idempotency_key,
        )

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_set_keyword_tags(
        project_id: int,
        keyword_id: int,
        tags: list[int],
        action: str = "set",
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Set/add/remove Topvisor color tags 1..10 on one keyword; dry-run by default."""
        return await _topvisor_plan_or_apply(
            "topvisor_set_keyword_tags",
            SET_KEYWORD_TAGS_OPERATION,
            {"project_id": project_id, "id": keyword_id, "tags": tags, "action": action},
            apply,
            idempotency_key,
        )

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_add_searcher(
        project_id: int,
        searcher_key: int | str,
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Add one search engine to a project; dry-run is the default."""
        return await _topvisor_plan_or_apply(
            "topvisor_add_searcher",
            ADD_SEARCHER_OPERATION,
            {"project_id": project_id, "searcher_key": searcher_key},
            apply,
            idempotency_key,
        )

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_add_region(
        project_id: int,
        searcher_key: int | str,
        region_key: int,
        depth: int = 1,
        lang: str | None = None,
        device: int | str | None = None,
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Add one region/depth configuration to a project; dry-run by default."""
        params: dict[str, Any] = {
            "project_id": project_id,
            "searcher_key": searcher_key,
            "region_key": region_key,
            "region_depth": depth,
        }
        if lang is not None:
            params["region_lang"] = lang
        if device is not None:
            params["region_device"] = device
        return await _topvisor_plan_or_apply(
            "topvisor_add_region",
            ADD_REGION_OPERATION,
            params,
            apply,
            idempotency_key,
        )

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_import_regions(
        project_id: int,
        regions: list[dict[str, Any]],
        apply: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Import bounded searcher/region rows; dry-run is the default."""
        _payload, normalized = TopvisorAdapter.prepare_regions_import(project_id, regions)
        receipt = await _topvisor_plan_or_apply(
            "topvisor_import_regions",
            IMPORT_REGIONS_OPERATION,
            {"project_id": project_id, "regions": regions},
            apply,
            idempotency_key,
        )
        return {**receipt, "region_count": len(normalized), "preview": normalized[:10]}

    @server.tool(auth=require_scopes("topvisor:write"))
    async def topvisor_apply(
        operation: list[str],
        params: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Legacy single keyword/group write; prefer the typed dry-run tools."""
        adapter = registry.topvisor()
        op = tuple(operation)

        def validate_legacy() -> tuple[tuple[str, ...], dict[str, Any]]:
            if op not in LEGACY_WRITE_OPERATIONS:
                raise ValueError("use a typed Topvisor write tool for this operation")
            return adapter.validate_write(op, params)

        return cast(
            dict[str, Any],
            await _autonomous_write(
                "topvisor",
                "/".join(str(part) for part in operation),
                {"operation": list(operation), "params": params},
                idempotency_key,
                enabled=settings.topvisor_write_enabled,
                validate=validate_legacy,
                apply_fn=lambda: adapter.apply_write(op, params),
                readback_fn=lambda _result: adapter.readback(op, params),
            ),
        )
