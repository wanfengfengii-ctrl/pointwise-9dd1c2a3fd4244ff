from dataclasses import dataclass
from fractions import Fraction
import sqlite3

from freeze.evidence_store import EVIDENCE_SCHEMA, EvidenceStore, ReceivedEntry, install_evidence_tables
from ledger_sql import initialize_database, write_transaction


_OFFLINE_KIND = 0x52504F31
REPORT_SCHEMA = {
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
MIXTURE_SCHEMA = {
    'received_mixtures': '''CREATE TABLE received_mixtures (
        mix_id TEXT PRIMARY KEY NOT NULL,
        manifest BLOB NOT NULL,
        left_id TEXT NOT NULL REFERENCES received_evidence(evidence_id),
        right_id TEXT NOT NULL REFERENCES received_evidence(evidence_id),
        low TEXT NOT NULL,
        high TEXT NOT NULL
    )''',
    'mix_reports': '''CREATE TABLE mix_reports (
        report_id INTEGER PRIMARY KEY,
        mix_id TEXT NOT NULL REFERENCES received_mixtures(mix_id),
        passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
        completion_min TEXT NOT NULL,
        review_max TEXT NOT NULL
    )''',
}
LEGACY_OFFLINE_SCHEMA = EVIDENCE_SCHEMA | REPORT_SCHEMA
OFFLINE_SCHEMA = LEGACY_OFFLINE_SCHEMA | MIXTURE_SCHEMA


@dataclass(frozen=True)
class ReportEntry:
    completion_probability: str
    review_kind: str
    review_value: str | None
    evidence_id: str
    source_id: str
    batch_id: str
    revision_id: int


@dataclass(frozen=True)
class MixtureEntry:
    mix_id: str
    manifest: bytes
    left_id: str
    right_id: str
    low: Fraction
    high: Fraction


@dataclass(frozen=True)
class MixReportEntry:
    mix_id: str
    passed: int
    completion_min: str
    review_max: str


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

    def store_mixture(self, mixture: MixtureEntry, parents: tuple[ReceivedEntry, ReceivedEntry]) -> str:
        """Store both parent evidence items and the manifest in one transaction."""
        with write_transaction(self.db):
            for entry in parents:
                existing = self.evidence.find_received(entry.evidence_id)
                if existing is None:
                    self.db.execute(
                        '''INSERT INTO received_evidence
                           (evidence_id, payload, source_id, batch_id, revision_id)
                           VALUES (?, ?, ?, ?, ?)''',
                        (entry.evidence_id, entry.payload, entry.source_id, entry.batch_id, entry.revision_id),
                    )
                elif existing != entry:
                    raise sqlite3.IntegrityError('received identity already refers to different evidence')
            current = self.find_mixture(mixture.mix_id)
            if current is None:
                self.db.execute(
                    '''INSERT INTO received_mixtures (mix_id, manifest, left_id, right_id, low, high)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (
                        mixture.mix_id, mixture.manifest, mixture.left_id, mixture.right_id,
                        str(mixture.low), str(mixture.high),
                    ),
                )
            elif current != mixture:
                raise sqlite3.IntegrityError('mixture identity already refers to a different manifest')
        return mixture.mix_id

    def find_mixture(self, mix_id) -> MixtureEntry | None:
        row = self.db.execute(
            '''SELECT mix_id, manifest, left_id, right_id, low, high
               FROM received_mixtures WHERE mix_id = ?''',
            (mix_id,),
        ).fetchone()
        if row is None:
            return None
        mix_id, manifest, left_id, right_id, low, high = row
        return MixtureEntry(mix_id, manifest, left_id, right_id, Fraction(low), Fraction(high))

    def commit_mix_report(self, entry: MixReportEntry) -> int:
        with write_transaction(self.db):
            cursor = self.db.execute(
                '''INSERT INTO mix_reports (mix_id, passed, completion_min, review_max)
                   VALUES (?, ?, ?, ?)''',
                (entry.mix_id, entry.passed, entry.completion_min, entry.review_max),
            )
            report_id = cursor.lastrowid
        return report_id

    def read_mix_report(self, report_id) -> MixReportEntry | None:
        row = self.db.execute(
            '''SELECT mix_id, passed, completion_min, review_max
               FROM mix_reports WHERE report_id = ?''',
            (report_id,),
        ).fetchone()
        return None if row is None else MixReportEntry(*row)


def _install(db):
    install_evidence_tables(db)
    for statement in (REPORT_SCHEMA | MIXTURE_SCHEMA).values():
        db.execute(statement)


def _schema_of(db):
    rows = db.execute(
        'SELECT name, sql FROM sqlite_schema WHERE substr(name, 1, 7) <> ?',
        ('sqlite_',),
    )
    return {name: sql.split() for name, sql in rows}


def _upgrade_legacy(connection):
    """Add the mixture tables to a ledger written by the V1-only version."""
    if connection.in_transaction:
        return
    try:
        current_id = connection.execute('PRAGMA application_id').fetchone()[0]
        version = connection.execute('PRAGMA user_version').fetchone()[0]
    except sqlite3.Error:
        return
    if (current_id, version) != (_OFFLINE_KIND, 1):
        return
    legacy = {name: sql.split() for name, sql in LEGACY_OFFLINE_SCHEMA.items()}
    if _schema_of(connection) != legacy:
        return
    with write_transaction(connection):
        for statement in MIXTURE_SCHEMA.values():
            connection.execute(statement)


def initialize_offline(connection) -> ReportStore:
    _upgrade_legacy(connection)
    initialize_database(connection, _OFFLINE_KIND, OFFLINE_SCHEMA, _install)
    return ReportStore(connection)
