# 炉次复测换页

常规收页、登记、计量和定稿领取沿用 README.md。复测可能和单炉或日批的签发走到一起。计量班先收原件，再办理是否换入。

## 收取复测件

`MeasurementLake.receive_page(page, *, replaces=None, commit_probe=None)` 和 `MeasurementLake.deliver_source_page(path, *, replaces=None, commit_probe=None)` 接受可选的原页实收号。设备文件仍用原格式。省略 `replaces` 或给 `None` 时走普通收页。

`replaces=P` 时，Q 使用一个新实收号，P 必须是已接纳的普通原页并与 Q 同设备、同炉次、同页位。每个 P 最多接纳一份 Q。普通页和候选页的实收号共用原有身份规则。原件与确认同时持久保存，返回可用于 `clear_source_page` 的 `Receipt`。重投相同原件及同一绑定可领取同一个确认，清源和重开之后也可复投。错页位、未知原页、第二个不同候选、同号异件或改绑均抛 `ValueError`，已存结果保持原样。

## 换入与首签

`MeasurementLake.apply_retest(receipt_id, *, commit_probe=None)` 办理已实收的候选 Q。未知候选号抛 `LookupError`。实收确认允许设备清源，待裁决的页位仍使用 P。换页先成功时返回 `('applied', Q)`，以后凡覆盖该页位的定稿都使用 Q。若 P 已先进入正式定稿，则返回 `('already_used', report_id)`，`report_id` 为实际最先使用 P 的已提交定稿号。之后所有覆盖该页位的定稿继续使用 P。

同一仓目录的实例可以交错调用换页和签发。两种结果须对应某个先后次序。待件或签发提交前失败时，页位仍可换入。胜出页缺自己的确切码表时按原规则返回待件，原码顺序及出处跟随胜出原件。原定稿、确认及签发首执仍可按原方式领取。

复测收页与换入沿用 `commit_probe` 的提交边界语义。发生新写入时，`before_commit` 回调抛出的异常阻止该次提交，`after_commit` 回调抛出的异常表示持久结果已经生效但调用方没有拿到答复。异常向调用方传播。重开后同参重试可核回已提交的原结果。

## 班次样例

炉次 R 属于日批 B，设备 D 的第一页原件 P 使用 charge/r1，码 1 计 7 kg。Q 使用 charge/r2，原码为 `[2, 1, 2]`，该版码 2 计 2 kg、码 1 计 9 kg。P 的首签若在提交前失败，换入 Q 后可用同一签发号继续，单炉和日批均领 Q、原序 `[2, 9, 2]` 和 13 kg。P 的首签若已提交后失答，换页须答复该定稿号，之后日批亦领 P 和 7 kg。

保留原回归，运行清单的 verify 须核对原回归及复测换页，demo 须展示清源后的换页结果、胜出页出处及净重。沿用现有 `.pointwise-runtime.json` 的参数数组格式。`python3 -B -m examples.retest baseline` 核对初始工程的提交边界及普通收页。新增能力完成后，可用 `python3 -B -m examples.retest verify` 运行原套件和复测场景，用 `python3 -B -m examples.retest demo` 查看实得裁决与两种范围的定稿。
