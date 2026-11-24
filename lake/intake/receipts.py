from dataclasses import dataclass
import sqlite3

from lake.intake.pages import RawPage, page_fingerprint


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    device: str
    run_id: str
    page_number: int
    fingerprint: str

    def matches(self, page: RawPage) -> bool:
        return (self.receipt_id == page.receipt_id and self.device == page.device
                and self.run_id == page.run_id and self.page_number == page.page_number
                and self.fingerprint == page_fingerprint(page))


@dataclass(frozen=True)
class ReceiptRecord:
    receipt: Receipt
    archived_report: str | None


def initialize_receipts(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id TEXT PRIMARY KEY,
            device TEXT NOT NULL,
            run_id TEXT NOT NULL,
            page_number TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            archived_report TEXT,
            UNIQUE (run_id, page_number)
        )
    ''')


def _record_from_row(row) -> ReceiptRecord | None:
    if row is None:
        return None
    receipt = Receipt(row['receipt_id'], row['device'], row['run_id'],
                      int(row['page_number'], 16), row['fingerprint'])
    return ReceiptRecord(receipt, row['archived_report'])


def find_receipt(connection: sqlite3.Connection, receipt_id: str) -> ReceiptRecord | None:
    row = connection.execute('SELECT * FROM receipts WHERE receipt_id = ?', (receipt_id,)).fetchone()
    return _record_from_row(row)


def find_page_receipt(connection: sqlite3.Connection, run_id: str,
                      page_number: int) -> ReceiptRecord | None:
    row = connection.execute(
        'SELECT * FROM receipts WHERE run_id = ? AND page_number = ?',
        (run_id, hex(page_number)),
    ).fetchone()
    return _record_from_row(row)


def record_receipt(connection: sqlite3.Connection, page: RawPage) -> Receipt:
    fingerprint = page_fingerprint(page)
    connection.execute('''
        INSERT INTO receipts (receipt_id, device, run_id, page_number, fingerprint)
        VALUES (?, ?, ?, ?, ?)
    ''', (page.receipt_id, page.device, page.run_id, hex(page.page_number), fingerprint))
    return Receipt(page.receipt_id, page.device, page.run_id, page.page_number, fingerprint)


def mark_archived(connection: sqlite3.Connection, receipt_id: str, report_id: str) -> None:
    connection.execute(
        'UPDATE receipts SET archived_report = ? WHERE receipt_id = ? AND archived_report IS NULL',
        (report_id, receipt_id),
    )
