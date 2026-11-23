import sqlite3

from freeze.evidence import EvidenceProvenance, FrozenEvidence
from freeze.evidence_codec import decode_evidence
from freeze.evidence_store import EvidenceStore, ReceivedEntry
from freeze.mix_codec import decode_mix_manifest
from handover.report_store import MixtureEntry, ReportStore
from intake.record_checks import valid_name
from ledger_sql import is_row_id


class ReceiptRejected(ValueError):
    """The evidence is invalid, unavailable, or bound to another provenance."""


def _checked_evidence(payload, expected):
    if (
        not isinstance(expected, EvidenceProvenance)
        or not is_row_id(expected.revision_id)
        or not all(valid_name(value) for value in (expected.evidence_id, expected.source_id, expected.batch_id))
    ):
        raise ReceiptRejected('expected the complete evidence provenance')
    try:
        evidence = decode_evidence(payload)
    except ValueError as exc:
        raise ReceiptRejected(str(exc)) from exc
    if evidence.provenance != expected:
        raise ReceiptRejected('received evidence does not match the handover provenance')
    return evidence


def receive_evidence(store: EvidenceStore, payload: bytes, expected: EvidenceProvenance) -> str:
    evidence = _checked_evidence(payload, expected)
    origin = evidence.provenance
    entry = ReceivedEntry(origin.evidence_id, payload, origin.source_id, origin.batch_id, origin.revision_id)
    try:
        return store.store_received(entry)
    except sqlite3.Error as exc:
        raise ReceiptRejected('could not store the received evidence') from exc


def load_received_evidence(store: EvidenceStore, evidence_id: str) -> FrozenEvidence:
    if not valid_name(evidence_id):
        raise ReceiptRejected('invalid received evidence id')
    try:
        entry = store.find_received(evidence_id)
    except sqlite3.Error as exc:
        raise ReceiptRejected('could not read the received evidence') from exc
    if entry is None:
        raise ReceiptRejected(f'unknown received evidence: {evidence_id}')
    expected = EvidenceProvenance(evidence_id, entry.source_id, entry.batch_id, entry.revision_id)
    return _checked_evidence(entry.payload, expected)


def _checked_payload(payload):
    try:
        return decode_evidence(payload)
    except ValueError as exc:
        raise ReceiptRejected(str(exc)) from exc


def _received_entry(evidence, payload):
    origin = evidence.provenance
    return ReceivedEntry(origin.evidence_id, payload, origin.source_id, origin.batch_id, origin.revision_id)


def receive_mix(offline: ReportStore, expected_id, manifest, left_payload, right_payload) -> str:
    """Verify a mixture manifest against its id and both V1 parents, then store it."""
    if not valid_name(expected_id):
        raise ReceiptRejected('expected a valid mixture id')
    try:
        mix_id, left_id, right_id, low, high = decode_mix_manifest(manifest)
    except ValueError as exc:
        raise ReceiptRejected(str(exc)) from exc
    if mix_id != expected_id:
        raise ReceiptRejected('received manifest does not match the expected mixture id')
    left = _checked_payload(left_payload)
    right = _checked_payload(right_payload)
    if (left.provenance.evidence_id, right.provenance.evidence_id) != (left_id, right_id):
        raise ReceiptRejected('received evidence does not match the ordered manifest parents')
    mixture = MixtureEntry(mix_id, manifest, left_id, right_id, low, high)
    parents = (_received_entry(left, left_payload), _received_entry(right, right_payload))
    try:
        return offline.store_mixture(mixture, parents)
    except sqlite3.Error as exc:
        raise ReceiptRejected('could not store the received mixture') from exc
