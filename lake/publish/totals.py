from collections.abc import Iterable
from dataclasses import dataclass

from lake.catalog.scope import SettlementScope
from lake.process.complete import ProcessedPage


@dataclass(frozen=True)
class RunTotal:
    run_id: str
    kilograms: int


def calculate_totals(scope: SettlementScope, pages: Iterable[ProcessedPage]) -> tuple[RunTotal, ...]:
    kilograms = {run.run_id: 0 for run in scope.runs}
    for page in pages:
        kilograms[page.provenance.run_id] += sum(row.kilograms for row in page.rows)
    return tuple(RunTotal(run_id, total) for run_id, total in kilograms.items())
