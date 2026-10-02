import pytest

from app.collectors.cogsci_oai import parse_page


def document(
    source="Proceedings of the Annual Meeting of the Cognitive Science Society, vol 46, iss 0",
    date="2024-01-01",
):
    return (
        '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords><record><header><identifier>oai:escholarship.org:ark:/13030/qt1234abcd</identifier></header><metadata><dc xmlns="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:d="http://purl.org/dc/elements/1.1/"><d:title>Cognitive models</d:title><d:creator>Lee, Ada</d:creator><d:date>'
        + date
        + "</d:date><d:source>"
        + source
        + "</d:source><d:type>article</d:type><d:publisher>eScholarship, University of California</d:publisher><d:identifier>https://escholarship.org/uc/item/1234abcd</d:identifier></dc></metadata></record></ListRecords></OAI-PMH>"
    )


def test_only_exact_published_proceedings_volume_and_year():
    rows, token, count = parse_page(document())
    assert (
        len(rows) == 1
        and rows[0].year == 2024
        and rows[0].official_url.endswith("/1234abcd")
    )
    assert token is None and count == 1
    assert parse_page(document(date="2025-01-01"))[0] == []
    assert parse_page(document(source="Unrelated repository"))[0] == []
    with pytest.raises(ValueError):
        parse_page("<!DOCTYPE x>" + document())
