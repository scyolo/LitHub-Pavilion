from app.collectors.joint_journal_lists import parse_publication_list


def test_pods_2026_author_affiliations_are_not_mistaken_for_author_names():
    html='''<title>The 2026 ACM SIGMOD/PODS Conference: Bengaluru</title>
    <h1>Accepted Papers for PODS</h1><div id="maincontent"><ul><li>
    <strong>Query containment</strong>
    Ada Lovelace (University, Computing Lab)*; Alan Turing (Institute (Research))
    </li></ul></div>'''
    papers=parse_publication_list(html,'PODS',2026)
    assert papers[0]['authors']==['Lovelace, Ada','Turing, Alan']
