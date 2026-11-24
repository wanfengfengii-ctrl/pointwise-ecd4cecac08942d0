from pathlib import Path

from lake._storage import CommitProbe, local_transaction, open_connection
from lake.intake.pages import initialize_raw_pages
from lake.intake.receipts import initialize_receipts


class IntakeStore:
    def __init__(self, path):
        self.path = Path(path)

    def initialize(self) -> None:
        with self.transaction() as connection:
            initialize_receipts(connection)
            initialize_raw_pages(connection)

    def connection(self):
        return open_connection(self.path)

    def transaction(self, commit_probe: CommitProbe | None = None):
        return local_transaction(self.path, commit_probe)
