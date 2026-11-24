import json
import subprocess
import sys

from lake import PendingSettlement
from lake.process.complete import find_processed_page
from tests.support import BOOK, CommitRejected, LakeTestCase, reject_commit


class DailyTests(LakeTestCase):
    def test_book_first_original_daily_totals(self):
        self.register_run((1, 2))
        self.lake.publish_book('charge', 'r2', {2: 7, 1: 11, 3: 13})
        self.deliver_and_clear(self.page('P1', (2, 1)))
        self.deliver_and_clear(self.page('P2', (3,), 2))
        issued = self.lake.settle('S', 'batch', 'B')
        self.assertEqual([row.kilograms for page in issued.pages for row in page.rows], [7, 11, 13])
        self.assertEqual([(total.run_id, total.kilograms) for total in issued.totals], [('R', 31)])
        self.assertEqual(self.lake.read_report('S').receipt, issued.receipt)

    def test_raw_and_registered_order_survive_reverse_delivery(self):
        self.register_run((2, 1))
        self.lake.publish_book('charge', 'r2', {2: 7, 1: 11, 3: 13})
        self.deliver_and_clear(self.page('P2', (3,), 1))
        self.deliver_and_clear(self.page('P1', (2, 1), 2))
        self.lake.settle('S', 'run', 'R')
        view = self.lake.read_report('S')
        self.assertEqual([page.page_number for page in view.pages], [2, 1])
        self.assertEqual([(row.receipt_id, row.position, row.raw_code, row.kilograms)
                          for row in view.rows], [('P1', 1, 2, 7), ('P1', 2, 1, 11), ('P2', 1, 3, 13)])
        self.assertEqual(view.totals[0].kilograms, 31)

    def test_batch_scope_and_missing_exact_slot(self):
        self.register_run((1, 2), 'Z-first')
        self.register_run((1,), 'A-second')
        self.lake.publish_book('charge', 'r2', {1: 7, 2: 24, 3: -4})
        self.deliver_and_clear(self.page('Q1', (3,), run='A-second'))
        self.deliver_and_clear(self.page('P1', run='Z-first'))
        pending = self.lake.settle('S', 'batch', 'B')
        self.assertIsInstance(pending, PendingSettlement)
        self.assertEqual([(part.kind, part.run_id, part.page_number) for part in pending.missing],
                         [('page', 'Z-first', 2)])
        self.assertIsNone(self.stored_report())
        self.deliver_and_clear(self.page('P2', (2,), 2, run='Z-first'))
        report = self.lake.settle('S', 'batch', 'B')
        self.assertEqual([page.provenance.receipt_id for page in report.pages], ['P1', 'P2', 'Q1'])
        self.assertEqual([(total.run_id, total.kilograms) for total in report.totals],
                         [('Z-first', 31), ('A-second', -4)])
        with self.assertRaises(LookupError):
            self.lake.settle('unknown', 'batch', 'unknown')

    def test_integer_edges_zero_row_page_and_zero_page_run(self):
        self.register_run((1, 2), 'R')
        self.register_run((), 'zero')
        self.lake.publish_book('charge', 'r2', {1: 2**90, 2: -17, 3: 0})
        self.lake.publish_book('empty', 'r1', {})
        from lake import BookRef
        self.deliver_and_clear(self.page('P1', (1, 2, 1, 3)))
        self.deliver_and_clear(self.page('P2', (), 2, book=BookRef('empty', 'r1')))
        self.lake.settle('S', 'batch', 'B')
        self.reopen()
        view = self.lake.read_report('S')
        self.assertEqual([row.kilograms for row in view.rows], [2**90, -17, 2**90, 0])
        self.assertTrue(all(type(row.kilograms) is int for row in view.rows))
        self.assertEqual([(total.run_id, total.kilograms) for total in view.totals],
                         [('R', 2**91 - 17), ('zero', 0)])
        empty = self.lake.read_report('S', 'P2')
        self.assertEqual(empty.rows, ())
        self.assertEqual(empty.pages[0].receipt_id, 'P2')
        self.assertEqual(empty.pages[0].book, BookRef('empty', 'r1'))
        self.assertEqual(empty.totals[0].kilograms, 2**91 - 17)

    def test_undefined_code_is_invalid_and_leaves_payload(self):
        self.register_run()
        original = self.page(codes=(1, 2))
        self.deliver_and_clear(original)
        self.lake.publish_book('charge', 'r1', {2: 7})
        self.lake.publish_book('charge', 'r2', {1: 13})
        with self.assertRaisesRegex(ValueError, 'undefined code'):
            self.lake.settle('S', 'run', 'R')
        self.assertIsNone(self.stored_report())
        self.assertEqual(self.intake_state('P')[1], original)

    def test_late_revision_after_device_process_exits(self):
        self.register_run()
        page = self.page()
        path = self.source(page)
        result = subprocess.run([sys.executable, '-B', '-m', 'tests.support',
                                 str(self.lake.directory), str(path)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(path.exists())
        self.reopen()
        self.lake.publish_book('charge', 'r1', {1: 7})
        pending = self.lake.settle('S', 'run', 'R')
        self.assertIsInstance(pending, PendingSettlement)
        self.assertEqual([(part.kind, part.receipt_id, part.book) for part in pending.missing],
                         [('revision', 'P', BOOK)])
        self.assertIsNone(self.stored_report())
        with self.lake.warehouse.connection() as connection:
            self.assertIsNone(find_processed_page(connection, 'R', 1))
        self.lake.publish_book('charge', 'r2', {1: 13})
        issued = self.lake.settle('S', 'run', 'R')
        view = self.lake.read_report('S', 'P')
        source = view.pages[0]
        self.assertEqual(source.as_raw_page(), page)
        self.assertEqual([(row.position, row.raw_code, row.kilograms) for row in view.rows], [(1, 1, 13)])
        self.assertEqual(view.totals[0].kilograms, 13)
        self.assertEqual(view.receipt, issued.receipt)
        self.assertTrue(view.reconciliation[0].matches)
        evidence = {
            'case_id': 'v5',
            'input': {'receipt': 'P', 'codes': [1], 'old': {'1': 7}, 'specified': {'1': 13}},
            'expected': {'waiting_for': 'r2', 'readings': [13]},
            'actual': {'waiting_for': pending.missing[0].book.revision,
                       'readings': [row.kilograms for row in issued.pages[0].rows]},
            'downstream_expected': {'receipt': 'P', 'revision': 'r2', 'total_kg': 13},
            'downstream_actual': {'receipt': source.receipt_id, 'revision': source.book.revision,
                                  'total_kg': view.totals[0].kilograms},
            'code_paths': ['lake/intake/recovery.py', 'lake/process/staging.py',
                           'lake/process/decode.py', 'lake/publish/issue.py', 'lake/audit/readback.py'],
            'oracle': 'Old revision has no eligibility. The only raw position is 1, whose r2 value is 13 kg.',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(evidence, separators=(',', ':')))

    def test_revision_is_immutable_and_survives_reinitialize(self):
        self.register_run()
        old = self.lake.publish_book('charge', 'r1', {1: 7})
        exact = self.lake.publish_book('charge', 'r2', {1: 13})
        self.reopen()
        self.assertEqual(self.lake.publish_book('charge', 'r1', {1: 7}), old)
        self.assertEqual(self.lake.publish_book('charge', 'r2', {1: 13}), exact)
        with self.assertRaises(ValueError):
            self.lake.publish_book('charge', 'r2', {1: 99})
        for mapping in ({True: 1}, {1: False}, {1: 2.5}, {1: None}):
            with self.subTest(mapping=mapping):
                with self.assertRaises(ValueError):
                    self.lake.publish_book('charge', 'invalid', mapping)
        self.deliver_and_clear(self.page())
        self.assertEqual(self.lake.settle('S', 'run', 'R').totals[0].kilograms, 13)

    def test_publish_rejection_keeps_handoff_and_retries_once(self):
        self.register_run()
        page = self.page()
        receipt = self.deliver_and_clear(page)
        self.lake.publish_book('charge', 'r2', {1: 13})
        with self.assertRaises(CommitRejected):
            self.lake.settle('S', 'run', 'R', commit_probe=reject_commit)
        self.reopen()
        self.assertIsNone(self.stored_report())
        with self.lake.warehouse.connection() as connection:
            self.assertIsNone(find_processed_page(connection, 'R', 1))
        record, payload = self.intake_state('P')
        self.assertEqual(record.receipt, receipt)
        self.assertIsNone(record.archived_report)
        self.assertEqual(payload, page)
        issued = self.lake.settle('S', 'run', 'R')
        self.assertEqual(issued.totals[0].kilograms, 13)
        self.assertEqual(issued.pages[0].provenance.as_raw_page(), page)
        self.assertEqual(self.lake.settle('S', 'run', 'R'), issued)
        record, payload = self.intake_state('P')
        self.assertEqual(record.archived_report, 'S')
        self.assertIsNone(payload)
        with self.lake.warehouse.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM reports').fetchone()[0], 1)
