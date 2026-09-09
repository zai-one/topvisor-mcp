from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol
from urllib.parse import urlsplit

from zai_topvisor.coalescing import AsyncSingleFlight
from zai_topvisor.transport import JsonHttpClient, ProviderError, request_hash

OFFICIAL_BASE_URL = "https://api.topvisor.com/v2/json"
MAX_LIMIT = 500
MAX_OFFSET = 100_000
MAX_ID = 2_147_483_647
MAX_IMPORT_KEYWORDS = 1_000
MAX_IMPORT_REGIONS = 250

PROJECT_FIELDS = frozenset(
    {
        "id",
        "name",
        "url",
        "on",
        "favorite",
        "right",
        "status_positions",
        "positions_time",
        "positions_percent",
        "status_volumes",
        "status_claster",
    }
)
DEFAULT_PROJECT_FIELDS = (
    "id",
    "name",
    "url",
    "on",
    "status_positions",
    "positions_time",
    "positions_percent",
    "status_volumes",
    "status_claster",
)
KEYWORD_FIELDS = frozenset(
    {
        "id",
        "name",
        "project_id",
        "group_id",
        "group_name",
        "group_on",
        "target",
        "tags",
        "group_folder_path",
    }
)
DEFAULT_KEYWORD_FIELDS = (
    "id",
    "name",
    "group_id",
    "group_name",
    "group_folder_path",
    "target",
    "tags",
)

FOLDER_FIELDS = frozenset(
    {
        "id",
        "project_id",
        "parent_id",
        "name",
        "path",
        "count_folders",
        "count_groups",
        "count_groups_active",
    }
)
DEFAULT_FOLDER_FIELDS = ("id", "project_id", "parent_id", "name", "path")
GROUP_FIELDS = frozenset(
    {
        "id",
        "project_id",
        "folder_id",
        "name",
        "on",
        "folder_path",
        "count_keywords",
    }
)
DEFAULT_GROUP_FIELDS = (
    "id",
    "project_id",
    "folder_id",
    "name",
    "on",
    "folder_path",
    "count_keywords",
)

PROJECTS_OPERATION = ("get", "projects_2", "projects")
KEYWORDS_OPERATION = ("get", "keywords_2", "keywords")
FOLDERS_OPERATION = ("get", "keywords_2", "folders")
GROUPS_OPERATION = ("get", "keywords_2", "groups")
REGIONS_OPERATION = ("get", "system_2", "common", "regions")
HISTORY_OPERATION = ("get", "positions_2", "history")
ALLOWED_OPERATIONS = frozenset(
    {
        PROJECTS_OPERATION,
        KEYWORDS_OPERATION,
        FOLDERS_OPERATION,
        GROUPS_OPERATION,
        REGIONS_OPERATION,
        HISTORY_OPERATION,
    }
)

# Guarded WRITE surface for project provisioning and semantic inventory. Every
# endpoint is an explicit reviewed allowlist entry. Destructive del/* methods and
# paid checker/go methods remain deliberately absent.
#
# Endpoints follow /{action}/{service}/{method...} and are CONFIRMED against the
# official Topvisor sources (openapi: github.com/topvisor/topvisor-openapi; php
# sdk: github.com/topvisor/topvisor-sdk). Topvisor v2 write methods are often
# multi-segment, so an operation is a 3- or 4-segment tuple:
#   add/keywords_2/keywords         single keyword: project_id + name (+ to_id)
#   add/keywords_2/groups           new group:      project_id + name (+ on)
#   edit/keywords_2/groups/rename   rename group:   project_id + id + name
#   edit/keywords_2/groups/on       toggle group:   project_id + id + on
# Edit operations target one scalar id. Bulk selectors are excluded. Imports are
# bounded and translated from typed records into Topvisor's documented CSV form.
ADD_KEYWORD_OPERATION = ("add", "keywords_2", "keywords")
ADD_GROUP_OPERATION = ("add", "keywords_2", "groups")
RENAME_GROUP_OPERATION = ("edit", "keywords_2", "groups", "rename")
TOGGLE_GROUP_OPERATION = ("edit", "keywords_2", "groups", "on")
LEGACY_WRITE_OPERATIONS = frozenset(
    {
        ADD_KEYWORD_OPERATION,
        ADD_GROUP_OPERATION,
        RENAME_GROUP_OPERATION,
        TOGGLE_GROUP_OPERATION,
    }
)
ADD_PROJECT_OPERATION = ("add", "projects_2", "projects")
ADD_FOLDER_OPERATION = ("add", "keywords_2", "folders")
IMPORT_KEYWORDS_OPERATION = ("add", "keywords_2", "keywords", "import")
SET_KEYWORD_TARGET_OPERATION = ("edit", "keywords_2", "keywords", "target")
SET_KEYWORD_TAGS_OPERATION = ("edit", "keywords_2", "keywords", "tags")
ADD_SEARCHER_OPERATION = ("add", "positions_2", "searchers")
ADD_REGION_OPERATION = ("add", "positions_2", "searchers_regions")
IMPORT_REGIONS_OPERATION = ("add", "positions_2", "searchers_regions", "import")
WRITE_ALLOWLIST: dict[tuple[str, ...], str] = {
    ADD_KEYWORD_OPERATION: "medium",
    ADD_GROUP_OPERATION: "medium",
    RENAME_GROUP_OPERATION: "medium",
    TOGGLE_GROUP_OPERATION: "medium",
    ADD_PROJECT_OPERATION: "medium",
    ADD_FOLDER_OPERATION: "medium",
    IMPORT_KEYWORDS_OPERATION: "medium",
    SET_KEYWORD_TARGET_OPERATION: "medium",
    SET_KEYWORD_TAGS_OPERATION: "medium",
    ADD_SEARCHER_OPERATION: "medium",
    ADD_REGION_OPERATION: "medium",
    IMPORT_REGIONS_OPERATION: "medium",
}

