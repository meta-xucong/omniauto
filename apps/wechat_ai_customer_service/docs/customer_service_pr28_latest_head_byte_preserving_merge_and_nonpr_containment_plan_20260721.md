# 新 PR 字节级合并与非 PR 问题收束开发文档

> 状态：开发方案与实施记录；代码在专用分支落地，尚未合并到 `main`。
>
> 适用范围：微信 AI 客服的最新 PR #28（当前审计头 `8f832dd7e2ed78ff5535924b12818475de066a27`）与现有代码的受控合并。
>
> PR 地址：[meta-xucong/omniauto#28](https://github.com/meta-xucong/omniauto/pull/28)

## 1. 先说结论

可以采用“先处理与 PR 无关的问题，再把最新 PR 原样合入，最后只在既有外围适配层做兼容”的方案，但不能承诺所有问题都能在外围解决。

能够在外围、且不增加模块、不改变字段、变量名和对外接口的事项，主要有三类：

1. 修复当前独立 Vision 模块中一个与 PR 无关的旧入口返回值缺失问题。
2. PR 合入后，更新现有运行时适配器里的 PR 头和文件哈希清单，以及历史审计记录的“当前头指针”；这是元数据更新，不改 PR 文件。
3. 检查并修正既有生产调用点，确保它们继续通过现有 `wechat_pr28_runtime_adapter.py` 和现有 Vision 入口工作；不新增包装模块、不改变调用方契约。

不能用外围最小改动可靠修复、应反馈给同事优化 PR 的事项，包括：

- 同侧、等时长语音新增消息导致结构锚点序号漂移；
- Windows 平台下 `_Win32ConFallback` 外部契约快照不稳定；
- Sidecar 仍残留图片判断/动态导入，若要求 Vision 绝对独立则 PR 本身尚未收束干净；
- 只按当前会话标题接受 `open_chat`，可能出现同名会话目标不唯一；
- 私聊同名行变化导致 `rpa_session_key` 漂移；
- PR 删除旧图片入口后，第三方直接调用原始 Connector/Sidecar 图片方法的兼容风险。

这些问题如果用外围硬补，会产生新的字段、状态、分支或二次身份规则，违反本项目的最小变更原则，应在 PR 内部修正后再合并。

本轮只产出本方案文档，不执行下列任何代码改动或 Git 合并。

## 2. 不可突破的边界

以下约束是验收条件，不是建议：

1. **PR 字节级不变**：PR 最新头的 9 个 PR-owned 文件必须逐文件等于 `git show 8f832dd7:<path>` 的字节内容。不得在 PR 文件中加兼容分支、改测试、改文档、改注释或改换行。
2. **不改字段、变量名和对外接口**：现有 Brain、RPA、调度、历史消息、Vision 插件协议、Connector/Sidecar 外部可见名称和参数保持不变。PR 已声明的新增可选参数只能保持其原有默认行为，不得借合并机会再扩展。
3. **不增加模块**：只使用当前已有的 `wechat_pr28_runtime_adapter.py`、现有 Vision 模块、现有测试和既有适配入口；不得新建“补丁模块”“桥接模块”或第二套身份/发送机制。
4. **Brain 仍是唯一回复作者**：任何外围修复只能处理捕获、绑定、调度、证据和发送正确性，不得生成、拼接或替换客户可见话术。必须遵守 [customer_visible_reply_ownership_baseline.md](./customer_visible_reply_ownership_baseline.md)。
5. **外部契约与可插拔边界不变**：Vision 仍是独立可选插件，核心不能在导入时依赖 Vision；所有边界必须遵守 [customer_service_external_contract_and_optional_plugin_baseline.md](./customer_service_external_contract_and_optional_plugin_baseline.md)。
6. **群聊问题冻结**：本次不处理群聊识别、群聊身份、群聊发言人、群聊 session key 等问题。它们只登记为冻结项，不进入本次合并的通过条件，也不能通过私聊代码打补丁“顺手”改变群聊行为。
7. **不覆盖现有用户产物**：当前工作区中已有的未跟踪图片、租户测试数据和 `__pycache__` 修改均视为用户产物，不能删除、重置或格式化。

## 3. 当前基线与审计证据

### 3.1 PR 身份

- PR：#28
- 最新 head：`8f832dd7e2ed78ff5535924b12818475de066a27`
- PR 父提交：`46a7dd0880e71a0fbd158a9a47d021ac2b7a90fc`
- 当前本地工作分支：`codex/pr28-upstream-review-20260720`
- 当前本地 HEAD：`c5e94503385f3c42c085487cb2472439f4e0cc8a`

### 3.2 PR-owned 文件清单

以下 9 个文件视为 PR 的不可修改范围：

1. `apps/wechat_ai_customer_service/adapters/wechat_connector.py`
2. `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
3. `apps/wechat_ai_customer_service/docs/wechat_win32_ocr_sidecar_callable_contract_v1_20260721.md`
4. `apps/wechat_ai_customer_service/tests/fixtures/customer_service_external_contract_snapshot_20260713.json`
5. `apps/wechat_ai_customer_service/tests/run_customer_service_external_contract_compat_checks.py`
6. `apps/wechat_ai_customer_service/tests/run_wechat_image_save_capture_contract_checks.py`
7. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_capture_checks.py`
8. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
9. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_activation_checks.py`

相对 PR 父提交，本地与 PR 的重叠文件包括外部契约快照、外部契约检查脚本和图片捕获契约脚本。直接合并已确认会产生真实冲突，不能采用普通“自动合并后再手工修几行”的方式。

### 3.3 已确认的非 PR 基线问题

当前分支单独运行 `run_wechat_image_save_capture_contract_checks.py` 已失败，失败点是：

- 文件：`apps/wechat_ai_customer_service/optional_plugins/vision/capture/wechat.py`
- 函数：`build_image_saved_payload`
- 现状：旧入口执行了 fail-closed 清理逻辑，但缺少既有返回对象。
- 判断：这是当前 Vision 模块自己的问题，与 PR #28 无关；不能把它归因于 PR。

该问题应在合并前使用原有返回形状补齐，不能新增字段、不能改变旧函数名、不能重新启用已退休的图片保存路径。

### 3.4 最新 PR 的独立审计结果

在 PR head 临时工作树中已确认：

- Win32 OCR 兼容检查：240/240 通过；新增加长语音展开绑定和同 duration 歧义拒绝测试；
- 窗口动作规划检查：28/28 通过；
- OCR 捕获检查：14/14 通过；
- 图片旧入口退休检查：7/7 通过；
- `git diff --check` 与相关文件编译检查通过；
- 外部契约兼容检查在当前 Windows 环境失败 1 项：快照要求 `_Win32ConFallback`，但本机 `win32con` 可正常导入，导致该 fallback 符号不定义。这是 PR 快照/测试的跨平台稳定性问题，不是外围业务代码问题。

新 head 的改动只涉及 `wechat_win32_ocr_sidecar.py` 与其兼容测试：它解决了长语音转写展开后覆盖原语音行时的结构绑定问题，但没有解决同侧同 duration 语音的稳定锚点 ordinal 漂移。另有一个需要上游复核的边界：当只有一个同 duration 候选、但候选距离原锚点很远时，当前逻辑会采用 `unique_duration_after_viewport_shift` 接受，缺少充分的局部位置证据。该项不在外围打补丁，列为 PR 待优化项。

## 4. 分阶段实施方案

### 阶段 0：先修非 PR 问题（本轮不执行）

目标是把合并前基线清干净，避免把旧问题误判成 PR 回归。

1. 仅修改现有 `optional_plugins/vision/capture/wechat.py` 的 `build_image_saved_payload`，恢复其原有返回形状；不添加字段，不修改调用协议，不恢复已退休的旧图片落盘行为。
2. 运行现有图片捕获契约测试，确认该项通过。
3. 对 OCR、RPA、Brain、发送和调度做只读调用链盘点，记录实际入口，不改变实现。
4. 保存当前工作区状态，确保用户现有测试数据、图片和缓存不被清理。

阶段 0 通过标准：除已知 PR 快照平台问题外，当前分支的既有 Vision/非 PR 契约检查不再有失败。

### 阶段 1：创建隔离合并工作树（后续实施）

1. 拉取 `refs/pull/28/head`，确认其指向 `8f832dd7`；如果 head 变化，停止并重新审计，不得默认跟进新 head。
2. 从当前分支创建临时合并分支/工作树，不在用户当前分支直接试错。
3. 对 9 个 PR-owned 文件统一采用 PR head 的完整文件内容。出现冲突时整文件取 PR 版本，不做行级拼接。
4. 对非 PR 文件只保留原有适配和审计元数据；不得把本地新增业务逻辑复制进 PR 文件。
5. 合并后逐文件执行：
   - `git show HEAD:<path>` 与 `git show 8f832dd7:<path>` 字节比较；
   - 搜索冲突标记；
   - `git diff --check`；
   - 相关 Python 文件编译/语法检查。

阶段 1 的结果必须是“PR 文件原样存在”，而不是“功能看起来等价”。

### 阶段 2：只在既有外围做兼容收束（后续实施）

只允许使用现有外围文件和既有接口：

1. 更新 `apps/wechat_ai_customer_service/adapters/wechat_pr28_runtime_adapter.py` 中的 `PR28_HEAD` 与 `PR28_BLOBS`，使其记录 `8f832dd7` 的实际哈希。这个动作只更新版本锁定元数据，不改变 PR 文件。
2. 在既有审计文档中追加新 head 的审计附录，并把旧 head 标成历史记录；不重写历史结论，不覆盖同事 PR 文档。
3. 检查所有生产调用点是否继续经由现有 runtime adapter 和现有 Vision 入口；若只是漏接既有适配器，可在原调用点做等价绑定调整，保持原函数名、参数和返回值不变。
4. 不在 Sidecar、Connector 外围再造图片识别、图片保存、剪贴板读取或第二套 OCR 入口。Vision 的实现、生命周期、失败处理和测试继续由现有独立 Vision 模块承担。
5. 不对 Brain evidence、历史消息字段、session key 字段做新增或改名，也不引入本地回复模板。

### 阶段 3：验收与实机前置检查（后续实施）

按以下顺序执行，任何一项失败即停止，不进入微信实机测试：

1. 非 PR Vision 图片契约测试；
2. PR 原有 240/3/14/7 项测试；
3. 现有 `run_wechat_pr28_additive_integration_audit.py`；
4. 现有 `run_wechat_pr28_runtime_adapter_checks.py`；
5. 现有 `run_customer_service_absolute_vision_module_boundary_checks.py`；
6. 外部契约兼容检查，并在真实 Windows 环境确认 `_Win32ConFallback` 结论；
7. 多会话私聊冒烟：无新消息不点击、不发送；有新消息才进入既有处理链；目标会话二次确认；发送失败不得跨会话重试；
8. 群聊测试标记为冻结，不纳入本次通过条件。

## 5. 问题分类：能否在不动 PR 的前提下解决

| 问题 | 是否可在外围解决 | 处理方式 |
|---|---|---|
| Vision 旧入口缺返回值 | 可以 | 阶段 0 修复现有 Vision 文件，保持原返回形状 |
| 合并后 PR head/文件哈希过期 | 可以 | 更新既有 runtime adapter 元数据和审计附录 |
| 生产调用未走现有 Vision/runtime adapter | 视盘点结果而定 | 只在现有调用点补回既有适配绑定，不改接口、不加模块 |
| 长语音展开后覆盖原行的结构绑定 | 新 PR 已处理 | 保留 PR 文件原样，运行新增的 240 项兼容测试 |
| 同侧等时长语音的 ordinal 锚点漂移 | 仍未解决 | 新 PR 未触及稳定身份算法；外围只能止血去重，不能保证不重复转写 |
| 唯一 duration 但远离原锚点的候选被接受 | 不建议 | 应由 PR 增加 viewport-shift 证据或拒绝测试；外围不增加第二套语音绑定规则 |
| `_Win32ConFallback` 快照平台差异 | 不能可靠解决 | 应由 PR 改为平台中立快照或稳定定义；外围改测试会破坏字节级原则 |
| Sidecar 残留图片识别/动态导入 | 不能在不改 PR 的前提下彻底消除 | 生产路径保持不可达并记录技术债；若要求绝对独立，必须由同事清理 PR |
| `open_chat` 仅按标题/唯一可见名称接受目标 | 不宜外围硬补 | 应在 PR 内加强物理行与 session key 的绑定；外围不能新增第二套身份规则 |
| 私聊同名行变化导致 `rpa_session_key` 漂移 | 不宜外围硬补 | 应在 PR 内重做稳定身份来源；群聊以外同样适用 |
| 旧 Connector/Sidecar 图片方法删除后的第三方直调兼容 | 取决于调用盘点 | 若仓内无调用，保持退休；若外部确有依赖，应先由同事确认兼容窗口，不能在外围私自复活旧入口 |
| PR 残留无效图片 flags/state | 不需要本次处理 | 记录技术债，避免在外围复制同名状态；待同事下一版 PR 清理 |

## 6. 为什么不能用“止血补丁”处理不可外围修复项

上述身份和锚点问题都发生在 PR 内部的“物理观察结果到稳定身份”的转换层。若在外部再加一个计数器、车型关键词表、重复发送拦截器或 session 别名表，会造成：

- 同一消息拥有两套身份；
- Brain 历史与 RPA 当前目标无法证明来自同一会话；
- 新字段或隐式状态穿过模块边界；
- 失败时无法区分捕获错误、绑定错误和发送错误；
- 后续同事优化 PR 时出现第三套兼容行为。

因此本方案只允许修复明确的本地基线错误和版本元数据，拒绝在外围伪造 PR 应提供的稳定身份能力。

## 7. 版本与审计记录要求

合并实施时必须新增一份“最新 head 附录”，至少记录：

- PR URL、head、父提交和合并分支；
- 9 个 PR-owned 文件的最终 blob 哈希；
- 发生过的冲突及“整文件取 PR”的处理结论；
- 阶段 0 修改的非 PR 文件与测试结果；
- 外部适配器更新前后的 head/hash；
- 已知未解决问题及是否属于 PR 内部责任；
- 群聊冻结声明。

旧的 PR 审计文档只追加“已被新 head 取代”的标记，不得删除历史证据或直接改写旧测试结论。

## 8. 最终决策门槛

在以下条件全部满足前，不得宣称“已合并可实测”：

1. 阶段 0 的非 PR Vision 契约测试通过；
2. 9 个 PR-owned 文件与 `8f832dd7` 字节一致；
3. 没有新增模块、字段、变量名、公开接口或第二套会话身份机制；
4. 现有 Brain/RPA/Vision 外部契约测试通过；
5. 外部契约快照的 Windows 平台问题已由同事在 PR 内解决，或明确得到可接受的冻结结论；
6. `open_chat` 目标绑定、私聊 session key 漂移、语音锚点漂移等不可外围修复项已登记给同事，不能被外围“伪修复”；
7. 群聊相关项仍保持冻结，未被本次适配意外改变。

达到门槛后，才进入重启客户端和人工实测；本轮文档阶段不重启进程、不执行合并、不修改源码。

## 9. 本次实施记录（2026-07-21）

本次已在专用分支中开始落地，目标分支不是 `main`，也不会直接合并到 `main`。

已完成的外围改动：

- 修复现有 Vision 旧入口 `build_image_saved_payload` 的 fail-closed 返回值缺失；返回字段沿用原有形状，没有恢复文件保存行为。
- 将既有 `wechat_pr28_runtime_adapter.py` 的 `PR28_HEAD` 和 `PR28_BLOBS` 更新到 `8f832dd7`，用于锁定最新 PR 的实际 blob。
- 将现有 Vision 边界审计从旧 PR 残留字符串检查，更新为对最新 PR 已审计残留入口的检查；没有修改 Sidecar 内容。
- PR-owned 文件在冲突处整文件采用 PR head 内容，未做行级拼接。

当前验证结果：

- 图片旧入口契约：7/7 通过；
- Win32/OCR 兼容：240/240 通过；
- 窗口激活：3/3 通过；
- OCR 捕获：14/14 通过；
- runtime adapter：5/5 通过；
- Vision 边界检查：已按最新 PR 残留规则修正检查口径，待合并提交后复跑；
- 外部契约快照：仍有 1 项已知 PR 内部问题：Windows 环境中 `win32con` 可导入时，快照仍要求不存在的 `_Win32ConFallback`。本问题不在外围修复，已保留为 PR 阻塞项并反馈给同事。

新 head `8f832dd7` 已在专用分支完成受控合并，形成提交 `83317d57`；PR-owned 文件仍采用 PR head 的完整内容。“ancestor + blob”审计已通过，9 个 PR-owned 文件全部一致。外部契约快照仍有 PR 内部的 `_Win32ConFallback` 平台问题，因此后续 PR 应以草稿方式推送给同事修正，未得到确认前不合并 `main`。
