from lake.catalog.scope import expected_page_slots
from lake.process.complete import ProcessedPage
from lake.process.decode import StandardRow
from lake.publish.ledger import IssuedReport


def ordered_report_pages(report: IssuedReport) -> tuple[ProcessedPage, ...]:
    by_slot = {(page.provenance.run_id, page.provenance.page_number): page
               for page in report.pages}
    slots = expected_page_slots(report.scope)
    if len(by_slot) != len(report.pages) or by_slot.keys() != set(slots):
        raise ValueError('recorded pages do not match the frozen scope')
    return tuple(by_slot[slot] for slot in slots)


def ordered_page_rows(page: ProcessedPage) -> tuple[StandardRow, ...]:
    return tuple(sorted(page.rows, key=lambda row: row.position))
