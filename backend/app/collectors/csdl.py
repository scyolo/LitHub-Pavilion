"""IEEE Computer Society public issue inventories (metadata only, no login/PDF).

Issue years take precedence over early-access/DOI years. A successful inventory
covers all non-preview issues listed by the publisher at the time of collection,
not unpublished issues later in an open year. Pagination fails closed.
"""
import json
import re
from datetime import date
from urllib.parse import urlencode

from app.cleaning import normalize_doi
from app.collectors.crossref import metadata_text
from app.collectors.publisher_toc import _raw, _validate

API = "https://www.computer.org/csdl/api/v1/graphql"
PAGE_SIZE = 100


def query_url(query):
    return API + "?" + urlencode({"query": query})


def index_url(year):
    return query_url('{periodicalIssues(idPrefix:"tp",year:"%s"){id idPrefix year issueNum title isPreviewOnly}}' % year)


def articles_url(year, issue, skip, limit=PAGE_SIZE):
    return query_url('{articlesWithPagination(idPrefix:"tp",year:"%s",issueNum:"%s",limit:%s,skip:%s){skipped limit totalResults articleResults{id title doi year issueNum pubDate contentType authors{fullName givenName surname} abstract}}}' % (year, issue, limit, skip))


def payload(text, field):
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("errors") or not isinstance(data.get("data"), dict) or data["data"].get(field) is None:
        raise ValueError("CSDL GraphQL errors or missing " + field)
    return data["data"][field]


def csdl_text(value):
    # CSDL wraps TeX in Z_..._Z sentinels; remove only inside tex-math markup.
    if value is not None and not isinstance(value, str):
        raise ValueError("CSDL metadata text is not a string")
    value = re.sub(r"(<tex-math\b[^>]*>)Z_(.*?)_Z(</tex-math>)", r"\1\2\3", value or "", flags=re.S)
    return metadata_text(value)


def non_research(title):
    return bool(re.match(r"^(?:(?:20\d{2} )?reviewers list|front\s?matter|back\s?matter|table of contents|(?:guest )?editorial(?: introduction)?|errat(?:um|a)|correction(?:s)? to|reviewer acknowledg|list of reviewers|annual index|IEEE Transactions on Pattern Analysis and Machine Intelligence)\b", title, re.I))


async def fetch_csdl_inventory(read, year):
    issues = payload(await read(index_url(year)), "periodicalIssues")
    if not isinstance(issues, list) or not issues:
        raise ValueError("CSDL issue inventory unavailable")
    seen_issues, seen_ids, seen_dois, records = set(), set(), set(), []
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("CSDL malformed issue identity")
        number = issue.get("issueNum")
        if (issue.get("idPrefix") != "tp" or str(issue.get("year")) != str(year)
                or not isinstance(number, str) or not re.fullmatch(r"\d{2}", number)
                or not 1 <= int(number) <= 12 or number in seen_issues
                or type(issue.get("isPreviewOnly")) is not bool or not issue.get("id")):
            raise ValueError("CSDL unexpected or duplicate issue identity")
        seen_issues.add(number)
        if issue["isPreviewOnly"]:
            continue
        skip, total = 0, None
        while True:
            page = payload(await read(articles_url(year, number, skip)), "articlesWithPagination")
            if not isinstance(page, dict):
                raise ValueError("CSDL malformed pagination envelope")
            current_total, batch = page.get("totalResults"), page.get("articleResults")
            if (type(current_total) is not int or current_total <= 0 or page.get("skipped") != skip
                    or page.get("limit") != PAGE_SIZE or not isinstance(batch, list)
                    or (total is not None and total != current_total)
                    or len(batch) != min(PAGE_SIZE, current_total - skip)):
                raise ValueError("CSDL incomplete or changing pagination")
            total = current_total
            for item in batch:
                if not isinstance(item, dict):
                    raise ValueError("CSDL malformed article identity")
                identity = item.get("id")
                title = csdl_text(item.get("title"))
                if (not identity or identity in seen_ids or not title
                        or str(item.get("year")) != str(year) or item.get("issueNum") != number):
                    raise ValueError("CSDL article identity/year mismatch")
                seen_ids.add(identity)
                if non_research(title) or item.get("contentType") == "content-announce":
                    continue
                doi = normalize_doi(item.get("doi"))
                if not isinstance(item.get("authors"), list) or any(not isinstance(a, dict) for a in item["authors"]):
                    raise ValueError("CSDL malformed author list")
                authors = [a.get("fullName") or " ".join(filter(None, (a.get("givenName"), a.get("surname")))) for a in item.get("authors") or []]
                if not doi or not doi.startswith("10.1109/tpami.") or doi in seen_dois or not authors or any(not isinstance(a, str) or not a.strip() for a in authors):
                    raise ValueError("CSDL missing or duplicate article DOI/authors: " + title[:100])
                seen_dois.add(doi)
                raw = _raw("https://doi.org/" + doi, title, authors, year, doi=doi, abstract=csdl_text(item.get("abstract")))
                published = item.get("pubDate")
                if published:
                    parsed = date.fromisoformat(published[:10])
                    if parsed.year != year:
                        raise ValueError("CSDL issue publication date/year mismatch")
                    raw.publication_date = parsed.isoformat()
                records.append(raw)
            skip += len(batch)
            if skip == total:
                break
    return _validate(records, len(records))
