"""MCP server exposing the Standoff 365 Bug Bounty platform to AI agents.

Run over stdio (the transport Claude Code and most MCP clients use):

    uvx sf365-bugbounty-mcp
    # or
    python -m sf365_bugbounty_mcp

Configuration via environment variables:
    SF365_TOKEN      Optional bearer token to unlock private programs.
    SF365_LANGUAGE   "ru-RU" (default) or "en-US" for UI strings.

Each tool returns a human/LLM-readable Markdown summary followed by the raw
JSON payload, so agents can both reason over the text and pull exact fields.
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import formatting as fmt
from .client import Sf365Client, Sf365Error

mcp = FastMCP("sf365-bugbounty")

_client: Sf365Client | None = None


def get_client() -> Sf365Client:
    global _client
    if _client is None:
        _client = Sf365Client(
            token=os.environ.get("SF365_TOKEN"),
            language=os.environ.get("SF365_LANGUAGE", "ru-RU"),
        )
    return _client


def _render(summary: str, raw: Any) -> str:
    """Markdown summary + fenced raw JSON for precise field access."""
    payload = json.dumps(raw, ensure_ascii=False, indent=2)
    return f"{summary}\n\n```json\n{payload}\n```"


# --------------------------------------------------------------------------
# Programs
# --------------------------------------------------------------------------


@mcp.tool()
async def list_programs(page: int = 1, search: str | None = None) -> str:
    """List bug bounty programs on Standoff 365 (paginated, ~5 per page).

    Args:
        page: 1-based page number.
        search: Optional text filter applied server-side (matches name/vendor).

    Returns a Markdown summary plus raw JSON. The envelope includes ``total``
    (page count) and ``totalEntries`` (program count) for pagination.
    """
    try:
        data = await get_client().list_programs(page=page, search=search)
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.programs_summary(data, search=search), data)


@mcp.tool()
async def search_programs(query: str, max_results: int = 25) -> str:
    """Search across ALL program pages and return matches in one shot.

    Use this instead of paging through ``list_programs`` when you have a
    keyword (company name, product, vendor) and want every match.

    Args:
        query: Search text (matches program/vendor name).
        max_results: Cap on returned programs.
    """
    try:
        items = await get_client().iter_all_programs(search=query)
    except Sf365Error as exc:
        return f"Error: {exc}"
    items = items[: max(1, max_results)]
    summary = fmt.programs_summary(
        {"items": items, "page": 1, "total": 1, "totalEntries": len(items)},
        search=query,
    )
    return _render(summary, items)


@mcp.tool()
async def get_program(program: str) -> str:
    """Get the full card for one program by numeric id or slug.

    Includes the program's rules/policy text, special rules, vendor info,
    terms, visibility and statistics. Pass either the numeric ``id`` or the
    ``slug`` (e.g. "vkontakte_vk").
    """
    try:
        data = await get_client().get_program(program)
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.program_detail(data), data)


@mcp.tool()
async def get_program_scope(program_id: int, sort: str = "scope") -> str:
    """Get in-scope targets/assets for a program (by numeric program id).

    Returns the assets in scope grouped by type (Domain, iOS, Android, ...),
    each with its severity ceiling. ``sort`` accepts: scope, severity,
    app_type_id, created_at (optionally with a ``_desc`` suffix).
    """
    try:
        data = await get_client().get_program_scope(program_id, sort=sort)
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.scope_summary(data, program_id), data)


@mcp.tool()
async def get_program_rewards(program_id: int) -> str:
    """Get the reward range table for a program (by numeric program id).

    Returns min/max payout per severity (none, low, medium, high, critical)
    and the currency.
    """
    try:
        data = await get_client().get_program_rewards(program_id)
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.rewards_summary(data, program_id), data)


@mcp.tool()
async def get_program_full(program: str) -> str:
    """Get everything about one program: card + scope + rewards in one call.

    Convenience tool that fetches the program detail, its scope, and its
    reward table together. Pass a numeric id or a slug.
    """
    client = get_client()
    try:
        detail = await client.get_program(program)
        program_id = detail.get("id")
        scope = await client.get_program_scope(program_id) if program_id else []
        rewards = await client.get_program_rewards(program_id) if program_id else {}
    except Sf365Error as exc:
        return f"Error: {exc}"
    summary = "\n\n".join(
        [
            fmt.program_detail(detail),
            fmt.scope_summary(scope, detail.get("id")),
            fmt.rewards_summary(rewards, detail.get("id")),
        ]
    )
    raw = {"program": detail, "scope": scope, "rewards": rewards}
    return _render(summary, raw)


# --------------------------------------------------------------------------
# Landing highlights & vendors
# --------------------------------------------------------------------------


@mcp.tool()
async def list_top_programs() -> str:
    """Get the platform's featured/top programs (landing highlights)."""
    try:
        data = await get_client().top_programs()
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.top_programs_summary(data, "Top programs"), data)


@mcp.tool()
async def list_top_rewards() -> str:
    """Get the platform's top rewards/payouts (landing highlights)."""
    try:
        data = await get_client().top_rewards()
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.top_programs_summary(data, "Top rewards"), data)


@mcp.tool()
async def list_vendors(page: int = 1) -> str:
    """List companies/vendors running programs on the platform (paginated)."""
    try:
        data = await get_client().list_vendors(page=page)
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.vendors_summary(data), data)


# --------------------------------------------------------------------------
# Disclosed reports
# --------------------------------------------------------------------------


@mcp.tool()
async def list_disclosed_reports(page: int = 1) -> str:
    """List publicly disclosed vulnerability reports (paginated).

    Useful for learning from past findings: each entry references its program,
    severity, reward and author.
    """
    try:
        data = await get_client().list_disclosed_reports(page=page)
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.disclosed_list_summary(data), data)


@mcp.tool()
async def get_disclosed_report(report_id: int) -> str:
    """Get the full text of one disclosed report by its disclose id.

    The id is the ``reportDiscloseInfo.id`` from ``list_disclosed_reports``.
    """
    try:
        data = await get_client().get_disclosed_report(report_id)
    except Sf365Error as exc:
        return f"Error: {exc}"
    return _render(fmt.disclosed_detail_summary(data), data)


def main() -> None:
    """Console-script / module entry point. Serves over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
