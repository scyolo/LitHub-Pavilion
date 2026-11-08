"""Vocabulary front coding retains every term and global title frequency."""
import json

import pytest

from app.services.snapshot import _json_bytes
from app.services.snapshot_search import compact_vocabulary_parts


def collected_parts(vocabulary, max_bytes=8 * 1024 * 1024):
    emitted = []

    def emit(prefix, raw, count):
        assert prefix == 'vocabulary' and count == 1
        emitted.append(raw)
        return {'path': str(len(emitted)), 'count': count}

    entries = compact_vocabulary_parts(vocabulary, emit, _json_bytes, max_bytes)
    return entries, emitted


def decoded(files):
    result = []
    for raw in files:
        rows = json.loads(raw)
        assert len(rows) == 1
        marker, codes, joined, frequencies = rows[0]
        assert marker == '$vocab'
        suffixes = joined.split(' ')
        assert len(codes) == len(suffixes) == len(frequencies)
        previous = ''
        for code, suffix, frequency in zip(codes, suffixes, frequencies, strict=True):
            prefix = ord(code) - 32
            assert 0 <= prefix <= len(previous)
            word = previous[:prefix] + suffix
            assert word > previous
            result.append([word, frequency])
            previous = word
    return result


def test_front_coded_vocabulary_restores_exact_sorted_terms_and_frequencies():
    vocabulary = {'specul': 19, 'spectral': 4, 'decod': 800, 'decode': 2, '11': 1, '1': 7, 'a': 9}
    entries, files = collected_parts(vocabulary)
    assert len(entries) == 1
    assert decoded(files) == [list(row) for row in sorted(vocabulary.items())]
    assert json.loads(files[0])[0][1][0] == ' '


def test_split_vocabulary_files_restart_prefix_without_loss():
    vocabulary = {f'speculative{i:03d}': i + 1 for i in range(100)}
    entries, files = collected_parts(vocabulary, max_bytes=150)
    assert len(entries) > 1
    assert all(len(raw) <= 150 for raw in files)
    assert all(json.loads(raw)[0][1][0] == ' ' for raw in files)
    assert decoded(files) == [list(row) for row in sorted(vocabulary.items())]


def test_empty_vocabulary_needs_no_file():
    assert collected_parts({}) == ([], [])


@pytest.mark.parametrize('vocabulary', [{'two words': 1}, {'word': 0}, {'word': True}, {'名字': 2}])
def test_malformed_vocabulary_is_not_published(vocabulary):
    with pytest.raises(ValueError, match='vocabulary'):
        collected_parts(vocabulary)
