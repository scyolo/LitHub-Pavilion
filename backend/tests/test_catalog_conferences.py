from types import SimpleNamespace

import pytest

from app.collectors.catalog_conferences import (
    conference_year,
    identify_catalog_conference,
)


def venue(abbr='CHI',name='ACM Conference on Human Factors in Computing Systems'):
    return SimpleNamespace(abbr=abbr,name=name,type='conf',ccf_level='A')


def article(container="Proceedings of the CHI Conference on Human Factors in Computing Systems", acronym="CHI '24"):
    return {'DOI':'10.1145/3613904.3642679','type':'proceedings-article','container-title':[container], 'event':{'acronym':acronym}, 'published':{'date-parts':[[2025]]}}


def test_exact_conference_title_and_event_year_not_imprint():
    assert conference_year(article(),venue())==2024
    assert identify_catalog_conference(article(),{'CHI':venue()}).abbr=='CHI'


@pytest.mark.parametrize('suffix',['Companion','Extended Abstracts','Workshops','Doctoral Consortium'])
def test_never_accept_companion_or_workshops(suffix):
    assert conference_year(article('Proceedings of the CHI Conference on Human Factors in Computing Systems '+suffix),venue()) is None


def test_no_fuzzy_name_match_and_no_year_guess():
    assert conference_year(article('Proceedings of CHI PLAY',"CHI '24"),venue()) is None
    row=article(); row['event']={}
    assert conference_year(row,venue()) is None
    row=article('2023 CHI Conference on Human Factors in Computing Systems',"CHI '24")
    assert conference_year(row,venue()) is None


def test_ordinal_ampersand_and_acm_group_normalization():
    v=venue('PPoPP','ACM SIGPLAN Symposium on Principles & Practice of Parallel Programming')
    row=article('Proceedings of the 28th ACM SIGPLAN Annual Symposium on Principles and Practice of Parallel Programming',"PPoPP '23")
    assert conference_year(row,v)==2023


def test_same_acronym_different_full_name_or_ambiguous_source_is_rejected():
    row=article(); v=venue()
    assert identify_catalog_conference(row,{'one':v,'two':v}) is None
    assert conference_year(row,venue('CHI','International Conference on Healthcare Informatics')) is None


def test_ccf_workshop_itself_is_allowed_but_not_satellite():
    v=venue('IWQoS','IEEE/ACM International Workshop on Quality of Service')
    row=article('2024 IEEE/ACM 32nd International Workshop on Quality of Service (IWQoS)','IWQoS 2024')
    assert conference_year(row,v)==2024
    row['container-title']=['2024 IEEE/ACM International Workshop on Quality of Service Workshops']
    assert conference_year(row,v) is None


@pytest.mark.asyncio
async def test_discovery_ignores_unrelated_results_and_tries_aliases():
    import httpx

    from scripts.backfill_catalog_conferences import discover_containers
    queries = []
    candidate = article()
    candidate['ISBN'] = ['9781450399999']
    v = venue()
    v.dblp_stream = 'conf/chi'
    class Client:
        async def get(self, url, params=None):
            queries.append(params)
            rows = [article('Unrelated conference')] if len(queries) == 1 else [candidate]
            return httpx.Response(200, request=httpx.Request('GET', url), json={'message': {'items': rows}})
    class Limiter:
        async def acquire(self):
            pass
    containers, count = await discover_containers(Client(), v, 2024, Limiter())
    assert 'isbn:9781450399999' in containers
    assert [q['query.container-title'] for q in queries] == [v.name, 'CHI', 'chi']
    assert count == 3
    assert all('from-pub-date:2023-01-01,until-pub-date:2025-12-31' in q['filter'] for q in queries)


@pytest.mark.asyncio
async def test_discovery_rejects_other_years_and_companion_containers():
    import httpx

    from scripts.backfill_catalog_conferences import discover_containers
    v = venue()
    v.dblp_stream = 'conf/chi'
    class Client:
        async def get(self, url, params=None):
            return httpx.Response(200, request=httpx.Request('GET', url), json={'message': {'items': [
                article(acronym="CHI '23"),
                article('Proceedings of the CHI Conference on Human Factors in Computing Systems Companion'),
            ]}})
    class Limiter:
        async def acquire(self):
            pass
    containers, _ = await discover_containers(Client(), v, 2024, Limiter())
    assert containers == {}


