from app.collectors.fmcad_catalog import parse_parent, parse_chapter


def record(title, suffix='', kind='Proceedings'):
    doi='10.34727/2024/isbn.978-3-85448-065-5'+suffix
    return {'id':doi,'attributes':{'doi':doi,'publisher':'TU Wien','publicationYear':2024,'titles':[{'title':title}],'types':{'resourceType':kind},'creators':[{'name':'Lee, Ada'}]}}


def test_parent_and_chapter_require_same_registry_identity():
    title='Proceedings of the 24th Conference on Formal Methods in Computer-Aided Design – FMCAD 2024'
    parent=record(title)
    assert parse_parent(parent)==2024
    child=record('Verifying distributed systems','_7','Inproceedings')
    assert parse_chapter(child,parent).year==2024
    child['attributes']['doi']='10.34727/2025/isbn.978-3-85448-084-6_7'
    assert parse_chapter(child,parent) is None
    assert parse_chapter(record('The FMCAD 2024 Student Forum','_5','Inproceedings'),parent) is None
    assert parse_parent(record('Unrelated proceedings')) is None
