from dataclasses import replace

from lake import BookRef
from lake.intake.recovery import pending_pages
from tests.support import CommitRejected, LakeTestCase, ReplyLost, lose_reply, reject_commit


class IntakeTests(LakeTestCase):
    def test_two_pages_and_original_receipt(self):
        self.register_run((1, 2))
        first = self.page('P1', (2, 1))
        second = self.page('P2', (3,), 2)
        first_receipt = self.lake.receive_page(first)
        second_receipt = self.lake.receive_page(second)
        self.assertNotEqual(first_receipt, second_receipt)
        self.assertEqual(self.lake.receive_page(second), second_receipt)
        self.assertEqual(self.intake_state('P1')[1], first)
        self.assertEqual(self.intake_state('P2')[1], second)

    def test_registration_survives_reinitialize(self):
        record = self.register_run([3, 1], run='user-run', batch='night', device='kiln')
        self.reopen()
        self.assertEqual(self.register_run([3, 1], 'user-run', 'night', 'kiln'), record)
        for pages, batch, device in [([1, 3], 'night', 'kiln'), ([3, 1], 'day', 'kiln'),
                                     ([3, 1], 'night', 'other')]:
            with self.subTest(pages=pages, batch=batch, device=device):
                with self.assertRaises(ValueError):
                    self.register_run(pages, 'user-run', batch, device)
        for pages in ([1, 1], [0], [True], [1.5], [None]):
            with self.subTest(invalid=pages):
                with self.assertRaises(ValueError):
                    self.register_run(pages, 'invalid')
        self.assertEqual(self.register_run([3, 1], 'user-run', 'night', 'kiln'), record)

    def test_conflicting_retry_preserves_order_and_identity(self):
        self.register_run((1, 2))
        self.register_run((1,), 'other', device='other-device')
        original = self.page(codes=(2, 1))
        receipt = self.lake.receive_page(original)
        variants = (
            replace(original, codes=(1, 2)),
            replace(original, book=BookRef('charge', 'r1')),
            replace(original, book=BookRef('different', 'r2')),
            replace(original, page_number=2),
            replace(original, device='other-device'),
            replace(original, run_id='other', device='other-device'),
            replace(original, receipt_id='another'),
        )
        for page in variants:
            with self.subTest(page=page):
                with self.assertRaises(ValueError):
                    self.lake.receive_page(page)
        self.assertEqual(pending_pages(self.lake.intake, [('R', 1)])['R', 1], original)
        self.assertEqual(self.lake.receive_page(original), receipt)
        for codes in ((True,), (1.0,), (None,)):
            with self.assertRaises(ValueError):
                self.page(codes=codes)

    def test_rejection_before_intake_commit_keeps_source(self):
        self.register_run()
        page = self.page()
        path = self.source(page)
        with self.assertRaises(CommitRejected):
            self.lake.deliver_source_page(path, commit_probe=reject_commit)
        self.assertTrue(path.is_file())
        self.reopen()
        self.assertEqual(self.intake_state('P'), (None, None))
        with self.assertRaises(ValueError):
            self.lake.clear_source_page(path, None)
        self.assertTrue(path.is_file())
        self.assertTrue(self.lake.deliver_source_page(path).matches(page))

    def test_clear_requires_receipt_for_current_source(self):
        self.register_run((1, 2))
        original = self.page(codes=(2, 1))
        path = self.source(original)
        receipt = self.lake.deliver_source_page(path)
        other = self.lake.receive_page(self.page('Q', page_number=2))
        with self.assertRaises(ValueError):
            self.lake.clear_source_page(path, other)
        self.assertTrue(path.exists())
        self.source(replace(original, codes=(1, 2)))
        with self.assertRaises(ValueError):
            self.lake.clear_source_page(path, receipt)
        self.assertTrue(path.exists())
        self.source(original)
        self.lake.clear_source_page(path, receipt)
        self.assertFalse(path.exists())

    def test_intake_lost_reply_then_clear_and_recover(self):
        self.register_run()
        page = self.page()
        path = self.source(page)
        with self.assertRaises(ReplyLost):
            self.lake.deliver_source_page(path, commit_probe=lose_reply)
        self.assertTrue(path.exists())
        self.reopen()
        record, retained = self.intake_state('P')
        self.assertEqual(retained, page)
        receipt = self.lake.deliver_source_page(path)
        self.assertEqual(receipt, record.receipt)
        self.lake.clear_source_page(path, receipt)
        self.assertFalse(path.exists())
        self.reopen()
        self.assertEqual(pending_pages(self.lake.intake, [('R', 1)]), {('R', 1): page})
        self.lake.publish_book('charge', 'r2', {1: 13})
        result = self.lake.settle('S', 'run', 'R')
        self.assertEqual(result.pages[0].rows[0].kilograms, 13)

    def test_archived_retry_uses_complete_frozen_source(self):
        self.register_run()
        page = self.page(codes=(2, 1, 2))
        receipt = self.deliver_and_clear(page)
        self.lake.publish_book('charge', 'r2', {1: 11, 2: 7})
        self.lake.settle('S', 'run', 'R')
        self.reopen()
        record, payload = self.intake_state('P')
        self.assertIsNone(payload)
        self.assertEqual(record.archived_report, 'S')
        self.assertEqual(self.lake.receive_page(page), receipt)
        with self.assertRaises(ValueError):
            self.lake.receive_page(replace(page, codes=(2, 2, 1)))
        self.assertEqual(self.lake.read_report('S', 'P').pages[0].codes, (2, 1, 2))
