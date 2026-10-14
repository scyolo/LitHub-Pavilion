"""Less common open proceedings share the exact same evidence contract."""
import pytest
from app.services.open_access import publisher_open_url

@pytest.mark.parametrize('url', [
    'https://papers.nips.cc/paper_files/paper/2023/hash/feb34ce77fc8b94c85d12e608b23ce67-Abstract-Datasets_and_Benchmarks.html',
    'https://ojs.aaai.org/index.php/ICAPS/article/view/36143',
])
def test_article_urls_with_additional_open_series_and_tracks(url):
    assert publisher_open_url(publisher_key=url).url == url

@pytest.mark.parametrize('doi', [
    '10.14722/ndss.2023.23072', '10.48786/edbt.2023.01',
])
def test_fully_open_proceedings_resolver(doi):
    assert publisher_open_url(doi=doi).url == 'https://doi.org/' + doi

def test_icaps_doi_points_to_article_not_table_of_contents():
    assert publisher_open_url(doi='10.1609/icaps.v35i1.36143').url == 'https://ojs.aaai.org/index.php/ICAPS/article/view/36143'

@pytest.mark.parametrize('doi', ['10.14722/unrelated.2023.23072', '10.48786/unrelated.2023.01'])
def test_open_proceedings_prefix_does_not_include_other_publications(doi):
    assert publisher_open_url(doi=doi) is None


def test_common_closed_metadata_does_not_repeat_full_url_parsing(monkeypatch):
    from app.services import open_access
    def unexpected_parse(value):
        raise AssertionError('Unrecognized publisher/DOI namespace must be rejected before costly URL parsing')
    monkeypatch.setattr(open_access, 'safe_http_url', unexpected_parse)
    assert open_access.publisher_open_url(doi='10.1109/icassp.2025.1',
        publisher_key='https://doi.org/10.1109/icassp.2025.1',
        official_url='https://doi.org/10.1109/icassp.2025.1') is None


def test_fast_rejection_preserves_invalid_doi_fallback_and_identity_precedence():
    open_doi = 'https://doi.org/10.18653/v1/2025.acl-long.10'
    assert publisher_open_url(doi='10.1109/../invalid', official_url=open_doi).url == 'https://aclanthology.org/2025.acl-long.10/'
    assert publisher_open_url(doi='10.1109/valid.1', official_url=open_doi) is None
