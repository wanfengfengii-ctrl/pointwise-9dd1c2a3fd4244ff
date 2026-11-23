from fractions import Fraction

from freeze.evidence import EvidenceProvenance, FrozenEvidence
from freeze.evidence_codec import compute_evidence_id, decode_evidence
from freeze.frequency import build_joint_frequencies
from freeze.mix_codec import compute_mix_id, encode_mix_manifest
from revision.count_audit import audit_revision
from revision.revisions import RevisionNotFound


class IssuanceRejected(ValueError):
    """The requested revision cannot be issued as an offline evidence item."""


def freeze_revision(source, revision_id) -> FrozenEvidence:
    try:
        audit = audit_revision(source, revision_id)
        rows = build_joint_frequencies(audit)
    except (RevisionNotFound, ValueError) as exc:
        raise IssuanceRejected(f'cannot issue revision {revision_id!r}: {exc}') from exc
    evidence_id = compute_evidence_id(audit.source_id, audit.batch_id, audit.revision_id, rows)
    origin = EvidenceProvenance(evidence_id, audit.source_id, audit.batch_id, audit.revision_id)
    return FrozenEvidence(origin, rows)


def _mix_bound(value):
    if type(value) is bool or not isinstance(value, (int, Fraction)):
        raise IssuanceRejected('mixture bounds must be integers or fractions')
    return Fraction(value)


def _issued_payload(payload):
    try:
        return decode_evidence(payload)
    except ValueError as exc:
        raise IssuanceRejected(f'invalid evidence payload: {exc}') from exc


def freeze_mix(left_payload, right_payload, low, high):
    """Freeze two V1 evidence payloads into an ordered mixture manifest."""
    low, high = _mix_bound(low), _mix_bound(high)
    if not Fraction(0) <= low <= high <= Fraction(1):
        raise IssuanceRejected('mixture bounds must satisfy 0 <= low <= high <= 1')
    left = _issued_payload(left_payload)
    right = _issued_payload(right_payload)
    left_id, right_id = left.provenance.evidence_id, right.provenance.evidence_id
    return compute_mix_id(left_id, right_id, low, high), encode_mix_manifest(left_id, right_id, low, high)
