import pytest

from app.collectors.crossref import item_to_raw
from app.collectors.title_corrections import CORRECTIONS


@pytest.mark.parametrize('doi', ['10.1145/3676641.3715996', '10.1145/3695053.3731008'])
def test_verified_type_setting_corrections_require_the_same_doi_year_and_authors(doi):
    proof = next(row for row in CORRECTIONS if row['doi'] == doi)
    authors = []
    for author in proof['catalogue_authors']:
        family, given = author.split(', ', 1)
        authors.append({'family': family, 'given': given})
    item = {'DOI': doi, 'title': [proof['catalogue_title']], 'type': 'proceedings-article',
            'published': {'date-parts': [[proof['year']]]}, 'author': authors}
    assert item_to_raw(item).title == proof['title']
    changed = item | {'author': [{'given': 'Different', 'family': 'Author'}]}
    assert item_to_raw(changed).title == proof['catalogue_title']
