import pytest

from app.collectors.spm_program import parse_spm_program


def document():
    return '<meta property="og:url" content="https://sites.google.com/view/spm-2023/program"><p>INVITED TALK</p><p>David Gu - Invited talk</p><p>SESSION: MODELING</p><p>A. Lee, B. Smith - Geometric modeling</p><p>BEZIER AWARD TALK</p><p>W. Wang - Award talk</p><p>SESSION: SHAPES</p><p>- C. Zong, J. Zhao, - Shape analysis</p>'


def test_main_sessions_only_and_official_identity():
    rows = parse_spm_program(document(), 2023)
    assert [r.title for r in rows] == ["Geometric modeling", "Shape analysis"]
    assert rows[0].authors == ["Lee, A.", "Smith, B."]
    assert rows[0].extra["provenance"] == "official_conference_list"
    with pytest.raises(ValueError):
        parse_spm_program(document(), 2024)
    with pytest.raises(ValueError):
        parse_spm_program(document().replace("sites.google.com", "example.com"), 2023)
