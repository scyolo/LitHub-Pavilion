from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.collectors import conference_registry as registry
from app.collectors import crossref


def venue():
    return SimpleNamespace(abbr="SenSys", name="ACM Conference on Embedded Networked Sensor Systems", type="conf", ccf_level="B")


def article(doi="10.1145/3774906.3800458", suffix="", event_year=2026):
    return {
        "DOI": doi, "type": "proceedings-article",
        "title": ["Verified sensing research"],
        "author": [{"given": "Alice", "family": "Researcher"}],
        "container-title": ["Proceedings of the 2026 ACM/IEEE International Conference on Embedded Artificial Intelligence and Sensing Systems" + suffix],
        "event": {"acronym": f"SenSys '{str(event_year)[2:]}"},
        "published": {"date-parts": [[2027]]},
    }


@pytest.mark.asyncio
async def test_source_year_is_verified_per_article_after_discovery(monkeypatch):
    monkeypatch.setattr(registry, "discover_containers", AsyncMock(return_value=({"isbn:9798400723094": "Verified main proceedings"}, 100)))
    monkeypatch.setattr(registry, "_fetch_inventory", AsyncMock(return_value=[
        article(), article(), article("10.1145/1.2", " - Posters and Demos"),
        article("10.1145/1.3", event_year=2025),
    ]))
    records = await registry.fetch_discovered_inventory(object(), venue(), 2026)
    assert len(records) == 1
    assert records[0].year == 2026 and records[0].publication_date is None
    assert records[0].extra["crossref_item"]["DOI"] == records[0].doi
    assert records[0].extra["inventory_scope"]


@pytest.mark.asyncio
async def test_scheduled_fallback_uses_the_same_discovery_and_run_cache(monkeypatch):
    fetch = AsyncMock(return_value=["verified-source-record"])
    monkeypatch.setattr(registry, "fetch_discovered_inventory", fetch)
    cache = {}
    assert await crossref.fetch_configured_inventory(object(), venue(), 2026, cache=cache) == ["verified-source-record"]
    await crossref.fetch_configured_inventory(object(), venue(), 2026, cache=cache)
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_registered_conference_journal_issues_are_scheduled_without_fuzzy_discovery(monkeypatch):
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr(crossref, "fetch_journal", fetch)
    discovery = AsyncMock()
    monkeypatch.setattr(registry, "fetch_discovered_inventory", discovery)
    target = SimpleNamespace(abbr="MobileHCI", name="Mobile Human-Computer Interaction", type="conf", ccf_level="B")
    assert await crossref.fetch_configured_inventory(object(), target, 2026) == []
    assert fetch.call_args.args[1] == "2573-0142"
    discovery.assert_not_called()
