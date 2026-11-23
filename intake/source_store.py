from uuid import uuid4

from intake.batches import TrialBatch
from intake.outcomes import Disposition, TrialRecord, WorkClass
from intake.record_checks import valid_name
from ledger_sql import StoreInitializationError, initialize_database, write_transaction
from revision.revisions import REVISION_SCHEMA, install_revision_tables


_SOURCE_KIND = 0x52505331
_SOURCE_SCHEMA = {
    'source_identity': '''CREATE TABLE source_identity (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        source_id TEXT NOT NULL
    )''',
    'trial_batches': '''CREATE TABLE trial_batches (
        batch_id TEXT PRIMARY KEY NOT NULL
    )''',
    'trial_records': '''CREATE TABLE trial_records (
        record_id TEXT PRIMARY KEY NOT NULL,
        batch_id TEXT NOT NULL REFERENCES trial_batches(batch_id),
        source_ref TEXT NOT NULL,
        work_class TEXT NOT NULL CHECK (work_class IN ('ordinary', 'special')),
        ordinary_children INTEGER NOT NULL,
        special_children INTEGER NOT NULL,
        review INTEGER NOT NULL CHECK (review IN (0, 1)),
        UNIQUE (batch_id, record_id)
    )''',
}


class SourceStore:
    def __init__(self, db, source_id):
        self.db = db
        self.source_id = source_id

    def transaction(self):
        return write_transaction(self.db)

    def insert_batch(self, batch: TrialBatch):
        self.db.execute('INSERT INTO trial_batches (batch_id) VALUES (?)', (batch.batch_id,))
        values = (
            (
                record.record_id, batch.batch_id, record.source_ref, record.work_class.value,
                record.disposition.ordinary_children, record.disposition.special_children,
                int(record.disposition.review),
            )
            for record in batch.records
        )
        self.db.executemany(
            '''INSERT INTO trial_records
               (record_id, batch_id, source_ref, work_class, ordinary_children, special_children, review)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            values,
        )

    def read_batch_records(self, batch_id):
        rows = self.db.execute(
            '''SELECT record_id, source_ref, work_class, ordinary_children, special_children, review
               FROM trial_records WHERE batch_id = ? ORDER BY record_id''',
            (batch_id,),
        )
        return tuple(
            TrialRecord(record_id, origin, WorkClass(kind), Disposition(ordinary, special, bool(review)))
            for record_id, origin, kind, ordinary, special, review in rows
        )


def _install(db):
    for statement in _SOURCE_SCHEMA.values():
        db.execute(statement)
    install_revision_tables(db)
    db.execute('INSERT INTO source_identity VALUES (1, ?)', (uuid4().hex,))


def initialize_source(connection) -> SourceStore:
    initialize_database(connection, _SOURCE_KIND, _SOURCE_SCHEMA | REVISION_SCHEMA, _install)
    row = connection.execute('SELECT source_id FROM source_identity WHERE singleton = 1').fetchone()
    if row is None or not valid_name(row[0]):
        raise StoreInitializationError('source ledger has no valid identity')
    return SourceStore(connection, row[0])
