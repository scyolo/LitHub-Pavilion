import pytest
from app.collectors.publisher_html_catalogs import parse_cidr, parse_edbt, parse_isca


def test_cidr_paper_links_only_and_author_affiliations_removed():
    text='<title>CIDR 2024 Program</title><span class="session-talk"><a href="papers/p1-lee.pdf">Storage systems</a></span><span class="session-presenter">Ada Lee (University)*; Bob Smith (Lab)</span>'
    rows=parse_cidr(text,2024)
    assert rows[0].authors==['Lee, Ada','Smith, Bob']
    assert rows[0].official_url.endswith('/cidr2024/papers/p1-lee.pdf')
    with pytest.raises(ValueError):parse_cidr(text,2025)


def test_edbt_research_track_not_demo_or_keynote():
    paper='<div class="paper"><a href="https://dx.doi.org/10.48786/edbt.2024.01">DOI</a><b><a href="paper.pdf">Database queries</a></b><div>Ada Lee, Bob Smith pp. 1–14</div></div>'
    text='<h1>EDBT 2024</h1><h4>Research Track</h4>'+paper+'<h4>Demo Track</h4>'+paper.replace('2024.01','2024.02')
    rows=parse_edbt(text,2024)
    assert len(rows)==1 and rows[0].doi=='10.48786/edbt.2024.01'


def test_isca_static_index_not_remote_javascript_or_demo():
    card='<a href="lee24_interspeech.html"><p>Speech models<br><span>Ada Lee, Bob Smith</span></p></a>'
    text='<h2>Interspeech 2024</h2><div><h4>Speech recognition</h4>'+card+'</div><div><h4>Show and Tell Demonstrations</h4>'+card.replace('lee24','smith24')+'</div>'
    rows=parse_isca(text,2024)
    assert len(rows)==1 and rows[0].title=='Speech models'
    assert rows[0].official_url=='https://www.isca-archive.org/interspeech_2024/lee24_interspeech.html'


def test_i3d_official_doi_list_excludes_invited_ieee_presentations():
    from app.collectors.publisher_html_catalogs import parse_i3d
    text='<title>I3D 2024 Papers</title><dl><dt>Interactive rendering</dt><dd>Ada Lee and Bob Smith</dd><dd><a href="https://dl.acm.org/doi/10.1145/3651298">DOI link</a></dd><dt>Invited journal paper</dt><dd>Another Author</dd><dd><a href="https://ieeexplore.ieee.org/document/1">DOI link</a></dd></dl>'
    rows=parse_i3d(text,2024)
    assert len(rows)==1 and rows[0].doi=='10.1145/3651298'


def test_msst_published_research_rows_only():
    from app.collectors.publisher_html_catalogs import parse_msst
    text='<title>MSST 2024</title><ul class="papers"><li><span class="ptitle">Reliable storage</span><a href="../MSST-history/2024/Papers/msst24-1.1.pdf">PDF</a><span class="authors">Ada Lee (MIT); Bob Smith (Lab)</span></li></ul><div class="slot">Keynote talk</div>'
    row=parse_msst(text,2024)[0]
    assert row.authors==['Lee, Ada','Smith, Bob']
    assert row.official_url=='https://msstconference.org/MSST-history/2024/Papers/msst24-1.1.pdf'


@pytest.mark.parametrize('year,href',[(2025,'https://vldb.org/cidrdb/papers/2025/p1-lambrecht.pdf'),(2026,'https://www.cidrdb.org/cidr2026/papers/p14-xiao.pdf')])
def test_cidr_absolute_official_migration_paths_and_wrong_year_rejection(year,href):
    from app.collectors.publisher_html_catalogs import parse_cidr
    doc=f'<title>CIDR {year} Program</title><span class="session-talk"><a href="{href}">Database research</a></span><span class="session-presenter">Ada Lee (Lab); Bob Smith (Lab)</span>'
    row=parse_cidr(doc,year)[0]
    assert row.official_url==href
    with pytest.raises(ValueError):parse_cidr(doc.replace(href,href.replace(str(year),str(year-1))),year)
    with pytest.raises(ValueError):parse_cidr(doc.replace('https://','https://untrusted.example/'),year)
