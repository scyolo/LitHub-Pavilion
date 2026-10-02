import pytest

from app.services.fuzzy_terms import edit_one_variants, expand_tokens


def test_edit_expansion_is_bounded_and_preserves_acronyms():
    vocabulary = [('specul', 12), ('agent', 100), ('decod', 9), ('decode', 2)]
    assert expand_tokens(['spceul', 'dec'], vocabulary) == [['spceul', 'specul'], ['dec', 'decod', 'decode']]
    assert edit_one_variants('ai') == set()
    assert edit_one_variants('a' * 33) == set()
    assert len(expand_tokens(['dec'], [('dec' + str(i), i + 1) for i in range(30)])[0]) <= 4


@pytest.mark.parametrize('query', ['spceulative decoding', 'speculative dec', 'decding', 'speculativ decoding'])
def test_fuzzy_typo_and_prefix_search_recalls_only_real_papers(client, sample_paper, query):
    response = client.get('/api/search', params={'q': query, 'match': 'fuzzy'})
    assert response.status_code == 200, response.text
    assert sample_paper.id in [row['id'] for row in response.json()['items']]
    assert response.json()['match_mode'] == 'fuzzy'


def test_exact_full_title_mode_and_auto_typo_fallback(client, sample_paper):
    exact = client.get('/api/search', params={'q': sample_paper.title.upper(), 'match': 'exact'}).json()
    assert [row['id'] for row in exact['items']] == [sample_paper.id]
    assert exact['match_mode'] == 'exact'
    assert client.get('/api/search', params={'q': 'speculative decoding', 'match': 'exact'}).json()['total'] == 0
    corrected = client.get('/api/search', params={'q': 'spceulative decoding'}).json()
    assert corrected['match_mode'] == 'fuzzy' and corrected['items'][0]['id'] == sample_paper.id
    assert client.get('/api/search', params={'q': 'spceulative decoding', 'match': 'keywords'}).json()['total'] == 0


def test_fuzzy_respects_filters_and_multi_topic_or(client, sample_paper, db, sample_direction):
    from app.models import Direction, PaperDirection
    second = Direction(code='llm', name='Large language models')
    db.add(second); db.flush()
    for direction in (sample_direction, second):
        db.add(PaperDirection(paper_id=sample_paper.id, direction_id=direction.id, source='manual', score=3))
    db.commit()
    for direction in ('specdec', 'llm', 'specdec,llm'):
        result = client.get('/api/search', params={'q': 'spceulative dec', 'match': 'fuzzy', 'direction': direction}).json()
        assert result['total'] == 1 and result['items'][0]['id'] == sample_paper.id
    assert client.get('/api/search', params={'q': 'spceulative dec', 'match': 'fuzzy', 'year': 2001}).json()['total'] == 0
    assert client.get('/api/search', params={'q': 'speculative', 'match': 'unsafe'}).status_code == 400
