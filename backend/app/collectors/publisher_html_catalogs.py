"""Small official main-track HTML indexes. PDF links are retained, never fetched."""
import re
from urllib.parse import urljoin
from app.cleaning import normalize_doi
from app.collectors.usenix_catalog import Tree, Node
from app.collectors.publisher_toc import _raw


def checked(rows):
    unique={}
    for row in rows:
        row.title = re.sub(r'\s+', ' ', row.title).strip()
        if not row.title or not row.authors:raise ValueError('Missing publication title/authors')
        if row.venue_key in unique and (row.title,row.authors)!=(unique[row.venue_key].title,unique[row.venue_key].authors):raise ValueError('Conflicting duplicate publication')
        unique[row.venue_key]=row
    if not unique:raise ValueError('No main-track publication records parsed')
    return list(unique.values())


def parse_cidr(text,year):
    tree=Tree();tree.feed(text)
    titles=tree.root.find(lambda n:n.tag in ('title','h1'))
    if not any(re.search(r'CIDR\s+'+str(year)+r'\b',n.text()) for n in titles):raise ValueError('CIDR edition mismatch')
    spans=tree.root.find(lambda n:n.tag=='span');rows=[]
    for index,node in enumerate(spans):
        if not node.has_class('session-talk'):continue
        links=node.find(lambda n:n.tag=='a' and re.fullmatch(r'(?:papers/|https://www\.cidrdb\.org/cidr'+str(year)+r'/papers/|https://vldb\.org/cidrdb/papers/'+str(year)+r'/)p[0-9]+-[A-Za-z0-9_.-]+\.pdf',n.attrs.get('href','')))
        if not links:continue
        authors=None
        for following in spans[index+1:]:
            if following.has_class('session-talk'):break
            if following.has_class('session-presenter'):authors=following.text();break
        if authors is None:raise ValueError('CIDR published paper missing authors')
        authors=re.sub(r'\([^)]*\)','',authors).replace('*','')
        names=[re.sub(r'\s+',' ',x).strip(' ;') for x in authors.split(';') if x.strip()]
        rows.append(_raw(urljoin(f'https://www.cidrdb.org/cidr{year}/',links[0].attrs['href']),links[0].text(),names,year))
    return checked(rows)


def parse_edbt(text,year):
    tree=Tree();tree.feed(text)
    if not any(re.search(r'EDBT\s+'+str(year)+r'\b',n.text()) for n in tree.root.find(lambda n:n.tag=='h1')):raise ValueError('EDBT edition mismatch')
    elements=tree.root.find(lambda n:n.tag=='h4' or n.has_class('paper'));section='';rows=[]
    for node in elements:
        if node.tag=='h4':section=node.text().strip();continue
        if section not in {'Research Track', 'Experiments & Analyses Track', 'Vision Papers'}:continue
        titles=node.find(lambda n:n.tag=='b');author_nodes=[n for n in node.children if isinstance(n,Node) and n.tag=='div']
        dois={normalize_doi(n.attrs.get('href', '').replace('https://dx.doi.org/', 'https://doi.org/')) for n in node.find(lambda n:n.tag=='a')};dois.discard(None)
        dois={d for d in dois if re.fullmatch(r'10\.48786/edbt\.'+str(year)+r'\.[0-9]+',d)}
        if len(titles)!=1 or len(author_nodes)!=1 or len(dois)!=1:raise ValueError('EDBT record identity incomplete')
        names=re.split(r'\bpp\.',author_nodes[0].text())[0].strip().split(',')
        doi=dois.pop();rows.append(_raw('https://doi.org/'+doi,titles[0].text(),names,year,doi=doi))
    return checked(rows)