@pytest.mark.parametrize('value', [object(), SimpleNamespace(type='conf'), SimpleNamespace(type='conf', ccf_level='A')])
def test_incomplete_catalog_identity_fails_closed_without_breaking_legacy(value):
    assert conference_year(article(), value) is None


@pytest.mark.parametrize('abbr,name,doi,acronym', [
    ('ACL', 'Annual Meeting of the Association for Computational Linguistics', '10.18653/v1/2024.acl-short.1', "ACL '24"),
    ('AAAI', 'AAAI Conference on Artificial Intelligence', '10.9999/unrelated', "AAAI '24"),
])
def test_generic_catalog_does_not_bypass_special_track_or_doi_rules(abbr, name, doi, acronym):
    from app.collectors.crossref import identify_venue
    v = venue(abbr, name)
    row = article('Proceedings of the ' + name, acronym)
    row['DOI'] = doi
    assert identify_venue(row, {abbr: v}) is None


@pytest.mark.parametrize('ordinal,year', [('Eighteenth', 2023), ('Nineteenth', 2024), ('Twentieth', 2025), ('Twenty-First', 2026)])
def test_eurosys_publisher_spelled_edition_matches_exact_semantic_name(ordinal, year):
    v = venue('EuroSys', 'European Conference on Computer Systems')
    row = article('Proceedings of the ' + ordinal + ' European Conference on Computer Systems', f"EuroSys '{str(year)[-2:]}")
    assert conference_year(row, v) == year
    row['container-title'][0] += ' Workshops'
    assert conference_year(row, v) is None


@pytest.mark.parametrize('abbr,name,title,acronym', [
 ('ASPLOS','International Conference on Architectural Support for Programming Languages and Operating Systems','Proceedings of the 29th ACM International Conference on Architectural Support for Programming Languages and Operating Systems, Volume 2',"ASPLOS '24"),
 ('CCS','ACM Conference on Computer and Communications Security','Proceedings of the 2024 ACM SIGSAC Conference on Computer and Communications Security',"CCS '24"),
 ('ISSTA','International Symposium on Software Testing and Analysis','Proceedings of the 33rd ACM SIGSOFT International Symposium on Software Testing and Analysis',"ISSTA '24"),
 ('INFOCOM','IEEE International Conference on Computer Communications','IEEE INFOCOM 2024 - IEEE Conference on Computer Communications','INFOCOM 2024'),
 ('VR','IEEE Conference on Virtual Reality and 3D User Interfaces','2024 IEEE Conference Virtual Reality and 3D User Interfaces (VR)','VR 2024'),
 ('MobiHoc','International Symposium on Theory, Algorithmic Foundations, and Protocol Design for Mobile Networks and Mobile Computing','Proceedings of the Twenty-fifth International Symposium on Theory, Algorithmic Foundations, and Protocol Design for Mobile Networks and Mobile Computing',"MobiHoc '24"),
 ('MoDELS','ACM/IEEE International Conference on Model Driven EngineeringLanguages and Systems','2024 ACM/IEEE 27th International Conference on Model Driven Engineering Languages and Systems (MODELS)','MODELS 2024'),
 ('RAID','International Symposium on Recent Advances in Intrusion Detection','2024 27th International Symposium on Research in Attacks, Intrusions and Defenses (RAID)','RAID 2024'),
])
def test_verified_publisher_main_title_variants(abbr,name,title,acronym):
    v=venue(abbr,name); row=article(title,acronym)
    assert conference_year(row,v)==2024
    row['container-title']=[title+' Workshops']
    assert conference_year(row,v) is None


def test_abstracts_only_proceedings_are_not_full_papers():
    v=venue('SIGMETRICS','International Conference on Measurement and Modeling of Computer Systems')
    row=article('Abstracts of the 2024 ACM SIGMETRICS International Conference on Measurement and Modeling of Computer Systems',"SIGMETRICS '24")
    assert conference_year(row,v) is None


