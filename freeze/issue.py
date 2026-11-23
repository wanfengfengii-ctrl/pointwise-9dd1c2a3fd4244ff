from freeze.evidence import EvidenceProvenance, FrozenEvidence
from freeze.evidence_codec import compute_evidence_id
from freeze.frequency import build_joint_frequencies
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
