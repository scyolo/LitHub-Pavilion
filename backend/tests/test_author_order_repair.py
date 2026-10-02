import pytest
from app.services.author_order_repair import plan_author_order


def test_order_plan_requires_equal_complete_author_identity_sets():
    stored = [(11, 'Wang, Jingyuan', 1), (12, 'Han, Chengkai', 1)]
    plan = plan_author_order(stored, ['Chengkai Han', 'Jingyuan Wang'])
    assert plan == [(12, 1), (11, 2)]
    assert stored[0][2] == 1
    for incoming in [['Chengkai Han'], ['Chengkai Han', 'Other Person'], ['Chengkai Han', 'Chengkai Han']]:
        with pytest.raises(ValueError):
            plan_author_order(stored, incoming)


def test_order_plan_rejects_ambiguous_normalized_names():
    with pytest.raises(ValueError):
        plan_author_order([(11, 'Wei, Wen-Da', 1), (12, 'Wei, Wenda', 1)], ['Wenda Wei', 'Wen-Da Wei'])


def test_alias_removal_needs_full_names_from_both_sources_and_same_slot():
    from app.services.author_order_repair import plan_verified_aliases
    stored = [(1,'Feng, Diedong',2),(2,'Feng, D.',2),(3,'Liu, Zhen',1)]
    source = ['Zhen Liu','Diedong Feng']
    assert plan_verified_aliases(stored,source,source) == {'keep':[(3,1),(1,2)],'remove':[2]}
    for changed in [source[::-1], ['Zhen Liu','Different Feng']]:
        with pytest.raises(ValueError):plan_verified_aliases(stored,source,changed)
    with pytest.raises(ValueError):
        plan_verified_aliases([(1,'Feng, Diedong',2),(2,'Feng, D.',1),(3,'Liu, Zhen',1)],source,source)
    with pytest.raises(ValueError):
        plan_verified_aliases([(1,'Feng, Diedong',1),(2,'Feng, D.',1),(3,'Feng, Dong',2)],['Diedong Feng','Dong Feng'],['Diedong Feng','Dong Feng'])
