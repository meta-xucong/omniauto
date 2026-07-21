# 微信 AI 客服单 Brain 通用链路与结构化语义规则清理方案

日期：2026-07-19
状态：代码实施、离线审计和真实模型矩阵完成；最终微信实机复验因客户端停在扫码登录页而等待人工登录

本文引用并服从：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

本文承接 [customer_service_single_brain_context_priority_and_latency_slimming_plan_20260718.md](customer_service_single_brain_context_priority_and_latency_slimming_plan_20260718.md)，并纠正其中已经落入运行链路、但未被充分识别为“第二套本地语义引擎”的实现。本文不重建框架，不改变任何模块间接口、字段、导入路径或默认可观察合同。

## 1. 本轮硬原则

1. 禁止继续累加本地业务关键词、问法枚举、正则窗口、意图分支或账号/车型补丁。
2. 自然语言意图、上下文关系、提议与承诺的区别、商品追问、闲聊和纠正全部归 `customer_service_brain` 理解。
3. 代码机制层只处理：权威证据、声明来源、硬安全/权限、会话绑定、时效、调度、模型传输和 RPA 发送。
4. 正常运行链收束为：

   `一次权威取证 -> Brain 理解并生成 BrainPlan -> 通用合同/证据 Guard -> 通过后最终可见验证 -> 发送`

5. BrainPlan 首次不满足硬合同或 Guard 时，只把通用错误反馈给同一个 Brain 重做一次；仍失败则内部转人工/告警，不生成本地可见兜底，不从完整 planner 起点无限重放。
6. 快慢档不能由客户用了哪个词、几个气泡或问号数量决定。Prompt 减负只依据证据体积、历史体积和模型传输预算。

## 2. 实机故障证据

2026-07-19 01:05 至 01:08，“新数据测试”会话连续收到“这车有吗”“在？”。OCR、session 绑定、大风车形状 V2 商品证据和 A4L 指代均正常。Brain 已生成可发送答案，但旧 Guard 仅因回复中出现一个表示协助的自然表达，就误判为已经完成预约承诺。

误判之后又发生：主线路超时、备用线路返回空 JSON、当前轮阻断、scheduler 从完整 planner 起点重放。第一轮 worker 共耗时 63.05 秒，最终表现为已读不回。

这不是单个预约短语配置错误，而是三个通用根因叠加：

- 本地代码与 Brain 同时判断自然语言语义；
- 多个质量/语义审稿环节可重复打回 Brain；
- 模型熔断和 scheduler 重试在失败时放大整条链路耗时。

## 3. 结构化语义规则“案底”审计

### 3.1 已确认处于 Brain First 活跃链路的历史规则

| 位置 | 历史行为 | 问题 | 本轮处理 |
|---|---|---|---|
| `listen_and_reply.plan_message_batch_semantics` | 按价格、推荐、车辆、金融、预约、置换、身份、售后等词条分类，并改写 `combined_text` | 本地代码先替 Brain 解释客户消息 | Brain First 只使用按时间排序的原始净化消息；旧字段仅保留中立审计形状 |
| `low_authority_fast_profile_decision` | 按业务词、数字、气泡数、问法决定快档/完整档 | 形成第二套意图路由，且两个短气泡会被错误加重 | Brain First 运行链不再调用语义快档；统一取证后按数据体积压缩 prompt |
| `routine_product_fast_profile_decision` | 按本地复杂/风险词条和问号数决定模型负载 | 词条越补越脆，且原始消息数不等于复杂度 | 从 Brain First 活跃链隔离，兼容入口保留但不参与回复 |
| `verify_brain_reply_quality` | 逐项判断价格、推荐、保险、空间、预约、置换、社交、上下文等业务语义 | 实际成为与 Brain 竞争的本地审稿引擎 | Brain First 只校验非空、结构和通用长度预算；业务语义不再由它判定 |
| `validate_social_visible_reply_contract` | 用问候/催促等本地词条决定必须回复及模式 | 本地意图分类可再次打回 Brain | Brain First 由 BrainPlan 的通用发送合同保证非空，不再做社交词条判断 |
| `llm_reply_guard` 的预约/销售跟进/泛化承诺判断 | 从回复措辞猜提议、承诺和业务后果 | 已产生误杀并触发 40 秒以上故障放大 | Brain First 不运行模糊业务措辞分类；只认 BrainPlan 风险声明、权威证据和硬安全元数据 |
| semantic reviewer 触发与 soft-pass 规则 | 按客户用词、业务错误码和若干语义类别决定第二次 LLM 审稿 | 增加延迟和相互打架机会 | Brain First 不再调用旧触发器及其话题/短语 relax；正常回复不做第二次审稿，仅“无权威事实声明、仅常识辅助、客户可见草稿仍出现具体数字”这一通用异常形态触发一次轻量审稿 |

