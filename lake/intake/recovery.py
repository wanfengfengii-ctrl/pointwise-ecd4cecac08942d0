from collections.abc import Iterable, Mapping

from lake.intake.pages import RawPage, load_raw_page
from lake.intake.receipts import find_page_receipt, find_receipt, mark_archived
from lake.intake.store import IntakeStore


def pending_pages(store: IntakeStore, slots: Iterable[tuple[str, int]],
                  winners: Mapping[tuple[str, int], str] | None = None
                  ) -> dict[tuple[str, int], RawPage]:
    winners = winners or {}
    pages = {}
    with store.connection() as connection:
        # Read receipts and their payloads from the same intake snapshot.
        connection.execute('BEGIN')
        for run_id, page_number in slots:
            candidate_id = winners.get((run_id, page_number))
            if candidate_id is not None:
                record = find_receipt(connection, candidate_id)
            else:
                # Before a retest is granted the slot is settled from P.
                record = find_page_receipt(connection, run_id, page_number)
            if record is None or record.archived_report is not None:
                continue
            receipt = record.receipt
            page = load_raw_page(connection, receipt.receipt_id)
            if page is None or not receipt.matches(page):
                raise RuntimeError(f'confirmed source unavailable or inconsistent: {receipt.receipt_id}')
            pages[(run_id, page_number)] = page
    return pages


def retire_payload(store: IntakeStore, report_id: str, committed_source: RawPage) -> None:
    receipt_id = committed_source.receipt_id
    with store.transaction() as connection:
        record = find_receipt(connection, receipt_id)
        if record is None or not record.receipt.matches(committed_source):
            raise ValueError(f'committed source does not match intake receipt: {receipt_id}')
        if record.archived_report is not None:
            return
        original = load_raw_page(connection, receipt_id)
        if original != committed_source:
            raise ValueError(f'committed source does not match retained payload: {receipt_id}')
        mark_archived(connection, receipt_id, report_id)
        connection.execute('DELETE FROM raw_pages WHERE receipt_id = ?', (receipt_id,))
