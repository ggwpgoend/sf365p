# Standoff 365 Bug Bounty — MCP server

An [MCP](https://modelcontextprotocol.io) server that exposes the
[bugbounty.standoff365.com](https://bugbounty.standoff365.com) bug bounty
platform to AI agents (Claude Code and any other MCP client).

It gives an agent structured, read-only access to:

- **Programs** — the full list, search, and per-program detail (rules/policy).
- **Scope / targets** — in-scope assets (domains, mobile apps, …) with severity.
- **Rewards** — the min/max payout table per severity level.
- **Vendors** — companies running programs.
- **Disclosed reports** — publicly disclosed vulnerability write-ups.

Every tool returns a readable Markdown summary **plus** the raw JSON, so the
agent can reason over the text and still pull exact fields.

## How it works

The public site is a Next.js front end backed by a REST API at
`https://api.standoff365.com/api/bug-bounty`, which sits behind a WAF. This
server sends the browser-style headers the WAF requires, caches responses
in-process, and retries transient errors. No scraping of rendered HTML.

## Install & run

Run directly with [uv](https://docs.astral.sh/uv/) (no install step):

```bash
uvx sf365-bugbounty-mcp
```

Or install into an environment:

```bash
pip install -e .
sf365-bugbounty-mcp          # or: python -m sf365_bugbounty_mcp
```

The server speaks MCP over **stdio**.

## Use with Claude Code

```bash
claude mcp add sf365-bugbounty -- uvx sf365-bugbounty-mcp
```

Or add it to your MCP config manually:

```json
{
  "mcpServers": {
    "sf365-bugbounty": {
      "command": "uvx",
      "args": ["sf365-bugbounty-mcp"],
      "env": {
        "SF365_LANGUAGE": "ru-RU"
      }
    }
  }
}
```

## Configuration

| Env var         | Default  | Purpose                                                        |
| --------------- | -------- | -------------------------------------------------------------- |
| `SF365_TOKEN`   | _(none)_ | Bearer token to unlock **private** programs the account can see. |
| `SF365_LANGUAGE`| `ru-RU`  | UI language (`ru-RU` or `en-US`). Program content is authored in Russian. |

Most data is public and needs no token. Private programs return an access
error unless a valid `SF365_TOKEN` is set. To obtain one, copy the bearer
token from an authenticated browser session (DevTools → Network →
`Authorization` header on an `api.standoff365.com` request).

## Tools

| Tool                    | Description                                            |
| ----------------------- | ------------------------------------------------------ |
| `list_programs`         | One page of programs (with optional `search`).         |
| `search_programs`       | Search across all pages for a keyword.                 |
| `get_program`           | Full program card by id or slug (rules included).      |
| `get_program_scope`     | In-scope assets for a program.                         |
| `get_program_rewards`   | Reward range table by severity.                        |
| `get_program_full`      | Card + scope + rewards in one call.                    |
| `list_top_programs`     | Featured programs (landing).                           |
| `list_top_rewards`      | Top payouts (landing).                                 |
| `list_vendors`          | Companies running programs.                            |
| `list_disclosed_reports`| Publicly disclosed reports.                            |
| `get_disclosed_report`  | Full text of one disclosed report.                     |

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests mock the HTTP layer (via `respx`) and run fully offline.

## Notes & etiquette

- Read-only; this server never submits reports or mutates anything.
- Responses are cached for 5 minutes to be gentle on the API.
- This is an unofficial client and not affiliated with Positive Technologies.
