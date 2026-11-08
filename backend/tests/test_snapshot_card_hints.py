"""Hints cache true display rows without replacing full result computation."""
import hashlib
import json
import sqlite3

import pytest

from app.services import snapshot_card_hints as hints
from app.services.snapshot import _json_bytes, _write_content
from app.services.snapshot_reader import FIELDS


def fixture(tmp_path, rows):
    papers=[]
    for pid,title in rows:
        paper={field:None for field in FIELDS}
        paper.update(id=pid,title=title,venue='ICML',year=2025,citation_count=pid,
                     directions=['ml'],venue_confirmed=True,first_author='Ada',authors_count=1,pdf_status='closed')
        papers.append(paper)
    entry={**_write_content(tmp_path,'papers',_json_bytes(papers)),'count':len(papers)}
    manifest={'paper_count':len(papers),'chunks':[entry]}
    database=sqlite3.connect(':memory:')
    database.execute('CREATE TABLE postings (bucket TEXT,token TEXT,id INTEGER,frequency INTEGER,length INTEGER,positions TEXT)')
    payloads={}
    def emit(prefix,content,count):
        digest=hashlib.sha256(content).hexdigest();path=f'{prefix}-{digest}.json.gz'
        payloads[path]=json.loads(content)
        return {'path':path,'sha256':digest,'count':count}
    return database,manifest,papers,payloads,emit


def add(database,token,pid,frequency=8,positions=None):
    database.execute('INSERT INTO postings VALUES (?,?,?,?,?,?)',(
        hashlib.sha256(token.encode()).hexdigest()[:3],token,pid,frequency,10,json.dumps(positions or [])))


def all_hints(index,payloads):
    groups={}
    for parts in index['terms'].values():
        for entry in parts:
            payload=payloads[entry['path']]
            dictionary={row[0]:row for token,rows in payload if token=='$cards' for row in rows}
            for token,rows in payload:
                if token!='$cards':groups.setdefault(token,[]).extend(dictionary[pid] for pid in rows)
    return groups


def test_rare_title_terms_include_every_true_card_but_not_abstract_only_vocabulary(tmp_path):
    database,manifest,papers,payloads,emit=fixture(tmp_path,[(1,'Learning method'),(2,'Other article')])
    add(database,'learn',1,positions=[0]);add(database,'learn',2)
    add(database,'abstractonly',1)
    index=hints.build_card_hints(database,tmp_path,manifest,emit,10)
    groups=all_hints(index,payloads)
    assert groups['learn']==[[paper[field] for field in FIELDS] for paper in papers]
    assert 'abstractonly' not in groups
    assert index['bucket_chars']==3
    database.close()


def test_common_hints_preserve_base_top_page_and_are_bounded_across_raw_variants(tmp_path,monkeypatch):
    database,manifest,_papers,payloads,emit=fixture(tmp_path,[
        (1,'Learning method'),(2,'Learned method'),(3,'Learn method'),(4,'Learning'),
        (5,'Abstract article'),(6,'Learned')])
    for pid in range(1,7):add(database,'learn',pid,frequency=pid*8,positions=[0] if pid!=5 else [])
    monkeypatch.setattr(hints,'RARE_CARD_LIMIT',2);monkeypatch.setattr(hints,'PAGE_HINT_SIZE',2)
    monkeypatch.setattr(hints,'COMMON_CARD_LIMIT',4)
    monkeypatch.setattr(hints,'EXPANDED_CARD_LIMIT',4)
    groups=all_hints(hints.build_card_hints(database,tmp_path,manifest,emit,10),payloads)
    ids=[row[0] for row in groups['learn']]
    assert ids[:2]==[6,4]
    assert len(ids)<=4 and len(ids)==len(set(ids))
    database.close()


def test_invalid_average_length_is_rejected_before_reading_source(tmp_path):
    database=sqlite3.connect(':memory:')
    for value in [0,-1,float('nan'),float('inf')]:
        with pytest.raises(ValueError,match='average'):
            hints.build_card_hints(database,tmp_path,{'paper_count':0,'chunks':[]},lambda *_:None,value)
    database.close()


