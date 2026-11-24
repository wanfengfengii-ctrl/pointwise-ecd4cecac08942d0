from collections.abc import Callable
import sqlite3

from lake._storage import CommitProbe
from lake.catalog.runs import RunRecord
from lake.intake.pages import RawPage, load_raw_page, save_raw_page, validate_page
from lake.intake.receipts import Receipt, ReceiptRecord, find_page_receipt, find_receipt, record_receipt
from lake.intake.store import IntakeStore


ArchivedSource = Callable[[str, str], RawPage | None]


def match_received_page(connection: sqlite3.Connection, record: ReceiptRecord,
                        page: RawPage, archived_source: ArchivedSource) -> bool:
    receipt_id = record.receipt.receipt_id
    if record.archived_report is None:
        original = load_raw_page(connection, receipt_id)
    else:
        original = archived_source(record.archived_report, receipt_id)
    if original is None or not record.receipt.matches(original):
        raise RuntimeError(f'confirmed source unavailable or inconsistent: {receipt_id}')
    return original == page


def receive_page(store: IntakeStore, run: RunRecord, page: RawPage,
                 archived_source: ArchivedSource, *, commit_probe: CommitProbe | None = None) -> Receipt:
    validate_page(page, run)
    with store.transaction(commit_probe) as connection:
        previous = find_receipt(connection, page.receipt_id)
        if previous is not None:
            if not match_received_page(connection, previous, page, archived_source):
                raise ValueError(f'receipt already binds a different source: {page.receipt_id}')
            receipt = previous.receipt
        else:
            if find_page_receipt(connection, page.run_id, page.page_number) is not None:
                raise ValueError('page slot already belongs to another receipt')
            receipt = record_receipt(connection, page)
            save_raw_page(connection, page)
    return receipt
