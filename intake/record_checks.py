from intake.outcomes import Disposition, TrialRecord, WorkClass


class InvalidDisposition(ValueError):
    """A trial record or one of its disposition fields is invalid."""


def valid_name(value):
    if not isinstance(value, str) or not value or value != value.strip() or '\x00' in value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def validate_disposition(work_class, disposition):
    if not isinstance(work_class, WorkClass) or not isinstance(disposition, Disposition):
        raise InvalidDisposition('expected a work class and a disposition')
    ordinary = disposition.ordinary_children
    special = disposition.special_children
    if type(ordinary) is not int or type(special) is not int or type(disposition.review) is not bool:
        raise InvalidDisposition('child counts must be integers and review must be a boolean')
    if work_class is WorkClass.ORDINARY:
        valid = (special == 0 and 0 <= ordinary <= 2) or (ordinary, special) == (0, 1)
    else:
        valid = ordinary == 0 and special in (0, 1)
    if not valid:
        raise InvalidDisposition(f'invalid children for {work_class.value}: {(ordinary, special)}')


def validate_trial_record(record):
    if not isinstance(record, TrialRecord):
        raise InvalidDisposition('expected a trial record')
    if not valid_name(record.record_id) or not valid_name(record.source_ref):
        raise InvalidDisposition('a trial record needs a valid record id and source reference')
    validate_disposition(record.work_class, record.disposition)