@pytest.mark.parametrize('abbr,name,title',[('SODA','ACM-SIAM Symposium on Discrete Algorithms','Proceedings of the 2024 Annual ACM-SIAM Symposium on Discrete Algorithms (SODA)'),('SDM','SIAM International Conference on Data Mining','Proceedings of the 2024 SIAM International Conference on Data Mining (SDM)')])
def test_siam_chapters_require_namespace_container_and_explicit_year(abbr,name,title):
    v=venue(abbr,name);row=article(title,'');row.update(type='book-chapter',DOI='10.1137/1.9781611978032.10')
    assert conference_year(row,v)==2024
    row['DOI']='10.9999/1.9781611978032.10'
    assert conference_year(row,v) is None


def test_companion_event_cannot_hide_behind_main_container_title():
    v=venue('CHI','ACM Conference on Human Factors in Computing Systems')
    row=article(acronym="CHI '24 Companion")
    assert conference_year(row,v) is None


@pytest.mark.parametrize('abbr,name,title,acronym',[
 ('SIGCOMM','ACM International Conference on Applications, Technologies, Architectures, and Protocols for Computer Communication','Proceedings of the ACM SIGCOMM 2024 Conference',"SIGCOMM '24"),
 ('NOSSDAV','International Workshop on Network and Operating System Support for Digital Audio and Video','Proceedings of the 34th Workshop on Network and Operating System Support for Digital Audio and Video',"NOSSDAV '24"),
 ('IWQoS','IEEE/ACM International Workshop on Quality of Service','2024 IEEE/ACM International Symposium on Quality of Service (IWQoS)','IWQoS 2024'),
 ('S&P','IEEE Symposium on Security and Privacy','2024 IEEE Symposium on Security and Privacy (SP)','SP 2024'),
 ('CODES+ISSS','International Conference on Hardware/Software Co-design and System Synthesis','2024 International Conference on Hardware/Software Codesign and System Synthesis (CODES+ISSS)','CODES+ISSS 2024'),
])
def test_exact_publisher_conference_aliases(abbr,name,title,acronym):
    assert conference_year(article(title,acronym),venue(abbr,name))==2024


@pytest.mark.parametrize('abbr,name,title,acronym',[
 ('SIGGRAPH','ACM Special Interest Group on Computer Graphics','ACM SIGGRAPH 2024 Conference Papers',"SIGGRAPH '24"),
 ('HotOS','USENIX Workshop on Hot Topics in Operating Systems','Proceedings of the 19th Workshop on Hot Topics in Operating Systems',"HotOS '24"),
 ('CSFW','IEEE Computer Security Foundations Workshop','2024 IEEE 37th Computer Security Foundations Symposium (CSF)','CSF 2024'),
 ('DATE','Design, Automation & Test in Europe','2024 Design, Automation & Test in Europe Conference & Exhibition (DATE)','DATE 2024'),
])
def test_additional_exact_main_proceedings_names(abbr,name,title,acronym):
    assert conference_year(article(title,acronym),venue(abbr,name))==2024


def test_hot_chips_registered_proceedings_title_not_generic_symposium():
    v=venue('HOT CHIPS','Hot Chips: A Symposium on High Performance Chips')
    assert conference_year(article('2024 IEEE Hot Chips 36 Symposium (HCS)','HCS 2024'),v)==2024
    assert conference_year(article('2024 IEEE Symposium (HCS)','HCS 2024'),v) is None


def test_siggraph_officially_linked_parent_proceedings_not_siggraph_asia():
    v=venue('SIGGRAPH','ACM Special Interest Group on Computer Graphics')
    title='Special Interest Group on Computer Graphics and Interactive Techniques Conference Conference Papers 24'
    row=article(title,"SIGGRAPH '24");row['DOI']='10.1145/3641519.3650123'
    row['_official_siggraph_parent']={'DOI':'10.1145/3641519','type':'proceedings','title':[title]}
    assert conference_year(row,v)==2024
    row['DOI']='10.1145/3680528.3687670'
    assert conference_year(row,v) is None
