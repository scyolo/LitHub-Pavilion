"""Publication identity checks for publisher-verified title/author matches."""
import re
import unicodedata

from app.cleaning import normalize_arxiv_id


def preprint_id(paper):
    doi = (getattr(paper, "doi", None) or "").lower()
    return (normalize_arxiv_id(getattr(paper, "arxiv_id", None))
            or normalize_arxiv_id(doi.removeprefix("10.48550/arxiv."))
            or normalize_arxiv_id(getattr(paper, "oa_url", None)))


def _tokens(value):
    value = value.casefold().translate(str.maketrans({'ł': 'l', 'ø': 'o', 'đ': 'd', 'ð': 'd', 'þ': 'th', 'æ': 'ae', 'œ': 'oe'}))
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", value)


def _parts(value):
    if "," in value:
        family, given = value.split(",", 1)
    else:
        words = value.rsplit(None, 1)
        given, family = words if len(words) == 2 else ("", value)
    return "".join(_tokens(family)), _tokens(given)


def _name_match(first, second):
    family_a, given_a = _parts(first)
    family_b, given_b = _parts(second)
    tokens_a, tokens_b = _tokens(first), _tokens(second)
    # Publishers occasionally reverse a full given/family name. This is not a
    # license to equate different full given names sharing an initial.
    if sorted(tokens_a) == sorted(tokens_b) and tokens_a:
        return True, any(len(t) > 1 for t in given_a + given_b)
    if not family_a or family_a != family_b or not given_a or not given_b:
        return False, False
    if ''.join(given_a) == ''.join(given_b):
        return True, len(''.join(given_a)) > 1
    for a, b in zip(given_a, given_b):
        if a != b and not (a[0] == b[0] and (len(a) == 1 or len(b) == 1)):
            return False, False
    anchor = given_a[0] == given_b[0] and len(given_a[0]) > 1
    return True, anchor


def publication_authors_match(first, second, *, shared_identity=False):
    """Require a unique one-to-one author match, not surname-set similarity.

    Initials and omitted middle names need at least one full-name anchor unless
    an independent shared identifier already ties the two records together.
    Unrelated full names, missing authors and ambiguous assignments fail closed.
    """
    if not first or len(first) != len(second):
        return False
    edges = []
    anchor = False
    for name in first:
        matches = []
        for index, candidate in enumerate(second):
            compatible, full_name = _name_match(name, candidate)
            if compatible:
                matches.append(index)
                anchor = anchor or full_name
        if not matches:
            return False
        edges.append(matches)
    if not anchor and not shared_identity:
        return False
    # Ambiguity is itself a reason to defer; never pick a convenient assignment.
    assigned = set()
    pending = list(edges)
    while pending:
        reduced = [set(options) - assigned for options in pending]
        if any(not options for options in reduced):
            return False
        singles = [(i, next(iter(options))) for i, options in enumerate(reduced) if len(options) == 1]
        if not singles or len({index for _, index in singles}) != len(singles):
            return False
        assigned.update(index for _, index in singles)
        done = {i for i, _ in singles}
        pending = [list(options) for i, options in enumerate(reduced) if i not in done]
    return True
