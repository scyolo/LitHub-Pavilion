from sqlalchemy import inspect

from app.bootstrap import initialize_database
from app.migrations import migrate_optional_dblp_stream
from app.models import Venue


def test_issn_only_journals_have_no_fabricated_dblp_stream(engine, session_factory):
    initialize_database(engine)
    with session_factory() as session:
        journals = session.query(Venue).filter(Venue.abbr.in_(("JASA", "JSLHR", "Cognition"))).all()
        assert len(journals) == 3
        assert all(v.dblp_stream is None and v.issn for v in journals)


def test_optional_dblp_migration_preserves_ids_references_indexes_and_custom_columns(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE venues (id INTEGER PRIMARY KEY, abbr TEXT UNIQUE NOT NULL, dblp_stream TEXT NOT NULL UNIQUE, custom_note TEXT)')
        connection.exec_driver_sql('CREATE TABLE papers (id INTEGER PRIMARY KEY, venue_id INTEGER REFERENCES venues(id))')
        connection.exec_driver_sql('CREATE INDEX custom_venue_note ON venues(custom_note)')
        connection.exec_driver_sql("INSERT INTO venues VALUES (17, 'AAAI', 'conf/aaai', 'keep')")
        connection.exec_driver_sql('INSERT INTO papers VALUES (9, 17)')
    migrate_optional_dblp_stream(engine)
    with engine.begin() as connection:
        assert connection.exec_driver_sql('SELECT * FROM venues').all() == [(17, 'AAAI', 'conf/aaai', 'keep')]
        assert connection.exec_driver_sql('SELECT venue_id FROM papers WHERE id=9').scalar() == 17
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        connection.exec_driver_sql("INSERT INTO venues VALUES (18, 'JASA', NULL, NULL)")
        connection.exec_driver_sql("INSERT INTO venues VALUES (19, 'JSLHR', NULL, NULL)")
    assert 'custom_venue_note' in {index['name'] for index in inspect(engine).get_indexes('venues')}
