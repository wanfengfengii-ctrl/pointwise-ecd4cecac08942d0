from dataclasses import dataclass
from hashlib import sha256
import json
import sqlite3

from lake.catalog.revisions import BookRef
from lake.catalog.runs import RunRecord


@dataclass(frozen=True)
class RawPage:
    receipt_id: str
    device: str
    run_id: str
    page_number: int
    book: BookRef
    codes: tuple[int, ...]

    def __post_init__(self):
        identifiers = (self.receipt_id, self.device, self.run_id)
        if any(type(value) is not str or not value.strip() for value in identifiers):
            raise ValueError('receipt, device and run identifiers must be nonblank strings')
        if type(self.page_number) is not int or self.page_number <= 0:
            raise ValueError('page number must be a positive integer')
        if not isinstance(self.book, BookRef):
            raise ValueError('page requires an exact book reference')
        if not isinstance(self.codes, (tuple, list)):
            raise ValueError('raw codes must be an ordered list or tuple')
        codes = tuple(self.codes)
        if any(type(code) is not int for code in codes):
            raise ValueError('raw codes must be integers')
        object.__setattr__(self, 'codes', codes)


def validate_page(page: RawPage, run: RunRecord) -> None:
    if page.run_id != run.run_id or page.device != run.device:
        raise ValueError('page does not match the registered run and device')
    if page.page_number not in run.expected_pages:
        raise ValueError('page number is outside the registered run')


def page_fingerprint(page: RawPage) -> str:
    identity = [page.receipt_id, page.device, page.run_id, hex(page.page_number),
                page.book.name, page.book.revision, [hex(code) for code in page.codes]]
    data = json.dumps(identity, ensure_ascii=True, separators=(',', ':'))
    return sha256(data.encode('ascii')).hexdigest()


def initialize_raw_pages(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS raw_pages (
            receipt_id TEXT PRIMARY KEY REFERENCES receipts(receipt_id),
            book_name TEXT NOT NULL,
            book_revision TEXT NOT NULL,
            codes TEXT NOT NULL
        )
    ''')


def save_raw_page(connection: sqlite3.Connection, page: RawPage) -> None:
    connection.execute(
        'INSERT INTO raw_pages (receipt_id, book_name, book_revision, codes) VALUES (?, ?, ?, ?)',
        (page.receipt_id, page.book.name, page.book.revision,
         json.dumps([hex(code) for code in page.codes])),
    )


def load_raw_page(connection: sqlite3.Connection, receipt_id: str) -> RawPage | None:
    row = connection.execute('''
        SELECT receipts.device, receipts.run_id, receipts.page_number,
               raw_pages.book_name, raw_pages.book_revision, raw_pages.codes
        FROM raw_pages JOIN receipts USING (receipt_id)
        WHERE raw_pages.receipt_id = ?
    ''', (receipt_id,)).fetchone()
    if row is None:
        return None
    return RawPage(receipt_id, row['device'], row['run_id'], int(row['page_number'], 16),
                   BookRef(row['book_name'], row['book_revision']),
                   tuple(int(code, 16) for code in json.loads(row['codes'])))
