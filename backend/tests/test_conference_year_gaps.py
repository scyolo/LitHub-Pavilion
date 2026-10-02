from types import SimpleNamespace

import pytest

from app.collectors.catalog_conferences import conference_year


def v(abbr, name):
    return SimpleNamespace(abbr=abbr, name=name, type="conf", ccf_level="A")


def item(title, event):
    return {
        "DOI": "10.1145/1234.5678",
        "type": "proceedings-article",
        "container-title": [title],
        "event": {"acronym": event},
    }


@pytest.mark.parametrize(
    "venue,title,event,year",
    [
        (
            v("SIGKDD", "ACM SIGKDD Conference on Knowledge Discovery and Data Mining"),
            "Proceedings of the 29th ACM SIGKDD Conference on Knowledge Discovery and Data Mining",
            "KDD '23",
            2023,
        ),
        (
            v("ACM MM", "ACM International Conference on Multimedia"),
            "Proceedings of the 31st ACM International Conference on Multimedia",
            "MM '23",
            2023,
        ),
        (
            v("CCS", "ACM Conference on Computer and Communications Security"),
            "Proceedings of the 2024 on ACM SIGSAC Conference on Computer and Communications Security",
            "CCS '24",
            2024,
        ),
        (
            v("IMC", "ACM Internet Measurement Conference"),
            "Proceedings of the 2024 ACM on Internet Measurement Conference",
            "IMC '24",
            2024,
        ),
        (
            v("DATE", "Design, Automation & Test in Europe"),
            "2024 Design, Automation &amp;amp; Test in Europe Conference &amp;amp; Exhibition (DATE)",
            "DATE 2024",
            2024,
        ),
        (
            v("RecSys", "ACM Conference on Recommender Systems"),
            "Proceedings of the Nineteenth ACM Conference on Recommender Systems",
            "RecSys '25",
            2025,
        ),
    ],
)
def test_real_publisher_title_and_edition_variants(venue, title, event, year):
    row = item(title, event)
    assert conference_year(row, venue) == year
    row["event"]["acronym"] = event + " Companion"
    assert conference_year(row, venue) is None


def test_acronym_alias_does_not_admit_other_multimedia_events():
    venue = v("ACM MM", "ACM International Conference on Multimedia")
    assert conference_year(item("ACM Multimedia Asia 2023", "MM '23"), venue) is None
    assert (
        conference_year(
            item("Proceedings of the ACM Multimedia Systems Conference", "MM '23"),
            venue,
        )
        is None
    )


def test_fse_2023_joint_main_proceedings_not_satellite():
    venue = v(
        "FSE", "ACM International Conference on the Foundations of Software Engineering"
    )
    title = "Proceedings of the 31st ACM Joint European Software Engineering Conference and Symposium on the Foundations of Software Engineering"
    row = item(title, "ESEC/FSE '23")
    assert conference_year(row, venue) == 2023
    row["container-title"] = [title + " Companion"]
    assert conference_year(row, venue) is None


@pytest.mark.parametrize(
    "abbr,title",
    [
        (
            "SODA",
            "Proceedings of the 2023 Annual ACM-SIAM Symposium on Discrete Algorithms (SODA)",
        ),
        (
            "SDM",
            "Proceedings of the 2023 SIAM International Conference on Data Mining (SDM)",
        ),
    ],
)
def test_siam_2023_chapter_suffix_is_official_not_a_new_event_year(abbr, title):
    venue = v(
        abbr,
        "ACM-SIAM Symposium on Discrete Algorithms"
        if abbr == "SODA"
        else "SIAM International Conference on Data Mining",
    )
    row = item(title, "")
    row.update(DOI="10.1137/1.9781611977554.ch67", type="book-chapter")
    assert conference_year(row, venue) == 2023
    row["DOI"] = "10.1137/1.9781611977554.frontmatter"
    assert conference_year(row, venue) is None


def test_siggraph_2025_requires_exact_verified_parent_not_shared_container_alone():
    venue = v('SIGGRAPH', 'Special Interest Group on Computer Graphics')
    title = 'Proceedings of the Special Interest Group on Computer Graphics and Interactive Techniques Conference Conference Papers'
    row = {'DOI':'10.1145/3721238.3730720','type':'proceedings-article','container-title':[title],
           '_official_siggraph_parent':{'DOI':'10.1145/3721238','type':'proceedings','title':[title]}}
    assert conference_year(row, venue) == 2025
    assert conference_year({**row,'DOI':'10.1145/9999999.3730720'}, venue) is None
    assert conference_year({k:value for k,value in row.items() if k!='_official_siggraph_parent'}, venue) is None
