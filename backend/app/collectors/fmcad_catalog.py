"""TU Wien's registered FMCAD main proceedings; no preprints or student forum."""
import re
from app.cleaning import normalize_doi,normalize_title
from app.collectors.publisher_toc import _raw
from app.services.publication_admission import nonresearch_title


def parse_parent(record):
    a=record.get('attributes') or {};doi=normalize_doi(a.get('doi')) or ''
    match=re.fullmatch(r'10.34727/(20\d{2})/isbn\.978-[0-9-]+',doi)
    if not match or normalize_doi(record.get('id'))!=doi or a.get('publisher')!='TU Wien':return None
    year=int(match[1])
    if year not in range(2023,2027) or a.get('publicationYear')!=year:return None
    if (a.get('types') or {}).get('resourceType')!='Proceedings':return None
    titles=a.get('titles') or []
    if len(titles)!=1:return None
    title=normalize_title(titles[0].get('title',''))
    if not re.fullmatch(r'proceedings of the [0-9]+(?:st|nd|rd|th) conference on formal methods in computer aided design fmcad '+str(year),title):return None
    return year


def parse_chapter(record,parent):
    year=parse_parent(parent)
    if not year:return None
    a=record.get('attributes') or {};doi=normalize_doi(a.get('doi')) or '';base=normalize_doi(parent['id'])
    if not re.fullmatch(re.escape(base)+r'_[0-9]+',doi) or normalize_doi(record.get('id'))!=doi:return None
    if a.get('publisher')!='TU Wien' or a.get('publicationYear')!=year or (a.get('types') or {}).get('resourceType')!='Inproceedings':return None
    titles=a.get('titles') or []
    if len(titles)!=1:return None
    title=titles[0].get('title','')
    if nonresearch_title(title) or re.search(r'\b(student forum|invited|keynote|preface|front matter)\b',title,re.IGNORECASE):return None
    authors=[c['name'] for c in a.get('creators',[]) if c.get('name')]
    if not authors:return None
    return _raw('https://doi.org/'+doi,title,authors,year,doi=doi)
