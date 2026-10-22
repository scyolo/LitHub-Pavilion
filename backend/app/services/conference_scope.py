"""Public conference memberships, separate from canonical publication counts."""

from dataclasses import replace

from sqlalchemy import func, inspect
from sqlalchemy.orm import aliased

from app.api.filtering import PaperFilters, paper_query
from app.models import Paper, PaperConference, Venue


def public_conference_associations(db, filters=None):
    if not inspect(db.bind).has_table('paper_conferences'):
        return {}
    filters = replace(filters or PaperFilters(), level=None, type=None, venue=None, include_associated=False)
    admitted = paper_query(db, filters).with_entities(Paper.id, Paper.venue_id).subquery()
    conference = aliased(Venue)
    rows = (
        db.query(conference.abbr, PaperConference.event_year, PaperConference.paper_id)
        .join(PaperConference, PaperConference.venue_id == conference.id)
        .join(admitted, admitted.c.id == PaperConference.paper_id)
        .filter(conference.type == 'conf', conference.ccf_level.in_(('A', 'B')),
                admitted.c.venue_id != conference.id)
        .order_by(conference.abbr, PaperConference.event_year, PaperConference.paper_id)
    )
    result = {}
    for abbr, year, paper_id in rows:
        result.setdefault(abbr, {}).setdefault(str(year), []).append(paper_id)
    return result


def associated_counts(db, filters=None):
    if not inspect(db.bind).has_table('paper_conferences'):
        return {}
    filters = replace(filters or PaperFilters(), level=None, type=None, venue=None, include_associated=False)
    admitted = paper_query(db, filters).with_entities(Paper.id, Paper.venue_id).subquery()
    conference = aliased(Venue)
    return dict(db.query(conference.abbr, func.count(func.distinct(PaperConference.paper_id)))
                .join(PaperConference, PaperConference.venue_id == conference.id)
                .join(admitted, admitted.c.id == PaperConference.paper_id)
                .filter(conference.type == 'conf', conference.ccf_level.in_(('A', 'B')),
                        admitted.c.venue_id != conference.id)
                .group_by(conference.abbr).all())


def validate_conference_associations(value, venues, paper_ids=None):
    """Validate compact references without treating a reference as a new paper."""
    if not isinstance(value, dict):
        raise ValueError('Invalid conference association index')
    all_ids = set()
    for abbr, years in value.items():
        if abbr not in venues or venues[abbr]['type'] != 'conf' or not isinstance(years, dict):
            raise ValueError('Unconfigured conference association')
        for year, ids in years.items():
            if (not isinstance(year, str) or not year.isascii() or not year.isdigit()
                    or len(year) != 4 or not 2000 <= int(year) <= 2100
                    or not isinstance(ids, list) or not ids
                    or any(type(pid) is not int or not 0 < pid <= 9007199254740991 for pid in ids)
                    or ids != sorted(set(ids))):
                raise ValueError('Invalid conference publication reference')
            all_ids.update(ids)
    if paper_ids is not None and not all_ids <= paper_ids:
        raise ValueError('Conference association references a non-public paper')
    return all_ids
