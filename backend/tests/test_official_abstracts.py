from app.services.official_abstracts import fill_verified_abstracts


def test_abstract_repair_only_fills_blank_verified_identity(db, sample_paper):
    from app.models import Author, PaperAuthor
    sample_paper.abstract = None
    author = Author(name='Ada Lovelace', name_norm='adalovelace')
    db.add(author); db.flush()
    db.add(PaperAuthor(paper_id=sample_paper.id, author_id=author.id, author_order=1))
    db.commit()
    row = {'doi': sample_paper.doi, 'title': sample_paper.title, 'authors': ['Ada Lovelace'], 'abstract': 'A real publisher abstract about language models.'}
    result = fill_verified_abstracts(db, [row], sample_paper.venue_id, sample_paper.year)
    assert result['filled'] == [sample_paper.id]
    assert sample_paper.abstract == row['abstract']
    assert fill_verified_abstracts(db, [{**row, 'abstract': 'Replace it'}], sample_paper.venue_id, sample_paper.year)['filled'] == []


def test_abstract_repair_rejects_title_author_and_unconfirmed_matches(db, sample_paper):
    sample_paper.abstract = None
    db.commit()
    row = {'doi': sample_paper.doi, 'title': 'Wrong title', 'authors': ['Nobody'], 'abstract': 'Text'}
    assert not fill_verified_abstracts(db, [row], sample_paper.venue_id, sample_paper.year)['filled']
    assert sample_paper.abstract is None


def test_unconfirmed_publication_does_not_gain_an_abstract(db, sample_paper):
    sample_paper.abstract = None
    sample_paper.venue_confirmed = 0
    db.commit()
    row = {'doi': sample_paper.doi, 'title': sample_paper.title, 'authors': ['Ada Lovelace'], 'abstract': 'Publisher text'}
    assert not fill_verified_abstracts(db, [row], sample_paper.venue_id, sample_paper.year)['filled']
    assert sample_paper.abstract is None


def test_wsdm_abstract_page_parser_rejects_truncation_and_duplicates():
    import pytest
    from scripts.fill_wsdm2023_abstracts import parse_page
    header = 'Sixteenth ACM International Conference on Web Search and Data Mining 3539597'
    def block(i):
        return f'<h3><a class="DLtitleLink" href="https://dl.acm.org/doi/10.1145/3539597.{i}">Title {i}</a></h3><ul class="DLauthors"><li>Ada Lovelace</li></ul><div class="DLabstract"><div><p>Real abstract.</p></div></div>'
    parsed = parse_page(header + ''.join(block(i) for i in range(187)))
    assert len(parsed) == 187 and parsed[0]['abstract'] == 'Real abstract.'
    with pytest.raises(ValueError, match='truncated'):
        parse_page(header + block(1))
    with pytest.raises(ValueError, match='truncated'):
        parse_page(header + block(1) * 187)


def test_wsdm2024_parser_accepts_attribute_order_but_not_wrong_parent():
    import pytest
    from scripts.fill_wsdm2023_abstracts import parse_page
    header = '<title>ACM Proceedings - WSDM 2024</title>'
    def block(i, parent='3616855'):
        return f'<h3><a class="DLtitleLink" title="Citation" href="https://dl.acm.org/doi/10.1145/{parent}.{i}">Title {i}</a></h3><ul class="DLauthors"><li>Ada Lovelace</li></ul><div class="DLabstract"><div><p>Publisher abstract.</p></div></div>'
    rows = parse_page(header + ''.join(block(i) for i in range(175)), year=2024)
    assert len(rows) == 175 and rows[0]['doi'] == '10.1145/3616855.0'
    with pytest.raises(ValueError):
        parse_page(header + ''.join(block(i, '3539597') for i in range(175)), year=2024)
    with pytest.raises(ValueError):
        parse_page(header + block(1), year=2024)


def test_sigir2024_reads_embedded_acm_identity_without_following_redirect():
    import pytest
    from scripts.fill_sigir2024_abstracts import parse_page
    def row(i):
        return f'<h3><a class="DLtitleLink" href="https://urldefense.com/v3/__https://dl.acm.org/doi/10.1145/3626772.{i}__;token">Paper {i}</a></h3><ul class="DLauthors"><li>Ada Lovelace</li></ul><div class="DLabstract"><div><p>Verified text.</p></div></div>'
    page = 'SIGIR 2024' + ''.join(row(i) for i in range(389))
    result = parse_page(page)
    assert len(result) == 389 and result[0]['doi'] == '10.1145/3626772.0'
    with pytest.raises(ValueError):
        parse_page(page.replace('3626772', '9999999'))
    with pytest.raises(ValueError):
        parse_page('SIGIR 2024' + row(1))


def test_sigir2023_abstracts_require_correct_parent_and_full_inventory():
    import pytest
    from scripts.fill_sigir2024_abstracts import parse_page
    def row(i):
        return f'<h3><a class="DLtitleLink" href="https://dl.acm.org/doi/10.1145/3539618.{i}">Title {i}</a></h3><ul class="DLauthors"><li>Ada Lovelace</li></ul><div class="DLabstract"><div><p>Official abstract.</p></div></div>'
    page = 'SIGIR | Taipei | Taiwan | 2023' + ''.join(row(i) for i in range(469))
    assert len(parse_page(page, year=2023)) == 469
    with pytest.raises(ValueError):
        parse_page(page.replace('3539618', '3626772'), year=2023)
    with pytest.raises(ValueError):
        parse_page('SIGIR | Taipei | Taiwan | 2023' + row(1), year=2023)


def test_author_punctuation_equivalence_keeps_multiplicity_and_full_names(db, sample_paper):
    from app.models import Author, PaperAuthor
    author = Author(name='Wei, Wen-Da', name_norm='weiwenda')
    db.add(author); db.flush()
    db.add(PaperAuthor(paper_id=sample_paper.id, author_id=author.id, author_order=1))
    sample_paper.abstract = None; db.commit()
    row = {'doi': sample_paper.doi, 'title': sample_paper.title, 'authors': ['Wenda Wei'], 'abstract': 'Official publisher text.'}
    for names in [['Wenda Wei', 'Wenda Wei'], ['W. Wei'], ['Wen Wei'], ['Other Person'], ['']]:
        assert not fill_verified_abstracts(db, [{**row, 'authors': names}], sample_paper.venue_id, sample_paper.year)['filled']
    assert fill_verified_abstracts(db, [row], sample_paper.venue_id, sample_paper.year)['filled'] == [sample_paper.id]


def test_sigir2025_partial_page_uses_only_explicit_google_target():
    import pytest
    from scripts.fill_sigir2024_abstracts import parse_page
    def row(i):
        return f'<h3><a class="DLtitleLink" href="https://www.google.com/url?q=https://dl.acm.org/doi/10.1145/3726302.{i}&amp;source=gmail">Title {i}</a></h3><ul class="DLauthors"><li>Ada Lovelace</li></ul><div class="DLabstract"><div>Abstract</div></div>'
    page = 'SIGIR 2025' + ''.join(row(i) for i in range(100))
    assert len(parse_page(page, year=2025)) == 100
    with pytest.raises(ValueError):
        parse_page(page.replace('q=https://dl.acm.org', 'q=https://other.example'), year=2025)
    with pytest.raises(ValueError):
        parse_page(page.replace('3726302', '3539618'), year=2025)
