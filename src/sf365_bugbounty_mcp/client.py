"""Async HTTP client for the Standoff 365 Bug Bounty API.

The public site at https://bugbounty.standoff365.com is a Next.js front end
that talks to a REST backend at https://api.standoff365.com/api/bug-bounty.
That backend sits behind PT Application Firewall, which rejects requests that
do not look like they come from the browser app. We therefore always send the
browser-style ``User-Agent``/``Origin``/``Referer`` headers the WAF expects.

Authentication is optional: most programs are public. Setting ``SF365_TOKEN``
(a bearer token copied from an authenticated browser session) unlocks private
programs the account has access to.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

API_BASE = "https://api.standoff365.com/api/bug-bounty"
SITE_BASE = "https://bugbounty.standoff365.com"

# A current desktop Chrome UA. The WAF blocks obviously non-browser clients.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Sort keys accepted by the scope endpoint (validated server-side).
SCOPE_SORTS = {
    "app_type_id",
    "app_type_id_desc",
    "scope",
    "scope_desc",
    "severity",
    "severity_desc",
    "created_at",
    "created_at_desc",
}

# Sort keys accepted by the program listing (validated server-side).
PROGRAM_SORTS = {"program_name", "activity", "created_at"}

# "terms" filter values for the program listing. only_vuln = classic bug
# bounty, only_risks = business-risk programs, no_limits = unrestricted.
PROGRAM_TERMS = {"only_vuln", "only_risks", "no_limits"}


class Sf365Error(RuntimeError):
    """Raised when the API returns an error that callers should see."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _TTLCache:
    """Tiny in-process cache so repeated agent calls don't re-hit the API."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        ts, value = hit
        if (time.monotonic() - ts) > self._ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._store.clear()


class Sf365Client:
    """Thin async wrapper over the Standoff 365 Bug Bounty REST API."""

    def __init__(
        self,
        *,
        token: str | None = None,
        language: str = "ru-RU",
        timeout: float = 25.0,
        cache_ttl: float = 300.0,
        max_retries: int = 4,
        user_agent: str | None = None,
    ) -> None:
        self.token = token if token is not None else os.environ.get("SF365_TOKEN")
        self.language = language or "ru-RU"
        self.max_retries = max_retries
        self._cache = _TTLCache(cache_ttl)
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=timeout,
            headers=self._base_headers(user_agent or DEFAULT_USER_AGENT),
            follow_redirects=True,
        )

    def _base_headers(self, user_agent: str) -> dict[str, str]:
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": f"{self.language},en;q=0.8",
            # The WAF keys off the front-end origin; without these we get 403.
            "Origin": SITE_BASE,
            "Referer": f"{SITE_BASE}/",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "Sf365Client":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- core request ----------------------------------------------------

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        language: str | None = None,
    ) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        lang = language or self.language
        cache_key = f"{lang}|{path}|{sorted(params.items())}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        headers = {"Accept-Language": f"{lang},en;q=0.8"} if language else None

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = await self._client.get(path, params=params, headers=headers)
            except httpx.HTTPError as exc:  # network-level failure
                last_exc = exc
                await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                data = resp.json()
                self._cache.set(cache_key, data)
                return data

            # Retry transient server / rate-limit errors with backoff.
            if resp.status_code in (429, 502, 503, 504) and attempt < self.max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue

            raise self._error_for(resp, path)

        raise Sf365Error(
            f"Network error calling {path}: {last_exc}"
        ) from last_exc

    def _error_for(self, resp: httpx.Response, path: str) -> Sf365Error:
        status = resp.status_code
        if status == 401 or status == 403:
            detail = (
                "Access denied. This usually means a private program that "
                "requires authentication — set SF365_TOKEN to a valid bearer "
                "token. (It can also be a WAF block.)"
            )
            return Sf365Error(detail, status=status)
        if status == 404:
            return Sf365Error(f"Not found: {path}", status=404)
        # Try to surface the API's own error message.
        try:
            body = resp.json()
            msg = body.get("message") or body.get("detail") or str(body)
        except Exception:
            msg = resp.text[:300]
        return Sf365Error(f"API error {status} for {path}: {msg}", status=status)

    # -- programs --------------------------------------------------------

    async def list_programs(
        self,
        *,
        page: int = 1,
        search: str | None = None,
        sort: str | None = None,
        terms: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        """One page of programs. Envelope: items, page, total (pages), totalEntries.

        ``sort`` must be one of PROGRAM_SORTS; ``terms`` one of PROGRAM_TERMS.
        Invalid values are dropped rather than sent (the API would 422).
        """
        if sort is not None and sort not in PROGRAM_SORTS:
            raise Sf365Error(
                f"Invalid sort '{sort}'. Allowed: {sorted(PROGRAM_SORTS)}"
            )
        if terms is not None and terms not in PROGRAM_TERMS:
            raise Sf365Error(
                f"Invalid terms '{terms}'. Allowed: {sorted(PROGRAM_TERMS)}"
            )
        return await self._get(
            "/ui/program",
            params={"page": max(1, page), "search": search, "sort": sort, "terms": terms},
            language=language,
        )

    async def iter_all_programs(
        self,
        *,
        search: str | None = None,
        sort: str | None = None,
        terms: str | None = None,
        language: str | None = None,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch every program across all pages (respecting search/sort/terms)."""
        first = await self.list_programs(
            page=1, search=search, sort=sort, terms=terms, language=language
        )
        items = list(first.get("items", []))
        total_pages = int(first.get("total", 1) or 1)
        for page in range(2, min(total_pages, max_pages) + 1):
            chunk = await self.list_programs(
                page=page, search=search, sort=sort, terms=terms, language=language
            )
            items.extend(chunk.get("items", []))
        return items

    async def get_program(
        self, program: str | int, *, language: str | None = None
    ) -> dict[str, Any]:
        """Full program card by numeric id or slug."""
        return await self._get(f"/ui/program/{program}", language=language)

    async def get_program_scope(
        self,
        program_id: int,
        *,
        sort: str = "scope",
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """In-scope assets (domains, mobile apps, ...) with per-asset severity."""
        if sort not in SCOPE_SORTS:
            sort = "scope"
        return await self._get(
            "/program/scope",
            params={"program_id": program_id, "sort": sort},
            language=language,
        )

    async def get_program_rewards(
        self, program_id: int, *, language: str | None = None
    ) -> dict[str, Any]:
        """Reward range table keyed by severity (none/low/medium/high/critical)."""
        return await self._get(
            "/program/reward-range",
            params={"program_id": program_id},
            language=language,
        )

    # -- landing / vendors ----------------------------------------------

    async def top_programs(self, *, language: str | None = None) -> list[dict[str, Any]]:
        return await self._get("/ui/landing/top-programs", language=language)

    async def top_rewards(self, *, language: str | None = None) -> list[dict[str, Any]]:
        return await self._get("/ui/landing/top-rewards", language=language)

    async def list_vendors(
        self, *, page: int = 1, language: str | None = None
    ) -> dict[str, Any]:
        return await self._get(
            "/ui/vendors", params={"page": max(1, page)}, language=language
        )

    # -- disclosed reports ----------------------------------------------

    async def list_disclosed_reports(
        self,
        *,
        page: int = 1,
        program_ids: list[int] | None = None,
        cwe: list[str] | None = None,
        reward_from: int | None = None,
        reward_to: int | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Publicly disclosed reports, with optional server-side filters.

        Filters: ``program_ids`` (repeatable), ``cwe`` (e.g. ["CWE-79"]),
        and a ``reward_from``/``reward_to`` payout range. The API does not
        filter by severity, so callers should filter the ``severity`` field
        client-side if needed.
        """
        params: dict[str, Any] = {"page": max(1, page)}
        if program_ids:
            params["program_ids"] = program_ids
        if cwe:
            params["cwe"] = cwe
        if reward_from is not None:
            params["reward_from"] = reward_from
        if reward_to is not None:
            params["reward_to"] = reward_to
        return await self._get("/report-disclose/", params=params, language=language)

    async def get_disclosed_report(
        self, report_id: int, *, language: str | None = None
    ) -> dict[str, Any]:
        return await self._get(f"/ui/report-disclose/{report_id}", language=language)
