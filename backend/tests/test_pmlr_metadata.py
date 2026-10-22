import pytest

from app.collectors.pmlr_metadata import citation_records


def row(**changes):
    return {
        "title": "Fast inference",
        "abstract": "We reduce language-model inference cost while preserving the target distribution. "
        * 3,
        "volume": 306,
        "publisher": "PMLR",
        "series": "Proceedings of Machine Learning Research",
        "container-title": "Proceedings of the 43rd International Conference on Machine Learning",
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "URL": "https://proceedings.mlr.press/v306/example26a.html",
        **changes,
    }


def test_pmlr_citation_metadata_retains_publisher_url_title_and_authors():
    (record,) = citation_records(
        [row()],
        "ICML",
        2026,
        "https://proceedings.mlr.press/v306/assets/bib/citeproc.yaml",
    )
    assert record.title == "Fast inference" and record.authors == ["Lovelace, Ada"]
    assert record.year == 2026 and record.extra["abstract"].startswith("We reduce")


@pytest.mark.parametrize(
    "change",
    [
        {"volume": 305},
        {"publisher": "Unknown"},
        {"URL": "https://example.org/paper.html"},
        {"container-title": "International Conference on Machine Learning Workshops"},
    ],
)
def test_citation_metadata_rejects_wrong_volume_source_or_track(change):
    with pytest.raises(ValueError):
        citation_records(
            [row(**change)],
            "ICML",
            2026,
            "https://proceedings.mlr.press/v306/assets/bib/citeproc.yaml",
        )
