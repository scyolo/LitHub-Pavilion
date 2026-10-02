import pytest

from app.collectors.usenix_catalog import parse_sessions, session_url


def document(slug="fast24", body=None):
    body = (
        body
        or '<article class="node node-paper"><h2><a href="/conference/fast24/presentation/lee">Fast storage</a></h2><div class="field-name-field-paper-people-text"><p>Ada Lee, <em>University;</em> Bob Smith and Carol Ng, <em>Lab</em></p></div><span class="usenix-schedule-media pdf"></span><div class="field-name-field-paper-description-long">Storage abstract.</div></article>'
    )
    return (
        '<html><head><link rel="canonical" href="https://www.usenix.org/conference/'
        + slug
        + '/technical-sessions"></head><h1 id="page-title">FAST '
        + slug[-2:]
        + " Technical Sessions</h1>"
        + body
        + "</html>"
    )


def test_main_paper_metadata_and_original_link_without_pdf_fetch():
    rows, stats = parse_sessions(document(), "FAST", 2024)
    assert len(rows) == 1 and stats["published_papers"] == 1
    row = rows[0]
    assert row.title == "Fast storage"
    assert row.authors == ["Lee, Ada", "Smith, Bob", "Ng, Carol"]
    assert row.year == 2024
    assert (
        row.official_url == "https://www.usenix.org/conference/fast24/presentation/lee"
    )
    assert row.extra["provenance"] == "publisher_toc"
    assert row.extra["abstract"] == "Storage abstract."


def test_keynote_slides_or_other_edition_are_never_admitted():
    text = document().replace(
        "usenix-schedule-media pdf", "usenix-schedule-media slides"
    )
    with pytest.raises(ValueError):
        parse_sessions(text, "FAST", 2024)
    with pytest.raises(ValueError):
        parse_sessions(document(), "FAST", 2025)
    text = document().replace("/presentation/lee", "/presentation/lee.pdf")
    with pytest.raises(ValueError):
        parse_sessions(text, "FAST", 2024)


def test_duplicate_or_missing_authors_fails_closed():
    text = document().replace(
        "Ada Lee, <em>University;</em> Bob Smith and Carol Ng, <em>Lab</em>", ""
    )
    with pytest.raises(ValueError):
        parse_sessions(text, "FAST", 2024)


def test_usenix_atc_catalog_rename_does_not_invent_future_usenix_edition():
    assert session_url("ACM SIGOPS ATC", 2024).endswith("/atc24/technical-sessions")
    with pytest.raises(ValueError):
        session_url("ACM SIGOPS ATC", 2026)
    with pytest.raises(ValueError):
        session_url("Unrelated", 2024)


def test_unicode_author_url_allowed_but_encoded_path_escape_rejected():
    rows, _ = parse_sessions(
        document().replace("/presentation/lee", "/presentation/schr%C3%B6der"),
        "FAST",
        2024,
    )
    assert rows[0].official_url.endswith("schr%C3%B6der")
    with pytest.raises(ValueError):
        parse_sessions(
            document().replace("/presentation/lee", "/presentation/%2e%2e%2fpaper"),
            "FAST",
            2024,
        )


def test_official_import_is_idempotent_and_public_without_pdf(db):
    from app.models import Paper, Venue
    from app.services.publication_admission import admission_reason
    from scripts.backfill_usenix import apply_records

    venue = Venue(
        abbr="FAST",
        name="USENIX Conference on File and Storage Technologies",
        type="conf",
        ccf_level="A",
        active=1,
    )
    db.add(venue)
    db.commit()
    records, _ = parse_sessions(document(), "FAST", 2024)
    assert apply_records(db, venue, records)["new"] == 1
    assert apply_records(db, venue, records)["updated"] == 1
    paper = db.query(Paper).one()
    assert admission_reason(paper, venue) is None
    assert paper.pdf_path is None and paper.pdf_status == "closed"


def test_official_security_2026_legacy_path_is_explicit_not_a_general_relaxation():
    html = document().replace('fast24', 'usenixsecurity26').replace('/presentation/lee', '/yu-jerry')
    rows, _ = parse_sessions(html, 'USENIX Security', 2026)
    assert rows[0].official_url == 'https://www.usenix.org/conference/usenixsecurity26/yu-jerry'
    with pytest.raises(ValueError): parse_sessions(html.replace('/yu-jerry','/unrelated'), 'USENIX Security', 2026)
