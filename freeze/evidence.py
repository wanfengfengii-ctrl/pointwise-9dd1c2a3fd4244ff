from dataclasses import dataclass

from freeze.frequency import JointFrequency


@dataclass(frozen=True)
class EvidenceProvenance:
    evidence_id: str
    source_id: str
    batch_id: str
    revision_id: int


@dataclass(frozen=True)
class FrozenEvidence:
    provenance: EvidenceProvenance
    rows: tuple[JointFrequency, ...]
