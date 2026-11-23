# 混料夜班签报

白班先用 README 中的 V1 入口为两份同工艺校准样本各发行一件。交班单里的比例指右件所代表的来料占比，左件占其余份额。校准样本的笔数只用于本件内估计频率。夜班拿到交班单和两份固定件后，可以独立实收和签报。

## 调用约定

仍用 Python 3.11 标准库与 SQLite。`offline` 由 `handover.report_store.initialize_offline(connection)` 返回。来源库可关闭后再调用实收和签报。四个新增入口如下。

- `freeze.issue.freeze_mix(left_payload, right_payload, low, high)` 返回 `(mix_id, manifest)`。左右参数是 V1 `encode_evidence` 生成的 `bytes`。两件均须有效。交班单正文 `manifest` 为 `bytes`，`mix_id` 为字符串。按同一顺序传入同两件和数值相同的两界，生成相同正文及单号。单号绑定有序双亲的 V1 身份及精确闭区间。闭区间满足 `0 <= low <= high <= 1`。非法参数或坏件抛 `IssuanceRejected`。
- `freeze.receive.receive_mix(offline, expected_id, manifest, left_payload, right_payload)` 返回实收号，值同通过核验的 `expected_id`。`expected_id` 是单独交给夜班的预期交班单号。核对正文和该单号，再核对两份 V1 固定件的完整性及其逐位身份。拒绝损坏、异版、换序或改区间的投递，抛 `ReceiptRejected`，且无新交班单实收。重交同一有效组合返回原实收号。实收后可凭该号在离线库取得两件的固定内容及区间。
- `handover.publish.sign_mix_report(offline, mix_id, completion_min, review_max)` 返回 `(report_id, passed)`，分别为正整数和布尔值。仅使用实收号对应的组合。两门槛分别为正有理数和非负有理数。签存成功才返回报告号，通过和不通过均可定稿。非法门槛抛 `ValueError`。无有效实收单或签存失败抛 `ReportSigningFailed`。提交失败留下的报告数量和此前定稿内容与调用前一致。
- `handover.reports.get_mix_report(offline, report_id)` 返回 `(passed, mix_id, (left_provenance, right_provenance), (low, high), (completion_min, review_max))`。双亲出处使用原 `EvidenceProvenance`，比例界和门槛以 `Fraction` 领取。未知报告号抛 `ReportNotFound`。重开读取存档判定，旧 V1 定稿继续经原入口按号领取。

比例界和门槛的输入使用 `int` 或 `Fraction`，布尔值非法。交班正文及其身份编码由实现确定。V1 固定件的字节格式、原签发和领取接口沿用 README。用新版初始化打开已有 V1 工作库后，原实收及报告仍可使用。

## 核定口径

对闭区间内每个实数占比 `t`，以左份额 `1−t`、右份额 `t` 混合每一工类在两件中的联合频率。联合行包括该次处置的子件组合及复核标记。同类各次处置独立，从一件常规件开工，所有子件结清才计作全批结案。沿用 V1 的结案概率和条件复核定义，以精确口径判定两条含等号的门槛。

结案概率为零的点直接失格。临界指结案条件下每件常规件的普通子件均值为 1。若该点每件常规件自身及其直接转出的专检链的预期复核贡献为零，条件复核次数记为零。贡献为正则条件复核次数为无穷，该点失格。

## 取数与核验

`mix_fixture.issue_pair(source, name, right_copies=1)` 用样例原始处置单经 V1 录入和发行，返回左右两个 `FrozenEvidence`。每组样例宜用新来源库。`right_copies=2` 为右侧每条处置再登记一份独立原号。`samples/mix_calibrations.json` 的每行依次为常规子件数、专检子件数、复核标记和原始处置笔数。`python3 -B mix_fixture.py` 可查看 V1 的八个端点签发结果。

- `critical` 的左端为 `(1,3/2)`，右端为 `(1/3,3/2)`，括号内依次是结案概率和条件复核次数。门槛为 `(1/3,2)` 时，左右单点窗都通过，[0,1] 不通过。半混时复核无穷，以 `(1/3,4)` 核定半混单点窗也不通过。复制右侧样本后这些判定相同。
- `zero-knot` 的结案概率恒为 1，左端复核为 0，正占比时复核为 4。门槛为 `(1,2)` 时，[0,0] 通过，[0,1] 不通过。复核上限为 4 时，[0,1] 通过。
- 样例 `interior-peak` 以 `(1,17/50)` 核定 `[0,1]` 不通过。两端复核均为 0，半混时为 `1/3`，右件占 `3/5` 时为 `12/35`。把复核上限提高到 `7/20` 后整窗通过。
- `renewal` 的左端从不全批结案，门槛为 `(1,0)` 时，[0,1] 不通过，[1/10,1] 通过。

联合核验还应覆盖同频异身份固定件、逆序、改窗和同单重交。可对同一双亲分别发行 `[0,1]` 与 `[0,0]`，以前者预期单号投递后者正文应拒收。验证真实签存失败后可重试，关源重开工作库后可同时领取 V1 定稿和新报告。

沿用根目录 `.pointwise-runtime.json` 的 `version=1`、`kind=cli` 与 `setup` 参数数组列表。更新 `verify` 和 `demo` 参数数组。`verify` 执行原回归和混料业务核验，核验失败退出非零。`demo` 用样例展示实际混料签报及停源重开后的原号领取。
