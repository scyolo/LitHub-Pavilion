import hashlib
import json

import pytest

from app.services.snapshot_descriptor import (
    decode_lookup_descriptor, detach_search_lookup, pack_descriptor, unpack_descriptor,
)


def test_compact_descriptor_restores_exact_entries_without_duplicate_hash_paths():
    digest='a'*64
    source={'browse':[{'path':f'browse-{digest}.json.gz','sha256':digest,'count':128,'min_id':1,'max_id':150}],
            'search':{'terms':{'abc':[{'path':f'search-{digest}.json.gz','sha256':digest,'count':5}]}}}
    packed=pack_descriptor(source)
    assert 'path' not in packed['browse'][0]
    assert packed['browse'][0]['$']==['browse',digest,128]
    assert unpack_descriptor(packed)==source


def test_detached_lookup_preserves_every_section_without_mutating_reader():
    sha = 'a' * 64
    entry = lambda prefix: {'path': f'{prefix}-{sha}.json.gz', 'sha256': sha, 'count': 2}
    source = {'version': 9, 'paper_count': 12, 'search': {
        'version': 5, 'terms': {'abc': [entry('search')], 'ffe': [entry('search')]},
        'titles': {'ab': [entry('titles')]}, 'metadata': {'bucket_chars': 3, 'terms': {'abc': [entry('matchrank')]}},
        'hints': {'bucket_chars': 3, 'terms': {'abc': [entry('cardhint')]}}, 'average_length': 8}}
    original = json.loads(json.dumps(source))
    emitted = {}

    def emit(prefix, raw, count):
        digest = hashlib.sha256(raw).hexdigest()
        value = {'path': f'{prefix}-{digest}.json.gz', 'sha256': digest, 'count': count}
        emitted[value['path']] = raw
        return value

    detached = detach_search_lookup(source, {'paper_count': 12}, emit)
    assert source == original
    assert detached['search']['terms'] == detached['search']['titles'] == {}
    assert detached['search']['metadata']['terms'] == detached['search']['hints']['terms'] == {}
    assert set(detached['search']['lookup']['parts']) == {'a', 'f'}
    restored = {section: {} for section in ('terms', 'titles', 'metadata', 'hints')}
    for prefix, part in detached['search']['lookup']['parts'].items():
        assert part['count'] == 12
        value = decode_lookup_descriptor(emitted[part['path']], prefix, part, 12)
        for section in restored:
            restored[section].update(value[section])
    assert restored['terms'] == source['search']['terms']
    assert restored['titles'] == source['search']['titles']
    assert restored['metadata'] == source['search']['metadata']['terms']
    assert restored['hints'] == source['search']['hints']['terms']
    assert detach_search_lookup(detached, {'paper_count': 12}, emit) == detached


@pytest.mark.parametrize('change', ['wrong-prefix', 'unsafe-path', 'count', 'unknown-fields'])
def test_detached_lookup_rejects_invalid_scopes_before_file_enumeration(change):
    digest = 'a' * 64
    value = {'version': 1, 'terms': {'abc': [{'path': f'search-{digest}.json.gz', 'sha256': digest, 'count': 1}]},
             'titles': {}, 'metadata': {}, 'hints': {}}
    entry = {'path': f'lookup-{digest}.json.gz', 'sha256': digest, 'count': 12}
    prefix = 'a'
    if change == 'wrong-prefix':
        prefix = 'b'
    elif change == 'unsafe-path':
        value['terms']['abc'][0]['path'] = '../escape.json.gz'
    elif change == 'count':
        entry['count'] = 13
    else:
        value['extra'] = {}
    with pytest.raises(ValueError, match='lookup'):
        decode_lookup_descriptor(json.dumps(value).encode(), prefix, entry, 12)