def test_oversized_token_card_hints_split_at_record_boundaries_without_loss(tmp_path,monkeypatch):
    from app.services import snapshot

    database,manifest,papers,payloads,emit=fixture(tmp_path,[(pid,f'Learning method {pid}') for pid in range(1,15)])
    for pid in range(1,15):add(database,'learn',pid,positions=[0])
    monkeypatch.setattr(snapshot,'MAX_FILE_BYTES',600)
    sizes=[]
    def bounded_emit(prefix,content,count):
        sizes.append(len(content));return emit(prefix,content,count)
    index=hints.build_card_hints(database,tmp_path,manifest,bounded_emit,10)
    groups=all_hints(index,payloads)
    assert len(index['terms'][hashlib.sha256(b'learn').hexdigest()[:3]])>1
    assert groups['learn']==[[paper[field] for field in FIELDS] for paper in papers]
    assert max(sizes)<=600
    database.close()


def test_each_split_contains_its_referenced_cards_and_shared_cards_are_deduplicated(tmp_path):
    database,manifest,papers,payloads,emit=fixture(tmp_path,[(1,'Learning model'),(2,'Learning model')])
    for pid in (1,2):
        add(database,'learn',pid,positions=[0]);add(database,'model',pid,positions=[1])
    index=hints.build_card_hints(database,tmp_path,manifest,emit,10)
    # Force both different tokens into one synthetic bucket to test dictionary
    # reuse even though their SHA buckets would ordinarily be separate files.
    database.execute("UPDATE postings SET bucket='000'")
    database.execute('DROP TABLE card_hint_tokens')
    index=hints.build_card_hints(database,tmp_path,manifest,emit,10)
    entry=index['terms']['000'][0];payload=payloads[entry['path']]
    assert payload[0][0]=='$cards' and len(payload[0][1])==2
    assert len(payload)==entry['count']==3
    assert all_hints(index,payloads)=={
        'learn':[[paper[field] for field in FIELDS] for paper in papers],
        'model':[[paper[field] for field in FIELDS] for paper in papers],
    }
    database.close()


def test_generic_common_title_phrases_and_venue_years_extend_hint_coverage(tmp_path,monkeypatch):
    rows=[(pid,'Large language model') for pid in range(1,111)]
    rows.extend((pid,'Large study') for pid in range(111,171))
    database,manifest,_papers,payloads,emit=fixture(tmp_path,rows)
    for pid in range(1,171):add(database,'larg',pid,frequency=pid*8,positions=[0])
    monkeypatch.setattr(hints,'RARE_CARD_LIMIT',2)
    monkeypatch.setattr(hints,'PAGE_HINT_SIZE',2)
    monkeypatch.setattr(hints,'PHRASE_HINT_SIZE',100)
    groups=all_hints(hints.build_card_hints(database,tmp_path,manifest,emit,10),payloads)
    ids=[row[0] for row in groups['larg']]
    assert {170,169}.issubset(ids)
    assert len(set(ids)&set(range(1,111)))==100
    assert len(ids)<=hints.EXPANDED_CARD_LIMIT
    database.close()


def test_common_source_neighborhood_is_reserved_before_phrase_family_exhausts_cap(monkeypatch):
    postings=[(pid,pid*8,10,[0]) for pid in range(1,211)]
    titles={pid:'large language model' if pid<=100 else 'large study' for pid in range(1,211)}
    words={pid:set(title.split()) for pid,title in titles.items()}
    cards={pid:[pid,titles[pid],'A' if pid<=100 else 'B',2025] for pid in range(1,211)}
    phrases={'larg':[(('larg','languag','model'),set(range(1,101)))]}
    monkeypatch.setattr(hints,'RARE_CARD_LIMIT',2);monkeypatch.setattr(hints,'PAGE_HINT_SIZE',20)
    monkeypatch.setattr(hints,'COMMON_CARD_LIMIT',20);monkeypatch.setattr(hints,'EXPANDED_CARD_LIMIT',110)
    monkeypatch.setattr(hints,'SCOPE_HINT_GROUPS',1)
    selected=hints._hint_ids('larg',postings,titles,words,{'larg':{'large'}},211,10,cards,phrases)
    assert set(range(191,211)).issubset(selected)
    assert len(selected)==110
