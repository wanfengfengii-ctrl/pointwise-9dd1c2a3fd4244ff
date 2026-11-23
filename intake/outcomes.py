from dataclasses import dataclass
from enum import StrEnum


class WorkClass(StrEnum):
    ORDINARY = 'ordinary'
    SPECIAL = 'special'


@dataclass(frozen=True, order=True)
class Disposition:
    ordinary_children: int
    special_children: int
    review: bool


@dataclass(frozen=True)
class TrialRecord:
    record_id: str
    source_ref: str
    work_class: WorkClass
    disposition: Disposition
