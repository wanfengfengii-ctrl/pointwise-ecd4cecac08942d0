import json
from pathlib import Path

from lake.catalog.revisions import BookRef
from lake.intake.pages import RawPage
from lake.intake.receipts import Receipt


_SOURCE_FIELDS = {'receipt_id', 'device', 'run_id', 'page_number', 'book', 'codes'}


def _read_source_page(path: Path) -> RawPage:
    with path.open(encoding='utf-8') as source:
        data = json.load(source)
    if not isinstance(data, dict) or data.keys() != _SOURCE_FIELDS:
        raise ValueError('invalid device page fields')
    book = data['book']
    if not isinstance(book, dict) or book.keys() != {'name', 'revision'}:
        raise ValueError('invalid device codebook reference')
    return RawPage(data['receipt_id'], data['device'], data['run_id'], data['page_number'],
                   BookRef(book['name'], book['revision']), data['codes'])


def deliver_source_page(path, receive, *, replaces=None, commit_probe=None) -> Receipt:
    page = _read_source_page(Path(path))
    if replaces is None:
        receipt = receive(page, commit_probe=commit_probe)
    else:
        receipt = receive(page, replaces=replaces, commit_probe=commit_probe)
    if not isinstance(receipt, Receipt) or not receipt.matches(page):
        raise ValueError('delivery did not return a matching receipt')
    return receipt


def clear_source_page(path, receipt: Receipt) -> None:
    if not isinstance(receipt, Receipt):
        raise ValueError('device requires a receipt to clear a source')
    source = Path(path)
    if not receipt.matches(_read_source_page(source)):
        raise ValueError('receipt does not match the current device source')
    source.unlink()
