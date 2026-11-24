from dataclasses import dataclass
import sqlite3

from lake.catalog.runs import RunRecord, get_run, runs_for_batch


@dataclass(frozen=True)
class SettlementScope:
    kind: str
    identifier: str
    runs: tuple[RunRecord, ...]


def validate_scope_key(kind: str, identifier: str) -> None:
    if kind not in ('run', 'batch'):
        raise ValueError('scope kind must be run or batch')
    if type(identifier) is not str or not identifier.strip():
        raise ValueError('scope identifier must be a nonblank string')


def resolve_scope(connection: sqlite3.Connection, kind: str, identifier: str) -> SettlementScope:
    validate_scope_key(kind, identifier)
    if kind == 'run':
        runs = (get_run(connection, identifier),)
    else:
        runs = runs_for_batch(connection, identifier)
        if not runs:
            raise LookupError(f'unknown batch: {identifier}')
    return SettlementScope(kind, identifier, runs)


def expected_page_slots(scope: SettlementScope) -> tuple[tuple[str, int], ...]:
    return tuple((run.run_id, page) for run in scope.runs for page in run.expected_pages)
