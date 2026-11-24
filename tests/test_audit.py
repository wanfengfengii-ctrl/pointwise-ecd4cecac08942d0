from dataclasses import replace

from lake import BookRef
from lake.audit.reconcile import reconcile_report
from lake.publish.totals import RunTotal
from tests.support import LakeTestCase, ReplyLost, lose_reply


class AuditTests(LakeTestCase):
    def test_committed_lost_reply_replays_original_report_and_receipt(self):
        self.register_run()
        page = self.page()
        receipt = self.deliver_and_clear(page)
        self.lake.publish_book('charge', 'r2', {1: 13})
        with self.assertRaises(ReplyLost):
            self.lake.settle('S', 'run', 'R', commit_probe=lose_reply)
        self.assertEqual(self.intake_state('P')[1], page)
        committed = self.stored_report()
        self.assertIsNotNone(committed)
        self.reopen()
        view = self.lake.read_report('S', 'P')
        self.assertEqual(view.receipt, committed.receipt)
        self.assertEqual((view.receipt.report_id, view.receipt.serial, view.receipt.kind,
                          view.receipt.identifier), ('S', 1, 'run', 'R'))
        self.assertEqual(view.pages[0].as_raw_page(), page)
        self.assertEqual(view.rows, committed.pages[0].rows)
        self.assertEqual(view.totals, (RunTotal('R', 13),))
        self.assertEqual(self.lake.settle('S', 'run', 'R'), committed)
        self.lake.finish_handoffs('S')
        record, payload = self.intake_state('P')
        self.assertEqual((record.receipt, record.archived_report, payload), (receipt, 'S', None))
        with self.lake.warehouse.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM reports').fetchone()[0], 1)

    def test_report_id_remains_bound_to_frozen_scope(self):
        self.register_run(())
        original = self.lake.settle('S', 'batch', 'B')
        self.register_run((), 'later')
        self.reopen()
        self.assertEqual(self.lake.settle('S', 'batch', 'B'), original)
        self.assertEqual([run.run_id for run in self.lake.read_report('S').scope.runs], ['R'])
        with self.assertRaises(ValueError):
            self.lake.settle('S', 'run', 'R')
        with self.assertRaises(ValueError):
            self.lake.settle('S', 'batch', 'different')
        later = self.lake.settle('S2', 'batch', 'B')
        self.assertEqual(later.totals, (RunTotal('R', 0), RunTotal('later', 0)))
        self.assertEqual(later.receipt.serial, original.receipt.serial + 1)

    def test_closed_source_audit_qualifies_same_number_in_different_runs(self):
        self.register_run((1, 2), 'R-first')
        self.register_run((1,), 'R-second')
        self.lake.publish_book('charge', 'r2', {1: 11, 2: 7, 3: 13})
        self.lake.publish_book('charge', 'r1', {2: -4})
        first = self.page('P1', (2, 1), run='R-first')
        second = self.page('P2', (3,), 2, run='R-first')
        other = self.page('Q1', (2,), run='R-second', book=BookRef('charge', 'r1'))
        for page in (other, second, first):
            self.deliver_and_clear(page)
        original = self.lake.settle('S', 'batch', 'B')
        self.inbox.rmdir()
        self.reopen()
        self.assertFalse(self.inbox.exists())
        self.assertEqual(self.lake.settle('S', 'batch', 'B'), original)
        for page, expected_rows, total in ((first, (7, 11), 31), (other, (-4,), -4)):
            with self.subTest(receipt=page.receipt_id):
                record, payload = self.intake_state(page.receipt_id)
                self.assertEqual((record.archived_report, payload), ('S', None))
                view = self.lake.read_report('S', page.receipt_id)
                self.assertEqual(view.pages[0].as_raw_page(), page)
                self.assertEqual(tuple(row.kilograms for row in view.rows), expected_rows)
                self.assertEqual(view.totals, (RunTotal(page.run_id, total),))
                self.assertEqual(view.receipt, original.receipt)
        entire = self.lake.read_report('S')
        self.assertEqual([row.kilograms for row in entire.rows], [7, 11, 13, -4])
        self.assertEqual([(check.run_id, check.signed_kilograms, check.recomputed_kilograms,
                           check.matches) for check in entire.reconciliation],
                         [('R-first', 31, 31, True), ('R-second', -4, -4, True)])
        mismatched = replace(original, totals=(RunTotal('R-first', 30), RunTotal('R-second', -4)))
        check = reconcile_report(mismatched)[0]
        self.assertEqual((check.signed_kilograms, check.recomputed_kilograms, check.matches),
                         (30, 31, False))

    def test_outside_page_and_unknown_report_are_explicit(self):
        self.register_run()
        self.register_run(run='other')
        self.lake.publish_book('charge', 'r2', {1: 13})
        self.deliver_and_clear(self.page())
        self.deliver_and_clear(self.page('Q', run='other'))
        self.lake.settle('S', 'run', 'R')
        self.lake.settle('S2', 'run', 'other')
        with self.assertRaisesRegex(LookupError, 'outside'):
            self.lake.read_report('S', 'Q')
        with self.assertRaisesRegex(LookupError, 'unknown report'):
            self.lake.read_report('unknown')
