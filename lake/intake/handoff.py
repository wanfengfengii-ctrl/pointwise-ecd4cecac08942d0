from collections.abc import Callable
import sqlite3

from lake._storage import CommitProbe
from lake.catalog.runs import RunRecord
from lake.intake.pages import RawPage, load_raw_page, save_raw_page, validate_page
from lake.intake.receipts import (
    Receipt,
    ReceiptRecord,
    find_candidate_for_original,
    find_page_receipt,
    find_receipt,
    record_receipt,
)
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


def _validate_binding(original: ReceiptRecord | None, page: RawPage,
                      replaces: str) -> None:
    if original is None:
        raise ValueError(f'retest must replace an accepted original page: {replaces}')
    if original.replaces is not None:
        raise ValueError(f'retest binding target is itself a candidate: {replaces}')
    target = original.receipt
    if target.device != page.device or target.run_id != page.run_id \
            or target.page_number != page.page_number:
        raise ValueError('retest page must share the original device, run and page slot')


def receive_page(store: IntakeStore, run: RunRecord, page: RawPage,
                 archived_source: ArchivedSource, *, replaces: str | None = None,
                 commit_probe: CommitProbe | None = None) -> Receipt:
    validate_page(page, run)
    if replaces is not None and (type(replaces) is not str or not replaces.strip()):
        raise ValueError('replaces must be a nonblank original receipt id or None')
    with store.transaction(commit_probe) as connection:
        previous = find_receipt(connection, page.receipt_id)
        if previous is not None:
            if not match_received_page(connection, previous, page, archived_source):
                raise ValueError(f'receipt already binds a different source: {page.receipt_id}')
            if previous.replaces != replaces:
                raise ValueError(
                    f'receipt is already bound to another retest link: {page.receipt_id}')
            return previous.receipt

        if replaces is None:
            if find_page_receipt(connection, page.run_id, page.page_number) is not None:
                raise ValueError('page slot already belongs to another receipt')
        else:
            original = find_receipt(connection, replaces)
            _validate_binding(original, page, replaces)
            if find_candidate_for_original(connection, replaces) is not None:
                raise ValueError(f'original page already has a retest candidate: {replaces}')

        try:
            receipt = record_receipt(connection, page, replaces)
            save_raw_page(connection, page)
        except sqlite3.IntegrityError as exc:
            raise ValueError('page slot or retest binding is already occupied') from exc
    return receipt
