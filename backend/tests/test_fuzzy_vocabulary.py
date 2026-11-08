"""Vocabulary reuse must never hide current or rolled-back title edits."""
from sqlalchemy import event

from app.services.fuzzy_terms import expand_tokens, title_vocabulary


def test_reuses_prepared_vocabulary_without_rescanning(db, engine, sample_paper):
    scans = []

    def capture(_conn, _cursor, sql, _params, _context, _many):
        if 'FROM paper_titles_vocab' in sql:
            scans.append(sql)

    event.listen(engine, 'before_cursor_execute', capture)
    try:
        first = title_vocabulary(db)
        second = title_vocabulary(db)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert second is first
    assert len(scans) == 1
    assert expand_tokens(['spec', 'dec'], first) == [['spec', 'specul'], ['dec', 'decod']]


def test_refreshes_after_local_title_commit(db, sample_paper):
    title_vocabulary(db)
    sample_paper.title_norm = 'quasar'
    db.commit()
    vocabulary = title_vocabulary(db)
    assert expand_tokens(['quas'], vocabulary) == [['quas', 'quasar']]
    assert expand_tokens(['spec'], vocabulary) == [['spec']]


def test_refreshes_after_another_connection_commits(db, session_factory, sample_paper):
    title_vocabulary(db)
    with session_factory() as writer:
        writer.connection().exec_driver_sql(
            'UPDATE papers SET title_norm = ? WHERE id = ?', ('quasar', sample_paper.id))
        writer.commit()
    assert expand_tokens(['quas'], title_vocabulary(db)) == [['quas', 'quasar']]


def test_uncommitted_vocabulary_does_not_survive_rollback(db, sample_paper):
    title_vocabulary(db)
    sample_paper.title_norm = 'quasar'
    assert expand_tokens(['quas'], title_vocabulary(db)) == [['quas', 'quasar']]
    db.rollback()
    restored = title_vocabulary(db)
    assert expand_tokens(['quas'], restored) == [['quas']]
    assert expand_tokens(['spec'], restored) == [['spec', 'specul']]
