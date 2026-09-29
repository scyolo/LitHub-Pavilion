from dataclasses import replace
from app.collectors.title_corrections import CORRECTIONS, correct_catalogue_title
from app.collectors.publisher_toc import _raw


def test_verified_errata_are_identity_bound_and_not_fuzzy():
    for item in CORRECTIONS:
        raw = _raw(item["publisher_key"], item["catalogue_title"], item["catalogue_authors"], item["year"], doi=item["doi"])
        wrong = replace(raw, doi="10.1007/other", extra=dict(raw.extra))
        assert correct_catalogue_title(wrong).title == item["catalogue_title"]
        assert correct_catalogue_title(raw).title == item["title"]
        assert raw.extra["publisher_title_correction"] == item["source"]
