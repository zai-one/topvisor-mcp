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
| Track changes | Read saved position history for the search regions configured in the project, optionally only keywords with SERP features such as AI Overview (`serp_features`). |
| Track AI answers | Read AI tracker settings, mention/visibility/sentiment summary and per-prompt history (`topvisor_ai_tracker_*`); paid AI checks are not started. |
| Explain ranking changes | Compare two dates by keyword and relevant URL, then export JSON or CSV with missing values kept distinct from ranks. |
| Run a controlled check | Get a price quote, confirm its cost and launch once within operator-defined projects and estimate limits. |

[Ranking reports and paid-check walkthrough](docs/RANKINGS.md) includes requests, local configuration and recovery from an uncertain launch.

## Quick start

Prefer a ready package? [Install the release and generate your client configuration](INSTALL.md#install-a-release-package). No source checkout is required.

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


<!-- agent-block:start -->
## Install in your agent

Run `topvisor-mcp` straight from GitHub with [uv](https://docs.astral.sh/uv/). Pin a release tag (`@vX.Y.Z`) for
reproducible installs; placeholders below are examples, keep secrets in files outside the repo.

**Claude Code**

```bash
claude mcp add topvisor --env TOPVISOR_USER_ID=123456 --env TOPVISOR_API_KEY_FILE=/path/to/topvisor.token --env TOPVISOR_STATE_PATH=/path/to/topvisor.sqlite -- uvx --from git+https://github.com/zai-one/topvisor-mcp topvisor-mcp
```

Skills for Claude Code: copy `skills/*` into `~/.claude/skills/` (or install this repo as a plugin — it
ships `.claude-plugin/plugin.json` with the skills and the MCP server).

**Cursor** — `.cursor/mcp.json` ([one-click install](cursor://anysphere.cursor-deeplink/mcp/install?name=topvisor&config=eyJjb21tYW5kIjogInV2eCIsICJhcmdzIjogWyItLWZyb20iLCAiZ2l0K2h0dHBzOi8vZ2l0aHViLmNvbS96YWktb25lL3RvcHZpc29yLW1jcCIsICJ0b3B2aXNvci1tY3AiXSwgImVudiI6IHsiVE9QVklTT1JfVVNFUl9JRCI6ICIxMjM0NTYiLCAiVE9QVklTT1JfQVBJX0tFWV9GSUxFIjogIi9wYXRoL3RvL3RvcHZpc29yLnRva2VuIiwgIlRPUFZJU09SX1NUQVRFX1BBVEgiOiAiL3BhdGgvdG8vdG9wdmlzb3Iuc3FsaXRlIn19)):

```json
{
  "mcpServers": {
    "topvisor": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/zai-one/topvisor-mcp",
        "topvisor-mcp"
      ],
      "env": {
        "TOPVISOR_USER_ID": "123456",
        "TOPVISOR_API_KEY_FILE": "/path/to/topvisor.token",
        "TOPVISOR_STATE_PATH": "/path/to/topvisor.sqlite"
      }
    }
  }
}
```

**Codex** — `~/.codex/config.toml` (skills: copy `skills/*` into `~/.codex/skills/`, or keep the
repo's `.agents/skills` link):

```toml
[mcp_servers.topvisor]
command = "uvx"
args = ["--from", "git+https://github.com/zai-one/topvisor-mcp", "topvisor-mcp"]
env = { TOPVISOR_USER_ID = "123456", TOPVISOR_API_KEY_FILE = "/path/to/topvisor.token", TOPVISOR_STATE_PATH = "/path/to/topvisor.sqlite" }
```

**Claude Desktop** — `claude_desktop_config.json`: the same `mcpServers` block as Cursor.

## Skills (agent playbooks)

Each skill is a self-contained folder `skills/<name>/` (`SKILL.md` + its own `references/`,
`templates/`); copy the folder and it works. Agents load the short `SKILL.md` only when the task matches
and open the other files on demand. Clients without skills get the same flows as MCP prompts and the
`topvisor://playbook` / `topvisor://guide/{topic}` resources.

| Skill | What it does |
|---|---|
| `topvisor-weekly-report` | Weekly ranking report from saved positions: TOP-3/10/30, movers, URL changes (free). |
| `topvisor-rank-check-safe` | Paid rank check with balance, quote, explicit approval, one launch, polling. |
| `topvisor-competitor-tracking` | AI-tracker competitor visibility and keywords lost from TOP-10. |
| `seo-weekly-client-report` | Agency client report: Topvisor + optional yandex-mcp, roistat-mcp, keysso-mcp. |

## Toolsets and read-only mode

`TOPVISOR_TOOLSETS=all` (default) or a comma list (see `topvisor://toolsets`); `TOPVISOR_TOOLS=a,b` adds single tools,
`TOPVISOR_DISABLED_TOOLS=a,b` removes them, `TOPVISOR_READ_ONLY=1` removes every write/paid tool.

## Example requests

- Покажи мои проекты Topvisor и регионы проекта X.
- Сделай недельный отчёт по позициям проекта X (без платных проверок).
- Сколько стоит обновить позиции по проекту X? Запусти только после моего OK.
- Какие запросы выпали из ТОП-10 за неделю?
- Как бренд виден в AI-ответах по сравнению с конкурентами?
- Собери еженедельный SEO-отчёт клиенту.
<!-- agent-block:end -->

## Access and limits

Ranking reports read history already saved in Topvisor. Paid checks use a separate quote and confirmation workflow, disabled until the operator sets project and estimate limits. Keyword changes default to a preview. Deletion is unavailable; history uses project region indexes. [Limits and reconciliation](docs/RANKINGS.md).

### Updates

`topvisor_check_update` compares the installed version with the latest [GitHub release](https://github.com/zai-one/topvisor-mcp/releases) and returns the release link and the matching `uv tool install --force ...` command. It never installs anything. The result is cached for 24 hours next to the state database; when a newer release is cached, the server instructions mention it once. Set `TOPVISOR_DISABLE_UPDATE_CHECK=1` to turn off both the tool's network request and the startup refresh.

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

## Built by ZAI.ONE

[ZAI.ONE](https://zai.one) is a digital agency working on websites, SEO, advertising and analytics. We also build tools that connect AI assistants to everyday work. [Talk to us on Telegram](https://t.me/zai_one) about setup, automation or an integration for your team.

## Use and feedback

You may install and use this project for your own accounts under [LicenseRef-ZAI-ONE](LICENSE).
This is not an open-source license. Third-party notices remain in [NOTICE](NOTICE).
If it helps, give the repository a ⭐. Missing something or found a bug? [Open an issue](https://github.com/zai-one/topvisor-mcp/issues/new/choose).
I'm working on this project; accepted improvements are implemented here. Support is not guaranteed.
