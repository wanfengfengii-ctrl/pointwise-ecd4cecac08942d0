from pathlib import Path

from lake.audit.readback import read_report
from lake.catalog.books import publish_book
from lake.catalog.revisions import BookRef as BookRef
from lake.catalog.runs import get_run, register
from lake.intake.device import clear_source_page as clear_source_page, deliver_source_page
from lake.intake.handoff import receive_page
from lake.intake.pages import RawPage as RawPage
from lake.intake.store import IntakeStore
from lake.publish.issue import PendingSettlement as PendingSettlement, finish_handoffs, settle
from lake.publish.ledger import find_committed_page
from lake.publish.retest import apply_retest as decide_retest
from lake.publish.storage import LakeStore


class MeasurementLake:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.intake = IntakeStore(self.directory / 'intake.sqlite3')
        self.warehouse = LakeStore(self.directory / 'warehouse.sqlite3')

    def initialize(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.intake.initialize()
        self.warehouse.initialize()
        return self

    def register(self, run_id, batch, device, expected_pages):
        with self.warehouse.transaction() as connection:
            return register(connection, run_id, batch, device, expected_pages)

    def publish_book(self, name, revision, mapping):
        with self.warehouse.transaction() as connection:
            return publish_book(connection, name, revision, mapping)

    def receive_page(self, page, *, replaces=None, commit_probe=None):
        if not isinstance(page, RawPage):
            raise ValueError('expected a RawPage')
        with self.warehouse.connection() as connection:
            run = get_run(connection, page.run_id)
        return receive_page(self.intake, run, page, self._archived_source,
                            replaces=replaces, commit_probe=commit_probe)

    def _archived_source(self, report_id, receipt_id):
        with self.warehouse.connection() as connection:
            source = find_committed_page(connection, report_id, receipt_id)
        return None if source is None else source.as_raw_page()

    def deliver_source_page(self, path, *, replaces=None, commit_probe=None):
        return deliver_source_page(path, self.receive_page, replaces=replaces,
                                   commit_probe=commit_probe)

    clear_source_page = staticmethod(clear_source_page)

    def apply_retest(self, receipt_id, *, commit_probe=None):
        return decide_retest(self.intake, self.warehouse, receipt_id,
                             commit_probe=commit_probe)

    def settle(self, report_id, kind, identifier, *, commit_probe=None):
        return settle(self.intake, self.warehouse, report_id, kind, identifier,
                      commit_probe=commit_probe)

    def finish_handoffs(self, report_id):
        return finish_handoffs(self.intake, self.warehouse, report_id)

    def read_report(self, report_id, receipt_id=None):
        return read_report(self.warehouse, report_id, receipt_id)
