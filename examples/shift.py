import json
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from lake import BookRef, MeasurementLake, PendingSettlement


def main():
    samples = Path(__file__).resolve().parent
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        lake = MeasurementLake(root / 'lake').initialize()
        lake.register('R', 'B', 'D', [1, 2])
        for sample in ('P1.json', 'P2.json'):
            source = root / sample
            copyfile(samples / sample, source)
            receipt = lake.deliver_source_page(source)
            lake.clear_source_page(source, receipt)
            if source.exists():
                raise RuntimeError('device source was not cleared')

        lake = MeasurementLake(root / 'lake').initialize()
        lake.publish_book('charge', 'r1', {1: 70, 2: 71, 3: 72})
        pending = lake.settle('S', 'batch', 'B')
        if not isinstance(pending, PendingSettlement) or len(pending.missing) != 2:
            raise RuntimeError('expected waiting pages before the exact revision')
        if any(part.kind != 'revision' or part.book != BookRef('charge', 'r2')
               for part in pending.missing):
            raise RuntimeError('waiting pages do not identify the required revision')
        lake.publish_book('charge', 'r2', {2: 7, 1: 11, 3: 13})
        issued = lake.settle('S', 'batch', 'B')
        next_shift = MeasurementLake(root / 'lake').initialize()
        audit = next_shift.read_report('S', 'P2')
        actual = {'readings_kg': [row.kilograms for page in issued.pages for row in page.rows],
                  'total_kg': issued.totals[0].kilograms}
        downstream = {'receipt_id': audit.pages[0].receipt_id,
                      'revision': audit.pages[0].book.revision,
                      'readings_kg': [row.kilograms for row in audit.rows],
                      'recomputed_kg': audit.reconciliation[0].recomputed_kilograms}
        if actual != {'readings_kg': [7, 11, 13], 'total_kg': 31}:
            raise RuntimeError(f'wrong daily measurement: {actual}')
        expected_audit = {'receipt_id': 'P2', 'revision': 'r2', 'readings_kg': [13],
                          'recomputed_kg': 31}
        if downstream != expected_audit or audit.receipt != issued.receipt:
            raise RuntimeError(f'wrong archive readback: {downstream}')
        print(json.dumps({'report_id': issued.receipt.report_id, 'serial': issued.receipt.serial,
                          'run': issued.totals[0].run_id, **actual, 'audit': downstream}, indent=2))


if __name__ == '__main__':
    main()
