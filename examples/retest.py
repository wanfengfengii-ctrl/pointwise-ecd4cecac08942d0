"""Device inputs and public-API checks for the retest handoff."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

import check_project
from lake import BookRef, MeasurementLake, PendingSettlement, RawPage
from tests.support import CommitRejected, ReplyLost, lose_reply, reject_commit


def require(condition, message):
    if not condition:
        raise AssertionError(message)


@contextmanager
def raises(exception):
    try:
        yield
    except exception:
        return
    raise AssertionError(f"expected {exception.__name__}")


def write_source(root, page):
    path = root / f"{page.receipt_id}.json"
    path.write_text(json.dumps(asdict(page)), encoding="utf-8")
    return path


def reopen(root):
    return MeasurementLake(root / "lake").initialize()


def prepare(root):
    root.mkdir()
    lake = reopen(root)
    lake.register("R", "B", "D", [1])
    original = RawPage("P", "D", "R", 1, BookRef("charge", "r1"), (1,))
    candidate = RawPage("Q", "D", "R", 1, BookRef("charge", "r2"), (2, 1, 2))
    path = write_source(root, original)
    ack = lake.deliver_source_page(path)
    lake.clear_source_page(path, ack)
    require(not path.exists(), "original device file was not cleared")
    return lake, original, candidate, ack


def read_weight(lake, report_id, page, readings):
    view = lake.read_report(report_id, page.receipt_id)
    require(tuple(p.as_raw_page() for p in view.pages) == (page,), "wrong frozen source")
    require([(r.position, r.raw_code, r.kilograms) for r in view.rows]
            == [(i, code, kg) for i, (code, kg) in enumerate(zip(page.codes, readings), 1)],
            "wrong original code order or readings")
    require([(t.run_id, t.kilograms) for t in view.totals] == [("R", sum(readings))],
            "wrong frozen total")
    require(all(check.matches for check in view.reconciliation), "report does not reconcile")
    require(lake.read_report(report_id).pages == view.pages, "scope selects a different page")
    return {"report": report_id, "source": page.receipt_id, "revision": page.book.revision,
            "codes": page.codes, "rows_kg": readings, "total_kg": view.totals[0].kilograms,
            "serial": view.receipt.serial}


def baseline(root, probe, exception):
    lake, original, candidate, ack = prepare(root)
    lake.publish_book("charge", "r1", {1: 7})
    lake.publish_book("charge", "r2", {1: 9, 2: 2})
    with raises(exception):
        lake.settle("S", "run", "R", commit_probe=probe)
    lake = reopen(root)
    if exception is CommitRejected:
        with raises(LookupError):
            lake.read_report("S")
    else:
        read_weight(lake, "S", original, [7])
    path = write_source(root, candidate)
    with raises(ValueError):
        lake.deliver_source_page(path)
    require(path.exists(), "refused device file must remain")
    lake.settle("D1", "batch", "B")
    require(lake.receive_page(original) == ack, "lost original confirmation")
    return read_weight(lake, "D1", original, [7])


def check_wait(lake, page):
    result = lake.settle("S", "run", "R")
    require(isinstance(result, PendingSettlement), "settlement should be waiting")
    require([(m.kind, m.run_id, m.page_number, m.receipt_id, m.book) for m in result.missing]
            == [("revision", page.run_id, page.page_number, page.receipt_id, page.book)],
            "waiting material names the wrong receipt or codebook")


def try_after_rollback(root):
    lake, original, candidate, original_ack = prepare(root)
    path = write_source(root, candidate)
    with raises(CommitRejected):
        lake.deliver_source_page(path, replaces="P", commit_probe=reject_commit)
    require(path.exists(), "failed intake cleared the device file")
    with raises(LookupError):
        reopen(root).apply_retest("Q")
    with raises(ReplyLost):
        lake.deliver_source_page(path, replaces="P", commit_probe=lose_reply)
    lake = reopen(root)
    ack = lake.deliver_source_page(path, replaces="P")
    lake.clear_source_page(path, ack)
    require(not path.exists(), "candidate device file was not cleared")
    lake = reopen(root)
    require(lake.receive_page(candidate, replaces="P") == ack, "lost candidate confirmation")
    with raises(ValueError):
        lake.receive_page(replace(candidate, receipt_id="Q2"), replaces="P")
    with raises(ValueError):
        lake.receive_page(replace(candidate, codes=(1, 2, 2)), replaces="P")
    check_wait(lake, original)
    lake.publish_book("charge", "r1", {1: 7})
    with raises(CommitRejected):
        lake.settle("S", "run", "R", commit_probe=reject_commit)
    lake = reopen(root)
    with raises(LookupError):
        lake.read_report("S")
    with raises(ReplyLost):
        lake.apply_retest("Q", commit_probe=lose_reply)
    lake = reopen(root)
    decision = lake.apply_retest("Q")
    require(decision == ("applied", "Q"), "failed settlement consumed the slot")
    check_wait(lake, candidate)
    lake.publish_book("charge", "r2", {1: 9, 2: 2})
    issued = lake.settle("S", "run", "R")
    lake.settle("D1", "batch", "B")
    lake = reopen(root)
    require(lake.receive_page(original) == original_ack, "lost original confirmation")
    require(lake.receive_page(candidate, replaces="P") == ack, "lost archived confirmation")
    require(lake.apply_retest("Q") == decision, "applied verdict changed after issuance")
    require(lake.settle("S", "run", "R").receipt == issued.receipt, "changed publication receipt")
    with raises(LookupError):
        lake.read_report("S", "P")
    return {"decision": decision, "run": read_weight(lake, "S", candidate, [2, 9, 2]),
            "batch": read_weight(lake, "D1", candidate, [2, 9, 2])}


def overlap(root, retest_first):
    lake, original, candidate, original_ack = prepare(root)
    path = write_source(root, candidate)
    ack = lake.deliver_source_page(path, replaces="P")
    lake.clear_source_page(path, ack)
    require(not path.exists(), "candidate device file was not cleared")
    lake.publish_book("charge", "r1", {1: 7})
    lake.publish_book("charge", "r2", {1: 9, 2: 2})
    peer = reopen(root)
    committed = Event()
    peer_started = Event()

    def pause_reply(phase):
        if phase == "after_commit":
            committed.set()
            require(peer_started.wait(10), "peer did not start while reply was paused")
            raise ReplyLost(phase)

    def first():
        if retest_first:
            return lake.apply_retest("Q", commit_probe=pause_reply)
        return lake.settle("Z-first", "run", "R", commit_probe=pause_reply)

    def second():
        peer_started.set()
        if retest_first:
            return peer.settle("Z-first", "run", "R")
        return peer.apply_retest("Q")

    with ThreadPoolExecutor(max_workers=2) as workers:
        earlier = workers.submit(first)
        if not committed.wait(10):
            earlier.result(timeout=20)
            raise AssertionError("first operation did not reach the commit probe")
        later = workers.submit(second)
        with raises(ReplyLost):
            earlier.result(timeout=20)
        second_result = later.result(timeout=20)

    expected = ("applied", "Q") if retest_first else ("already_used", "Z-first")
    page, readings = (candidate, [2, 9, 2]) if retest_first else (original, [7])
    lake = reopen(root)
    first_report = read_weight(lake, "Z-first", page, readings)
    if retest_first:
        require(second_result.receipt == lake.read_report("Z-first").receipt, "wrong peer receipt")
    else:
        require(second_result == expected, "wrong refusal after committed use")
    lake.settle("A-next", "batch", "B")
    lake = reopen(root)
    require(lake.apply_retest("Q") == expected, "wrong verdict after reopen and batch issuance")
    require(lake.receive_page(original) == original_ack, "lost original confirmation")
    require(lake.receive_page(candidate, replaces="P") == ack, "lost candidate confirmation")
    return {"decision": expected, "run": first_report,
            "batch": read_weight(lake, "A-next", page, readings)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "verify", "demo"))
    args = parser.parse_args()
    if args.mode == "verify" and check_project.main():
        return 1
    with TemporaryDirectory() as directory:
        root = Path(directory)
        if args.mode == "baseline":
            result = {"before_commit": baseline(root / "before", reject_commit, CommitRejected),
                      "after_commit": baseline(root / "after", lose_reply, ReplyLost)}
        else:
            result = {"after_rollback": try_after_rollback(root / "rollback"),
                      "report_first": overlap(root / "report", False),
                      "retest_first": overlap(root / "retest", True)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