# Risk classification by write action for operations outside the executable
# allowlist (e.g. a not-yet-enabled del/*). Fail-closed: an unknown action tier
# is "high" so the governor never under-throttles an unfamiliar mutation class.
_WRITE_RISK_BY_ACTION = {"add": "medium", "edit": "medium", "del": "high"}
_DEFAULT_WRITE_RISK_TIER = "high"

MIN_WRITE_SEGMENTS = 3
MAX_WRITE_SEGMENTS = 5

# Bounds for guarded writes (chosen conservative caps, not Topvisor-published).
MAX_KEYWORD_LEN = 255
MAX_GROUP_NAME_LEN = 255
MAX_FOLDER_NAME_LEN = 255
MAX_PROJECT_NAME_LEN = 255
MAX_URL_LEN = 2_048

# CONFIRMED enum from Topvisor OpenAPI Types for single keyword placement.
_KEYWORD_TO_TYPES = frozenset({"in_group", "in_group_last", "before_keyword", "after_keyword"})

_ADD_KEYWORD_PARAMS = frozenset({"project_id", "name", "to_id", "to_type"})
_ADD_KEYWORD_REQUIRED = frozenset({"project_id", "name"})
_ADD_GROUP_PARAMS = frozenset({"project_id", "name", "on"})
_ADD_GROUP_REQUIRED = frozenset({"project_id", "name"})
_RENAME_GROUP_PARAMS = frozenset({"project_id", "id", "name"})
_RENAME_GROUP_REQUIRED = frozenset({"project_id", "id", "name"})
_TOGGLE_GROUP_PARAMS = frozenset({"project_id", "id", "on"})
_TOGGLE_GROUP_REQUIRED = frozenset({"project_id", "id", "on"})

_ADD_PROJECT_PARAMS = frozenset({"url", "name", "tags", "folder_id", "on"})
_ADD_PROJECT_REQUIRED = frozenset({"url"})
_ADD_FOLDER_PARAMS = frozenset({"project_id", "name", "to_id", "to_type"})
_ADD_FOLDER_REQUIRED = frozenset({"project_id", "name"})
_ADD_GROUPS_PARAMS = frozenset({"project_id", "names", "on", "to_id", "to_type"})
_ADD_GROUPS_REQUIRED = frozenset({"project_id", "names"})
_IMPORT_KEYWORDS_PARAMS = frozenset({"project_id", "keywords"})
_IMPORT_KEYWORDS_REQUIRED = frozenset({"project_id", "keywords"})
_SET_TARGET_PARAMS = frozenset({"project_id", "id", "target"})
_SET_TARGET_REQUIRED = frozenset({"project_id", "id", "target"})
_SET_TAGS_PARAMS = frozenset({"project_id", "id", "tags", "action"})
_SET_TAGS_REQUIRED = frozenset({"project_id", "id", "tags", "action"})
_ADD_SEARCHER_PARAMS = frozenset({"project_id", "searcher_key"})
_ADD_SEARCHER_REQUIRED = _ADD_SEARCHER_PARAMS
_ADD_REGION_PARAMS = frozenset(
    {"project_id", "searcher_key", "region_key", "region_lang", "region_device", "region_depth"}
)
_ADD_REGION_REQUIRED = frozenset({"project_id", "searcher_key", "region_key"})
_IMPORT_REGIONS_PARAMS = frozenset({"project_id", "regions"})
_IMPORT_REGIONS_REQUIRED = _IMPORT_REGIONS_PARAMS

_PROJECT_PARAMS = frozenset(
    {
        "fields",
        "limit",
        "offset",
        "show_site_stat",
        "show_searchers_and_regions",
        "include_positions_summary",
        "id",
    }
)
_KEYWORD_PARAMS = frozenset({"project_id", "fields", "limit", "offset", "show_trash"})
# Topvisor accepts show_trash on keywords_2/keywords only. keywords_2/folders and
# keywords_2/groups answer application error 2002 whenever the field is present at
# all, so it is not part of their parameter contract.
_FOLDER_PARAMS = frozenset({"project_id", "fields", "limit", "offset", "view", "id"})
_GROUP_PARAMS = frozenset({"project_id", "fields", "limit", "offset", "folder_id_depth", "id"})
_REGION_PARAMS = frozenset(
    {
        "searcher_key",
        "search",
        "country_code",
        "only_countries",
        "regions_keys",
        "for_project_id",
        "limit",
        "offset",
    }
)


def _reject_folder_group_trash(show_trash: bool) -> None:
    if show_trash:
        raise ValueError("show_trash is not supported by Topvisor for folders and groups")


_PATH_SEGMENT = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_SAFE_ERROR_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")

# Topvisor's public API uses numeric identifiers here.  Keep a small alias
# layer at the MCP boundary so operators may use readable names, but always
# send the documented integer to Topvisor.
SEARCHER_KEYS = frozenset({0, 1, 4, 5, 7, 8, 9, 20, 21})
SEARCHER_KEY_ALIASES = {
    "yandex": 0,
    "google": 1,
    "youtube": 4,
    "bing": 5,
    "seznam": 7,
    "appstore": 8,
    "app_store": 8,
    "googleplay": 9,
    "google_play": 9,
    "yandex_com": 20,
    "yandex_com_tr": 21,
}
REGION_DEVICES = frozenset({0, 1, 2})
REGION_DEVICE_ALIASES = {
    "desktop": 0,
    "pc": 0,
    "tablet": 1,
    "smartphone": 2,
    "mobile": 2,
    "phone": 2,
}


