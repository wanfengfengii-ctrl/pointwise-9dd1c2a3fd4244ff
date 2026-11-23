from dataclasses import dataclass

from freeze.evidence_store import EVIDENCE_SCHEMA, EvidenceStore, install_evidence_tables
from ledger_sql import initialize_database, write_transaction


_OFFLINE_KIND = 0x52504F31
_REPORT_SCHEMA = {
    'signed_reports': '''CREATE TABLE signed_reports (
        report_id INTEGER PRIMARY KEY,
        completion_probability TEXT NOT NULL,
        review_kind TEXT NOT NULL,
        review_value TEXT,
        evidence_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        batch_id TEXT NOT NULL,
        revision_id INTEGER NOT NULL,
        FOREIGN KEY (evidence_id, source_id, batch_id, revision_id)
            REFERENCES received_evidence(evidence_id, source_id, batch_id, revision_id),
        CHECK (
            (review_kind = 'finite' AND review_value IS NOT NULL)
            OR (review_kind IN ('not_applicable', 'infinite') AND review_value IS NULL)
        )
    )''',
}


@dataclass(frozen=True)
class ReportEntry:
    completion_probability: str
    review_kind: str
    review_value: str | None
    evidence_id: str
    source_id: str
    batch_id: str
    revision_id: int


class ReportStore:
    def __init__(self, db):
        self.db = db
        self.evidence = EvidenceStore(db)

    def commit_report(self, entry: ReportEntry) -> int:
        with write_transaction(self.db):
            cursor = self.db.execute(
                '''INSERT INTO signed_reports
                   (completion_probability, review_kind, review_value, evidence_id, source_id, batch_id, revision_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    entry.completion_probability, entry.review_kind, entry.review_value,
                    entry.evidence_id, entry.source_id, entry.batch_id, entry.revision_id,
                ),
            )
            report_id = cursor.lastrowid
        return report_id

    def read_report(self, report_id) -> ReportEntry | None:
        row = self.db.execute(
            '''SELECT completion_probability, review_kind, review_value,
                      evidence_id, source_id, batch_id, revision_id
               FROM signed_reports WHERE report_id = ?''',
            (report_id,),
        ).fetchone()
        return None if row is None else ReportEntry(*row)


def _install(db):
    install_evidence_tables(db)
    for statement in _REPORT_SCHEMA.values():
        db.execute(statement)


def initialize_offline(connection) -> ReportStore:
    initialize_database(connection, _OFFLINE_KIND, EVIDENCE_SCHEMA | _REPORT_SCHEMA, _install)
    return ReportStore(connection)
