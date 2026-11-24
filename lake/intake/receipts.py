from dataclasses import dataclass
from pathlib import Path
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
    replaces: str | None = None


def initialize_receipts(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id TEXT PRIMARY KEY,
            device TEXT NOT NULL,
            run_id TEXT NOT NULL,
            page_number TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            archived_report TEXT,
            replaces TEXT
        )
    ''')
    # Exactly one ordinary original page per run/page slot.
    connection.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS receipts_ordinary_slot
        ON receipts(run_id, page_number) WHERE replaces IS NULL
    ''')
    # At most one retest candidate bound to each original receipt.
    connection.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS receipts_single_candidate
        ON receipts(replaces) WHERE replaces IS NOT NULL
    ''')


def migrate_receipts_schema(path: Path) -> None:
    """Rebuild a pre-retest receipts table so a slot may hold P and one Q."""
    path = Path(path)
    if not path.exists():
        return
    connection = sqlite3.connect(str(path), timeout=10)
    try:
        connection.isolation_level = None
        columns = [row[1] for row in connection.execute('PRAGMA table_info(receipts)')]
        if not columns or 'replaces' in columns:
            return
        # The old table has a table-level UNIQUE(run_id, page_number) that no
        # index edit can relax; rebuild it with the binding column. FK enforcement
        # must be off while the parent receipts table is dropped and renamed.
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('BEGIN IMMEDIATE')
        # Re-check under the write lock: another initializer may have migrated.
        columns = [row[1] for row in connection.execute('PRAGMA table_info(receipts)')]
        if 'replaces' in columns:
            connection.rollback()
            return
        connection.execute('''
            CREATE TABLE receipts_retest (
                receipt_id TEXT PRIMARY KEY,
                device TEXT NOT NULL,
                run_id TEXT NOT NULL,
                page_number TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                archived_report TEXT,
                replaces TEXT
            )
        ''')
        connection.execute('''
            INSERT INTO receipts_retest
                (receipt_id, device, run_id, page_number, fingerprint,
                 archived_report, replaces)
            SELECT receipt_id, device, run_id, page_number, fingerprint,
                   archived_report, NULL
            FROM receipts
        ''')
        connection.execute('DROP TABLE receipts')
        connection.execute('ALTER TABLE receipts_retest RENAME TO receipts')
        violations = connection.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f'foreign key violations after receipts migration: {violations!r}')
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _record_from_row(row) -> ReceiptRecord | None:
    if row is None:
        return None
    receipt = Receipt(row['receipt_id'], row['device'], row['run_id'],
                      int(row['page_number'], 16), row['fingerprint'])
    try:
        replaces = row['replaces']
    except (IndexError, KeyError):
        replaces = None
    return ReceiptRecord(receipt, row['archived_report'], replaces)


def find_receipt(connection: sqlite3.Connection, receipt_id: str) -> ReceiptRecord | None:
    row = connection.execute('SELECT * FROM receipts WHERE receipt_id = ?', (receipt_id,)).fetchone()
    return _record_from_row(row)


def find_page_receipt(connection: sqlite3.Connection, run_id: str,
                      page_number: int) -> ReceiptRecord | None:
    # The slot lookup names the ordinary original; candidates share the slot
    # and are reached through their binding or a retest verdict.
    row = connection.execute('''
        SELECT * FROM receipts
        WHERE run_id = ? AND page_number = ? AND replaces IS NULL
    ''', (run_id, hex(page_number))).fetchone()
    return _record_from_row(row)


def find_candidate_for_original(connection: sqlite3.Connection,
                                original_id: str) -> ReceiptRecord | None:
    row = connection.execute(
        'SELECT * FROM receipts WHERE replaces = ?', (original_id,),
    ).fetchone()
    return _record_from_row(row)


def record_receipt(connection: sqlite3.Connection, page: RawPage,
                   replaces: str | None = None) -> Receipt:
    fingerprint = page_fingerprint(page)
    connection.execute('''
        INSERT INTO receipts (receipt_id, device, run_id, page_number, fingerprint,
                              archived_report, replaces)
        VALUES (?, ?, ?, ?, ?, NULL, ?)
    ''', (page.receipt_id, page.device, page.run_id, hex(page.page_number),
          fingerprint, replaces))
    return Receipt(page.receipt_id, page.device, page.run_id, page.page_number, fingerprint)


def mark_archived(connection: sqlite3.Connection, receipt_id: str, report_id: str) -> None:
    connection.execute(
        'UPDATE receipts SET archived_report = ? WHERE receipt_id = ? AND archived_report IS NULL',
        (report_id, receipt_id),
    )
