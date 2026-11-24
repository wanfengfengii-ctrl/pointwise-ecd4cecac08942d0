from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lake.audit.order import ordered_report_pages
from lake.process.complete import ProcessedPage
from lake.publish.ledger import IssuedReport


@dataclass(frozen=True)
class ReportPageIndex:
    pages: Mapping[str, ProcessedPage]


def build_page_index(report: IssuedReport) -> ReportPageIndex:
    pages = ordered_report_pages(report)
    by_receipt = {page.provenance.receipt_id: page for page in pages}
    if len(by_receipt) != len(pages):
        raise ValueError('duplicate receipt in the frozen report')
    return ReportPageIndex(MappingProxyType(by_receipt))