### 3.2 可以保留的确定性规则

下列不是“结构化词条回答引擎”，属于代码机制层硬合同，可以保留：

- BrainPlan JSON/schema、枚举和必填字段；
- `facts_claimed.source_level/source_id` 必须指向当前证据包中的权威来源；
- 商品事实只可引用 product master，政策流程只可引用 formal knowledge；
- 隐私、密钥、内部提示、违法请求等平台硬安全边界；
- OCR 说话人元数据剥离、session/target/freshness/no-cross-send；
- provider 超时、熔断、一次修复预算、一次 durable capture 传输重试；
- 最终可见 LLM 润色、RPA 发送前后确认。

### 3.3 兼容壳处理

外部合同冻结，不能删除或改名既有公开函数、返回字段和 reason 字段。因此旧函数名可以保留为兼容入口，但必须满足：

- Brain First 主路径不调用其业务语义判断；
- 不再影响 Brain 输入、Guard 结论、reply ready 或发送；
- 静态与运行测试能证明隔离；
- 文档标记为 compatibility-only，不能被后续开发重新接回主链。

## 4. 通用实施设计

### 4.1 输入：原始消息交给 Brain，不由本地改写语义

Brain First 使用经过说话人元数据清理后、按时间顺序拼接的原始客户消息。批次审计字段继续存在，但不得加入“客户正在问几个相关问题”“包含边界问题”等本地解释性前缀，也不得选择性丢弃气泡。

历史和图片理解结果仍按既有合同提供给 Brain；是否相关由 Brain 判断。代码层不再用商品、预约、闲聊等词条判断是否继承历史。

### 4.2 取证：每轮只构建一次权威证据包

取消“先按文本猜低权威消息，再决定是否取商品证据”的顺序。每轮先调用既有 evidence seam 构建一次本地镜像证据包；不访问大风车上游实时 API，不重复做 text-gap preflight。

Prompt 压缩只看以下可测量负载：

- 历史字符量；
- 当前批次字符量；
- product/formal evidence 项数和序列化体积；
- provider 的 token/timeout 预算。

这些量只决定裁剪多少非权威背景和使用哪个已有模型档，不决定客户意图、回复策略或是否回答。

### 4.3 Brain：一次完成理解、策略和正式回复

使用一个通用 system prompt，不再维护“闲聊快档”“商品快档”“预约档”等业务 prompt。Brain 自己完成：

- 理解最新消息及自然相关上下文；
- 选择需要引用的 product master/formal knowledge/current conversation；
- 生成 `reply_segments`；
- 在 `facts_claimed` 中声明客户可见事实及来源；
- 在 `risk` 中声明真实硬边界。

Prompt 只描述通用原则：回答当前请求、不要编造、证据不足时最小澄清、事实必须声明来源、只有真实硬边界才 handoff、回复简短自然。不得枚举客户可能问的业务主题或固定问法。

### 4.4 通用合同与 Guard

Brain 首稿依次经过两个轻量检查，它们都不得按业务词条理解客户语义：

