# 榆川炉次计量湖

榆川熔炼厂计量班从投料设备接收编码原页。设备接到确认后会回收源文件，计量员发布的码表可以晚到。加工班按登记范围签发计量日批，质控员下一班按定稿号核对原页及净重。

使用 Python 3.11 标准库。在项目根目录运行完整回归和样例。

```text
python3 -B check_project.py
python3 -B -m examples.shift
```

演示在临时工作目录投递两份样例设备文件，凭确认删除这两份副本，只发旧修订时检查待件，再送达指定修订并签发。原码 `[2, 1]`、`[3]` 依次解释为 7、11、13 kg，炉次合计 31 kg。重开后按第二页实收号查得 13 kg 及该页的出处，并复核整炉合计。

## Python 公开入口

```python
from lake import BookRef, MeasurementLake, PendingSettlement, RawPage

lake = MeasurementLake('shift-data')
lake.initialize()
lake.register('R', 'B', 'D', [1])
ack = lake.receive_page(RawPage('P', 'D', 'R', 1, BookRef('charge', 'r2'), (1,)))
pending = lake.settle('S', 'run', 'R')
assert isinstance(pending, PendingSettlement)
lake.publish_book('charge', 'r2', {1: 13})
issued = lake.settle('S', 'run', 'R')
view = lake.read_report('S', 'P')
assert view.rows[0].kilograms == 13
assert view.totals[0].kilograms == 13
assert view.receipt == issued.receipt
```

- `initialize()` 分别初始化 `intake.sqlite3` 和 `warehouse.sqlite3`，重复执行保留业务记录。样例由显式演示命令运行。
- `register(run_id, batch, device, expected_pages)` 返回固定登记。标识是非空白字符串。页次是唯一的正整数，保留输入次序。空列表表示零页炉次。
- `receive_page(page)` 返回绑定原件的 `Receipt`。每个炉次页位仅接纳一个实收号。同号同参领回原确认，设备、炉次、页次、码表修订或原码序有变化则报 `ValueError`。归档后仍执行同样的判等。
- `deliver_source_page(path)` 读取设备 JSON 并返回确认。文件字段为 `receipt_id`、`device`、`run_id`、`page_number`、`book` 和 `codes`，其中 `book` 含 `name`、`revision`。`clear_source_page(path, receipt)` 核对确认和当前原件后实际删除文件。设备负责在投递和清源操作期间独占管理该路径。清源不匹配报 `ValueError` 并保留文件。
- `publish_book(name, revision, mapping)` 发布具名确切修订，接受整数到整数的映射。同键同映射领回原修订，同键异映射报 `ValueError`。空映射合法。
- `settle(report_id, kind, identifier)` 接受 `run` 或 `batch`，返回 `PendingSettlement` 或 `IssuedReport`。待件逐页指出缺页或缺确切修订。已到的确切修订缺少原码时报 `ValueError`。未知炉次或日批报 `LookupError`。同一个签发号可复领原定稿及首执，异范围报 `ValueError`。另用签发号时按当时的登记范围办理，可以复用先前已签的加工页。
- `read_report(report_id, receipt_id=None)` 领取固定定稿。按页查询限定出处和行，合计及复核取该页所属整炉。未知定稿和定稿范围外的实收号报 `LookupError`。认定复核是否一致可查每炉的 `matches`。

## 计量与持久边界

每行代表 1 kg 精度的整数净重增量，允许负值与零。整数输入拒绝布尔值、浮点及空值。重复码逐位置计量。空原码页需要确切修订，带页出处但没有标准行。批内按炉次首次登记顺序，炉内按登记页序，页内位置从 1 起。页号、原码、读值与合计的持久表示保持整数精度。

原页与确认在采集库同一事务落定。加工页、固定快照、按炉合计和首执在湖仓同一事务落定。提交前异常无该次成功记录，提交后失答按原号重新领取。`receive_page`、`deliver_source_page` 和 `settle` 的可选 `commit_probe` 回调在实际写事务的 `before_commit`、`after_commit` 边界运行，回调异常向调用方传播。

签发后的原页结清由已提交的定稿出处驱动，在采集库单独提交。失答后重试 `settle` 会从原定稿继续结清，也可调用 `finish_handoffs(report_id)`。审计读取使用固定成果。清源和归档后，原来源、清源凭据、签发凭据与合计均可核回。
