from dataclasses import dataclass
import json
import sqlite3


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    batch: str
    device: str
    expected_pages: tuple[int, ...]


def initialize_runs(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS runs (
            registration_order INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            batch TEXT NOT NULL,
            device TEXT NOT NULL,
            expected_pages TEXT NOT NULL
        )
    ''')
    connection.execute('CREATE INDEX IF NOT EXISTS runs_by_batch ON runs(batch, registration_order)')


def _run_from_row(row) -> RunRecord:
    return RunRecord(row['run_id'], row['batch'], row['device'],
                     tuple(int(page, 16) for page in json.loads(row['expected_pages'])))


def register(connection: sqlite3.Connection, run_id: str, batch: str, device: str,
             expected_pages) -> RunRecord:
    if any(type(value) is not str or not value.strip() for value in (run_id, batch, device)):
        raise ValueError('run, batch and device must be nonblank strings')
    if not isinstance(expected_pages, (tuple, list)):
        raise ValueError('expected pages must be an ordered list or tuple')
    pages = tuple(expected_pages)
    if any(type(page) is not int or page <= 0 for page in pages):
        raise ValueError('expected pages must be positive integers')
    if len(set(pages)) != len(pages):
        raise ValueError('duplicate expected page')

    record = RunRecord(run_id, batch, device, pages)
    row = connection.execute('SELECT * FROM runs WHERE run_id = ?', (run_id,)).fetchone()
    if row is not None:
        previous = _run_from_row(row)
        if previous != record:
            raise ValueError(f'run already registered with different data: {run_id}')
        return previous
    connection.execute(
        'INSERT INTO runs (run_id, batch, device, expected_pages) VALUES (?, ?, ?, ?)',
        (run_id, batch, device, json.dumps([hex(page) for page in pages])),
    )
    return record


def get_run(connection: sqlite3.Connection, run_id: str) -> RunRecord:
    if type(run_id) is not str or not run_id.strip():
        raise ValueError('run identifier must be a nonblank string')
    row = connection.execute('SELECT * FROM runs WHERE run_id = ?', (run_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown run: {run_id}')
    return _run_from_row(row)


def runs_for_batch(connection: sqlite3.Connection, batch: str) -> tuple[RunRecord, ...]:
    rows = connection.execute(
        'SELECT * FROM runs WHERE batch = ? ORDER BY registration_order', (batch,),
    )
    return tuple(_run_from_row(row) for row in rows)
