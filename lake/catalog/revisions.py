from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
import json
import sqlite3


@dataclass(frozen=True)
class BookRef:
    name: str
    revision: str

    def __post_init__(self):
        if any(type(value) is not str or not value.strip() for value in (self.name, self.revision)):
            raise ValueError('book name and revision must be nonblank strings')


@dataclass(frozen=True)
class BookRevision:
    ref: BookRef
    mapping: Mapping[int, int]

    def __post_init__(self):
        object.__setattr__(self, 'mapping', MappingProxyType(dict(self.mapping)))


def initialize_revisions(connection: sqlite3.Connection) -> None:
    connection.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            name TEXT NOT NULL,
            revision TEXT NOT NULL,
            mapping TEXT NOT NULL,
            PRIMARY KEY (name, revision)
        )
    ''')


def find_revision(connection: sqlite3.Connection, ref: BookRef) -> BookRevision | None:
    row = connection.execute(
        'SELECT mapping FROM revisions WHERE name = ? AND revision = ?',
        (ref.name, ref.revision),
    ).fetchone()
    if row is None:
        return None
    pairs = json.loads(row['mapping'])
    return BookRevision(ref, {int(code, 16): int(value, 16) for code, value in pairs})


def insert_revision(connection: sqlite3.Connection, revision: BookRevision) -> None:
    pairs = [(hex(code), hex(value)) for code, value in sorted(revision.mapping.items())]
    connection.execute(
        'INSERT INTO revisions (name, revision, mapping) VALUES (?, ?, ?)',
        (revision.ref.name, revision.ref.revision, json.dumps(pairs)),
    )