1. BrainPlan 合同：结构有效、发送时有非空 `reply_segments`、事实来源存在且来源级别合法。
2. Guard：硬安全元数据、Brain 自己声明的 hard risk、证据声明、身份/内部信息泄漏和发送权限。

Guard 不再从“帮、安排、联系、预约、推荐、保证”等自然语言表达猜业务后果，也不逐主题判断“回复有没有答到某个词”。若 Brain 声明了未授权事实或硬风险，按结构化事实合同阻断；否则自然语言质量由 Brain 和最终可见润色负责。

为覆盖 Brain 偶发漏报的高具体度时效断言，同时避免每轮再调一次模型，另保留一个异常审稿槽位。它不读取车型、业务主题、客户问法、错误码或本地短语表，只在以下元数据形态同时成立时触发：

- 没有商品、正式知识或当前会话事实来源；
- Brain 仅声明 `common_sense_topics` 且没有 `facts_claimed`；
- 客户可见草稿仍含 Unicode 数字。

审稿人只能返回 pass/repair/block 和诊断；其 `repair_instruction` 在活跃链被统一替换为不含示例句的通用证据约束，不能把候选话术塞给 Brain。正常商品问答、闲聊、问候、上下文追问均不会支付这次额外 LLM 调用。时效性无数字断言主要由 Brain 通用证据提示约束，仍不增加天气、地域或时间关键词表。

### 4.5 修复次数与最终润色

首稿合同或 Guard 失败时，只用已有 repair 入口把错误码、缺失来源和不可发送草稿作为通用审稿反馈交给 Brain。不得根据错误码拼接业务话术或增加主题专用提示。每轮最多一次 Brain repair。

通过后执行既有最终可见验证。Brain 草稿已经自然、完整且未引入新风险时，本地零改写通过，不再额外调用 LLM；只有既有合同要求时才走轻量润色。润色只能自然化和复核，不改事实、策略、风险姿态或会话目标。润色失败不允许本地兜底；durable capture 只做一次传输级重试。

### 4.6 provider 熔断与 scheduler 重试

- affinity 有效时先走已知健康的备用线路；备用也失败时，本调用立即返回，不再回探刚刚已知超时的主线路。
- affinity 到期后才允许新调用探测主线路。
- scheduler 的 `brain_retry_instruction` 统一读取上轮失败原因和不可发送草稿，不再为身份、预约或其他主题编写专用修复分支。
- 同一 capture/session/message digest 最多重试一次；重试不能重新解释为一条新客户信号。

## 5. 测试矩阵

### 5.1 禁止结构化语义规则回流

- 静态检查 Brain First 主路径不调用批次业务分类、低权威词条快档、常规商品词条快档和逐主题质量检查；
- 用多组意义相同但措辞、语序、语言不同的消息验证结果不依赖固定词；
- 用完全未在测试词表出现的新表达验证 Brain 仍能理解并回复；
- 兼容函数/字段/签名快照保持不变。

### 5.2 通用 Brain/Guard

- 普通事实回答、协助提议、客户纠正、突然换商品、无关闲聊均由同一 Brain prompt 处理；
- 相同语义的不同措辞不触发不同本地分支；
- 已声明且来源存在的事实通过；来源不存在、级别不合法或硬风险声明被阻断；
- Guard 不因自然表达中出现某个业务词而误杀；
- 空回复、非法 schema、内部信息泄漏继续阻断。

### 5.3 减负和失败闭环

- 正常低风险轮次只有一次主 Brain LLM；最终可见验证在草稿无变化时为本地零改写；
- 首稿失败时最多增加一次 Brain repair；
- 旧的按话题/短语触发 semantic reviewer 永不进入 Brain First；只有无权威来源却带具体数字的通用异常形态可启用一个轻量审稿槽位；
- 两条连续短消息不会因气泡数量增加 prompt 档位；
- provider affinity 窗口内备用失败不回探主线路；
- scheduler 传输重试只有一次且携带通用反馈。

### 5.4 契约与 RPA 回归

