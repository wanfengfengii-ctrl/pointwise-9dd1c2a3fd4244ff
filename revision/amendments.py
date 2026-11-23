from dataclasses import replace

from intake.record_checks import validate_disposition
from revision.count_audit import AuditResult, count_selected_sample
from revision.revisions import Revision, append_revision
from revision.selection import select_revision_sample


class RecordOutsideRevision(LookupError):
    """The original record is outside the selected parent's sample."""


def amend_revision(source, parent_id, record_id, disposition) -> tuple[Revision, AuditResult]:
    with source.transaction():
        parent_sample = select_revision_sample(source, parent_id)
        original = next((record for record in parent_sample.records if record.record_id == record_id), None)
        if original is None:
            raise RecordOutsideRevision(record_id)
        validate_disposition(original.work_class, disposition)
        revision = append_revision(source.db, parent_sample.revision, original.record_id, disposition)
        replacement = replace(original, disposition=disposition)
        updated_records = tuple(replacement if record is original else record for record in parent_sample.records)
        audit = count_selected_sample(replace(parent_sample, revision=revision, records=updated_records))
    return revision, audit
