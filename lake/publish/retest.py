from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import TYPE_CHECKING

from lake._storage import CommitProbe
from lake.intake.receipts import find_receipt

if TYPE_CHECKING:
    from lake.intake.store import IntakeStore
    from lake.publish.storage import LakeStore


@dataclass(frozen=True)
class RetestVerdict:
    candidate_receipt: str
    original_receipt: str
    run_id: str
    page_number: int
    decision: str
    report_id: str | None

    def answer(self) -> tuple[str, str]:
        if self.decision == 'applied':
            return ('applied', self.candidate_receipt)
        return ('already_used', self.report_id)  # type: ignore[return-value]


def initialize_retest_verdicts(connection: sqlite3.Connection) -> None:
    # The warehouse is the ordering point between page swaps and report
    # commitment: both decisions take its BEGIN IMMEDIATE write lock.
    connection.execute('''
        CREATE TABLE IF NOT EXISTS retest_verdicts (
            candidate_receipt TEXT PRIMARY KEY,
            original_receipt TEXT NOT NULL,
            run_id TEXT NOT NULL,
            page_number TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('applied', 'already_used')),
            report_id TEXT,
            UNIQUE (run_id, page_number),
            CHECK (
                (decision = 'applied' AND report_id IS NULL)
                OR (decision = 'already_used' AND report_id IS NOT NULL)
            )
        )
    ''')


def _row_to_verdict(row) -> RetestVerdict:
    return RetestVerdict(
        row['candidate_receipt'], row['original_receipt'], row['run_id'],
        int(row['page_number'], 16), row['decision'], row['report_id'],
    )


def find_verdict(connection: sqlite3.Connection,
                 candidate_receipt: str) -> RetestVerdict | None:
    row = connection.execute(
        'SELECT * FROM retest_verdicts WHERE candidate_receipt = ?',
        (candidate_receipt,),
    ).fetchone()
    return None if row is None else _row_to_verdict(row)


def applied_winners(connection: sqlite3.Connection) -> dict[tuple[str, int], str]:
    rows = connection.execute('''
        SELECT candidate_receipt, run_id, page_number
        FROM retest_verdicts WHERE decision = 'applied'
    ''').fetchall()
    return {(row['run_id'], int(row['page_number'], 16)): row['candidate_receipt']
            for row in rows}


def first_report_using_receipt(connection: sqlite3.Connection,
                               receipt_id: str) -> str | None:
    row = connection.execute('''
        SELECT reports.report_id AS report_id
        FROM report_pages
        JOIN reports ON reports.report_id = report_pages.report_id
        WHERE report_pages.receipt_id = ?
        ORDER BY reports.serial ASC
        LIMIT 1
    ''', (receipt_id,)).fetchone()
    return None if row is None else row['report_id']


def apply_retest(intake: IntakeStore, warehouse: LakeStore, receipt_id: str,
                 *, commit_probe: CommitProbe | None = None) -> tuple[str, str]:
    # The binding is immutable once the candidate is received, so this short
    # read does not need to share the warehouse critical section.
    with intake.connection() as connection:
        record = find_receipt(connection, receipt_id)
        if record is None or record.replaces is None:
            raise LookupError(f'unknown retest candidate: {receipt_id}')
        original_id = record.replaces

    with warehouse.transaction(commit_probe) as connection:
        previous = find_verdict(connection, receipt_id)
        if previous is not None:
            return previous.answer()

        # P has already entered a committed finalization: the answer is a
        # fact read from the immutable ledger, so no new verdict is written.
        report_id = first_report_using_receipt(connection, original_id)
        if report_id is not None:
            return ('already_used', report_id)

        # Holding the warehouse IMMEDIATE lock and seeing no P report makes
        # 'applied' and 'P was used first' a single linear ordering decision.
        slot = record.receipt
        connection.execute('''
            INSERT INTO retest_verdicts
                (candidate_receipt, original_receipt, run_id, page_number,
                 decision, report_id)
            VALUES (?, ?, ?, ?, 'applied', NULL)
        ''', (receipt_id, original_id, slot.run_id, hex(slot.page_number)))
        answer: tuple[str, str] = ('applied', receipt_id)
    return answer
