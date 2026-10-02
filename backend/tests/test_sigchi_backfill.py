import json
from argparse import Namespace
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.models import Paper, Venue
from scripts import backfill_sigchi_papers as module


@pytest.mark.asyncio
async def test_confirmed_program_import_is_idempotent_and_preserves_publication_year(
    db, session_factory, tmp_path, monkeypatch
):
    db.add(
        Venue(
            abbr="CSCW",
            name="ACM Conference On Computer-Supported Cooperative Work And Social Computing",
            type="conf",
            ccf_level="A",
            active=1,
        )
    )
    db.commit()
    conf = {
        "id": 10140,
        "shortName": "CSCW",
        "year": 2025,
        "url": "https://cscw.acm.org/2025/",
    }
    info = {"publicationStatus": "PUBLISHED", "isDraft": False, "version": 49}
    program = {
        "conference": conf,
        "publicationInfo": info,
        "contentTypes": [{"id": 1, "name": "Paper"}],
        "people": [{"id": 10, "firstName": "Ada", "lastName": "Lee"}],
        "contents": [
            {
                "id": 20,
                "typeId": 1,
                "title": "Collaborative research",
                "authors": [{"personId": 10}],
            }
        ],
    }
    item = {
        "DOI": "10.1145/1234567",
        "type": "journal-article",
        "title": ["Collaborative research"],
        "author": [{"given": "Ada", "family": "Lee"}],
        "container-title": ["Proceedings of the ACM on Human-Computer Interaction"],
        "ISSN": ["2573-0142"],
        "published": {"date-parts": [[2024, 10, 1]]},
    }
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps([item]), encoding="utf-8")
    listing = tmp_path / "list.json"
    listing.write_text(
        json.dumps([{"conference": conf, "publicationInfo": info}]), encoding="utf-8"
    )
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=program)),
            **kwargs,
        ),
    )
    args = Namespace(
        database=Path(session_factory.kw["bind"].url.database),
        metadata=metadata,
        program_list=listing,
        output=tmp_path / "report",
        apply=True,
        as_of=date(2026, 10, 2),
    )
    first = await module.run(args)
    second = await module.run(args)
    assert first["units"][0]["counts"]["new"] == 1
    assert second["units"][0]["counts"]["updated"] == 1
    paper = db.query(Paper).one()
    assert paper.year == 2024 and paper.venue_confirmed == 1
    assert paper.pdf_path is None
