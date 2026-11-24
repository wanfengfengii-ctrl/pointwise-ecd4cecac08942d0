from collections.abc import Mapping
from dataclasses import dataclass

from lake.catalog.revisions import BookRef
from lake.catalog.scope import SettlementScope, expected_page_slots
from lake.intake.pages import RawPage, validate_page
from lake.process.complete import ProcessedPage


@dataclass(frozen=True)
class MissingMaterial:
    kind: str
    run_id: str
    page_number: int
    receipt_id: str | None = None
    book: BookRef | None = None


@dataclass(frozen=True)
class Coverage:
    pages: tuple[ProcessedPage, ...]
    missing: tuple[MissingMaterial, ...]


def assess_completeness(scope: SettlementScope, processed: Mapping[tuple[str, int], ProcessedPage],
                        waiting: Mapping[tuple[str, int], RawPage]) -> Coverage:
    slots = expected_page_slots(scope)
    if not (processed.keys() | waiting.keys()) <= set(slots):
        raise ValueError('material falls outside the settlement scope')
    if processed.keys() & waiting.keys():
        raise ValueError('page cannot be both processed and waiting')
    runs = {run.run_id: run for run in scope.runs}
    pages = []
    missing = []
    used_receipts = set()
    for run_id, page_number in slots:
        slot = (run_id, page_number)
        page = processed.get(slot)
        if page is None:
            raw = waiting.get(slot)
            if raw is None:
                missing.append(MissingMaterial('page', run_id, page_number))
            else:
                validate_page(raw, runs[run_id])
                if raw.page_number != page_number:
                    raise ValueError('waiting source does not match its page slot')
                missing.append(MissingMaterial('revision', run_id, page_number,
                                               raw.receipt_id, raw.book))
            continue

        source = page.provenance
        validate_page(source.as_raw_page(), runs[run_id])
        if source.page_number != page_number or source.receipt_id in used_receipts:
            raise ValueError('processed source does not uniquely match its page slot')
        row_codes = tuple((row.position, row.raw_code) for row in page.rows)
        if row_codes != tuple(enumerate(source.codes, start=1)):
            raise ValueError('standard rows do not match the original code sequence')
        if any(row.receipt_id != source.receipt_id or type(row.kilograms) is not int
               for row in page.rows):
            raise ValueError('invalid standard row source or reading')
        used_receipts.add(source.receipt_id)
        pages.append(page)
    return Coverage(tuple(pages), tuple(missing))
