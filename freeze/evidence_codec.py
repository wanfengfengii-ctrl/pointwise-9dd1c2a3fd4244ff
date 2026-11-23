from fractions import Fraction
from hashlib import sha256
import json

from freeze.evidence import EvidenceProvenance, FrozenEvidence
from freeze.frequency import JointFrequency, validate_joint_frequencies
from intake.outcomes import Disposition, WorkClass
from intake.record_checks import valid_name
from ledger_sql import is_row_id


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _body(source_id, batch_id, revision_id, rows):
    return {
        'version': 1,
        'source_id': source_id,
        'batch_id': batch_id,
        'revision_id': revision_id,
        'rows': [
            {
                'work_class': row.work_class.value,
                'ordinary_children': row.disposition.ordinary_children,
                'special_children': row.disposition.special_children,
                'review': row.disposition.review,
                'count': row.count,
                'frequency': str(row.frequency),
            }
            for row in rows
        ],
    }


def compute_evidence_id(source_id, batch_id, revision_id, rows):
    return sha256(_canonical(_body(source_id, batch_id, revision_id, rows))).hexdigest()


def encode_evidence(evidence: FrozenEvidence) -> bytes:
    origin = evidence.provenance
    body = _body(origin.source_id, origin.batch_id, origin.revision_id, evidence.rows)
    return _canonical({'id': origin.evidence_id, 'body': body})


def _parse_row(row):
    frequency = row['frequency']
    if not isinstance(frequency, str):
        raise ValueError('joint frequencies must use rational strings')
    return JointFrequency(
        WorkClass(row['work_class']),
        Disposition(row['ordinary_children'], row['special_children'], row['review']),
        row['count'], Fraction(frequency),
    )


def decode_evidence(payload: bytes) -> FrozenEvidence:
    if type(payload) is not bytes or not payload:
        raise ValueError('expected a nonempty evidence byte string')
    try:
        envelope = json.loads(payload)
        body = envelope['body']
        source_id, batch_id, revision_id = body['source_id'], body['batch_id'], body['revision_id']
        if type(body['version']) is not int or body['version'] != 1 or type(body['rows']) is not list:
            raise ValueError('unsupported evidence version or row format')
        if not valid_name(source_id) or not valid_name(batch_id) or not is_row_id(revision_id):
            raise ValueError('invalid evidence provenance')
        rows = tuple(_parse_row(row) for row in body['rows'])
        validate_joint_frequencies(rows)
        evidence_id = compute_evidence_id(source_id, batch_id, revision_id, rows)
        if envelope['id'] != evidence_id:
            raise ValueError('evidence identity does not match its body')
        evidence = FrozenEvidence(EvidenceProvenance(evidence_id, source_id, batch_id, revision_id), rows)
        if encode_evidence(evidence) != payload:
            raise ValueError('evidence is not in its canonical encoding')
        return evidence
    except (KeyError, TypeError, ValueError, ZeroDivisionError, RecursionError) as exc:
        raise ValueError(f'invalid evidence: {exc}') from exc
