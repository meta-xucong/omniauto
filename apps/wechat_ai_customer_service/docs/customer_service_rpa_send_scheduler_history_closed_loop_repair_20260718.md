# 微信客服 OCR/RPA 发送、调度与历史闭环修复方案（2026-07-18）

本文服从并引用：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

本轮只修复代码机制层。`customer_service_brain` 仍是客户可见回复的唯一作者；商品证据、Brain 输入输出、RPA 对外调用方式、模块间参数、配置键、持久化字段、event/action/reason 名称、HTTP/CLI/import 合同均不增加、不删除、不改名、不改变类型。

> 2026-07-19 复盘修正：本文早期把“输入框已清空且目标窗口仍可读”列为真实发送的快速成功依据，这个结论已被实机事故否定。它只能证明触发动作发生、输入面板发生变化，不能证明微信生成了我方消息气泡。下文涉及真实客户发送的快速确认描述，均由本修正覆盖：除明确的文件传输助手模拟回环外，真实发送必须读取到匹配文本的我方/右侧结构气泡才可标记 `verified=true`。

## 1. 已确认的根因

1. Win32/OCR 快速确认把“已经触发 Enter/点击且窗口仍可读”误当成“消息已经发出”，没有验证输入框是否发生发送后的清空效果。
2. 接近纯白的输入框静态边框会产生少量 OCR 框，旧判定把它当成真实草稿，执行 96 次退格和 8 次删除，既慢又会导致 `send_input_not_ready`。
3. 直接工作流会延期无触发的传输失败，但 scheduler 收集 send future 后直接写成终态 `send_failed`，同一故障在两条路径的处理不一致。
4. 多气泡的中间气泡把 transport `ok` 当成已验证；后续气泡失败时，已发出的部分没有进入历史上下文，旧客户消息又可能被整轮重放。
5. 进程重启后，持久化的 `sending` 回复直接失败，没有先检查最近的我方消息，也没有进入安全重捕获。
6. bridge 每轮先同步轮询会话，再让 runtime 收集已完成的 send future；轮询与仍在运行/刚完成的发送会争用同一 RPA 锁。
7. `pending_session_ttl_seconds` 只清理 queued LLM/polish 和 ready reply，没有处理陈旧 `pending_capture`，不可达会话能长期占用调度。
8. 已确认会话与早期 `configured/unknown` 会话键可能分裂历史；仅按显示名模糊合并又会造成同名私聊/群聊串线。
9. freshness 在安全的唯一名称/旧键漂移时仍可能退化成完整消息 OCR，增加 8–18 秒延迟；完整 OCR 与实际发送之间仍存在时间窗口。
10. 实机 scheduler state 已增长到约 30MB；bridge、freshness、capture 和 Brain 上下文读取曾在同一轮重复完整解析该文件。小状态单元测试无法暴露这类阻塞，造成“自问自答通过、人工多会话卡住”。
11. 实机一轮前台 OCR 可耗时 20–40 秒；旧顺序会连续捕获多个会话后才收割已经完成的 planner/polish future，导致回复明明生成却长期不进入发送。
12. sidecar 每次调用都是新进程，旧逻辑先因内存 session-key 缓存为空而完整 OCR 失败，再打开会话并重复 OCR；当前会话也可能被重复点击，产生选中行折叠/界面隐藏等误操作。
13. 微信侧栏可能在我方已回复后仍保留客户旧预览，并把时间更新成我方回复的分钟；OCR 又可能用两个英文句点截断。旧回放判断不认识该形态，会把已闭环客户消息重新当作新信号。
14. 人工停止进程后遗留的 queued/running planner、polish 或 ready reply 超时恢复时，旧清理会把未回复计数直接归零，后续追加消息因此可能没有可恢复的客户轮次。

## 2. 不可突破的合同

- 不修改 `CustomerServiceSchedulerRuntime.__init__`、`tick`、connector、sidecar、Brain bridge、RPA send/capture 的公开签名。
- 不向 scheduler state、session ledger summary/event、send payload、Brain payload、配置文件增加字段。
- 不删除或重命名任何现有字段、状态、事件、reason 或 import path。
- 不通过本地模板补写客户可见内容；发送失败只能延期、重捕获、对账或内部交接。
- 不把显示名相同当成发送身份；实际发送仍只使用原 session key、conversation type 和目标确认链。
- 不在测试中启动真实 AI 客服，不操作微信窗口，不发送真实消息。

## 3. 内部修复设计

### 3.1 输入框与发送确认

- 保留现有像素阈值和 OCR 辅助，只把“极高均值、极低暗像素”的静态 chrome 投影为空白；真实短草稿仍因暗像素超过阈值而被保护。
- 复用 `validate_post_send_target` 已有截图判断触发动作后的输入区变化，但它只作为传输诊断证据，不作为真实客户发送成功证据。
- 输入区无论是否已空，真实客户发送都必须进入既有消息读取验证；只有匹配文本的明确我方 sender，或具有右侧/self lane 结构证据的气泡，才可确认发送。客户气泡中恰好出现相同文本不得误判为我方已发送。
- `guarded_send_confirmation_fallback`、`blind_send_without_ocr` 和快速 guard 确认仅保留给明确的文件传输助手模拟回环，不进入真实客户链路。

