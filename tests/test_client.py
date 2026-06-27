import httpx
import pytest
import respx

from sf365_bugbounty_mcp.client import API_BASE, SITE_BASE, Sf365Client, Sf365Error


@pytest.fixture
def client():
    c = Sf365Client(cache_ttl=0)
    yield c


@respx.mock
async def test_list_programs_sends_waf_headers_and_parses(client):
    route = respx.get(f"{API_BASE}/ui/program").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": 1, "name": "X"}], "page": 1, "total": 2, "totalEntries": 7},
        )
    )
    data = await client.list_programs(page=1, search="x")
    assert data["totalEntries"] == 7

    sent = route.calls.last.request
    # WAF-required headers must be present.
    assert sent.headers["origin"] == SITE_BASE
    assert sent.headers["referer"].startswith(SITE_BASE)
    assert "Chrome" in sent.headers["user-agent"]
    assert sent.url.params["page"] == "1"
    assert sent.url.params["search"] == "x"
    await client.aclose()


@respx.mock
async def test_token_sets_authorization_header():
    c = Sf365Client(token="abc123", cache_ttl=0)
    route = respx.get(f"{API_BASE}/ui/program").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 1})
    )
    await c.list_programs()
    assert route.calls.last.request.headers["authorization"] == "Bearer abc123"
    await c.aclose()


@respx.mock
async def test_403_raises_friendly_auth_error(client):
    respx.get(f"{API_BASE}/ui/program/secret").mock(
        return_value=httpx.Response(403, text="Forbidden")
    )
    with pytest.raises(Sf365Error) as ei:
        await client.get_program("secret")
    assert ei.value.status == 403
    assert "SF365_TOKEN" in str(ei.value)
    await client.aclose()


@respx.mock
async def test_retries_on_502_then_succeeds(client):
    route = respx.get(f"{API_BASE}/program/reward-range").mock(
        side_effect=[
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json={"programId": 5, "currency": "rub"}),
        ]
    )
    data = await client.get_program_rewards(5)
    assert data["programId"] == 5
    assert route.call_count == 2
    await client.aclose()


@respx.mock
async def test_scope_sort_is_validated(client):
    route = respx.get(f"{API_BASE}/program/scope").mock(
        return_value=httpx.Response(200, json=[])
    )
    await client.get_program_scope(5, sort="not_a_real_sort")
    assert route.calls.last.request.url.params["sort"] == "scope"
    await client.aclose()


@respx.mock
async def test_iter_all_programs_walks_pages(client):
    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json={
                "items": [{"id": page, "name": f"p{page}"}],
                "page": page,
                "total": 3,
                "totalEntries": 3,
            },
        )

    respx.get(f"{API_BASE}/ui/program").mock(side_effect=handler)
    items = await client.iter_all_programs()
    assert [i["id"] for i in items] == [1, 2, 3]
    await client.aclose()


@respx.mock
async def test_cache_avoids_second_request():
    c = Sf365Client(cache_ttl=300)
    route = respx.get(f"{API_BASE}/ui/landing/top-programs").mock(
        return_value=httpx.Response(200, json=[{"name": "A"}])
    )
    await c.top_programs()
    await c.top_programs()
    assert route.call_count == 1
    await c.aclose()