class JsonRequester(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]: ...


def _validate_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.topvisor.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v2/json"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Topvisor base URL must be the official API v2 JSON endpoint")
    return OFFICIAL_BASE_URL


def _positive_int(value: object, field: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        try:
            normalized = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field} must be a positive integer") from exc
    else:
        raise ValueError(f"{field} must be a positive integer")
    if normalized < 1 or normalized > maximum:
        raise ValueError(f"{field} must be between 1 and {maximum}")
    return normalized


def _non_negative_int(value: object, field: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        try:
            normalized = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field} must be a non-negative integer") from exc
    else:
        raise ValueError(f"{field} must be a non-negative integer")
    if normalized < 0 or normalized > maximum:
        raise ValueError(f"{field} must be between 0 and {maximum}")
    return normalized


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _fields(value: object, *, allowed: frozenset[str], field: str = "fields") -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a list")
    if not value or len(value) > 16:
        raise ValueError(f"{field} must contain between 1 and 16 items")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise ValueError(f"unsupported Topvisor {field} item")
        if item not in normalized:
            normalized.append(item)
    return normalized


def _string_value(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{field} must be between 1 and {maximum} characters")
    return text


def normalize_keyword(value: object) -> str:
    """Return the stable phrase key used for duplicate detection."""

    text = _string_value(value, "query", MAX_KEYWORD_LEN)
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _tags(value: object, field: str = "tags") -> list[int]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a list")
    normalized: list[int] = []
    for item in value:
        tag = _positive_int(item, field, 10)
        if tag not in normalized:
            normalized.append(tag)
    if len(normalized) > 10:
        raise ValueError(f"{field} must contain at most 10 items")
    return normalized


def _project_url(value: object, field: str = "url") -> str:
    text = _string_value(value, field, MAX_URL_LEN)
    if any(char.isspace() for char in text):
        raise ValueError(f"{field} must not contain whitespace")
    candidate = text if "://" in text else f"https://{text}"
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"{field} must be a valid HTTP(S) site or domain")
    return text.rstrip("/")


def _target_url(value: object, field: str = "target") -> str:
    text = _string_value(value, field, MAX_URL_LEN)
    parsed = urlsplit(text)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"{field} must be a valid absolute HTTP(S) URL")
    return text


def _searcher_key(value: object, field: str = "searcher_key") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a documented Topvisor searcher key or alias")
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        text = value.strip().casefold().replace("-", "_").replace(".", "_")
        if text in SEARCHER_KEY_ALIASES:
            normalized = SEARCHER_KEY_ALIASES[text]
        else:
            try:
                normalized = int(text)
            except ValueError as exc:
                raise ValueError(f"{field} must be a documented Topvisor searcher key or alias") from exc
    else:
        raise ValueError(f"{field} must be a documented Topvisor searcher key or alias")
    if normalized not in SEARCHER_KEYS:
        raise ValueError(f"{field} is not a documented Topvisor searcher key")
    return normalized


def _region_device(value: object, field: str = "region_device") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be 0, 1, 2, or a documented device alias")
    if isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        text = value.strip().casefold()
        if text in REGION_DEVICE_ALIASES:
            normalized = REGION_DEVICE_ALIASES[text]
        else:
            try:
                normalized = int(text)
            except ValueError as exc:
                raise ValueError(f"{field} must be 0, 1, 2, or a documented device alias") from exc
    else:
        raise ValueError(f"{field} must be 0, 1, 2, or a documented device alias")
    if normalized not in REGION_DEVICES:
        raise ValueError(f"{field} must be 0, 1, 2, or a documented device alias")
    return normalized


def _region_depth(value: object, searcher_key: int, field: str = "region_depth") -> int:
    maximum = 3 if searcher_key in {0, 9} else 10
    return _positive_int(value, field, maximum)


def _string_list(value: object, field: str, *, maximum_items: int, maximum_length: int) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a list")
    if not value or len(value) > maximum_items:
        raise ValueError(f"{field} must contain between 1 and {maximum_items} items")
    normalized: list[str] = []
    for item in value:
        text = _string_value(item, field, maximum_length)
        if text not in normalized:
            normalized.append(text)
    return normalized


def _csv_text(rows: Sequence[Sequence[object]]) -> str:
    target = io.StringIO(newline="")
    writer = csv.writer(target, delimiter=";", lineterminator="\n")
    writer.writerows(rows)
    return target.getvalue()


def _keyword_import_csv(value: object) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("keywords must be a list")
    if not value or len(value) > MAX_IMPORT_KEYWORDS:
        raise ValueError(
            f"keywords must contain between 1 and {MAX_IMPORT_KEYWORDS} items; received "
            f"{len(value) if isinstance(value, Sequence) else 0}"
        )

    normalized: list[dict[str, Any]] = []
    rows: list[list[object]] = [["name", "tags", "target", "group_folder_path", "group_name"]]
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"keywords[{index}] must be a mapping")
        unknown = sorted(set(item) - {"query", "target_url", "tags", "group_folder_path", "group_name"})
        if unknown:
            raise ValueError(f"unsupported keywords[{index}] fields: " + ", ".join(unknown))
        query = _string_value(item.get("query"), f"keywords[{index}].query", MAX_KEYWORD_LEN)
        target = (
            _target_url(item["target_url"], f"keywords[{index}].target_url") if item.get("target_url") else ""
        )
        tags = _tags(item.get("tags", []), f"keywords[{index}].tags")
        folder_path = (
            _string_value(
                item["group_folder_path"],
                f"keywords[{index}].group_folder_path",
                MAX_FOLDER_NAME_LEN * 8,
            )
            if item.get("group_folder_path")
            else ""
        )
        group_name = (
            _string_value(item["group_name"], f"keywords[{index}].group_name", MAX_GROUP_NAME_LEN)
            if item.get("group_name")
            else ""
        )
        record = {
            "query": query,
            "normalized_query": normalize_keyword(query),
            "target_url": target or None,
            "tags": tags,
            "group_folder_path": folder_path or None,
            "group_name": group_name or None,
        }
        normalized.append(record)
        rows.append([query, ",".join(str(tag) for tag in tags), target, folder_path, group_name])
    return _csv_text(rows), normalized


