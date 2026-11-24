from dataclasses import asdict
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from lake import BookRef, MeasurementLake, RawPage
from lake.intake.pages import load_raw_page
from lake.intake.receipts import find_receipt
from lake.publish.ledger import find_report


BOOK = BookRef('charge', 'r2')


class CommitRejected(Exception):
    pass


class ReplyLost(Exception):
    pass


def reject_commit(phase):
    if phase == 'before_commit':
        raise CommitRejected(phase)


def lose_reply(phase):
    if phase == 'after_commit':
        raise ReplyLost(phase)


class LakeTestCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inbox = self.root / 'device'
        self.inbox.mkdir()
        self.reopen()

    def reopen(self):
        self.lake = MeasurementLake(self.root / 'lake').initialize()

    def register_run(self, pages=(1,), run='R', batch='B', device='D'):
        return self.lake.register(run, batch, device, pages)

    def page(self, receipt_id='P', codes=(1,), page_number=1, run='R', device='D', book=BOOK):
        return RawPage(receipt_id, device, run, page_number, book, codes)

    def source(self, page):
        path = self.inbox / f'{page.receipt_id}.json'
        path.write_text(json.dumps(asdict(page)), encoding='utf-8')
        return path

    def deliver_and_clear(self, page):
        path = self.source(page)
        receipt = self.lake.deliver_source_page(path)
        self.lake.clear_source_page(path, receipt)
        self.assertFalse(path.exists())
        return receipt

    def intake_state(self, receipt_id):
        with self.lake.intake.connection() as connection:
            return find_receipt(connection, receipt_id), load_raw_page(connection, receipt_id)

    def stored_report(self, report_id='S'):
        with self.lake.warehouse.connection() as connection:
            return find_report(connection, report_id)


if __name__ == '__main__':
    lake = MeasurementLake(sys.argv[1]).initialize()
    source = Path(sys.argv[2])
    receipt = lake.deliver_source_page(source)
    lake.clear_source_page(source, receipt)
