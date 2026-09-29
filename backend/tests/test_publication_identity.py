import pytest

from app.services.publication_identity import publication_authors_match


@pytest.mark.parametrize("first,second", [
    (["Lovelace, Ada", "Turing, A."], ["Ada Lovelace", "Alan Turing"]),
    (["Zhang, Hanxue", "Sima, Chong-Hao"], ["Hanxue, Zhang", "Sima, Chong Hao"]),
    (["Trella, Anna L.", "Zhang, Kelly W."], ["Trella, Anna", "Zhang, Kelly"]),
    (["Beißwenger, Jens", "Renz, Katrin"], ["Beisswenger, Jens", "Renz, Katrin"]),
])
def test_publication_authors_accept_unique_variants(first, second):
    assert publication_authors_match(first, second)


@pytest.mark.parametrize("first,second", [
    (["Smith, John"], ["Smith, Jane"]),
    (["Wang, Wei", "Guo, Hongcan"], ["Wang, Wen-Kai", "Guo, Hongcan"]),
    (["Turing, A."], ["Turing, Alan"]),
    (["Lovelace, Ada", "Smith, A.", "Smith, A."], ["Lovelace, Ada", "Smith, Alan", "Smith, Alice"]),
    (["Lovelace, Ada"], ["Lovelace, Ada", "Turing, Alan"]),
    ([], []),
])
def test_publication_authors_reject_ambiguous_or_different_people(first, second):
    assert not publication_authors_match(first, second)


def test_shared_identity_can_disambiguate_initials_but_not_full_name_conflicts():
    assert publication_authors_match(["Turing, A."], ["Turing, Alan"], shared_identity=True)
    assert not publication_authors_match(["Smith, John"], ["Smith, Jane"], shared_identity=True)
