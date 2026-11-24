from dataclasses import dataclass
import sqlite3

from lake.catalog.revisions import BookRevision, find_revision
from lake.intake.pages import RawPage


@dataclass(frozen=True)
class StagedPage:
    page: RawPage
    revision: BookRevision


def stage_page(connection: sqlite3.Connection, page: RawPage) -> StagedPage | None:
    revision = find_revision(connection, page.book)
    if revision is None:
        return None
    return StagedPage(page, revision)
