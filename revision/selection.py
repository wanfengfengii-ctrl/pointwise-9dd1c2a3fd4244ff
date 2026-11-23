from dataclasses import dataclass, replace

from intake.outcomes import TrialRecord
from intake.source_store import SourceStore
from revision.revisions import Revision, read_revision


@dataclass(frozen=True)
class SelectedSample:
    source_id: str
    revision: Revision
    records: tuple[TrialRecord, ...]


def select_revision_sample(source: SourceStore, revision_id) -> SelectedSample:
    selected = read_revision(source.db, revision_id)
    chain = []
    cursor = selected
    while cursor.parent_id is not None:
        chain.append(cursor)
        cursor = read_revision(source.db, cursor.parent_id)
    records = {record.record_id: record for record in source.read_batch_records(selected.batch_id)}
    for correction in reversed(chain):
        original = records[correction.record_id]
        records[correction.record_id] = replace(original, disposition=correction.replacement)
    return SelectedSample(source.source_id, selected, tuple(records.values()))
