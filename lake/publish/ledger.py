from dataclasses import dataclass
import json
import sqlite3

from lake.catalog.runs import RunRecord
from lake.catalog.scope import SettlementScope
from lake.process.complete import ProcessedPage, decode_processed_page
from lake.process.provenance import PageProvenance
from lake.publish.totals import RunTotal


@dataclass(frozen=True)
class PublicationReceipt:
    report_id: str
    serial: int
    kind: str
    identifier: str


@dataclass(frozen=True)
class IssuedReport:
    scope: SettlementScope
    pages: tuple[ProcessedPage, ...]
    totals: tuple[RunTotal, ...]
    receipt: PublicationReceipt


def initialize_ledger(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            serial INTEGER PRIMARY KEY,
            report_id TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('run', 'batch')),
            identifier TEXT NOT NULL,
            runs TEXT NOT NULL,
            totals TEXT NOT NULL
        )
    ''')
    connection.execute('''
        CREATE TABLE IF NOT EXISTS report_pages (
            report_id TEXT NOT NULL REFERENCES reports(report_id),
            position INTEGER NOT NULL,
            receipt_id TEXT NOT NULL REFERENCES processed_pages(receipt_id),
            PRIMARY KEY (report_id, position),
            UNIQUE (report_id, receipt_id)
        )
    ''')


def _report_scope(row) -> SettlementScope:
    runs = tuple(RunRecord(run_id, batch, device, tuple(int(page, 16) for page in pages))
                 for run_id, batch, device, pages in json.loads(row['runs']))
    return SettlementScope(row['kind'], row['identifier'], runs)


def find_report(connection: sqlite3.Connection, report_id: str) -> IssuedReport | None:
    row = connection.execute('SELECT * FROM reports WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        return None
    linked_pages = connection.execute('''
        SELECT processed_pages.body
        FROM report_pages JOIN processed_pages USING (receipt_id)
        WHERE report_pages.report_id = ? ORDER BY report_pages.position
    ''', (report_id,))
    pages = tuple(decode_processed_page(page['body']) for page in linked_pages)
    totals = tuple(RunTotal(run_id, int(total, 16)) for run_id, total in json.loads(row['totals']))
    receipt = PublicationReceipt(row['report_id'], row['serial'], row['kind'], row['identifier'])
    return IssuedReport(_report_scope(row), pages, totals, receipt)


def record_report(connection: sqlite3.Connection, report_id: str, scope: SettlementScope,
                  pages: tuple[ProcessedPage, ...], totals: tuple[RunTotal, ...]) -> IssuedReport:
    encoded_runs = [(run.run_id, run.batch, run.device, [hex(page) for page in run.expected_pages])
                    for run in scope.runs]
    encoded_totals = [(total.run_id, hex(total.kilograms)) for total in totals]
    cursor = connection.execute('''
        INSERT INTO reports (report_id, kind, identifier, runs, totals) VALUES (?, ?, ?, ?, ?)
    ''', (report_id, scope.kind, scope.identifier, json.dumps(encoded_runs), json.dumps(encoded_totals)))
    receipt = PublicationReceipt(report_id, cursor.lastrowid, scope.kind, scope.identifier)
    connection.executemany('''
        INSERT INTO report_pages (report_id, position, receipt_id) VALUES (?, ?, ?)
    ''', ((report_id, position, page.provenance.receipt_id)
          for position, page in enumerate(pages, start=1)))
    return IssuedReport(scope, pages, totals, receipt)


def find_committed_page(connection: sqlite3.Connection, report_id: str,
                        receipt_id: str) -> PageProvenance | None:
    row = connection.execute('''
        SELECT processed_pages.body
        FROM report_pages JOIN processed_pages USING (receipt_id)
        WHERE report_pages.report_id = ? AND report_pages.receipt_id = ?
    ''', (report_id, receipt_id)).fetchone()
    return None if row is None else decode_processed_page(row['body']).provenance
