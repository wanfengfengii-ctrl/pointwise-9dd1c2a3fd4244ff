from dataclasses import dataclass
import sqlite3

from ledger_sql import write_transaction


EVIDENCE_SCHEMA = {
    'received_evidence': '''CREATE TABLE received_evidence (
        evidence_id TEXT PRIMARY KEY NOT NULL,
        payload BLOB NOT NULL,
        source_id TEXT NOT NULL,
        batch_id TEXT NOT NULL,
        revision_id INTEGER NOT NULL CHECK (revision_id > 0),
        UNIQUE (evidence_id, source_id, batch_id, revision_id)
    )''',
}


@dataclass(frozen=True)
class ReceivedEntry:
    evidence_id: str
    payload: bytes
    source_id: str
    batch_id: str
    revision_id: int


def install_evidence_tables(db):
    for statement in EVIDENCE_SCHEMA.values():
        db.execute(statement)


class EvidenceStore:
    def __init__(self, db):
        self.db = db

    def store_received(self, entry: ReceivedEntry) -> str:
        with write_transaction(self.db):
            existing = self.find_received(entry.evidence_id)
            if existing is None:
                self.db.execute(
                    '''INSERT INTO received_evidence
                       (evidence_id, payload, source_id, batch_id, revision_id)
                       VALUES (?, ?, ?, ?, ?)''',
                    (entry.evidence_id, entry.payload, entry.source_id, entry.batch_id, entry.revision_id),
                )
            elif existing != entry:
                raise sqlite3.IntegrityError('received identity already refers to different evidence')
        return entry.evidence_id

    def find_received(self, evidence_id) -> ReceivedEntry | None:
        row = self.db.execute(
            '''SELECT evidence_id, payload, source_id, batch_id, revision_id
               FROM received_evidence WHERE evidence_id = ?''',
            (evidence_id,),
        ).fetchone()
        return None if row is None else ReceivedEntry(*row)
