"""Exact CCF main-proceedings identity from publisher-deposited metadata.

Search finds candidate containers only. Every article must independently match
one full catalog name and an explicit event edition. No substring/fuzzy admission.
"""

import html
import re
from functools import lru_cache

from app.cleaning import normalize_doi, normalize_title

EXCLUDED = re.compile(
    r"\b(companion|adjunct|abstracts|doctoral|tutorials?|posters?|demonstrations?|demos?|workshops)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=4096)
def canonical_container(title, abbr):
    value = title
    # Publisher deposits sometimes HTML-encode an entity twice. Decode only
    # the fixed title string; this is not fuzzy matching or HTML execution.
    for _ in range(3):
        decoded = html.unescape(value)
        if decoded == value:
            break
        value = decoded
    value = value.casefold().replace("&", " and ")
    if abbr == "S&P":
        value = re.sub(r"\(sp\)", " ", value)
    if abbr == "CSFW":
        value = re.sub(r"\(csf\)", " ", value)
    if abbr == "HOT CHIPS" and re.fullmatch(
        r"20\d{2} ieee hot chips \d+ high performance chips symposium(?: \(hcs\))?|20\d{2} ieee hot chips \d+ symposium \(hcs\)",
        value,
    ):
        value = "hot chips: a symposium on high performance chips"
    acronym = re.escape(abbr.casefold())
    value = re.sub(r"\b" + acronym + r"(?:\s*['’:-]?\s*(?:20)?\d{2})?\b", " ", value)
    value = re.sub(
        r"\b(?:proceedings|of the|the|annual|acm|ieee|ifip|sigplan|sigarch|sighpc|sigsac|sigops|sigsoft|sigmm|siggraph|sigbed|sigact|sigai)\b",
        " ",
        value,
    )
    value = re.sub(r"\b(?:20\d{2}|\d+(?:st|nd|rd|th))\b", " ", value)
    value = re.sub(r"[, ]+volume\s+[0-9]+$", " ", value)
    value = re.sub(
        r"\b(?:twenty|thirty|forty|fifty|sixty)[- ](?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)\b",
        " ",
        value,
    )
    if abbr.casefold() in {"eurosys", "recsys"}:
        value = re.sub(
            r"^\s*(?:eighteenth|nineteenth|twentieth|twenty[- ]first)\s+", " ", value
        )
    value = normalize_title(value)
    if (
        abbr == "SIGCOMM"
        and value == "conference"
        and re.search(r"\bsigcomm\b", title, re.IGNORECASE)
    ):
        value = "international conference on applications technologies architectures and protocols for computer communication"
    if (
        abbr == "SIGGRAPH"
        and value == "conference papers"
        and re.search(r"\bsiggraph\b", title, re.IGNORECASE)
    ):
        value = "special interest group on computer graphics"
    aliases = {
        "FSE": {
            "joint european software engineering conference and symposium on foundations of software engineering": "international conference on foundations of software engineering"
        },
        "CCS": {
            "on conference on computer and communications security": "conference on computer and communications security"
        },
        "IMC": {
            "on internet measurement conference": "internet measurement conference"
        },
        "HotOS": {
            "workshop on hot topics in operating systems": "usenix workshop on hot topics in operating systems"
        },
        "CSFW": {
            "computer security foundations symposium": "computer security foundations workshop"
        },
        "DATE": {
            "design automation and test in europe conference and exhibition": "design automation and test in europe",
            "design automation and test in europe conference": "design automation and test in europe",
        },
        "CODES+ISSS": {
            "international conference on hardware software codesign and system synthesis": "international conference on hardware software co design and system synthesis"
        },
        "NOSSDAV": {
            "workshop on network and operating system support for digital audio and video": "international workshop on network and operating system support for digital audio and video"
        },
        "IWQoS": {
            "international symposium on quality of service": "international workshop on quality of service"
        },
        "INFOCOM": {
            "conference on computer communications": "international conference on computer communications"
        },
        "VR": {
            "conference virtual reality and 3d user interfaces": "conference on virtual reality and 3d user interfaces"
        },
        "MoDELS": {
            "international conference on model driven engineeringlanguages and systems": "international conference on model driven engineering languages and systems"
        },
        "RAID": {
            "international symposium on research in attacks intrusions and defenses": "international symposium on recent advances in intrusion detection"
        },
    }
    return aliases.get(abbr, {}).get(value, value)


def conference_year(item, venue):
    if getattr(venue, "abbr", None) == "SIGGRAPH" and item.get(
        "_official_siggraph_parent"
    ):
        parent = item["_official_siggraph_parent"]
        year = {"10.1145/3588432": 2023, "10.1145/3641519": 2024, "10.1145/3721238": 2025}.get(parent.get("DOI"))
        doi = normalize_doi(item.get("DOI")) or ""
        if (
            year
            and getattr(venue, "type", None) == "conf"
            and getattr(venue, "ccf_level", None) in {"A", "B"}
            and parent.get("type") == "proceedings"
            and item.get("type") == "proceedings-article"
            and len(parent.get("title") or []) == 1
            and item.get("container-title") == parent["title"]
            and re.fullmatch(re.escape(parent["DOI"]) + r"\.[0-9]+", doi)
        ):
            return year
        return None

    if item.get("type") == "journal-article":
        from app.collectors.journal_conferences import publication_year

        return publication_year(item, venue)
    siam = (
        getattr(venue, "abbr", None) in {"SODA", "SDM"}
        and item.get("type") == "book-chapter"
        and re.fullmatch(
            r"10\.1137/1\.[0-9]+\.(?:ch)?[0-9]+", normalize_doi(item.get("DOI")) or ""
        )
    )
    if item.get("type") == "book-chapter" and not siam:
        from app.collectors.catalog_books import chapter_year

        return chapter_year(item, venue)
    if (
        getattr(venue, "type", None) != "conf"
        or getattr(venue, "ccf_level", None) not in {"A", "B"}
        or not isinstance(getattr(venue, "abbr", None), str)
        or not isinstance(getattr(venue, "name", None), str)
        or not venue.abbr
        or not venue.name
        or (item.get("type") != "proceedings-article" and not siam)
    ):
        return None
    doi = normalize_doi(item.get("DOI"))
    if not doi or doi.startswith(("10.48550/", "10.5281/")):
        return None
    containers = item.get("container-title") or []
    if len(containers) != 1 or not isinstance(containers[0], str):
        return None
    title = containers[0]
    if EXCLUDED.search(title) or canonical_container(
        title, venue.abbr
    ) != canonical_container(venue.name, venue.abbr):
        return None
    event = item.get("event") or {}
    texts = [title, str(event.get("name") or ""), str(event.get("acronym") or "")]
    if any(EXCLUDED.search(text) for text in texts):
        return None
    years = {int(year) for text in texts for year in re.findall(r"\b(20\d{2})\b", text)}
    # ACM deposits use a real event identity such as PPoPP '23; never infer a
    # conference year from the DOI suffix, article title or publication date.
    acronyms = {
        venue.abbr,
        *{"SIGKDD": ("KDD",), "ACM MM": ("MM",)}.get(venue.abbr, ()),
    }
    for text in texts[1:]:
        for acronym in acronyms:
            for year in re.findall(
                r"\b" + re.escape(acronym) + r"\s*['’]\s*(\d{2})\b", text, re.IGNORECASE
            ):
                years.add(2000 + int(year))
    for field in ("start", "end"):
        parts = (event.get(field) or {}).get("date-parts") or []
        if parts and parts[0] and type(parts[0][0]) is int:
            years.add(parts[0][0])
    return (
        next(iter(years))
        if len(years) == 1 and 2000 <= next(iter(years)) <= 2100
        else None
    )


def identify_catalog_conference(item, venues):
    matches = [v for v in venues.values() if conference_year(item, v) is not None]
    return matches[0] if len(matches) == 1 else None
