from dataclasses import dataclass

from lake.process.staging import StagedPage


@dataclass(frozen=True)
class StandardRow:
    receipt_id: str
    position: int
    raw_code: int
    kilograms: int


def decode_page(staged: StagedPage) -> tuple[StandardRow, ...]:
    page = staged.page
    rows = []
    for position, code in enumerate(page.codes, start=1):
        try:
            kilograms = staged.revision.mapping[code]
        except KeyError:
            ref = staged.revision.ref
            raise ValueError(
                f'undefined code {hex(code)} at {page.receipt_id} row {position} '
                f'in {ref.name}/{ref.revision}'
            ) from None
        rows.append(StandardRow(page.receipt_id, position, code, kilograms))
    return tuple(rows)
