from scripts.resolve_catalog_issns import exact_identity


def test_exact_title_and_unique_registry_only():
    item={'title':'ACM Transactions on Database Systems','ISSN':['1557-4644','0362-5915']}
    assert exact_identity(item['title'],[item])['issn']=='0362-5915'
    assert exact_identity('ACM Database',[item]) is None
    assert exact_identity(item['title'],[item,item]) is None
    assert exact_identity(item['title'],[{**item,'ISSN':['../bad']}]) is None