### 3.2 scheduler 发送失败恢复

- 递归读取现有 send payload，区分“明确无触发、已触发/不确定、部分已发”。不新增结果字段。
- 明确无触发且首次失败：用现有 `ready`、`send_attempts`、`last_send_error`、`send_result` 恢复同一 Brain 回复；本轮不立即重派，防止紧循环。
- 第二次仍失败：写现有 `send_failed`，并用现有 pending session 重新捕获，避免永久静默。
- 已有 `sent_segments > 0`：绝不重发整轮；把已确认的我方文本写入 ledger 最近消息，但不把原客户输入标成已处理，然后进入重新捕获/对账。

### 3.3 重启与 RPA 串行化

- bridge 通过 runtime 私有回调对 orphaned `sending` 回复读取目标会话最近消息；只有先找到本轮冻结的客户输入消息锚点、再在锚点后匹配到原 Brain 文本，才按现有 `sent` 完成。历史上相同文字不得冒充本轮发送。
- 未匹配或读取不确定时，不盲发；按现有 `stale + pending capture` 进入对账。
- 只要 runtime 仍持有 send future（包括已经完成但尚未 collect），bridge 本轮跳过 session poll，先收割发送结果，消除 RPA 锁竞争。

### 3.4 pending、历史与 freshness

- TTL 到期且没有其他 active task 的 pending：有未读/未回复证据则转现有 `internal_handoff_pending` 并保留计数/时间；无证据才回到 `idle`。不静默丢消息。
- 只合并“当前已确认 key + 同名唯一的 configured/unknown 旧 key”的 ledger 上下文；两个已确认 key、同名多会话、私聊/群聊冲突一律不合并。合并严格复用既有 `merge_session_alias_context`、summary 字段和 event 合同，只在其内部利用既有 `merged_session_aliases` 做幂等去重，不新增或删除公开方法、字段与事件。
- 旧 OCR 的独立联系人名/群名行只在 Brain 历史读投影中过滤，不重写 append-only ledger。
- freshness 的 key 漂移只允许在当前 monitor/list 里按唯一精确显示名回退；这只用于判断新消息，不改变发送目标。
- 发送前仍保留目标/session 严格确认；发送后的输入清空只保留为传输诊断，实际成功仍由我方气泡闭环；下一轮 monitor 继续捕获发送窗口内新到的客户消息。

### 3.5 多会话公平调度、重复预览与界面误点击

- 每轮进入新的前台 OCR/RPA 捕获前，先收割已完成的图片、planner、polish future，并优先推进已经可以发送的回复，防止慢图片/历史捕获把其他会话已生成的回复长期堵住。
- 前台捕获轮使用内部时间预算；单个会话捕获超时后，本轮主动让出，其余会话继续以现有 `pending_capture` 持久化，下一轮推进。该预算不增加任何模块间字段、事件或状态名。
- monitor 已有同一 session 的最新、唯一、无未读快照时，freshness 直接复用该快照；过期、未知、存在未读或同名歧义时仍走原严格读取，不牺牲跨会话安全。
- 对“同一红点已经确认、消息时间没有变化、侧栏预览只是 OCR 修正/截断/追加群成员标签”的情况，monitor 不能仅凭文本相似就吞掉信号；稳定变化仍进入一次真实聊天窗捕获。只有聊天窗没有发现新 occurrence，且 ledger 中存在同时间的完整客户输入、其后已有我方回复、当前没有未回复证据时，才消费该侧栏 fallback，不再把截断旧文合成为 Brain 新输入。新时间、不同正文、未回复 ledger 或聊天窗中的新 occurrence 均继续回复。
- 打开会话时，若当前标题与目标唯一严格匹配，直接绑定当前会话，不再次点击已经选中的侧栏行；只有当前目标不匹配时才执行行切换，同名歧义继续 fail-closed。这样消除选中行被重复点击后折叠/隐藏聊天面板的误操作。
- 群聊类型与成员名只依据结构证据修正：当前标题存在 `(人数>=2)` 时按群聊解析；左侧气泡上方独立、短标签才投影为既有 `speaker_name/group_member_name`，不进入 Brain 正文。不使用账号、车型或话术关键词规则。

### 3.6 真实大状态与人工多会话修复

