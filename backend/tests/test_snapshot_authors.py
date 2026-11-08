"""Author indexes cover every slot without scanning paper detail shards."""
import gzip
import hashlib
import json

import pytest

from app.models import Author, PaperAuthor
from app.services.snapshot import export_snapshot, validate_snapshot
from app.services.snapshot_reader import (
    decode_author_descriptor, load_reader_descriptor, read_compressed_asset, reader_entries,
)


@pytest.fixture()
def author_snapshot(db, session_factory, sample_paper, tmp_path):
    names = ['First, Writer', 'Bengio, Yoshua', 'José García', '王小明']
    for order, name in enumerate(names, 1):
        author = Author(name=name, name_norm=f'test-author-{order}')
        db.add(author)
        db.flush()
        db.add(PaperAuthor(paper_id=sample_paper.id, author_id=author.id, author_order=order))
    db.commit()
    manifest = export_snapshot(session_factory, tmp_path)
    catalog = json.loads((tmp_path / manifest['catalog']['path']).read_bytes())
    return manifest, catalog, sample_paper.id


def test_export_indexes_all_authors_and_new_reader_is_fully_validated(
    author_snapshot, tmp_path
):
    manifest, catalog, pid = author_snapshot
    assert catalog['reader']['version'] == 10
    descriptor = load_reader_descriptor(tmp_path, catalog)
    assert descriptor['version'] == 9 and descriptor['search']['version'] == 5
    pointer = descriptor['search']['authors']
    assert set(pointer) == {'version', 'bucket_chars', 'index'}
    assert pointer['index']['path'].startswith('authors-')
    _, raw = read_compressed_asset(tmp_path, pointer['index'])
    authors = decode_author_descriptor(raw, pointer, manifest['paper_count'])
    rows = []
    for key, entries in authors['terms'].items():
        for entry in entries:
            for row in json.loads(gzip.decompress((tmp_path / entry['path']).read_bytes())):
                assert hashlib.sha256(row[0].encode()).hexdigest()[:3] == key
                rows.append(row)
    assert ['bengio', 'Bengio, Yoshua', [pid]] in rows
    assert ['yoshua', 'Bengio, Yoshua', [pid]] in rows
    assert ['jose', 'José García', [pid]] in rows
    assert ['王小明', '王小明', [pid]] in rows
    assert pointer['index'] in reader_entries(catalog, tmp_path)
    assert any(entry['path'].startswith('author-') for entry in reader_entries(catalog, tmp_path))
    lookup_descriptors = None
    if descriptor['search'].get('lookup'):
        from app.services.snapshot_descriptor import decode_lookup_descriptor

        lookup_descriptors = {}
        for prefix, entry in descriptor['search']['lookup']['parts'].items():
            _, raw = read_compressed_asset(tmp_path, entry)
            lookup_descriptors[prefix] = decode_lookup_descriptor(raw, prefix, entry, manifest['paper_count'])
    assert reader_entries(catalog, tmp_path) == reader_entries(
        catalog, descriptor=descriptor, author_descriptor=authors, lookup_descriptors=lookup_descriptors)
    assert validate_snapshot(tmp_path) == manifest


@pytest.mark.parametrize('kind', ['directory', 'posting'])
def test_author_index_directory_and_postings_are_integrity_checked(author_snapshot, tmp_path, kind):
    manifest, catalog, _ = author_snapshot
    descriptor = load_reader_descriptor(tmp_path, catalog)
    pointer = descriptor['search']['authors']
    _, raw = read_compressed_asset(tmp_path, pointer['index'])
    authors = decode_author_descriptor(raw, pointer, manifest['paper_count'])
    entry = pointer['index'] if kind == 'directory' else next(iter(authors['terms'].values()))[0]
    (tmp_path / entry['path']).write_bytes(gzip.compress(b'[]'))
    with pytest.raises(ValueError, match='digest|match'):
        validate_snapshot(tmp_path)


@pytest.mark.parametrize('mutation', ['count', 'fields', 'bucket', 'entry'])
def test_author_directory_rejects_invalid_metadata_before_enumerating_files(author_snapshot, tmp_path, mutation):
    manifest, catalog, _ = author_snapshot
    descriptor = load_reader_descriptor(tmp_path, catalog)
    pointer = json.loads(json.dumps(descriptor['search']['authors']))
    _, raw = read_compressed_asset(tmp_path, pointer['index'])
    authors = json.loads(raw)
    if mutation == 'count':
        pointer['index']['count'] += 1
    elif mutation == 'fields':
        authors['extra'] = 'untrusted'
    elif mutation == 'bucket':
        authors['terms']['../escape'] = []
    else:
        next(iter(authors['terms'].values()))[0]['path'] = '../escape.json.gz'
    with pytest.raises(ValueError, match='Author'):
        decode_author_descriptor(json.dumps(authors).encode(), pointer, manifest['paper_count'])
