"""Validate PMLR's offered citation metadata without reading article PDFs."""

import re

from app.collectors.crossref import metadata_text
from app.collectors.publisher_toc import _raw, _validate


def citation_records(items, venue, year, source_url):
    labels = {
        "ICML": "International Conference on Machine Learning",
        "COLT": "Conference on Learning Theory",
        "UAI": "Uncertainty in Artificial Intelligence",
    }
    source = re.fullmatch(
        r"https://proceedings\.mlr\.press/v([1-9][0-9]*)/assets/bib/citeproc\.yaml",
        source_url,
    )
    if not source or venue not in labels or not 2023 <= year <= 2026:
        raise ValueError("Unverified citation source/venue/year")
    if not isinstance(items, list) or not 1 <= len(items) <= 20000:
        raise ValueError("Invalid citation inventory size")
    result = []
    for item in items:
        title = metadata_text(item.get("title") or "")
        container = item.get("container-title") or ""
        url = item.get("URL") or ""
        if (
            str(item.get("volume")) != source[1]
            or item.get("publisher") != "PMLR"
            or item.get("series") != "Proceedings of Machine Learning Research"
            or labels[venue].lower() not in container.lower()
            or re.search(
                r"\b(workshops?|tutorials?|companion)\b", container, re.IGNORECASE
            )
            or not re.fullmatch(
                r"https://proceedings\.mlr\.press/v"
                + source[1]
                + r"/[A-Za-z0-9][A-Za-z0-9_-]*\.html",
                url,
            )
        ):
            raise ValueError("Citation does not belong to the verified main volume")
        authors = [
            " ".join(filter(None, (a.get("given"), a.get("family"))))
            or a.get("literal", "")
            for a in item.get("author", [])
        ]
        abstract = item.get("abstract")
        if (
            not isinstance(abstract, str)
            or not 80 <= len(abstract) <= 100000
            or not title
            or not authors
        ):
            continue
        result.append(_raw(url, title, authors, year, abstract=metadata_text(abstract)))
    return _validate(result, len(result))
