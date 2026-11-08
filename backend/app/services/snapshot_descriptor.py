"""Lossless compact transport for paths deterministically derived from hashes."""
import re
import copy
import json


def pack_descriptor(value):
    if isinstance(value, list):
        return [pack_descriptor(item) for item in value]
    if not isinstance(value, dict):
        return value
    if {'path','sha256','count'} <= set(value):
        match=re.fullmatch(r'([a-z]+)-([0-9a-f]{64})\.json\.gz',value['path'])
        if match and match[2]==value['sha256']:
            extra={key:pack_descriptor(item) for key,item in value.items() if key not in ('path','sha256','count')}
            return {'$':[match[1],value['sha256'],value['count']],**extra}
    return {key:pack_descriptor(item) for key,item in value.items()}


def unpack_descriptor(value):
    if isinstance(value,list):
        return [unpack_descriptor(item) for item in value]
    if not isinstance(value,dict):
        return value
    if '$' in value:
        pointer=value['$']
        if (not isinstance(pointer,list) or len(pointer)!=3 or not isinstance(pointer[0],str)
                or not re.fullmatch('[a-z]+',pointer[0]) or not isinstance(pointer[1],str)
                or not re.fullmatch('[0-9a-f]{64}',pointer[1]) or type(pointer[2]) is not int or pointer[2]<0):
            raise ValueError('Invalid compact reader pointer')
        return {'path':f'{pointer[0]}-{pointer[1]}.json.gz','sha256':pointer[1],'count':pointer[2],
                **{key:unpack_descriptor(item) for key,item in value.items() if key!='$'}}
    return {key:unpack_descriptor(item) for key,item in value.items()}


def detach_search_lookup(index, manifest, emit):
    """Split immutable lookup maps by one hash nibble, leaving a tiny root."""
    from app.services.snapshot import _json_bytes

    result = copy.deepcopy(index)
    # Re-detachment is a no-op; the original full maps are intentionally gone.
    if result.get('search', {}).get('lookup') is not None:
        return result
    search = result['search']
    sections = {'terms': search['terms'], 'titles': search['titles'],
                'metadata': search.get('metadata', {}).get('terms', {}),
                'hints': search.get('hints', {}).get('terms', {})}
    parts = {}
    for prefix in '0123456789abcdef':
        directory = {'version': 1, **{
            section: {key: entries for key, entries in buckets.items() if key.startswith(prefix)}
            for section, buckets in sections.items()
        }}
        if any(directory[section] for section in sections):
            parts[prefix] = emit('lookup', _json_bytes(pack_descriptor(directory)), manifest['paper_count'])
    search['lookup'] = {'version': 1, 'bucket_chars': 1, 'parts': parts}
    search['terms'], search['titles'] = {}, {}
    for section in ('metadata', 'hints'):
        if section in search:
            search[section]['terms'] = {}
    return result


def decode_lookup_descriptor(raw, prefix, entry, paper_count):
    """Verify one detached map's scope before exposing referenced filenames."""
    if (not isinstance(prefix, str) or not re.fullmatch('[0-9a-f]', prefix)
            or not isinstance(entry, dict) or set(entry) != {'path', 'sha256', 'count'}
            or not isinstance(entry['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])
            or entry['path'] != f"lookup-{entry['sha256']}.json.gz"
            or type(entry['count']) is not int or entry['count'] != paper_count):
        raise ValueError('Invalid detached lookup entry')
    value = unpack_descriptor(json.loads(raw))
    if (not isinstance(value, dict) or set(value) != {'version', 'terms', 'titles', 'metadata', 'hints'}
            or type(value['version']) is not int or value['version'] != 1):
        raise ValueError('Invalid detached lookup fields')
    for section, filename_prefix, width in [('terms', 'search', 3), ('titles', 'titles', 2),
                                             ('metadata', 'matchrank', 3), ('hints', 'cardhint', 3)]:
        buckets = value[section]
        if not isinstance(buckets, dict) or len(buckets) > 16 ** (width - 1):
            raise ValueError('Invalid detached lookup buckets')
        for key, entries in buckets.items():
            if (not isinstance(key, str) or not re.fullmatch('[0-9a-f]{' + str(width) + '}', key)
                    or not key.startswith(prefix) or not isinstance(entries, list) or not entries or len(entries) > 4096):
                raise ValueError('Invalid detached lookup scope')
            for part in entries:
                if (not isinstance(part, dict) or set(part) != {'path', 'sha256', 'count'}
                        or not isinstance(part['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', part['sha256'])
                        or part['path'] != f"{filename_prefix}-{part['sha256']}.json.gz"
                        or type(part['count']) is not int or part['count'] < 1):
                    raise ValueError('Invalid detached lookup asset')
    return value
