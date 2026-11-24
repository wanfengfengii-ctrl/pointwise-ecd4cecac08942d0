from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator
import sqlite3


CommitProbe = Callable[[str], None]


@contextmanager
def open_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, isolation_level=None, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        yield connection
    finally:
        connection.close()


@contextmanager
def local_transaction(path: Path, commit_probe: CommitProbe | None = None):
    with open_connection(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        try:
            yield connection
            notify = commit_probe if connection.total_changes else None
            if notify is not None:
                notify('before_commit')
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        if notify is not None:
            notify('after_commit')
