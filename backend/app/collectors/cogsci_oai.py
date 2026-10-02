"""Official eScholarship CogSci OAI metadata, not PDF or repository-wide harvesting."""

import re
import xml.etree.ElementTree as ET

from app.collectors.publisher_toc import _raw
from app.services.publication_admission import nonresearch_title

OAI = "{http://www.openarchives.org/OAI/2.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"


def parse_page(text):
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("XML entities prohibited")
    root = ET.fromstring(text)
    if root.tag != OAI + "OAI-PMH" or root.find(OAI + "error") is not None:
        raise ValueError("Invalid OAI response")
    listing = root.find(OAI + "ListRecords")
    if listing is None:
        raise ValueError("No OAI records")
    rows = []
    records = listing.findall(OAI + "record")
    for record in records:
        header = record.find(OAI + "header")
        if header is None or header.get("status") == "deleted":
            continue
        metadata = record.find(OAI + "metadata")
        if metadata is None:
            continue
        values = lambda key, metadata=metadata: [n.text or "" for n in metadata.iter(DC + key)]
        source = values("source")
        dates = values("date")
        titles = values("title")
        authors = values("creator")
        if len(source) != 1 or len(dates) != 1 or len(titles) != 1 or not authors:
            continue
        m = re.fullmatch(
            r"Proceedings of the Annual Meeting of the Cognitive Science Society, vol (\d+), iss \d+",
            source[0],
        )
        if not m or not re.fullmatch(r"20\d{2}(?:-\d{2}){0,2}", dates[0]):
            continue
        year = int(dates[0][:4])
        if (
            year not in range(2023, 2027)
            or int(m[1]) + 1978 != year
            or values("type") != ["article"]
        ):
            continue
        if values("publisher") != ["eScholarship, University of California"]:
            continue
        title = titles[0]
        if nonresearch_title(title) or re.search(
            r"\b(invited|keynote|symposium|symposia|tutorial|abstracts|front matter)\b",
            title,
            re.IGNORECASE,
        ):
            continue
        urls = [
            url
            for url in values("identifier")
            if re.fullmatch(r"https://escholarship.org/uc/item/[a-z0-9]{8}", url)
        ]
        if len(urls) != 1 or not (header.findtext(OAI + "identifier") or "").endswith(
            "/qt" + urls[0].rsplit("/", 1)[-1]
        ):
            continue
        rows.append(
            _raw(
                urls[0],
                title,
                authors,
                year,
                abstract=next(iter(values("description")), None),
            )
        )
    token = listing.findtext(OAI + "resumptionToken")
    return rows, token or None, len(records)
