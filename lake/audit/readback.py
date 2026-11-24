from dataclasses import dataclass

from lake.audit.index import build_page_index
from lake.audit.order import ordered_page_rows, ordered_report_pages
from lake.audit.reconcile import Reconciliation, reconcile_report
from lake.audit.trace import trace_page
from lake.catalog.scope import SettlementScope
from lake.process.decode import StandardRow
from lake.process.provenance import PageProvenance
from lake.publish.ledger import PublicationReceipt, find_report
from lake.publish.storage import LakeStore
from lake.publish.totals import RunTotal


@dataclass(frozen=True)
class ReportView:
    scope: SettlementScope
    receipt: PublicationReceipt
    pages: tuple[PageProvenance, ...]
    rows: tuple[StandardRow, ...]
    totals: tuple[RunTotal, ...]
    reconciliation: tuple[Reconciliation, ...]


def read_report(warehouse: LakeStore, report_id: str, receipt_id: str | None = None) -> ReportView:
    if type(report_id) is not str or not report_id.strip():
        raise ValueError('report identifier must be a nonblank string')
    if receipt_id is not None and (type(receipt_id) is not str or not receipt_id.strip()):
        raise ValueError('receipt identifier must be a nonblank string')
    with warehouse.connection() as connection:
        report = find_report(connection, report_id)
    if report is None:
        raise LookupError(f'unknown report: {report_id}')

    if receipt_id is None:
        pages = ordered_report_pages(report)
        return ReportView(report.scope, report.receipt, tuple(page.provenance for page in pages),
                          tuple(row for page in pages for row in ordered_page_rows(page)),
                          report.totals, reconcile_report(report))

    trace = trace_page(build_page_index(report), receipt_id)
    run_id = trace.provenance.run_id
    return ReportView(report.scope, report.receipt, (trace.provenance,), trace.rows,
                      tuple(total for total in report.totals if total.run_id == run_id),
                      tuple(check for check in reconcile_report(report) if check.run_id == run_id))
