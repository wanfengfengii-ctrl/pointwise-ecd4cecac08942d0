from collections import defaultdict
from dataclasses import dataclass

from lake.audit.order import ordered_page_rows, ordered_report_pages
from lake.publish.ledger import IssuedReport


@dataclass(frozen=True)
class Reconciliation:
    run_id: str
    signed_kilograms: int
    recomputed_kilograms: int

    @property
    def matches(self) -> bool:
        return self.signed_kilograms == self.recomputed_kilograms


def reconcile_report(report: IssuedReport) -> tuple[Reconciliation, ...]:
    recomputed = defaultdict(int)
    for page in ordered_report_pages(report):
        for row in ordered_page_rows(page):
            recomputed[page.provenance.run_id] += row.kilograms
    signed = {total.run_id: total.kilograms for total in report.totals}
    return tuple(Reconciliation(run.run_id, signed[run.run_id], recomputed[run.run_id])
                 for run in report.scope.runs)
