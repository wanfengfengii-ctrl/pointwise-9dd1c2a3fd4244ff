from contextlib import closing
import json
from pathlib import Path
import sqlite3

from freeze.evidence_codec import encode_evidence
from freeze.issue import freeze_revision
from freeze.receive import receive_evidence
from handover.publish import sign_report
from handover.report_store import initialize_offline
from handover.reports import get_report
from intake.import_records import record_batch
from intake.outcomes import Disposition, TrialRecord, WorkClass
from intake.source_store import initialize_source


_CASES = Path(__file__).resolve().parent / "samples" / "mix_calibrations.json"
_SIDES = ("left", "right")


def _load_cases():
    return json.loads(_CASES.read_text(encoding="utf-8"))


def _issue(source, name, side, calibration, copies):
    batch_id = f"{name}-{side}-x{copies}"
    records = []
    for kind in WorkClass:
        for group, (ordinary, special, review, count) in enumerate(calibration[kind.value]):
            disposition = Disposition(ordinary, special, review)
            for index in range(count * copies):
                record_id = f"{batch_id}/{kind.value}/{group}/{index}"
                records.append(TrialRecord(record_id, f"bench/{record_id}", kind, disposition))
    revision = record_batch(source, batch_id, records)
    return freeze_revision(source, revision.revision_id)


def issue_pair(source, name, right_copies=1):
    case = _load_cases()[name]
    return (_issue(source, name, "left", case["left"], 1),
            _issue(source, name, "right", case["right"], right_copies))


def _verify_endpoints(name, case):
    with closing(sqlite3.connect(":memory:")) as offline_db:
        offline = initialize_offline(offline_db)
        with closing(sqlite3.connect(":memory:")) as source_db:
            source = initialize_source(source_db)
            receipts = []
            for side in _SIDES:
                piece = _issue(source, name, side, case[side], 1)
                receipts.append(receive_evidence(offline.evidence, encode_evidence(piece), piece.provenance))
        for side, receipt, expected in zip(_SIDES, receipts, case["v1_points"], strict=True):
            signed = sign_report(offline, receipt)
            review = signed.result.review
            actual = [str(signed.result.completion_probability), review.kind.value,
                      None if review.value is None else str(review.value)]
            if actual != expected or get_report(offline, signed.report_id) != signed:
                raise AssertionError((name, side, expected, actual))
            print(json.dumps({"case": name, "side": side, "completion_probability": actual[0],
                              "review_kind": actual[1], "review_value": actual[2]}))


def main():
    for name, case in _load_cases().items():
        _verify_endpoints(name, case)


if __name__ == "__main__":
    main()