- runtime 在状态文件身份、大小和修改时间均未变化时复用同一内存状态；外部/后台原子替换会立即使缓存失效。bridge 只读取 runtime 的只读顶层投影，Brain 工作线程只读取按 session key 隔离的小型会话上下文快照，不再每个会话重复解析完整任务历史。
- 不删除、裁剪、改名或迁移 scheduler state 任何现有字段；缓存和投影仅为进程内私有优化，旧 store、轻量测试桥和第三方调用形态继续兼容。
- 每次前台捕获前先收割完成的 planner/polish；任一捕获达到内部轮预算或检测到异步结果已完成，本轮立即让出。未捕获会话继续保留原 `pending_capture`，而不是被清掉或限制成单目标。
- 动态监听仍面向所有通过既有客户会话准入、且不在服务号/系统会话排除列表中的新会话；任何新消息都进入同一调度链，不增加账号白名单、车型关键词或结构化回复规则。
- fresh sidecar 通过“当前标题严格匹配 + 侧栏唯一行 + 原 session key”绑定当前会话时不执行点击；只有标题不匹配且唯一 session-key 行被确认时才切换。搜索 fallback 默认继续关闭。
- 空聊天窗捕获后的旧预览回放只在 ledger 已存在同文客户输入、其后已有我方回复、无未回复证据，且预览为明确截断并与回复分钟一致时关闭；新分钟、不同正文或未回复内容仍作为新消息处理。
- 结构消息发现 `group_member` 时，只修正同一 opaque session key 的会话类型，不在捕获中途换 key，避免私聊/群聊历史串线或任务搁浅。
- 过期孤儿 planner/polish/ready work 只释放旧任务所有权；只要仍有未回复证据，就保留既有计数与最早时间并进入现有内部交接状态。下一条新信号可重新进入捕获，不静默归零。

## 4. 测试矩阵

1. 精确复现 `dark_ratio=0.001616`、`mean=249.703`、`ocr_hits=2`，断言不触发退格；真实单字草稿仍被保护。
2. 真实客户发送即使 fast flag 开启也必须读取到我方气泡；只触发按键、只确认标题、只看到输入清空、只在客户侧看到同文均不得通过。文件传输助手显式模拟回环继续兼容原快速路径。
3. scheduler 首次无触发失败回到 `ready` 且不在同一 tick 重派；第二次失败进入现有失败/重捕获链。
4. 多气泡部分成功只保存已发文本，不处理原客户消息，不重发整轮。
5. orphaned reply 的“已发送匹配、未匹配、读取失败”三分支。
6. send future 运行中和已完成未收割时均禁止 session poll。
7. pending TTL 的“有证据交接、无证据清理、存在 active task 不清理”三分支。
8. configured→confirmed 唯一别名可读合并；私聊/群聊和同名多会话不合并。
9. freshness 的 exact key、唯一名称回退、同名歧义、真正新信号四分支。
10. 慢捕获达到轮预算后让出、其余会话保持 pending 并在下一轮推进；已完成 future 在下一次前台捕获前被收割。
11. 已回复预览的截断、群成员标签和 OCR 修正仍先到真实聊天窗核验；空捕获且 ledger 闭环后才不重放。真正的新时间、新内容、未回复内容或新 occurrence 仍派发。
12. 当前唯一目标不重复点击侧栏；目标不匹配和同名歧义继续遵守原切换/阻断边界。
13. 两个真实客户会话同时来消息、其中一个紧接追问，三轮都必须完成 capture→Brain→polish→verified send，且 session key 不串线。
14. 约 30MB 状态首次只解析一次，后续轮询命中内存；外部原子替换即使撞上同一时间粒度，也必须因文件身份/大小变化重新加载。
15. 已完成 Brain future 必须排在下一次慢 OCR 捕获之前收割；慢捕获达到轮预算后仍保留其他客户会话的 pending。
16. 实机形态的“客户原文 10:46、我方回复 10:48、侧栏旧预览两点截断且显示 10:48”不得重放；真正更晚的新消息不得被吞。
17. 人工停止遗留的孤儿 polish 过期后未回复计数不归零；新信号重新进入 capture pending。
18. 既有 scheduler、workflow、Win32/OCR、外部合同、可选插件、Brain First、多模态与大风车边界回归全部通过。

## 5. 完成标准

- 所有根因均有先失败后通过的回归测试。
- 真实消息发送次数只由测试桩统计；测试期间微信 AI 客服始终停止。
- `py_compile`、相关全量脚本、外部合同/插件/Brain 静态审计和 `git diff --check` 通过。
- 记录修复前后关键路径耗时，重点验证空输入判定不再产生约 16 秒清空阻塞，发送完成时 bridge 不再被 session poll 阻塞。

## 6. 2026-07-19 最终离线验收记录

- scheduler 多会话/发送/历史/恢复：189/189。
- Win32/OCR/RPA：209/209。
- workflow：127/127。
- 外部合同、RPA 验收、独立图像模块边界、Brain 通用链路、双向图片、自发图片上下文、vision worker、Brain 上下文减负、图片路由、多模态与当前剪贴板合同：合计 76/76。
- 本轮共 601 项通过；96 个变更/新增 Python 文件通过 `py_compile`，`git diff --check` 通过。
- 真实 `chejin` 状态只读性能复核：文件 30,197,098 字节，首次解析约 0.808 秒，同进程缓存读取约 0.000103 秒，会话快照约 0.0003 秒。
- 复制该真实状态后注入两个实际 session key 的同时新消息，并在其中一个会话追加追问；3 个客户轮次均完成 Brain 草稿、polish 与测试桩 `verified=true`，原状态未写入、微信窗口未操作、AI 客服未启动。
