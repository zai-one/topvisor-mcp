🇬🇧 English · [🇷🇺 Русский](README.ru.md)

# Topvisor MCP

MCP server for managing Topvisor projects and keyword lists. An AI assistant can organise keywords, configure search regions and read saved ranking history.

## What you can do

- Read projects, keywords, folders, groups and search settings.
- Create projects and groups, import keywords, and set target URLs and tags.
- Retrieve saved positions with `topvisor_positions_history`.

## Quick start

Install Python 3.12+ (below 3.15), [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git.

You need your Topvisor user ID and API key. The wizard saves the key in a private local file.

```sh
git clone https://github.com/zai-one/topvisor-mcp.git
cd topvisor-mcp
uv sync --frozen
uv run --frozen python scripts/configure.py
uv run --frozen topvisor-mcp --config mcp.local.json --check-config
uv run --frozen topvisor-mcp --config mcp.local.json
```

The last command starts stdio and waits for an MCP client; it is not an interactive chat.
See [INSTALL.md](INSTALL.md) for credentials, client configuration, HTTP and package integration.
`--check-config` checks local settings only; it never validates a provider account over the network.

## Scope and limits

Writes default to a preview and require explicit enabling to change project data. Deletion and launching paid position checks are not exposed. History requests use region indexes from the project settings, not geographic region codes. See [write and access settings](docs/RUNTIME.md).

## Verification

```sh
uv sync --frozen --all-groups
uv run --frozen python scripts/verify.py
uv run --frozen python scripts/verify_install.py
```

Tests use synthetic fixtures. A passing test run does not establish live provider connectivity.

## Use and feedback

You may install and use this project for your own accounts under [LicenseRef-ZAI-ONE](LICENSE).
This is not an open-source license. Third-party notices remain in [NOTICE](NOTICE).
If it helps, give the repository a ⭐. Missing something or found a bug? [Open an issue](https://github.com/zai-one/topvisor-mcp/issues/new/choose).
I'm working on this project; accepted improvements are implemented here. Support is not guaranteed.