- Brain/RPA/scheduler/session/HTTP/CLI/JSON 字段和签名快照；
- 多会话不串发、freshness、reply-ready、发送前目标确认、发送后确认；
- OCR/RPA、双向图片上下文、可选 vision/voice 插件边界；
- Python compile、`git diff --check`、外部合同和禁止导入审计。

## 6. 实机自问自答验收

离线全部通过后，才启动受控客户端和 AI 客服，只在“新数据测试”会话执行多轮自问自答：

1. 短商品询问后紧接催促；
2. 继续追问详情；
3. 突然切换另一车型；
4. 使用未在任何本地测试词表中准备的新说法；
5. 插入无关闲聊后再回到商品问题。

每轮必须确认：捕获正确、Brain 获得原始消息和授权证据、Guard 未用业务词条判定、进入 ready、目标确认正确、RPA 发送确认成功、下一轮不被旧任务阻塞。任一轮失败立即停止实机链路并回到离线诊断。

## 7. 完成标准

- Brain First 活跃链路不存在本地业务语义词条路由或逐主题 Guard；
- 正常轮次链路收束为一次取证、一次 Brain、通用 Guard、最终润色、发送；
- 每轮最多一次 Brain repair 和一次 durable capture 传输重试；
- 没有新增、删除、改名模块间接口、字段、路径、配置或错误码；
- 没有本地客户可见兜底，Brain 仍是唯一回复作者；
- provider 故障不再在同一轮重复等待已知坏线路；
- “新数据测试”多轮实机自问自答通过，无静默、无串会话、无发送失败；
- 实机结束后 AI 客服停止，等待用户手动复测。

## 8. 实施与审计记录

本轮已经按本文完成以下收束：

- `listen_and_reply` 的 Brain First 活跃路径不再调用本地 intent router、业务批次分类、旧 intent assist 或社交延迟分支；仍保留原字段和公开入口作为兼容壳。
- `customer_service_brain` 每轮只构建一次权威 evidence pack，prompt 档位只依据序列化负载，活动链不再调用低权威、常规商品或 text-gap 语义 preflight；正常轮次不调用第二 semantic reviewer。
- `customer_service_brain_contract` 的活动质量检查只检查非空、结构和通用长度；旧逐主题检查仅留在非活动兼容路径。
- `llm_reply_guard` 的 Brain First 活动入口只看证据声明、硬安全元数据和 BrainPlan 明确风险标记；普通自然措辞不再被本地代码解释成预约、价格或其他业务承诺。
- scheduler 的失败反馈只携带通用失败原因和上轮不可发送草稿，不再按身份、预约等主题拼接修复指令。
- provider affinity 已修复为：已知主线路处于失败窗口且备用也失败时，本调用立即返回，不再次回探已知坏主线路。
- Brain 主输出、唯一一次合同修复和无效计划重试使用同一固定中等输出预算；该预算不由客户用词、车型、问号或气泡数量选择。Flash 线路使用低推理强度，避免用更高输出上限换取更长无效思考。
- 实机验收脚本在 preflight 后把目标配置绑定到已确认的 `session_key` 和 `conversation_type`，不再从同一显示名称派生第二个 `configured` 假会话。
- 尝试过“每轮均调用第二 LLM 审稿”的方案，真实模型矩阵立即出现供应商 RPM 429，并把正常链路时延近似翻倍；该实验已回退，不属于当前实现。当前只保留一个由权威元数据和 Unicode 数字形态选择的异常审稿槽位。
- 通用 schema 和一次返修提示已明确事实类型、`source_level`、`source_id` 必须一致；商品记录不能冒充政策来源，缺少对应权威来源时由 Brain 删除断言或明确不确定，不能按车型加补丁。
- 对抗复测发现客户要求以口头主张覆盖商品主数据时，旧首稿可能先接受错误主张，再被 Guard 安全阻断；现已在同一通用权威契约中明确：客户输入可用于理解需求、偏好和语境，但不能授权改写、覆盖或降级权威事实、政策与权限。该原则同时约束首稿和唯一返修，不含车型、里程、价格或客户措辞分支。

