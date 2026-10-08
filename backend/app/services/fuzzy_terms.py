"""Bounded title-token typo/prefix expansion, shared contract with the reader."""
import bisect
import re

from app.services.search_tokens import stemmer

ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789'


def edit_one_variants(token):
    if not re.fullmatch(r'[a-z0-9]{4,32}', token):
        return set()
    result = set()
    for index in range(len(token) + 1):
        left, right = token[:index], token[index:]
        if right:
            result.add(left + right[1:])
            result.update(left + letter + right[1:] for letter in ALPHABET)
        result.update(left + letter + right for letter in ALPHABET)
        if len(right) > 1:
            result.add(left + right[1] + right[0] + right[2:])
    result.discard(token)
    return result


def expand_tokens(tokens, vocabulary, *, limit=4, raw_tokens=()):
    frequencies = dict(vocabulary)
    terms = sorted(frequencies)
    raw_by_stem = {}
    for raw in raw_tokens:
        raw_by_stem.setdefault(stemmer(raw), set()).add(raw)
    groups = []
    for token in tokens:
        choices = {}
        if token in frequencies:
            choices[token] = 0
        for candidate in edit_one_variants(token):
            if candidate in frequencies:
                choices.setdefault(candidate, 2)
        # Correct the original spelling too: removing the final e from
        # speculative changes its Porter stem by more than one character.
        for raw in raw_by_stem.get(token, ()):
            for variant in edit_one_variants(raw):
                candidate = stemmer(variant)
                if candidate in frequencies:
                    choices.setdefault(candidate, 2)
        # Complete every fragment ("spec dec"), with the same per-token cap
        # as typo expansion. Keep short acronyms and long terms literal.
        if 3 <= len(token) <= 32:
            start = bisect.bisect_left(terms, token)
            end = bisect.bisect_left(terms, token + '{')
            for candidate in terms[start:end]:
                if len(candidate) > len(token):
                    choices[candidate] = min(choices.get(candidate, 99), 1)
        ranked = sorted(choices, key=lambda value: (choices[value], -frequencies[value], value))
        groups.append([token] + [value for value in ranked if value != token][:limit - 1])
    return groups
