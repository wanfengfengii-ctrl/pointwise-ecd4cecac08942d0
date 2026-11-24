from dataclasses import dataclass
import sqlite3

from lake._storage import CommitProbe
from lake.catalog.scope import SettlementScope, expected_page_slots, resolve_scope, validate_scope_key
from lake.intake.recovery import pending_pages, retire_payload
from lake.intake.store import IntakeStore
from lake.process.complete import complete_page, find_processed_page, record_processed_pages
from lake.process.staging import stage_page
from lake.publish.completeness import MissingMaterial, assess_completeness
from lake.publish.ledger import IssuedReport, find_report, record_report
from lake.publish.storage import LakeStore
from lake.publish.totals import calculate_totals


@dataclass(frozen=True)
class PendingSettlement:
    report_id: str
    scope: SettlementScope
    missing: tuple[MissingMaterial, ...]


def _prepare_settlement(connection: sqlite3.Connection, intake: IntakeStore, report_id: str,
                        scope: SettlementScope) -> IssuedReport | PendingSettlement:
    processed = {}
    for slot in expected_page_slots(scope):
        page = find_processed_page(connection, *slot)
        if page is not None:
            processed[slot] = page
    remaining = (slot for slot in expected_page_slots(scope) if slot not in processed)
    waiting = {}
    new_pages = []
    for slot, raw in pending_pages(intake, remaining).items():
        staged = stage_page(connection, raw)
        if staged is None:
            waiting[slot] = raw
            continue
        page = complete_page(staged)
        processed[slot] = page
        new_pages.append(page)

    coverage = assess_completeness(scope, processed, waiting)
    if coverage.missing:
        return PendingSettlement(report_id, scope, coverage.missing)
    totals = calculate_totals(scope, coverage.pages)
    record_processed_pages(connection, new_pages)
    return record_report(connection, report_id, scope, coverage.pages, totals)


def settle(intake: IntakeStore, warehouse: LakeStore, report_id: str, kind: str, identifier: str,
           *, commit_probe: CommitProbe | None = None) -> IssuedReport | PendingSettlement:
    if type(report_id) is not str or not report_id.strip():
        raise ValueError('report identifier must be a nonblank string')
    validate_scope_key(kind, identifier)
    with warehouse.transaction(commit_probe) as connection:
        result = find_report(connection, report_id)
        if result is not None:
            if (kind, identifier) != (result.scope.kind, result.scope.identifier):
                raise ValueError(f'report is bound to another scope: {report_id}')
        else:
            scope = resolve_scope(connection, kind, identifier)
            result = _prepare_settlement(connection, intake, report_id, scope)

    if isinstance(result, IssuedReport):
        finish_handoffs(intake, warehouse, report_id)
    return result


def finish_handoffs(intake: IntakeStore, warehouse: LakeStore, report_id: str) -> None:
    with warehouse.connection() as connection:
        committed = find_report(connection, report_id)
    if committed is None:
        raise LookupError(f'unknown report: {report_id}')
    for page in committed.pages:
        retire_payload(intake, report_id, page.provenance.as_raw_page())