def parse_isca(text,year):
    tree=Tree();tree.feed(text)
    if not any(re.search(r'Interspeech\s+'+str(year)+r'\b',n.text()) for n in tree.root.find(lambda n:n.tag in ('h1','h2','h3','title'))):raise ValueError('ISCA edition mismatch')
    rows=[]
    for group in tree.root.find(lambda n:n.tag=='div'):
        headings=[n for n in group.children if isinstance(n,Node) and n.tag=='h4']
        if len(headings)!=1 or re.search(r'demo|show and tell|keynote|plenary|invited',headings[0].text(),re.IGNORECASE):continue
        for link in group.find(lambda n:n.tag=='a' and re.fullmatch(r'[a-z0-9_]+_interspeech\.html',n.attrs.get('href',''))):
            paragraphs=link.find(lambda n:n.tag=='p');authors=link.find(lambda n:n.tag=='span')
            if len(paragraphs)!=1 or len(authors)!=1:raise ValueError('ISCA record metadata incomplete')
            title=paragraphs[0].text(exclude=('span',)).strip()
            names=authors[0].text().strip().split(',')
            rows.append(_raw(f'https://www.isca-archive.org/interspeech_{year}/'+link.attrs['href'],title,names,year))
    return checked(rows)


SOURCES={'CIDR':('https://www.cidrdb.org/cidr{year}/program.html',parse_cidr),
         'EDBT':('https://openproceedings.org/html/pages/{year}_edbt.html',parse_edbt),
         'INTER- SPEECH':('https://www.isca-archive.org/interspeech_{year}/index.html',parse_isca)}


def parse_i3d(text,year):
    tree=Tree();tree.feed(text)
    if not any(re.search(r'I3D\s+'+str(year)+r'\b',n.text(),re.IGNORECASE) for n in tree.root.find(lambda n:n.tag=='title')):raise ValueError('I3D edition mismatch')
    rows=[]
    for dl in tree.root.find(lambda n:n.tag=='dl'):
        current=None;authors=None
        for n in dl.children:
            if not isinstance(n,Node):continue
            if n.tag=='dt':current=n.text().strip();authors=None
            elif n.tag=='dd' and current:
                links=n.find(lambda a:a.tag=='a' and re.fullmatch(r'https://dl.acm.org/doi/10\.1145/[0-9]+',a.attrs.get('href','')))
                if links and authors:
                    doi=links[0].attrs['href'].removeprefix('https://dl.acm.org/doi/')
                    names=re.split(r',|\band\b',authors)
                    rows.append(_raw('https://doi.org/'+doi,current,names,year,doi=doi));current=None
                elif authors is None:authors=n.text().strip()
    return checked(rows)


def parse_msst(text,year):
    tree=Tree();tree.feed(text)
    if not any(re.search(r'MSST\s+'+str(year)+r'\b',n.text(),re.IGNORECASE) for n in tree.root.find(lambda n:n.tag=='title')):raise ValueError('MSST edition mismatch')
    rows=[]
    for group in tree.root.find(lambda n:n.tag=='ul' and n.has_class('papers')):
        for node in group.find(lambda n:n.tag=='li'):
            titles=node.find(lambda n:n.has_class('ptitle'));authors=node.find(lambda n:n.has_class('authors'))
            links=node.find(lambda n:n.tag=='a' and re.fullmatch(r'../MSST-history/'+str(year)+r'/Papers/msst'+str(year)[-2:]+r'-[0-9.]+\.pdf',n.attrs.get('href','')))
            if not links:continue
            if len(titles)!=1 or len(authors)!=1:raise ValueError('MSST research record incomplete')
            names=[]
            for segment in authors[0].text().split(';'):
                segment=re.sub(r'\([^()]*\)\s*$','',segment).strip()
                names.extend(re.split(r',|\band\b',segment))
            rows.append(_raw(urljoin(f'https://msstconference.org/{year}/',links[0].attrs['href']),titles[0].text(),names,year))
    return checked(rows)

SOURCES.update({'I3D':('https://i3dsymposium.org/{year}/papers.html',parse_i3d),'MSST':('https://msstconference.org/{year}/',parse_msst)})