def _regions_import_csv(value: object) -> tuple[list[str], list[dict[str, Any]]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("regions must be a list")
    if not value or len(value) > MAX_IMPORT_REGIONS:
        raise ValueError(f"regions must contain between 1 and {MAX_IMPORT_REGIONS} items")
    rows: list[list[object]] = []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"regions[{index}] must be a mapping")
        unknown = sorted(
            set(item) - {"searcher_key", "name_or_key", "country_code", "lang", "device", "depth"}
        )
        if unknown:
            raise ValueError(f"unsupported regions[{index}] fields: " + ", ".join(unknown))
        searcher_key = _searcher_key(item.get("searcher_key"), f"regions[{index}].searcher_key")
        name_or_key = _string_value(item.get("name_or_key"), f"regions[{index}].name_or_key", 255)
        country_code = str(item.get("country_code") or "").strip().upper()
        if country_code and (len(country_code) != 2 or not country_code.isalpha()):
            raise ValueError(f"regions[{index}].country_code must be ISO alpha-2")
        lang = str(item.get("lang") or "").strip().lower()
        if lang and (len(lang) > 8 or not lang.replace("-", "").isalpha()):
            raise ValueError(f"regions[{index}].lang is invalid")
        device = (
            _region_device(item["device"], f"regions[{index}].device")
            if item.get("device") is not None
            else None
        )
        depth = _region_depth(item.get("depth", 1), searcher_key, f"regions[{index}].depth")
        row = [searcher_key, name_or_key, country_code, lang, "" if device is None else device, depth]
        rows.append(row)
        normalized.append(
            {
                "searcher_key": searcher_key,
                "name_or_key": name_or_key,
                "country_code": country_code or None,
                "lang": lang or None,
                "device": device,
                "depth": depth,
            }
        )
    return [_csv_text([row]).rstrip("\n") for row in rows], normalized