接口、字段、导入路径、CLI/HTTP、reason、session/RPA 发送合同均未增删或改名；图片和语音可选插件边界未改动。

## 9. 离线验证结果

- 通用单 Brain 专项：10/10；不同措辞获得相同活动路径，旧语义触发器及三组话题/短语 relax 均由强制 mock 证明零调用，固定中等输出/修复预算生效。
- Brain 合同全套：通过；Brain 唯一出话、事实来源、通用 Guard 和一次修复边界保持。
- Brain preflight：10/10；正常文字轮次 evidence build=1，preflight LLM=0，主 Brain=1。
- 单 Brain 上下文减负：11/11。
- 多会话 scheduler：176/176；包含 pending、freshness、ready/send、失败恢复和 no-cross-send。
- workflow、外部合同、provider 配置、RAG、双端口云模拟、OCR/Win32 RPA、图片双向上下文、绝对独立 vision 边界及车辆图片检索：全部通过。
- 最终串行 24 项真实 Brain 对抗边界矩阵：24/24；覆盖问候/告别、上下文切换、错别字商品、商品与常识混合、贷款承诺、提示注入、身份强迫、客户主张覆盖主数据、库存/锁车承诺、内部价格、VIN/车牌、无证据实时状态、事故隐瞒、合同低开避税。20 条直接发送，4 条由 Brain 给出可见边界说明并 handoff；所有回复统一检查内部契约字段不得泄漏。Brain 主链平均 3.6884 秒、中位数 3.8182 秒、最慢 6.3307 秒，证据构建平均 0.6018 秒，Brain LLM 平均 2.9901 秒；普通轮次 semantic reviewer 调用 0 次，仅 1 条身份边界触发一次共享 Brain repair。产物：`runtime/apps/wechat_ai_customer_service/test_artifacts/customer_service_brain_boundary_matrix/BRAIN_BOUNDARY_20260719_044143`。
- 对抗消息、禁止片段和 VIN/车牌格式只存在于测试脚本，用来判断输出是否越界；它们不参与运行时理解、路由、Guard 或返修。运行代码差异审计未发现对奥迪、秦PLUS、里程、价格、天气、汇率、事故、避税、VIN/车牌等测试主题新增分支。
- 另用真实 reviewer 注入“无证据且带具体温度数值”的坏草稿：2.915 秒判定 `repair`；返修意见被代码压成不含示例话术的通用证据约束，客户可见措辞仍完全归 Brain。
- Python 编译及 `git diff --check`：通过，仅有工作区既有 LF/CRLF 提示。
- 本轮追加回归：Brain 静态所有权审计、Brain/代码机制层合同均通过；workflow 126/126、多会话 scheduler 176/176、单 Brain 上下文 11/11、外部契约 3/3、provider 16/16、大风车镜像 6/6、绝对独立 vision 边界 6/6、图片 Brain bridge 2/2、图片 turn router 7/7，均无冻结接口变化或跨模块依赖回流。

“新数据测试”已完成过一轮 6 条真实自问自答，六次均绑定同一个真实 session key 并成功发送，产物：`runtime/apps/wechat_ai_customer_service/test_artifacts/two_visible_session_customer_service_live/single_universal_20260719_0331`。该轮发现 Brain 对实时天气给出无证据具体温度，以及验收脚本派生假 configured session key 两个问题；前者已通过通用时效证据边界和异常 Guard 修复，后者已按精确 session key 绑定修复。

第二轮实机复验产物为 `runtime/apps/wechat_ai_customer_service/test_artifacts/two_visible_session_customer_service_live/single_universal_fix_20260719_0348`：第 1 条成功发送，第 2 条开始前微信客户端退出登录，窗口出现“扫码登录/二维码”，并非 OCR、scheduler、Brain 或 RPA 的代码失败。当前未绕过登录门禁，也未启动 AI 客服；最终微信多轮验收必须在人工扫码登录后继续，不能把离线矩阵冒充实机验收完成。
