from dataclasses import dataclass

from lake.audit.index import ReportPageIndex
from lake.audit.order import ordered_page_rows
from lake.process.decode import StandardRow
from lake.process.provenance import PageProvenance


@dataclass(frozen=True)
class PageTrace:
    provenance: PageProvenance
    rows: tuple[StandardRow, ...]


def trace_page(index: ReportPageIndex, receipt_id: str) -> PageTrace:
    page = index.pages.get(receipt_id)
    if page is None:
        raise LookupError(f'receipt outside the report: {receipt_id}')
    return PageTrace(page.provenance, ordered_page_rows(page))
