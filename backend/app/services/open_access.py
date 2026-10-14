"""Conservative open-full-text evidence, shared by ingestion, readers and repair.

A DOI resolver, publisher homepage, conference program or search URL is NOT
open-access evidence. Only existing article URLs on known open platforms, or
identifiers from explicitly open publication series, are promoted. No requests
or PDF downloads are performed here. Keep the policy and tests in sync.
"""
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.api.serializers import arxiv_url, doi_url, safe_http_url


@dataclass(frozen=True)
class OpenLink:
    url: str
    source: str


# Exact hosts (never suffix matching) and article-level paths, not venue indexes.
_ARTICLE_RULES = (
    (('proceedings.mlr.press',), r'/v\d+/[^/]+\.(?:html|pdf)', 'PMLR'),
    (('papers.nips.cc', 'proceedings.neurips.cc'),
     r'/(?:paper_files/paper|paper)/\d{4}/(?:hash|file)/[a-z0-9_-]+\.(?:html|pdf)', 'NeurIPS'),
    (('aclanthology.org', 'www.aclanthology.org'),
     r'/(?:\d{4}\.[a-z0-9-]+\.\d+|[A-Z]\d{2}-\d{3,})(?:/|\.pdf)?', 'ACL Anthology'),
    (('openaccess.thecvf.com',), r'/content(?:_[a-z0-9]+)?/[^?#]*?(?:_paper\.html|\.pdf)', 'CVF Open Access'),
    (('ojs.aaai.org',), r'/index\.php/(?:AAAI|ICAPS|ICWSM|HCOMP|AIIDE)/article/(?:view|download)/\d+(?:/\d+)?/?', 'AAAI'),
    (('ijcai.org', 'www.ijcai.org'), r'/proceedings/\d{4}/(?:\d+/?|\d+\.pdf)', 'IJCAI'),
    (('proceedings.kr.org',), r'/\d{4}/(?:\d+/?|\d+\.pdf)', 'KR'),
    (('jmlr.org', 'www.jmlr.org'), r'/papers/(?:v\d+/[^/]+\.html|volume\d+/[^/]+/[^/]+\.pdf)', 'JMLR'),
    (('jair.org', 'www.jair.org'), r'/index\.php/jair/article/(?:view|download)/\d+(?:/\d+)?/?', 'JAIR'),
    (('ifaamas.org', 'www.ifaamas.org'), r'/Proceedings/aamas\d{4}/(?:pdfs/[^/]+\.pdf|[^/]+\.html)', 'AAMAS'),
    (('usenix.org', 'www.usenix.org'), r'/(?:conference/[^/]+/presentation/[^/]+/?|system/files/[^/]+\.pdf)', 'USENIX'),
    (('drops.dagstuhl.de',), r'/(?:entities/document/10\.4230/[^/]+|opus/volltexte/\d{4}/\d+(?:/[^/]+\.pdf)?/?)', 'Dagstuhl'),
    (('isca-archive.org', 'www.isca-archive.org'), r'/[a-z0-9]+_\d{4}/[^/]+\.(?:html|pdf)', 'ISCA Archive'),
    (('escholarship.org',), r'/uc/item/[a-z0-9]{8}/?', 'eScholarship'),
    (('ecva.net', 'www.ecva.net'), r'/papers/eccv_\d{4}/[^?#]+\.(?:php|pdf)', 'ECVA'),
    (('cidrdb.org', 'www.cidrdb.org'), r'/cidr\d{4}/papers/[^/]+\.pdf', 'CIDR'),
    (('vldb.org', 'www.vldb.org'), r'/(?:cidrdb/papers/\d{4}/[^/]+\.pdf|pvldb/vol\d+/[^/]+\.pdf)', 'VLDB / CIDR'),
    (('msstconference.org', 'www.msstconference.org'), r'/MSST-history/\d{4}/Papers/[^/]+\.pdf', 'MSST'),
    (('pmc.ncbi.nlm.nih.gov',), r'/articles/PMC\d+/(?:pdf/[^/]+\.pdf)?', 'PubMed Central'),
)
_RULES_BY_HOST = {}
for _hosts, _pattern, _source in _ARTICLE_RULES:
    for _host in _hosts:
        _RULES_BY_HOST.setdefault(_host, []).append((re.compile(_pattern, re.IGNORECASE), _source))


# Cheap rejection is important for SQL aggregation over hundreds of thousands of
# predominantly unresolved DOI records. A positive match still uses the full URL validator.
_ARTICLE_ORIGIN = re.compile(
    r'https?://(?:' + '|'.join(re.escape(host) for host in sorted(set(_RULES_BY_HOST) | {
        'openreview.net', 'www.openreview.net', 'arxiv.org', 'www.arxiv.org', 'export.arxiv.org',
    })) + r')\.?(?::(?:80|443))?(?=[/?#]|$)', re.IGNORECASE | re.ASCII,
)
_OPEN_DOI_NAMESPACES = {
    '10.18653', '10.1609', '10.24963', '10.1371', '10.4230', '10.14778', '10.14722',
    '10.48786', '10.1613', '10.1162', '10.21437', '10.46298', '10.4086', '10.18637',
}
_DOI_NAMESPACE = re.compile(r'10\.\d{4,9}', re.ASCII)
_SIMPLE_DOI = re.compile(r'10\.\d{4,9}/[a-z0-9._;()/:+-]+', re.IGNORECASE | re.ASCII)


