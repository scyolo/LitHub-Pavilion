"""Conference research tracks published as explicitly named journal issues.

The returned year is the journal publication year, not a guessed presentation year.
"""

import json
import re
from pathlib import Path

from app.cleaning import normalize_doi, normalize_title

SERIES = {
    "2475-1421": (
        "Proceedings of the ACM on Programming Languages",
        {
            "POPL": "POPL",
            "PLDI": "PLDI",
            "ICFP": "ICFP",
            "OOPSLA": "OOPSLA",
            "OOPSLA1": "OOPSLA",
            "OOPSLA2": "OOPSLA",
        },
    ),
    "2573-0142": (
        "Proceedings of the ACM on Human-Computer Interaction",
        {
            "CSCW": "CSCW",
            "CSCW1": "CSCW",
            "CSCW2": "CSCW",
            "ISS": "ISS",
            "MHCI": "MobileHCI",
        },
    ),
    "2994-970X": (
        "Proceedings of the ACM on Software Engineering",
        {"FSE": "FSE", "ISSTA": "ISSTA"},
    ),
}


DEDICATED = {
    "SIGMOD": (
        "2836-6573",
        "Proceedings of the ACM on Management of Data",
        r"10\.1145/[0-9]+",
    ),
    "SIG- METRICS": (
        "2476-1249",
        "Proceedings of the ACM on Measurement and Analysis of Computing Systems",
        r"10\.1145/[0-9]+",
    ),
    "UbiComp": (
        "2474-9567",
        "Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous Technologies",
        r"10\.1145/[0-9]+",
    ),
    "CHES": (
        "2569-2925",
        "IACR Transactions on Cryptographic Hardware and Embedded Systems",
        r"10\.46586/tches\.v(20\d{2})\.i[1-4]\.[0-9-]+",
    ),
    "FSE (Crypto)": (
        "2519-173X",
        "IACR Transactions on Symmetric Cryptology",
        r"10\.46586/tosc\.v(20\d{2})\.i[1-4]\.[0-9-]+",
    ),
    "VLDB": (
        "2150-8097",
        "Proceedings of the VLDB Endowment",
        r"10\.14778/[0-9]+\.[0-9]+",
    ),
    "ICWSM": (
        "2334-0770",
        "Proceedings of the International AAAI Conference on Web and Social Media",
        r"10\.1609/icwsm\.v[0-9]+i1\.[0-9]+",
    ),
}


_PODS_PROOF = (
    Path(__file__).resolve().parents[3] / "seeds/pods_verified_publications.json"
)
VERIFIED_PODS = {
    p["doi"] for p in json.loads(_PODS_PROOF.read_text(encoding="utf-8"))["papers"]
}


def publication_year(item, venue):
    if (
        getattr(venue, "type", None) != "conf"
        or getattr(venue, "ccf_level", None) not in ("A", "B")
        or item.get("type") != "journal-article"
    ):
        return None
    # Exact official paper-list evidence overrides the broad PACMMOD association.
    # Publication year is retained; this never labels an entire issue as PODS.
    if normalize_doi(item.get("DOI")) in VERIFIED_PODS:
        if (
            getattr(venue, "abbr", None) != "PODS"
            or "2836-6573" not in (item.get("ISSN") or [])
            or item.get("container-title")
            != ["Proceedings of the ACM on Management of Data"]
        ):
            return None
        from app.collectors.crossref import publication_date

        year, _ = publication_date(item)
        return year if year and 2023 <= year <= 2026 else None
    dedicated = DEDICATED.get(getattr(venue, "abbr", None))
    if dedicated:
        issn, title, pattern = dedicated
        match = re.fullmatch(pattern, normalize_doi(item.get("DOI")) or "")
        if (
            not match
            or issn not in (item.get("ISSN") or [])
            or item.get("container-title") != [title]
        ):
            return None
        from app.collectors.crossref import publication_date

        if match.lastindex:
            year = int(match[1])
            if str(item.get("volume")) != str(year):
                return None
        else:
            year, _ = publication_date(item)
        return year if year and 2023 <= year <= 2026 else None
    if not re.fullmatch(r"10\.1145/[0-9]+", normalize_doi(item.get("DOI")) or ""):
        return None
    containers = item.get("container-title") or []
    if len(containers) != 1:
        return None
    found = False
    for issn, (title, issues) in SERIES.items():
        if (
            issn in (item.get("ISSN") or [])
            and normalize_title(containers[0]) == normalize_title(title)
            and issues.get(item.get("issue")) == getattr(venue, "abbr", None)
        ):
            found = True
    if not found:
        return None
    from app.collectors.crossref import publication_date

    year, _ = publication_date(item)
    return year if year and 2023 <= year <= 2026 else None
