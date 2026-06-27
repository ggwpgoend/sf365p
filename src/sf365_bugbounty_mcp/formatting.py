"""Render API JSON into compact, LLM-friendly Markdown summaries.

Every MCP tool returns a Markdown summary (easy for the model to read) followed
by the raw JSON (so the agent can extract exact fields when it needs them).
"""

from __future__ import annotations

from typing import Any

SEVERITY_ORDER = ["critical", "high", "medium", "low", "none"]

_CURRENCY_SIGN = {"rub": "₽", "usd": "$", "eur": "€"}

# Fields kept in list/search raw JSON. The full program card (notably the
# ~18 KB `description`/rules) is dropped here to keep agent context small —
# fetch it with get_program / get_program_full instead.
PROGRAM_LIST_FIELDS = (
    "id",
    "vendorId",
    "slug",
    "name",
    "shortDescription",
    "visibility",
    "terms",
    "contractType",
    "status",
    "finished",
    "finishedAt",
    "publishedAt",
    "createdAt",
    "updatedAt",
    "participantsCount",
    "onlyMaxPayment",
    "canShareRewards",
    "triageEnabled",
    "reportsForbidden",
    "hasLimits",
    "participationFormat",
    "vendor",
    "statistics",
    # present on landing/top-program items:
    "vendorName",
    "maxSeverityReward",
    "currency",
    "severity",
    "reportsCount",
    "acceptedReportsCount",
)


def slim_program(p: dict[str, Any]) -> dict[str, Any]:
    """Project a program down to list-relevant fields (drops heavy text)."""
    return {k: p[k] for k in PROGRAM_LIST_FIELDS if k in p}


