🇬🇧 English · [🇷🇺 Русский](README.ru.md)

# Topvisor MCP

**Keep your keyword research and ranking history in the conversation.**

Ask your assistant to inspect a project, prepare keyword groups or find queries that lost positions in saved reports. Topvisor MCP connects those tasks to your existing projects, with previews before supported changes are applied.

[Quick start](#quick-start) · [Connect your assistant](#connect-your-assistant) · [Issues](https://github.com/zai-one/topvisor-mcp/issues)

Try asking your assistant:

> Compare saved rankings for my project on two dates I choose. Identify queries that lost positions and group them by target URL.

## What you can do

| Your task | What the MCP server provides |
|---|---|
| Review a project | Projects, folders, keyword groups, keywords and search settings. |
| Organise keywords | Create groups, import phrases, assign target URLs and tags; preview supported writes first. |
| Track changes | Read saved position history for the search regions configured in the project. |

## Quick start

Install **Python 3.12–3.14** and [uv](https://docs.astral.sh/uv/getting-started/installation/). Clone with Git or [download the ZIP](https://github.com/zai-one/topvisor-mcp/archive/refs/heads/main.zip). With a ZIP, open the extracted directory and skip the first two commands.

You need your Topvisor user ID and API key. The wizard saves the key in a private local file.

```sh
git clone https://github.com/zai-one/topvisor-mcp.git
cd topvisor-mcp
uv sync --frozen
uv run --frozen python scripts/configure.py
uv run --frozen topvisor-mcp --config mcp.local.json --check-config
```

The wizard creates a local configuration and stores secrets in private files. It refuses to overwrite an existing setup. `--check-config` validates local settings; the first request below checks your account connection.

## Connect your assistant

Add this configuration to an MCP client that uses `mcpServers`, such as Claude Desktop or Cursor. Replace `/ABSOLUTE/PATH/` with your absolute path; Windows JSON paths can use forward slashes, such as `D:/Tools/`.

```json
{
  "mcpServers": {
    "topvisor": {
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/topvisor-mcp",
        "run",
        "--frozen",
        "topvisor-mcp",
        "--config",
        "/ABSOLUTE/PATH/topvisor-mcp/mcp.local.json"
      ]
    }
  }
}
```

The client starts the MCP server for you. Refresh its tool list, then make your first request. For clients with a different config format, reuse the same `command` and `args`; `uv` must be available to the client process.

### First request

> List my Topvisor projects. For the project I choose, show its search regions and keyword groups.

You should see your projects and their existing settings. You can then request saved positions or prepare a keyword change. A preview does not change project data.

If tools do not appear, check the absolute path, whether the client can find `uv`, and the `--check-config` result. For access errors, check account credentials and permissions. [Installation and troubleshooting](INSTALL.md).

## Access and limits

Saved ranking history must already exist in Topvisor. This server does not launch paid position checks or delete data. Typed writes default to a preview and need explicit enabling for actual changes; history uses project region indexes.

Authenticated HTTP is available for a server deployment. See [HTTP setup](INSTALL.md#http), [configuration and permissions](docs/RUNTIME.md) and [Python package integration](INSTALL.md#python-package-and-platform-integration).

<details>
<summary>For developers: project checks</summary>

```sh
uv sync --frozen --all-groups
uv run --frozen python scripts/verify.py
uv run --frozen python scripts/verify_install.py
```

Tests use synthetic fixtures. A passing test run does not establish live provider connectivity.

</details>

## Use and feedback

You may install and use this project for your own accounts under [LicenseRef-ZAI-ONE](LICENSE).
This is not an open-source license. Third-party notices remain in [NOTICE](NOTICE).
If it helps, give the repository a ⭐. Missing something or found a bug? [Open an issue](https://github.com/zai-one/topvisor-mcp/issues/new/choose).
I'm working on this project; accepted improvements are implemented here. Support is not guaranteed.
