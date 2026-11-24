from dataclasses import dataclass

from lake.catalog.revisions import BookRef
from lake.intake.pages import RawPage


@dataclass(frozen=True)
class PageProvenance:
    receipt_id: str
    device: str
    run_id: str
    page_number: int
    book: BookRef
    codes: tuple[int, ...]

    def as_raw_page(self) -> RawPage:
        return RawPage(self.receipt_id, self.device, self.run_id, self.page_number,
                       self.book, self.codes)


def capture_provenance(page: RawPage, interpreted_with: BookRef) -> PageProvenance:
    if interpreted_with != page.book:
        raise ValueError(f'interpretation did not use the specified revision: {page.receipt_id}')
    return PageProvenance(page.receipt_id, page.device, page.run_id, page.page_number,
                          interpreted_with, page.codes)
