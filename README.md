# 返修试验室班组核账

试验室为工业维修班组复验返修件。白班记录员录入试验台的具名处置单，质量员按版核账并勘误。夜班排班员在来源账本停用后，凭实收件估报结案风险和可结案批次的人工复核量。接班员按原号领取定稿，对照各自的固定出处。

## 运行

使用 Python 3.11 标准库和随 Python 提供的 SQLite。从项目根目录运行。

```sh
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 由运行平台提供，它执行 `tests` 包的完整回归。演示从 `samples/` 读取处置单和勘误单，在临时目录内走完整流程。两次签发的结案概率均为 `1`，原版复核 `1` 次，勘误版复核 `0` 次。重开工作库后按交接顺序打印实领结果。

## 一天的业务流程

1. 打开来源 SQLite 连接并调用 `intake.source_store.initialize_source(connection)`。离线工作库用另一个连接调用 `handover.report_store.initialize_offline(connection)`。空库首次建账，正确的既有库保留原身份和班组写入。类型或结构不兼容时抛出 `ledger_sql.StoreInitializationError`。
2. 调用 `intake.import_records.record_batch(source, batch_id, records)`，传入 `intake.outcomes.TrialRecord(record_id, source_ref, work_class, disposition)` 序列。`Disposition(ordinary_children, special_children, review)` 接受整数子件数和布尔标记。工类用 `WorkClass.ORDINARY` 或 `WorkClass.SPECIAL`。返回起始 `Revision`。处置非法抛出 `InvalidDisposition`，空批、批号或原号冲突抛出 `BatchRejected`。原号在一个来源库内唯一。
3. `revision.count_audit.audit_revision(source, revision_id)` 返回 `AuditResult`，包括出处、父版、联合行、工类小计及总笔数。`revision.amendments.amend_revision(source, parent_id, record_id, disposition)` 返回 `(Revision, AuditResult)`。更正发生在明确父版上，保留原号、工类和台架来源。`RevisionNotFound`、`RecordOutsideRevision` 或 `InvalidDisposition` 分别表示未知版、记录不在所选版内或非法更正。兄弟版和历史核账继续可查。
4. `freeze.issue.freeze_revision(source, revision_id)` 返回 `FrozenEvidence`。每行同时保存工类、子件数、复核标记、联合计数和以工类总数为分母的频率。未知修订、缺任何工类或专检结案频率为零时抛出 `IssuanceRejected`。`freeze.evidence_codec.encode_evidence(evidence)` 将固定件编码为确定性的 JSON 字节。件号是绑定来源库、批号、修订和完整联合行的 SHA-256 摘要。
5. `freeze.receive.receive_evidence(offline.evidence, payload, evidence.provenance)` 在离线工作库验收并返回实收件号。坏件或出处错配抛出 `ReceiptRejected`。完全相同的固定件可以重复交接，实收件号保持一致。
6. 关闭来源连接。`handover.publish.sign_report(offline, evidence_id)` 按指定实收件签发 `SignedReport`。无可用证据或签存失败抛出 `ReportSigningFailed`，提交成功后才返回定稿号。签存失败时原报告仍可领取。
7. `handover.reports.get_report(offline, report_id)` 按原号领取精确值和随签出处。未知号抛出 `ReportNotFound`。`handover.shift_queue.collect_shift_reports` 按交接清单顺序领取，`handover.export.export_shift_reports` 将结果导出为 JSON 数组。空清单导出 `[]`，重复定稿号按输入顺序出现。
8. 勘误后按新修订再发行、实收和签报。接班员重开工作库后仍能按原号同时领取新旧定稿。历史领取读取存档原值，不重新分析。

公开入口接收调用者管理的 `sqlite3.Connection`，使用默认的行和文本表示。初始化及事务写入前，调用者应结束已有事务。审计和冻结读取既有修订，试验处置原记录只使用正常录入接口写入。

## 业务口径

一条处置单对应一次处置。当次结案没有子件。常规件也可派生一或两件常规件，或转一件专检件。专检件只可当次结案或派生一件专检件。复核标记为真时，本次增加一次人工复核。

排班以一件常规件为起点，同类各次处置按所选版频率独立。所有子件结清才算全批结案。结案概率是 `0` 到 `1` 的精确 `Fraction`。人工统计以每个已结案批次的复核次数为单位。结案概率为零时，状态为 `not_applicable`，值为空。结案概率为正时，状态为 `finite` 或 `infinite`。有限值使用 `Fraction`，可以为零。导出用分数字符串保存精确值，`infinite` 和 `not_applicable` 的 `value` 均为 JSON `null`，两者由状态区分。

确定性回归覆盖原始记录与父链、非法整批拒绝、重开和重复初始化、发行与实收边界、断源核算、提交失败回滚以及原号领取。分析场景使用固定计数和独立手算值，包含无法结案、有限正工时、有限零工时和临界无穷。
