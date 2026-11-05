"""Maintenance entrypoints must not create or alter a database during import or invalid input."""
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from scripts import prune_directions


def load_resolver():
    path = Path(__file__).resolve().parents[1] / "scripts" / "resolve_openalex_ids.py"
    spec = importlib.util.spec_from_file_location("resolver_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolver_import_does_not_start_a_crawl(monkeypatch):
    def no_run(coroutine):
        coroutine.close()
        raise AssertionError("Import must not start network or database work")

    monkeypatch.setattr(asyncio, "run", no_run)
    assert callable(load_resolver().main)


@pytest.mark.asyncio
async def test_resolver_obeys_configured_dns_without_network(monkeypatch, engine, db):
    resolver = load_resolver()
    modes = []

    class Transport:
        def __init__(self, dns_mode):
            modes.append(dns_mode)

        async def aclose(self):
            pass

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(resolver, "ABBR", [])
    monkeypatch.setattr(resolver, "db_file_path", lambda: Path(engine.url.database))
    monkeypatch.setattr(resolver, "PublicTransport", Transport)
    monkeypatch.setattr(resolver.httpx, "AsyncClient", Client)
    monkeypatch.setattr(resolver.settings, "outbound_dns_mode", "https")
    await resolver.main()
    assert modes == ["https"]


def test_prune_rejects_missing_database_without_creating_it(monkeypatch, tmp_path, capsys):
    database = tmp_path / "missing.db"
    monkeypatch.setattr(sys, "argv", ["prune_directions", "--database", str(database)])
    with pytest.raises(SystemExit):
        prune_directions.main()
    assert not database.exists()
    assert "existing SQLite database" in capsys.readouterr().err
