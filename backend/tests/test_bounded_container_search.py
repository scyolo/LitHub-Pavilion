import httpx
import pytest

from app.collectors.bounded_container_search import fetch_bounded_container


def row(doi, title="Main Conference"):
    return {
        "DOI": doi,
        "container-title": [title],
        "title": ["Research"],
        "type": "proceedings-article",
    }


@pytest.mark.asyncio
async def test_overlapping_result_pages_retain_new_exact_identities_without_claiming_fullness():
    pages = [
        [row("10.1/a"), row("10.1/b")],
        [row("10.1/b"), row("10.1/c")],
        [row("10.1/d", "Other"), row("10.1/e", "Other")],
    ]
    accepted = []

    def serve(request):
        assert request.url.params["sort"] == "score"
        assert "cursor" not in request.url.params
        page = int(request.url.params["offset"]) // 2
        return httpx.Response(
            200, json={"message": {"total-results": 100, "items": pages[page]}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        result = await fetch_bounded_container(
            client,
            "Main Conference",
            2024,
            2024,
            on_page=lambda rows: accepted.extend(rows),
            page_size=2,
            max_pages=4,
        )
    assert [r["DOI"] for r in accepted] == ["10.1/a", "10.1/b", "10.1/c"]
    assert result["overlapping_hits"] == 1
    assert result["complete"] is False and result["stop_reason"] == "no_target_hits"


@pytest.mark.asyncio
async def test_repeated_page_is_bounded_and_does_not_duplicate():
    accepted = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"message": {"total-results": 100, "items": [row("10.1/a")]}}
            )
        )
    ) as client:
        result = await fetch_bounded_container(
            client,
            "Main Conference",
            2024,
            2024,
            on_page=lambda rows: accepted.extend(rows),
            page_size=1,
            max_pages=8,
        )
    assert len(accepted) == 1 and result["requests"] == 3
    assert result["stop_reason"] == "repeated_pages" and result["complete"] is False


@pytest.mark.asyncio
async def test_invalid_identifier_fails_after_preserving_previous_page():
    seen = []

    def serve(req):
        items = (
            [row("10.1/a")]
            if req.url.params["offset"] == "0"
            else [{"container-title": ["Main Conference"]}]
        )
        return httpx.Response(
            200, json={"message": {"total-results": 2, "items": items}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        with pytest.raises(ValueError):
            await fetch_bounded_container(
                client,
                "Main Conference",
                2024,
                2024,
                on_page=lambda rows: seen.extend(rows),
                page_size=1,
                max_pages=3,
            )
    assert len(seen) == 1
