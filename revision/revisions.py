from dataclasses import dataclass

from intake.outcomes import Disposition
from ledger_sql import is_row_id


REVISION_SCHEMA = {
    'revisions': '''CREATE TABLE revisions (
        revision_id INTEGER PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES trial_batches(batch_id),
        parent_id INTEGER,
        record_id TEXT,
        ordinary_children INTEGER,
        special_children INTEGER,
        review INTEGER,
        UNIQUE (revision_id, batch_id),
        FOREIGN KEY (parent_id, batch_id) REFERENCES revisions(revision_id, batch_id),
        FOREIGN KEY (batch_id, record_id) REFERENCES trial_records(batch_id, record_id),
        CHECK (
            (parent_id IS NULL AND record_id IS NULL AND ordinary_children IS NULL
             AND special_children IS NULL AND review IS NULL)
            OR
            (parent_id IS NOT NULL AND parent_id < revision_id AND record_id IS NOT NULL
             AND ordinary_children IS NOT NULL AND special_children IS NOT NULL
             AND review IS NOT NULL AND review IN (0, 1))
        )
    )''',
    'revision_root': '''CREATE UNIQUE INDEX revision_root ON revisions(batch_id) WHERE parent_id IS NULL''',
}


class RevisionNotFound(LookupError):
    """There is no revision with the requested id in the source ledger."""


@dataclass(frozen=True)
class Revision:
    revision_id: int
    batch_id: str
    parent_id: int | None
    record_id: str | None = None
    replacement: Disposition | None = None


def install_revision_tables(db):
    for statement in REVISION_SCHEMA.values():
        db.execute(statement)


def create_root_revision(db, batch_id):
    cursor = db.execute('INSERT INTO revisions (batch_id) VALUES (?)', (batch_id,))
    return Revision(cursor.lastrowid, batch_id, None)


def append_revision(db, parent: Revision, record_id, disposition: Disposition):
    cursor = db.execute(
        '''INSERT INTO revisions
           (batch_id, parent_id, record_id, ordinary_children, special_children, review)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (
            parent.batch_id, parent.revision_id, record_id, disposition.ordinary_children,
            disposition.special_children, int(disposition.review),
        ),
    )
    return Revision(cursor.lastrowid, parent.batch_id, parent.revision_id, record_id, disposition)


def read_revision(db, revision_id):
    if not is_row_id(revision_id):
        raise RevisionNotFound(revision_id)
    row = db.execute(
        '''SELECT batch_id, parent_id, record_id, ordinary_children, special_children, review
           FROM revisions WHERE revision_id = ?''',
        (revision_id,),
    ).fetchone()
    if row is None:
        raise RevisionNotFound(revision_id)
    batch_id, parent_id, record_id, ordinary, special, review = row
    replacement = None if parent_id is None else Disposition(ordinary, special, bool(review))
    return Revision(revision_id, batch_id, parent_id, record_id, replacement)
