from dataclasses import dataclass

from intake.outcomes import TrialRecord
from intake.record_checks import valid_name, validate_trial_record


class BatchRejected(ValueError):
    """The trial batch could not be admitted as a whole."""


@dataclass(frozen=True)
class TrialBatch:
    batch_id: str
    records: tuple[TrialRecord, ...]


def prepare_batch(batch_id, records):
    if not valid_name(batch_id):
        raise BatchRejected('a batch needs a valid batch id')
    try:
        snapshot = tuple(records)
    except TypeError as exc:
        raise BatchRejected('records must be an iterable of trial records') from exc
    if not snapshot:
        raise BatchRejected('a batch needs at least one record')
    seen = set()
    for record in snapshot:
        validate_trial_record(record)
        if record.record_id in seen:
            raise BatchRejected(f'duplicate record in batch: {record.record_id}')
        seen.add(record.record_id)
    return TrialBatch(batch_id, snapshot)
