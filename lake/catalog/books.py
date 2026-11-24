from collections.abc import Mapping
import sqlite3

from lake.catalog.revisions import BookRef, BookRevision, find_revision, insert_revision


def validate_mapping(mapping: Mapping[int, int]) -> dict[int, int]:
    if not isinstance(mapping, Mapping):
        raise ValueError('a codebook must be an integer mapping')
    result = dict(mapping)
    if any(type(code) is not int or type(value) is not int for code, value in result.items()):
        raise ValueError('a codebook requires integer keys and integer readings')
    return result


def publish_book(connection: sqlite3.Connection, name: str, revision: str,
                 mapping: Mapping[int, int]) -> BookRevision:
    book = BookRevision(BookRef(name, revision), validate_mapping(mapping))
    previous = find_revision(connection, book.ref)
    if previous is not None:
        if previous != book:
            raise ValueError(f'published revision is immutable: {name}/{revision}')
        return previous
    insert_revision(connection, book)
    return book
