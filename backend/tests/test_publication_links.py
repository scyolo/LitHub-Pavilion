from types import SimpleNamespace

import pytest

from app.api.serializers import paper_links


def paper(**changes):
    values = dict(doi='10.48550/arxiv.2501.12345', publisher_key=None,
                  official_url='https://arxiv.org/abs/2501.12345',
                  dblp_key='conf/icml/Verified25', oa_url=None, arxiv_id='2501.12345')
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize('doi', ['10.48550/arxiv.2501.12345', 'https://doi.org/10.48550/arxiv.2501.12345', 'doi:10.48550/arxiv.2501.12345'])
@pytest.mark.parametrize('publisher_key', [None, 'https://doi.org/10.48550/arxiv.2501.12345', 'https://arxiv.org/abs/2501.12345'])
def test_repository_link_never_shadows_verified_dblp_publication(doi, publisher_key):
    links = paper_links(paper(doi=doi, publisher_key=publisher_key))
    assert links['official_url'] == 'https://dblp.org/rec/conf/icml/Verified25'
    assert links['oa_url'] == 'https://arxiv.org/abs/2501.12345'


def test_repository_only_record_has_no_official_publication_link():
    assert paper_links(paper(dblp_key=None))['official_url'] is None


def test_official_publisher_page_is_preferred_to_dblp_for_repository_doi():
    url = 'https://proceedings.mlr.press/v267/verified25a.html'
    assert paper_links(paper(publisher_key=url))['official_url'] == url


def test_formal_publication_doi_still_takes_precedence():
    assert paper_links(paper(doi='10.1145/12345.67890'))['official_url'] == 'https://doi.org/10.1145/12345.67890'
