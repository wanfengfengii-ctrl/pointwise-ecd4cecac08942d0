from pathlib import Path

from lake._storage import CommitProbe, local_transaction, open_connection
from lake.catalog.revisions import initialize_revisions
from lake.catalog.runs import initialize_runs
from lake.process.complete import initialize_processed
from lake.publish.ledger import initialize_ledger


class LakeStore:
    def __init__(self, path):
        self.path = Path(path)

    def initialize(self) -> None:
        with self.transaction() as connection:
            initialize_runs(connection)
            initialize_revisions(connection)
            initialize_processed(connection)
            initialize_ledger(connection)

    def connection(self):
        return open_connection(self.path)

    def transaction(self, commit_probe: CommitProbe | None = None):
        return local_transaction(self.path, commit_probe)
