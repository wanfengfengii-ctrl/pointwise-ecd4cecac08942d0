from collections.abc import Iterable
from dataclasses import dataclass
import json
import sqlite3

from lake.catalog.revisions import BookRef
from lake.process.decode import StandardRow, decode_page
from lake.process.provenance import PageProvenance, capture_provenance
from lake.process.staging import StagedPage


@dataclass(frozen=True)
class ProcessedPage:
    provenance: PageProvenance
    rows: tuple[StandardRow, ...]


def complete_page(staged: StagedPage) -> ProcessedPage:
    provenance = capture_provenance(staged.page, staged.revision.ref)
    return ProcessedPage(provenance, decode_page(staged))


def initialize_processed(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS processed_pages (
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            page_number TEXT NOT NULL,
            receipt_id TEXT NOT NULL UNIQUE,
            body TEXT NOT NULL,
            PRIMARY KEY (run_id, page_number)
        )
    ''')


def _encode_processed_page(page: ProcessedPage) -> str:
    source = page.provenance
    return json.dumps({
        'receipt_id': source.receipt_id,
        'device': source.device,
        'run_id': source.run_id,
        'page_number': hex(source.page_number),
        'book': [source.book.name, source.book.revision],
        'codes': [hex(code) for code in source.codes],
        'rows': [[row.position, hex(row.raw_code), hex(row.kilograms)] for row in page.rows],
    })


def decode_processed_page(body: str) -> ProcessedPage:
    data = json.loads(body)
    source = PageProvenance(data['receipt_id'], data['device'], data['run_id'],
                            int(data['page_number'], 16), BookRef(*data['book']),
                            tuple(int(code, 16) for code in data['codes']))
    rows = tuple(StandardRow(source.receipt_id, position, int(code, 16), int(value, 16))
                 for position, code, value in data['rows'])
    return ProcessedPage(source, rows)


def find_processed_page(connection: sqlite3.Connection, run_id: str,
                        page_number: int) -> ProcessedPage | None:
    row = connection.execute(
        'SELECT body FROM processed_pages WHERE run_id = ? AND page_number = ?',
        (run_id, hex(page_number)),
    ).fetchone()
    return None if row is None else decode_processed_page(row['body'])


def record_processed_pages(connection: sqlite3.Connection, pages: Iterable[ProcessedPage]) -> None:
    records = ((page.provenance.run_id, hex(page.provenance.page_number),
                page.provenance.receipt_id, _encode_processed_page(page)) for page in pages)
    connection.executemany('''
        INSERT INTO processed_pages (run_id, page_number, receipt_id, body) VALUES (?, ?, ?, ?)
    ''', records)