def slim_programs_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return the listing envelope with each item slimmed."""
    return {
        **envelope,
        "items": [slim_program(p) for p in envelope.get("items", [])],
    }


def money(amount: Any, currency: str | None) -> str:
    if amount is None:
        return "—"
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    sign = _CURRENCY_SIGN.get((currency or "").lower(), "")
    whole = f"{value:,.0f}".replace(",", " ")
    return f"{whole} {sign}".strip() if sign else f"{whole} {currency or ''}".strip()


def program_url(slug: str | None) -> str:
    if not slug:
        return "https://bugbounty.standoff365.com/"
    return f"https://bugbounty.standoff365.com/programs/{slug}"


def program_line(p: dict[str, Any]) -> str:
    """One-line summary of a program for list views."""
    name = p.get("name", "?")
    vendor = (p.get("vendor") or {}).get("name") or p.get("vendorName") or ""
    vis = p.get("visibility", "")
    pid = p.get("id") or p.get("programId")
    slug = p.get("slug")
    reward = p.get("maxSeverityReward")
    currency = p.get("currency")
    stats = p.get("statistics") or {}
    reports = stats.get("reportsCount", p.get("reportsCount"))
    bits = [f"**{name}**"]
    if vendor and vendor != name:
        bits.append(f"by {vendor}")
    meta = [f"id={pid}", f"slug={slug}", vis]
    if reward:
        meta.append(f"max {money(reward, currency)}")
    if reports is not None:
        meta.append(f"{reports} reports")
    return f"- {' '.join(bits)} ({', '.join(m for m in meta if m)})\n  {program_url(slug)}"


def programs_summary(envelope: dict[str, Any], *, search: str | None = None) -> str:
    items = envelope.get("items", [])
    total_entries = envelope.get("totalEntries")
    total_pages = envelope.get("total")
    page = envelope.get("page")
    header = "## Programs"
    if search:
        header += f" matching '{search}'"
    lines = [
        header,
        f"Page {page}/{total_pages} · {len(items)} shown · {total_entries} total\n",
    ]
    lines.extend(program_line(p) for p in items)
    if not items:
        lines.append("_No programs found._")
    return "\n".join(lines)


def _clip(text: str | None, limit: int = 4000) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n…(truncated)"


def program_detail(p: dict[str, Any]) -> str:
    name = p.get("name", "?")
    vendor = (p.get("vendor") or {}).get("name") or ""
    stats = p.get("statistics") or {}
    lines = [
        f"# {name}",
        f"{p.get('shortDescription', '').strip()}\n",
        "## Key facts",
        f"- ID: {p.get('id')}  ·  slug: {p.get('slug')}",
        f"- Vendor: {vendor}",
        f"- Visibility: {p.get('visibility')}",
        f"- Terms: {p.get('terms')}",
        f"- Status: {p.get('status')}  ·  finished: {p.get('finished')}",
        f"- Published: {p.get('publishedAt')}",
        f"- Participants: {p.get('participantsCount')}",
        f"- Only max payment: {p.get('onlyMaxPayment')}  ·  triage: {p.get('triageEnabled')}",
        f"- URL: {program_url(p.get('slug'))}",
    ]
    if stats:
        lines.append(
            "- Stats: "
            + ", ".join(f"{k}={v}" for k, v in stats.items() if v is not None)
        )
    if p.get("specialRules"):
        lines += ["\n## Special rules", _clip(p["specialRules"], 2000)]
    if p.get("description"):
        lines += ["\n## Program rules & policy", _clip(p["description"])]
    return "\n".join(lines)


def scope_summary(scopes: list[dict[str, Any]], program_id: int) -> str:
    if not scopes:
        return f"## Scope for program {program_id}\n_No scope entries returned._"
    lines = [f"## Scope for program {program_id} ({len(scopes)} entries)\n"]
    for s in scopes:
        kind = s.get("appTypeName", "?")
        sev = s.get("severity", "")
        targets = (s.get("scope") or "").strip()
        # The scope field packs many assets separated by blank lines.
        assets = [t.strip() for t in targets.replace("\r", "").split("\n") if t.strip()]
        lines.append(f"### {kind} — severity: {sev} (scope id {s.get('id')})")
        if len(assets) > 1:
            lines.extend(f"- {a}" for a in assets)
        else:
            lines.append(targets or "_(empty)_")
        lines.append("")
    return "\n".join(lines).rstrip()


def rewards_summary(rewards: dict[str, Any], program_id: int) -> str:
    currency = rewards.get("currency")
    lines = [
        f"## Rewards for program {program_id}",
        f"Currency: {currency} · only max payment: {rewards.get('onlyMaxPayment')}\n",
        "| Severity | Min | Max |",
        "| --- | --- | --- |",
    ]
    for sev in SEVERITY_ORDER:
        bucket = rewards.get(sev)
        if not isinstance(bucket, dict):
            continue
        lines.append(
            f"| {sev} | {money(bucket.get('minReward'), currency)} "
            f"| {money(bucket.get('maxReward'), currency)} |"
        )
    return "\n".join(lines)


def vendors_summary(envelope: dict[str, Any]) -> str:
    items = envelope.get("items", [])
    lines = [
        f"## Vendors (page {envelope.get('page')}, {envelope.get('totalEntries')} total)\n"
    ]
    for v in items:
        desc = (v.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 160:
            desc = desc[:160] + "…"
        lines.append(f"- **{v.get('name')}** (id={v.get('id')}, {v.get('shortName')}) — {desc}")
    return "\n".join(lines)


def top_programs_summary(items: list[dict[str, Any]], title: str) -> str:
    lines = [f"## {title}\n"]
    for p in items:
        lines.append(
            f"- **{p.get('name')}** by {p.get('vendorName', '')} "
            f"(slug={p.get('slug')}, max {money(p.get('maxSeverityReward'), p.get('currency'))}, "
            f"{p.get('reportsCount')} reports)"
        )
    return "\n".join(lines)


def disclosed_list_summary(envelope: dict[str, Any]) -> str:
    items = envelope.get("items", [])
    lines = [
        f"## Disclosed reports (page {envelope.get('page')}, "
        f"{envelope.get('totalEntries')} total)\n"
    ]
    for r in items:
        info = r.get("reportDiscloseInfo") or {}
        author = (r.get("author") or {}).get("username") or "?"
        lines.append(
            f"- **{info.get('reportName', '?')}** "
            f"(disclose id={info.get('id')}, program={info.get('programName')}, "
            f"severity={r.get('severity')}, reward={money(r.get('amount'), r.get('currency'))}, "
            f"by {author})"
        )
    if not items:
        lines.append("_No disclosed reports._")
    return "\n".join(lines)


def disclosed_detail_summary(r: dict[str, Any]) -> str:
    author = (r.get("author") or {}).get("username") or "?"
    lines = [
        f"# {r.get('name', 'Disclosed report')}",
        f"Severity: {r.get('severity')} · reward: {money(r.get('amount'), r.get('currency'))} "
        f"· author: {author}",
        f"Origin report id: {r.get('originReportId')} · created: {r.get('originCreatedAt')}\n",
        "## Description",
        _clip(r.get("description"), 8000),
    ]
    return "\n".join(lines)
