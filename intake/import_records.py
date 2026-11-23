import sqlite3

from intake.batches import BatchRejected as BatchRejected
from intake.batches import prepare_batch
from intake.source_store import SourceStore
from revision.revisions import Revision, create_root_revision


def record_batch(source: SourceStore, batch_id, records) -> Revision:
    """Accept all trial records and their starting revision in one transaction."""
    batch = prepare_batch(batch_id, records)
    try:
        with source.transaction():
            source.insert_batch(batch)
            revision = create_root_revision(source.db, batch.batch_id)
    except sqlite3.IntegrityError as exc:
        raise BatchRejected(f'batch or original record already exists: {batch_id}') from exc
    return revision
