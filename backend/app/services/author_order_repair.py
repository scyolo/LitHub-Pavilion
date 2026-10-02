"""Plan lossless author ordering from exact identities, never guess author aliases."""
from app.cleaning import author_name_norm, clean_author_name


def plan_author_order(stored, publisher_names):
    def key(name):
        return author_name_norm(clean_author_name(name))
    source = [key(name) for name in publisher_names]
    current = [key(name) for _, name, _ in stored]
    if (not source or not all(source) or not all(current)
            or len(source) != len(set(source)) or len(current) != len(set(current))
            or len(stored) != len(publisher_names) or set(source) != set(current)):
        raise ValueError('Author identities missing, conflicting, or ambiguous')
    by_name = {key(name): aid for aid, name, _ in stored}
    return [(by_name[name], order) for order, name in enumerate(source, 1)]


def plan_verified_aliases(stored, publisher_names, official_names):
    """Collapse only extra initials at the same verified full-name slot.

    Both publisher sources must supply the identical ordered full-name list.
    No author entity is deleted, and no cross-paper identity is merged.
    """
    from app.services.publication_identity import _parts
    def key(name):
        return author_name_norm(clean_author_name(name))
    source = [key(name) for name in publisher_names]
    if not source or source != [key(name) for name in official_names] or len(set(source)) != len(source):
        raise ValueError('Independent ordered author evidence disagrees')
    keep = []
    for index, name in enumerate(source, 1):
        exact = [(aid, order) for aid, stored_name, order in stored if key(stored_name) == name]
        if len(exact) != 1:
            raise ValueError('Full author identity missing or ambiguous')
        keep.append((exact[0][0], index))
    kept = {aid for aid, _ in keep}
    positions = {aid: order for aid, _, order in stored}
    removed = []
    for aid, name, old_order in stored:
        if aid in kept:
            continue
        family, given = _parts(clean_author_name(name))
        if not given or any(len(token) != 1 for token in given):
            raise ValueError('Extra author is not an initials-only duplicate')
        matches = []
        for index, full in enumerate(publisher_names):
            full_family, full_given = _parts(clean_author_name(full))
            if family == full_family and len(given) == len(full_given) and all(a == b[0] for a,b in zip(given,full_given)):
                matches.append(index)
        if len(matches) != 1:
            raise ValueError('Initials match multiple or no official authors')
        keeper = keep[matches[0]][0]
        if old_order != positions[keeper] or old_order != keep[matches[0]][1]:
            raise ValueError('Initials and full author are not at the same official position')
        removed.append(aid)
    return {'keep': keep, 'remove': removed}