class TopvisorAdapter:
    """Bounded Topvisor adapter.

    Strict read inventory plus a guarded, fail-closed project provisioning and
    semantic import surface. Reads coalesce; writes never coalesce and are never
    retried blindly.
    """

    def __init__(
        self,
        user_id: str,
        api_key: str,
        base_url: str = OFFICIAL_BASE_URL,
        http: JsonRequester | None = None,
        coalescer: AsyncSingleFlight | None = None,
    ) -> None:
        self.user_id = user_id.strip()
        self.api_key = api_key.strip()
        self.base_url = _validate_base_url(base_url)
        self.http = http or JsonHttpClient(timeout=60)
        self.coalescer = coalescer or AsyncSingleFlight()

    def _headers(self) -> dict[str, str]:
        user_id = _positive_int(self.user_id, "Topvisor user_id", MAX_ID)
        if not self.api_key:
            raise ProviderError("Topvisor API key is not configured")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Id": str(user_id),
            "Authorization": f"bearer {self.api_key}",
            "User-Agent": "ZAI-MCP-Platform/0.2.0 Topvisor",
        }

    @staticmethod
    def validate_operation(action: str, service: str, *method: str) -> tuple[str, ...]:
        operation = tuple(part.strip() for part in (action, service, *method))
        if any(_PATH_SEGMENT.fullmatch(part) is None for part in operation):
            raise ValueError("Topvisor operation contains an invalid path segment")
        if operation not in ALLOWED_OPERATIONS:
            raise ValueError("Topvisor operation is not allowed")
        return operation

    @staticmethod
    def validate_payload(operation: tuple[str, ...], payload: dict[str, Any]) -> dict[str, Any]:
        if operation == HISTORY_OPERATION:
            if set(payload) - {
                "project_id",
                "regions_indexes",
                "dates",
                "limit",
                "offset",
                "type_range",
                "positions_fields",
            }:
                raise ValueError("unsupported history parameter")
            if payload.get("type_range", 100) != 100 or payload.get(
                "positions_fields", ["position", "relevant_url"]
            ) != ["position", "relevant_url"]:
                raise ValueError("history uses explicit dates and fixed position fields")
            return TopvisorAdapter.validate_history(
                payload.get("project_id"),
                payload.get("regions_indexes"),
                payload.get("dates"),
                payload.get("limit", 100),
                payload.get("offset", 0),
            )
        if operation == PROJECTS_OPERATION:
            allowed_params = _PROJECT_PARAMS
        elif operation == KEYWORDS_OPERATION:
            allowed_params = _KEYWORD_PARAMS
        elif operation == FOLDERS_OPERATION:
            allowed_params = _FOLDER_PARAMS
        elif operation == GROUPS_OPERATION:
            allowed_params = _GROUP_PARAMS
        else:
            allowed_params = _REGION_PARAMS
        unknown = sorted(set(payload) - allowed_params)
        if unknown:
            raise ValueError("unsupported Topvisor parameters: " + ", ".join(unknown))

        validated = dict(payload)
        if "limit" in validated:
            validated["limit"] = _positive_int(validated["limit"], "limit", MAX_LIMIT)
        if "offset" in validated:
            validated["offset"] = _non_negative_int(validated["offset"], "offset", MAX_OFFSET)

        if operation == PROJECTS_OPERATION:
            if "fields" in validated:
                validated["fields"] = _fields(validated["fields"], allowed=PROJECT_FIELDS)
            for field in ("show_site_stat", "include_positions_summary"):
                if field in validated:
                    validated[field] = _boolean(validated[field], field)
            if "show_searchers_and_regions" in validated:
                value = _non_negative_int(
                    validated["show_searchers_and_regions"], "show_searchers_and_regions", 2
                )
                validated["show_searchers_and_regions"] = value
            if "id" in validated:
                validated["id"] = _positive_int(validated["id"], "id", MAX_ID)
        elif operation in {KEYWORDS_OPERATION, FOLDERS_OPERATION, GROUPS_OPERATION}:
            if "project_id" not in validated:
                raise ValueError("project_id is required for this Topvisor inventory")
            validated["project_id"] = _positive_int(validated["project_id"], "project_id", MAX_ID)
            if operation == KEYWORDS_OPERATION:
                allowed_fields = KEYWORD_FIELDS
            elif operation == FOLDERS_OPERATION:
                allowed_fields = FOLDER_FIELDS
            else:
                allowed_fields = GROUP_FIELDS
            if "fields" in validated:
                validated["fields"] = _fields(validated["fields"], allowed=allowed_fields)
            if "show_trash" in validated:
                validated["show_trash"] = _boolean(validated["show_trash"], "show_trash")
            if "id" in validated:
                validated["id"] = _positive_int(validated["id"], "id", MAX_ID)
            if (
                operation == FOLDERS_OPERATION
                and "view" in validated
                and validated["view"] not in {"flat", "tree"}
            ):
                raise ValueError("view must be flat or tree")
            if operation == GROUPS_OPERATION and "folder_id_depth" in validated:
                validated["folder_id_depth"] = _boolean(validated["folder_id_depth"], "folder_id_depth")
        else:
            if "searcher_key" not in validated or "search" not in validated:
                raise ValueError("searcher_key and search are required for Topvisor regions")
            validated["searcher_key"] = _searcher_key(validated["searcher_key"])
            validated["search"] = _string_value(validated["search"], "search", 255)
            if "country_code" in validated:
                country_code = _string_value(validated["country_code"], "country_code", 2).upper()
                if len(country_code) != 2 or not country_code.isalpha():
                    raise ValueError("country_code must be ISO alpha-2")
                validated["country_code"] = country_code
            if "only_countries" in validated:
                validated["only_countries"] = _boolean(validated["only_countries"], "only_countries")
            if "regions_keys" in validated:
                values = validated["regions_keys"]
                if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
                    raise ValueError("regions_keys must be a list")
                validated["regions_keys"] = [_positive_int(item, "regions_keys", MAX_ID) for item in values]
            if "for_project_id" in validated:
                validated["for_project_id"] = _positive_int(
                    validated["for_project_id"], "for_project_id", MAX_ID
                )
        return validated

    @staticmethod
    def validate_response(response: dict[str, Any]) -> dict[str, Any]:
        """Reject Topvisor's HTTP-200 application error envelopes without echoing details."""

        error_value: object | None = None
        if response.get("success") is False:
            error_value = response.get("error") or response.get("errors") or "failed"
        elif response.get("error"):
            error_value = response["error"]
        elif response.get("errors"):
            error_value = response["errors"]
        elif str(response.get("status", "")).lower() in {"error", "fail", "failed"}:
            error_value = response.get("status")

        if error_value is None:
            return response

        code: object | None = None
        if isinstance(error_value, dict):
            code = error_value.get("code") or error_value.get("error_code")
        elif isinstance(error_value, list) and error_value and isinstance(error_value[0], dict):
            code = error_value[0].get("code") or error_value[0].get("error_code")
        if (isinstance(code, int) and not isinstance(code, bool)) or (
            isinstance(code, str) and _SAFE_ERROR_CODE.fullmatch(code) is not None
        ):
            suffix = f" code={code}"
        else:
            suffix = ""
        raise ProviderError(f"Topvisor returned an application error{suffix}")

    async def _read(self, operation: tuple[str, ...], payload: dict[str, Any]) -> dict[str, Any]:
        operation = self.validate_operation(*operation)
        validated = self.validate_payload(operation, payload)
        key = request_hash({"provider": "topvisor", "operation": operation, "payload": validated})

        async def fetch() -> dict[str, Any]:
            response = await self.http.request(
                "POST",
                f"{self.base_url}/{'/'.join(operation)}",
                headers=self._headers(),
                payload=validated,
                idempotent=True,
            )
            return self.validate_response(response)

        return await self.coalescer.run(key, fetch)

    async def read(
        self,
        action: str,
        service: str,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Backward-compatible three-segment read entrypoint."""

        return await self._read((action, service, method), payload)

    @staticmethod
    def validate_history(project_id, region_indexes, dates, limit=100, offset=0) -> dict[str, Any]:
        if not isinstance(region_indexes, list) or not 1 <= len(region_indexes) <= 10:
            raise ValueError("provide 1-10 project region indexes")
        if not isinstance(dates, list) or not 1 <= len(dates) <= 31:
            raise ValueError("provide 1-31 explicit check dates")
        for value in dates:
            if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
                raise ValueError("dates must use YYYY-MM-DD")
            date.fromisoformat(value)
        return {
            "project_id": _positive_int(project_id, "project_id", MAX_ID),
            "regions_indexes": list(
                dict.fromkeys(_non_negative_int(value, "region_index", MAX_ID) for value in region_indexes)
            ),
            "dates": list(dict.fromkeys(dates)),
            "type_range": 100,
            "positions_fields": ["position", "relevant_url"],
            "limit": _positive_int(limit, "limit", MAX_LIMIT),
            "offset": _non_negative_int(offset, "offset", MAX_OFFSET),
        }

    async def positions_history(self, project_id, region_indexes, dates, limit=100, offset=0):
        return await self._read(
            HISTORY_OPERATION, self.validate_history(project_id, region_indexes, dates, limit, offset)
        )

    async def projects(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        fields: Sequence[str] | None = None,
        include_positions_summary: bool = False,
    ) -> dict[str, Any]:
        return await self._read(
            PROJECTS_OPERATION,
            {
                "limit": limit,
                "offset": offset,
                "fields": list(fields or DEFAULT_PROJECT_FIELDS),
                "include_positions_summary": include_positions_summary,
            },
        )

    async def keywords(
        self,
        project_id: int | str,
        *,
        limit: int = 100,
        offset: int = 0,
        fields: Sequence[str] | None = None,
        show_trash: bool = False,
    ) -> dict[str, Any]:
        return await self._read(
            KEYWORDS_OPERATION,
            {
                "project_id": project_id,
                "limit": limit,
                "offset": offset,
                "fields": list(fields or DEFAULT_KEYWORD_FIELDS),
                "show_trash": show_trash,
            },
        )

    async def project_setup(self, project_id: int | str) -> dict[str, Any]:
        return await self._read(
            PROJECTS_OPERATION,
            {
                "id": project_id,
                "limit": 1,
                "fields": list(DEFAULT_PROJECT_FIELDS),
                "show_searchers_and_regions": 2,
            },
        )

    async def folders(
        self,
        project_id: int | str,
        *,
        limit: int = 100,
        offset: int = 0,
        show_trash: bool = False,
        view: str = "flat",
    ) -> dict[str, Any]:
        _reject_folder_group_trash(show_trash)
        return await self._read(
            FOLDERS_OPERATION,
            {
                "project_id": project_id,
                "limit": limit,
                "offset": offset,
                "fields": list(DEFAULT_FOLDER_FIELDS),
                "view": view,
            },
        )

    async def groups(
        self,
        project_id: int | str,
        *,
        limit: int = 100,
        offset: int = 0,
        show_trash: bool = False,
    ) -> dict[str, Any]:
        _reject_folder_group_trash(show_trash)
        return await self._read(
            GROUPS_OPERATION,
            {
                "project_id": project_id,
                "limit": limit,
                "offset": offset,
                "fields": list(DEFAULT_GROUP_FIELDS),
            },
        )

    async def search_regions(
        self,
        searcher_key: int | str,
        search: str,
        *,
        country_code: str | None = None,
        only_countries: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "searcher_key": searcher_key,
            "search": search,
            "only_countries": only_countries,
            "limit": limit,
            "offset": offset,
        }
        if country_code:
            payload["country_code"] = country_code
        return await self._read(REGIONS_OPERATION, payload)

    @classmethod
    def validate_projects(cls, limit: int, offset: int, include_positions_summary: bool) -> dict[str, Any]:
        return cls.validate_payload(
            PROJECTS_OPERATION,
            {
                "limit": limit,
                "offset": offset,
                "fields": list(DEFAULT_PROJECT_FIELDS),
                "include_positions_summary": include_positions_summary,
            },
        )

    @classmethod
    def validate_keywords(
        cls, project_id: int | str, limit: int, offset: int, show_trash: bool
    ) -> dict[str, Any]:
        return cls.validate_payload(
            KEYWORDS_OPERATION,
            {
                "project_id": project_id,
                "limit": limit,
                "offset": offset,
                "fields": list(DEFAULT_KEYWORD_FIELDS),
                "show_trash": show_trash,
            },
        )

    # --- Guarded write surface -------------------------------------------------

    @staticmethod
    def _normalize_write_operation(operation: object) -> tuple[str, ...]:
        if isinstance(operation, (str, bytes)) or not isinstance(operation, Sequence):
            raise ValueError("Topvisor write operation must be a path-segment sequence")
        parts = tuple(str(part).strip() for part in operation)
        if not MIN_WRITE_SEGMENTS <= len(parts) <= MAX_WRITE_SEGMENTS:
            raise ValueError("Topvisor write operation must have three to five path segments")
        if any(_PATH_SEGMENT.fullmatch(part) is None for part in parts):
            raise ValueError("Topvisor write operation contains an invalid path segment")
        return parts

    @classmethod
    def risk_tier(cls, operation: object) -> str:
        """Classify a write operation as low/medium/high for governor throttling.

        Allowlisted operations return their reviewed tier; anything else is
        classified by its action (del -> high, add/edit -> medium) and defaults
        to "high" for an unknown action so an unfamiliar mutation is never
        under-throttled.
        """
        parts = cls._normalize_write_operation(operation)
        tier = WRITE_ALLOWLIST.get(parts)
        if tier is not None:
            return tier
        return _WRITE_RISK_BY_ACTION.get(parts[0], _DEFAULT_WRITE_RISK_TIER)

    @classmethod
    def validate_write_operation(cls, operation: object) -> tuple[str, ...]:
        parts = cls._normalize_write_operation(operation)
        if parts not in WRITE_ALLOWLIST:
            raise ValueError("Topvisor write operation is not allowed")
        return parts

    @classmethod
    def validate_write(
        cls, operation: object, params: dict[str, Any]
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        """Fail-closed validation of a Topvisor write before any admission.

        Only an allowlisted operation with a bounded, fully-known parameter set
        passes; project_id is always required and bounded, and each object is
        targeted by a single scalar id. Runs as the pre-admission validator so a
        bad write never opens the provider circuit.
        """
        op = cls.validate_write_operation(operation)
        if not isinstance(params, dict):
            raise ValueError("Topvisor write params must be a mapping")

        if op == ADD_PROJECT_OPERATION:
            allowed, required = _ADD_PROJECT_PARAMS, _ADD_PROJECT_REQUIRED
        elif op == ADD_FOLDER_OPERATION:
            allowed, required = _ADD_FOLDER_PARAMS, _ADD_FOLDER_REQUIRED
        elif op == ADD_KEYWORD_OPERATION:
            allowed, required = _ADD_KEYWORD_PARAMS, _ADD_KEYWORD_REQUIRED
        elif op == ADD_GROUP_OPERATION:
            if "names" in params:
                allowed, required = _ADD_GROUPS_PARAMS, _ADD_GROUPS_REQUIRED
            else:
                allowed, required = _ADD_GROUP_PARAMS, _ADD_GROUP_REQUIRED
        elif op == IMPORT_KEYWORDS_OPERATION:
            allowed, required = _IMPORT_KEYWORDS_PARAMS, _IMPORT_KEYWORDS_REQUIRED
        elif op == SET_KEYWORD_TARGET_OPERATION:
            allowed, required = _SET_TARGET_PARAMS, _SET_TARGET_REQUIRED
        elif op == SET_KEYWORD_TAGS_OPERATION:
            allowed, required = _SET_TAGS_PARAMS, _SET_TAGS_REQUIRED
        elif op == ADD_SEARCHER_OPERATION:
            allowed, required = _ADD_SEARCHER_PARAMS, _ADD_SEARCHER_REQUIRED
        elif op == ADD_REGION_OPERATION:
            allowed, required = _ADD_REGION_PARAMS, _ADD_REGION_REQUIRED
        elif op == IMPORT_REGIONS_OPERATION:
            allowed, required = _IMPORT_REGIONS_PARAMS, _IMPORT_REGIONS_REQUIRED
        elif op == RENAME_GROUP_OPERATION:
            allowed, required = _RENAME_GROUP_PARAMS, _RENAME_GROUP_REQUIRED
        else:
            allowed, required = _TOGGLE_GROUP_PARAMS, _TOGGLE_GROUP_REQUIRED

        unknown = sorted(set(params) - allowed)
        if unknown:
            raise ValueError("unsupported Topvisor write parameters: " + ", ".join(unknown))
        missing = sorted(required - set(params))
        if missing:
            raise ValueError("missing required Topvisor write parameters: " + ", ".join(missing))

        validated: dict[str, Any] = {}
        if "project_id" in params:
            validated["project_id"] = _positive_int(params["project_id"], "project_id", MAX_ID)

        if op == ADD_PROJECT_OPERATION:
            validated["url"] = _project_url(params["url"])
            if params.get("name") is not None:
                validated["name"] = _string_value(params["name"], "name", MAX_PROJECT_NAME_LEN)
            if params.get("tags") is not None:
                validated["tags"] = _tags(params["tags"])
            if params.get("folder_id") is not None:
                validated["folder_id"] = _positive_int(params["folder_id"], "folder_id", MAX_ID)
            if params.get("on") is not None:
                validated["on"] = int(_boolean(params["on"], "on"))
        elif op == ADD_FOLDER_OPERATION:
            validated["name"] = _string_value(params["name"], "name", MAX_FOLDER_NAME_LEN)
            if "to_id" in params:
                validated["to_id"] = _non_negative_int(params["to_id"], "to_id", MAX_ID)
            if "to_type" in params:
                if params["to_type"] not in {"before", "after", "in"}:
                    raise ValueError("unsupported Topvisor folder to_type")
                validated["to_type"] = params["to_type"]
        elif op == ADD_KEYWORD_OPERATION:
            validated["name"] = _string_value(params["name"], "name", MAX_KEYWORD_LEN)
            if "to_id" in params:
                validated["to_id"] = _positive_int(params["to_id"], "to_id", MAX_ID)
            if "to_type" in params:
                to_type = params["to_type"]
                if not isinstance(to_type, str) or to_type not in _KEYWORD_TO_TYPES:
                    raise ValueError("unsupported Topvisor to_type")
                validated["to_type"] = to_type
        elif op == ADD_GROUP_OPERATION:
            if "names" in params:
                validated["names"] = _string_list(
                    params["names"], "names", maximum_items=250, maximum_length=MAX_GROUP_NAME_LEN
                )
                if "to_id" in params:
                    validated["to_id"] = _non_negative_int(params["to_id"], "to_id", MAX_ID)
                if "to_type" in params:
                    if params["to_type"] not in {
                        "in_folder",
                        "in_folder_last",
                        "before_group",
                        "after_group",
                    }:
                        raise ValueError("unsupported Topvisor group to_type")
                    validated["to_type"] = params["to_type"]
            else:
                validated["names"] = [_string_value(params["name"], "name", MAX_GROUP_NAME_LEN)]
            if "on" in params:
                validated["on"] = _boolean(params["on"], "on")
        elif op == IMPORT_KEYWORDS_OPERATION:
            keywords_csv, _normalized = _keyword_import_csv(params["keywords"])
            validated["keywords"] = keywords_csv
        elif op == SET_KEYWORD_TARGET_OPERATION:
            validated["id"] = _positive_int(params["id"], "id", MAX_ID)
            validated["target"] = _target_url(params["target"])
        elif op == SET_KEYWORD_TAGS_OPERATION:
            validated["id"] = _positive_int(params["id"], "id", MAX_ID)
            validated["tags"] = _tags(params["tags"])
            if params["action"] not in {"set", "add", "remove"}:
                raise ValueError("action must be set, add, or remove")
            validated["action"] = params["action"]
        elif op == ADD_SEARCHER_OPERATION:
            validated["searcher_key"] = _searcher_key(params["searcher_key"])
        elif op == ADD_REGION_OPERATION:
            validated["searcher_key"] = _searcher_key(params["searcher_key"])
            validated["region_key"] = _positive_int(params["region_key"], "region_key", MAX_ID)
            if params.get("region_lang") is not None:
                validated["region_lang"] = _string_value(params["region_lang"], "region_lang", 8)
            if params.get("region_device") is not None:
                validated["region_device"] = _region_device(params["region_device"])
            if params.get("region_depth") is not None:
                validated["region_depth"] = _region_depth(params["region_depth"], validated["searcher_key"])
        elif op == IMPORT_REGIONS_OPERATION:
            regions_csv, _normalized = _regions_import_csv(params["regions"])
            validated["regions"] = regions_csv
        elif op == RENAME_GROUP_OPERATION:
            validated["id"] = _positive_int(params["id"], "id", MAX_ID)
            validated["name"] = _string_value(params["name"], "name", MAX_GROUP_NAME_LEN)
        else:  # TOGGLE_GROUP_OPERATION
            validated["id"] = _positive_int(params["id"], "id", MAX_ID)
            validated["on"] = _boolean(params["on"], "on")
        return op, validated

    @classmethod
    def prepare_keyword_import(
        cls, project_id: int | str, keywords: Sequence[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        _csv, normalized = _keyword_import_csv(keywords)
        _op, payload = cls.validate_write(
            IMPORT_KEYWORDS_OPERATION, {"project_id": project_id, "keywords": keywords}
        )
        return payload, normalized

    @classmethod
    def validate_project_setup(cls, project_id: int | str) -> dict[str, Any]:
        return cls.validate_payload(
            PROJECTS_OPERATION,
            {
                "id": project_id,
                "limit": 1,
                "fields": list(DEFAULT_PROJECT_FIELDS),
                "show_searchers_and_regions": 2,
            },
        )

    @classmethod
    def validate_folders(
        cls,
        project_id: int | str,
        limit: int,
        offset: int,
        show_trash: bool,
        view: str,
    ) -> dict[str, Any]:
        _reject_folder_group_trash(show_trash)
        return cls.validate_payload(
            FOLDERS_OPERATION,
            {
                "project_id": project_id,
                "limit": limit,
                "offset": offset,
                "fields": list(DEFAULT_FOLDER_FIELDS),
                "view": view,
            },
        )

    @classmethod
    def validate_groups(
        cls, project_id: int | str, limit: int, offset: int, show_trash: bool
    ) -> dict[str, Any]:
        _reject_folder_group_trash(show_trash)
        return cls.validate_payload(
            GROUPS_OPERATION,
            {
                "project_id": project_id,
                "limit": limit,
                "offset": offset,
                "fields": list(DEFAULT_GROUP_FIELDS),
            },
        )

    @classmethod
    def validate_region_search(
        cls,
        searcher_key: int | str,
        search: str,
        country_code: str | None,
        only_countries: bool,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "searcher_key": searcher_key,
            "search": search,
            "only_countries": only_countries,
            "limit": limit,
            "offset": offset,
        }
        if country_code:
            payload["country_code"] = country_code
        return cls.validate_payload(REGIONS_OPERATION, payload)

    @classmethod
    def prepare_regions_import(
        cls, project_id: int | str, regions: Sequence[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        _csv, normalized = _regions_import_csv(regions)
        _op, payload = cls.validate_write(
            IMPORT_REGIONS_OPERATION, {"project_id": project_id, "regions": regions}
        )
        return payload, normalized

    async def apply_write(self, operation: object, params: dict[str, Any]) -> dict[str, Any]:
        """Execute one allowlisted Topvisor write.

        Fail-closed validation runs first. A production mutation is never
        coalesced and never retried blindly (idempotent=False keeps the transport
        from replaying a non-idempotent POST). Topvisor returns an application
        error envelope even on HTTP 200, so the response is passed through
        validate_response, which raises ProviderError on any error markers.
        """
        op, validated = self.validate_write(operation, params)
        response = await self.http.request(
            "POST",
            f"{self.base_url}/{'/'.join(op)}",
            headers=self._headers(),
            payload=validated,
            idempotent=False,
        )
        return self.validate_response(response)

    async def readback(self, operation: object, params: dict[str, Any]) -> dict[str, Any]:
        """Re-read the affected project's keywords to confirm an applied write.

        Re-read the most specific bounded inventory for the mutation.
        """
        op, validated = self.validate_write(operation, params)
        if op == ADD_PROJECT_OPERATION:
            return await self.projects(limit=500)
        project_id = validated["project_id"]
        if op == ADD_FOLDER_OPERATION:
            return await self.folders(project_id, limit=500)
        if op in {ADD_SEARCHER_OPERATION, ADD_REGION_OPERATION, IMPORT_REGIONS_OPERATION}:
            return await self.project_setup(project_id)
        if op in {ADD_GROUP_OPERATION, RENAME_GROUP_OPERATION, TOGGLE_GROUP_OPERATION}:
            return await self.groups(project_id, limit=500)
        return await self.keywords(project_id, limit=500)