def publisher_open_url(*, doi=None, publisher_key=None, official_url=None) -> OpenLink | None:
    """Reuse real article identities; never construct a PDF URL from a title."""
    # Most historical rows only repeat a DOI outside the known open series.
    # They cannot supply a different open identity, even if the suffix is invalid.
    if isinstance(doi, str):
        namespace = doi.partition('/')[0]
        if _DOI_NAMESPACE.fullmatch(namespace) and namespace not in _OPEN_DOI_NAMESPACES:
            same_identity = (None, '', doi, 'https://doi.org/' + doi)
            if publisher_key in same_identity and official_url in same_identity:
                return None
    for value in (publisher_key, official_url):
        if not isinstance(value, str) or not _ARTICLE_ORIGIN.match(value.strip()):
            continue
        link = safe_http_url(value)
        if not link:
            continue
        parts = urlsplit(link)
        if parts.port not in (None, 80, 443) or any(part in ('.', '..') for part in parts.path.split('/')):
            continue
        if parts.hostname in ('openreview.net', 'www.openreview.net') and parts.path in ('/forum', '/pdf'):
            ids = parse_qs(parts.query).get('id', [])
            if len(ids) == 1 and re.fullmatch(r'[a-zA-Z0-9_-]+', ids[0]):
                return OpenLink(link, 'OpenReview')
        if parts.hostname in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org') and arxiv_url(link):
            return OpenLink(link, 'arXiv')
        for pattern, source in _RULES_BY_HOST.get(parts.hostname, []):
            if pattern.fullmatch(parts.path):
                return OpenLink(link, source)
    # A simple, valid DOI in an unsupported namespace cannot become OA through
    # another stored DOI; retain the same authoritative-identifier precedence.
    simple = doi.strip() if isinstance(doi, str) else ''
    if (_SIMPLE_DOI.fullmatch(simple) and simple.partition('/')[0] not in _OPEN_DOI_NAMESPACES
            and all(part not in ('.', '..') for part in simple.split('/'))):
        return None
    # A resolver is evidence only for these genuinely open publication series.
    canonical = doi_url(doi)
    if not canonical:
        for value in (publisher_key, official_url):
            canonical = doi_url(value)
            if canonical:
                break
    if not canonical:
        return None
    identifier = canonical.removeprefix('https://doi.org/')
    if match := re.fullmatch(r'10\.18653/v1/(\d{4}\.[a-z0-9-]+\.\d+)', identifier):
        return OpenLink(f'https://aclanthology.org/{match[1]}/', 'ACL Anthology')
    if match := re.fullmatch(r'10\.1609/(aaai|icaps|icwsm|hcomp|aiide)\.v\d+(?:i\d+)?\.(\d+)', identifier):
        return OpenLink(f'https://ojs.aaai.org/index.php/{match[1].upper()}/article/view/{match[2]}', 'AAAI')
    if match := re.fullmatch(r'10\.24963/(ijcai|kr)\.(\d{4})/(\d+)', identifier):
        url = (f'https://www.ijcai.org/proceedings/{match[2]}/{match[3]}' if match[1] == 'ijcai'
               else f'https://proceedings.kr.org/{match[2]}/{match[3]}/')
        return OpenLink(url, match[1].upper())
    for pattern, source in (
        (r'10\.1371/journal\.[a-z]+\.\d+', 'PLOS'),
        (r'10\.4230/(?:lipics|oasics|dagrep|darts|tgdk)\.[a-z0-9.-]+', 'Dagstuhl'),
        (r'10\.14778/\d+\.\d+', 'PVLDB'),
        (r'10\.14722/ndss\.\d{4}\.\d+', 'NDSS'),
        (r'10\.48786/edbt\.\d{4}\.\d+', 'EDBT'),
        (r'10\.1613/jair\.(?:1\.)?\d+', 'JAIR'),
        (r'10\.1162/(?:tacl|coli)_a_\d+', 'ACL / MIT Press'),
        (r'10\.21437/interspeech\.\d{4}-\d+', 'ISCA Archive'),
        (r'10\.46298/lmcs\.\d+', 'LMCS'),
        (r'10\.4086/toc\.\d{4}\.v\d+i\d+', 'Theory of Computing'),
        (r'10\.18637/jss\.v\d+\.i\d+', 'Journal of Statistical Software'),
    ):
        if re.fullmatch(pattern, identifier):
            return OpenLink(canonical, source)
    return None


def best_openalex_url(work: dict) -> str | None:
    """Use every explicit OA location, rejecting unsafe URLs and negative flags.

    best_oa_location/open_access are already OA-specific fields, so absent flags
    are allowed for older API records. General locations require is_oa=True.
    """
    if not isinstance(work, dict):
        return None
    candidates = []
    best = work.get('best_oa_location')
    if isinstance(best, dict) and best.get('is_oa') is not False:
        candidates.extend((best.get('pdf_url'), best.get('landing_page_url')))
    access = work.get('open_access')
    if isinstance(access, dict) and access.get('is_oa') is not False:
        candidates.append(access.get('oa_url'))
    primary = work.get('primary_location')
    locations = work.get('locations')
    for location in [primary, *(locations if isinstance(locations, list) else [])]:
        if isinstance(location, dict) and location.get('is_oa') is True:
            candidates.extend((location.get('pdf_url'), location.get('landing_page_url')))
    for candidate in candidates:
        if link := safe_http_url(candidate):
            return link
    return None
