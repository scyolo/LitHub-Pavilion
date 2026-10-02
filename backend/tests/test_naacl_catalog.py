import pytest

from app.collectors.publisher_toc import parse_anthology


def test_naacl_main_volume_excludes_short_findings_and_workshops():
    xml = '<collection id="2024.naacl"><volume id="long"><meta><year>2024</year><venue>naacl</venue></meta><paper id="1"><title>Language research</title><author><first>Ada</first><last>Lee</last></author><doi>10.18653/v1/2024.naacl-long.1</doi></paper></volume><volume id="short"><meta><year>2024</year><venue>naacl</venue></meta><paper id="1"><title>Short research</title></paper></volume></collection>'
    rows = parse_anthology(xml, 2024, "NAACL", "2024.naacl")
    assert len(rows) == 1 and rows[0].title == "Language research"
    assert rows[0].official_url == "https://aclanthology.org/2024.naacl-long.1/"
    with pytest.raises(ValueError):
        parse_anthology(xml, 2025, "NAACL", "2025.naacl")
