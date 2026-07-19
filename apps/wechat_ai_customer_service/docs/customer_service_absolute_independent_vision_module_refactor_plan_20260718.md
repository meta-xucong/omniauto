# 微信客服“完全独立图像识别模块”改造方案（2026-07-18）

> **2026-07-19 优先级说明：** 本文的独立性目标、当前剪贴板原则和单一图片能力所有者要求继续有效；但“已经完全收口/完成”的结论已被 [PR #28 原样合并与独立 Vision 总方案](customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md) 重新限定。严格审计仍发现核心层对具体 Vision compatibility 的直接依赖、Vision 到 Connector 图片方法的接缝，以及 PR #28 原样树中的旧图片残留。实施和验收以新总方案及其[问题台账](customer_service_pr28_post_merge_issue_audit_ledger_20260719.md)为准，本文保留为历史设计与需求记录。

## 0. 文档状态与决策记录

本文已由“开发前方案”进入“代码落地并完成自动化验收”状态。独立模块改造已经完成；真实微信桌面客户图/我方图仍需仓库所有者手测验收。本阶段没有合并、checkout、cherry-pick 或修改朋友的 PR。

本文服从并引用：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)：所有客户可见回复只能由 `customer_service_brain` 编写；图像模块只能提供事实理解、商品匹配和上下文证据。
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)：图像与语音必须是严格独立、可选、懒加载的能力域；核心程序、旧导入路径和既有共享字段必须保持兼容。
- [customer_service_ephemeral_clipboard_vision_rebuild_20260713.md](customer_service_ephemeral_clipboard_vision_rebuild_20260713.md)：微信图片内容的唯一实时来源是一次目标图片右键“复制”后、同一 RPA 事务内读取到的当前剪贴板图片；不得回退到截图裁切、历史文件、旧剪贴板或落盘图片。

仓库所有者在本轮明确批准并要求：

1. 先完成“完全独立图像识别模块”，再研究和合并 PR。
2. 图片专用能力必须端到端收束到单一模块，外界可以直接调用该模块获得完整能力。
3. 当前散落在 Sidecar、Connector、Scheduler、Workflow、Ledger 和 Brain 桥接中的图片专用实现必须迁出并删除。
4. 通用窗口、会话确认、OCR 帧、基础鼠标操作和全局 RPA 锁可以作为中性端口被注入，但这些通用模块不得认识图片、剪贴板图片、视觉模型或车型图片匹配。
5. 本阶段不合并、不修改朋友的 PR；待图像模块独立闭环通过后，再单独制定 PR 合并方案。
6. 后续 PR 合并以 PR 内容为准；PR 修改文件将作为不可修改上游。图片模块只能在其自身内部增加对应适配器，不得要求 PR 迁就图片模块。

当前待后续处理的上游为 [PR #28](https://github.com/meta-xucong/omniauto/pull/28)，审计时 head 为 `2120f16744aebe3d8edbdf9c3f407375bfeed279`。本文不执行该 PR 的 merge、checkout、cherry-pick 或代码改写。

---

## 1. “完全独立”的正式定义

### 1.1 必须独立拥有的完整能力

图像模块必须独立负责以下端到端闭环：

1. 图片信号判定。
2. 当前图片 occurrence 识别和去重。
3. 客户侧/我方侧方向确认。
4. 目标会话和当前图片的绑定校验。
5. 图片气泡定位。
6. 右键菜单定位和“复制”操作。
7. 剪贴板序号前后校验。
8. 当前剪贴板位图读取、校验、内存编码和释放。
9. 图片 LLM Provider 调用、重试、超时和结构化结果归一化。
10. 商品图片描述词生成和索引。
11. 客户图片与商品库车辆图片的相似匹配。
12. 客户图片与我方图片的不同处理边界。
13. 生成已有 Ledger、Brain evidence 和审计合同所需的兼容投影。
14. 图片能力自身的配置、健康状态、错误归一化、生命周期和测试。

任何需要理解“这是图片”“图片在哪一侧”“这次应该复制哪张图片”“图片表示什么”“图片对应哪个商品”的逻辑，都必须位于图像模块内部。

### 1.2 可以依赖的中性基础端口

图像模块不重复建设完整微信 RPA，只能通过依赖倒置使用以下中性能力：

- `RpaLeasePort`：申请和释放全局微信 RPA 锁。
- `ConversationTargetPort`：打开、确认目标会话并返回不可变会话绑定证据。
- `WindowFramePort`：获取当前窗口帧和 OCR items；不判断图片语义。
- `UiActionPort`：执行窗口坐标点击、右键、按键和安全等待。
- `ClipboardPort`：获取剪贴板序号、读取当前位图和释放资源。
- `VisionProviderPort`：执行多模态理解。
- `ProductImageRepositoryPort`：读取商品图片引用、写入已有商品图片描述/索引扩展。
- `ClockPort`、`AuditPort`：时间与模块私有审计。

端口的接口和实现不得包含客户回复、Scheduler 状态、Brain 状态或语音实现。

### 1.3 不属于图像识别模块的数据所有权

以下能力保留原所有者，但只能通过中性端口或兼容结果与图像模块协作：

- 商品库继续拥有原始车辆图片、图片顺序、上传/删除/展示和大风车原始图片字段。
- Ledger 继续拥有通用消息持久化和会话顺序，不拥有图片识别策略。
- Scheduler 继续拥有会话调度，不判断图片方向、不找图、不读剪贴板。
- Brain 继续独占客户可见回复，只消费经过允许的文字事实。
- RPA 核心继续拥有窗口和全局互斥，不拥有任何图片专用 action。

---

## 2. 当前实现审计结论

### 2.1 当前只是“模型插件化”，不是“完整能力插件化”

当前 `optional_plugins/vision/plugin.py` 仍反向导入：

- `workflows/customer_image_turn_router.py`
- `workflows/customer_image_asset_store.py`
- `workflows/customer_image_brain_bridge.py`

当前 `optional_plugins/vision/clipboard_payload.py` 又反向依赖外部 `customer_image_understanding_provider.py` 的限制常量。

因此依赖方向是“插件调用外部散落实现”，插件本身不是能力所有者。

### 2.2 当前图片专用实现的主要散落点

| 当前区域 | 散落内容 | 目标动作 |
|---|---|---|
| `adapters/wechat_win32_ocr_sidecar.py` | 图片 action、图片气泡结构识别、图片消息注入、右键复制委托 | 删除图片专用实现；只允许中性 RPA 能力 |
| `adapters/wechat_connector.py` | 客户/我方剪贴板事务、图片 action 参数、锁内图片 consumer | 实现迁入 vision；旧公开方法最多保留无逻辑兼容门面 |
| `adapters/wechat_image_save_capture.py` | 气泡定位、方向、菜单、复制、旧保存/裁切路径 | 有效剪贴板路径迁入 vision；旧保存/裁切路径删除；旧 import 仅保留门面 |
| `workflows/customer_image_turn_router.py` | 当前图片路由、客户/我方事务、理解调用 | 全部迁入 vision runtime |
| `workflows/customer_image_understanding*.py` | Provider、Prompt、合同、结果归一化 | 全部迁入 vision understanding 子包 |
| `workflows/customer_image_brain_bridge.py` | Brain 兼容投影 | 迁入 vision projection 子包；Brain 只接收既有投影 |
| `workflows/customer_image_catalog_assist.py` | 商品匹配辅助 | 迁入 vision retrieval/projection |
| `internal/scheduler/vision_bridge.py` | 图片方向、身份、去重、代理消息 | 迁入 vision occurrence/projection；旧路径变为门面 |
| Scheduler/Monitor/State | 图片 pending 分支和图片状态解释 | 删除图片判断；只调用可选能力协议并保存既有通用结果 |
| Session Ledger | 图片专用 enrichment、方向和上下文拼装 | 迁入 vision projection；Ledger 只执行通用写入 |
| `listen_and_reply.py` | 图片专用触发、拼接和恢复 | 收窄为中性插件调用和既有结果传递 |
| Brain/Preflight/Prompt archive | 图片专用拼接、裁剪、推断 | 图片转换迁入 vision；Brain 只消费已有允许字段 |
| `optional_plugins/vehicle_image_retrieval` | 单独的图片检索插件门面 | 合并为 vision 的 `vehicle_retrieval` 子能力；旧路径兼容转发 |
| `vehicle_image_retrieval_integration.py/jobs.py` | 商品图片索引、下载、任务和匹配 | 图片专用实现迁入 vision；宿主只提供 repository/job executor 端口 |
| `packages/vehicle_image_retrieval` | 描述、指纹、相似度算法 | 迁入 vision 的可移植纯逻辑子包；旧包只重导出 |

### 2.3 当前偏差的根因

此前把“图片模块独立”错误地缩小为“视觉模型和识图结果独立”，并为了复用会话确认、窗口截图和 RPA 锁，在 Sidecar 中增加了 `image-save`，后续又增加 `image-clipboard-copy`。之后为修复双方图片方向和历史上下文，继续把图片 occurrence 解析加入共享 `messages_payload()`，导致图片能力横跨多个模块。

此前测试只验证 Provider 懒加载、语音/视觉不互相 import 和 core-only 可启动，没有设置“图片专用符号不得出现在核心实现中”的静态边界门。因此旧审计结论不能证明端到端独立。

---

## 3. 目标目录与所有权

唯一图片能力所有者为：

```text
apps/wechat_ai_customer_service/optional_plugins/vision/
  __init__.py
  api.py                         # 外部可直接调用的稳定 API
  contract.py                    # 模块私有请求、结果、错误和生命周期合同
  ports.py                       # 中性宿主端口 Protocol
  service.py                     # 端到端编排，唯一能力入口
  plugin.py                      # 现有 OptionalCapabilityPlugin 门面
  trigger.py                     # 当前图片信号判定
  occurrence.py                  # 方向、身份、去重、freshness
  lifecycle.py                   # 内存图片和事务资源释放
  audit.py                       # 模块私有审计，不写图片内容
  capture/
    bubble_locator.py            # 图片气泡结构定位
    direction.py                 # customer/self 方向确认
    context_menu.py              # 右键菜单与复制项
    clipboard.py                 # 当前剪贴板读取与序号验证
    transaction.py               # 同锁端到端原子事务
  understanding/
    contract.py
    prompt.py
    provider.py
    normalize.py
    service.py
  vehicle_retrieval/
    descriptor.py
    fingerprint.py
    matcher.py
    indexer.py
    service.py
  projection/
    message.py                   # 既有消息 envelope 兼容投影
    ledger.py                    # 既有 Ledger 写入值
    brain.py                     # 既有 Brain evidence 投影
    catalog.py                   # 既有商品匹配投影
  integrations/
    wechat_current.py            # 当前 OCR/RPA 基线适配器
    product_master.py            # 商品库 repository port 适配器
  compatibility/
    legacy_workflows.py          # 旧 workflows import 门面
    legacy_connector.py          # 旧 Connector 调用门面
    legacy_retrieval.py          # 旧 vehicle retrieval 门面
```

约束：

- `vision` 内部不得 import `optional_plugins.voice`。
- `vision` 核心不得 import Scheduler、Brain、Ledger 的具体实现。
- `vision/service.py` 只能依赖本模块合同和 ports。
- `integrations/` 可以懒加载宿主实现，但不得反向要求宿主理解图片。
- 模块被整体复制后，只需第三方实现 ports 即可直接运行。

---

## 4. 对外完整 API

### 4.1 新模块 API

新 API 是新增的独立包合同，不修改现有 Connector、Sidecar、Brain、Scheduler 和插件协议：

```python
service = create_vision_service(ports=ports, config=config)

result = service.inspect_current_conversation(request)
result = service.understand_memory_image(request)
result = service.index_product_images(request)
result = service.match_product_image(request)
```

职责：

- `inspect_current_conversation`：从目标会话确认开始，到图片文字理解、商品匹配和兼容投影结束。
- `understand_memory_image`：供第三方传入内存图片，不执行微信 RPA。
- `index_product_images`：对商品图片生成描述、指纹和索引。
- `match_product_image`：把客户图片理解/指纹与商品图片索引匹配。

### 4.2 现有可选插件协议保持不变

现有 `OptionalCapabilityPlugin` 的：

- `available()`
- `should_run(context)`
- `run(context)`

不增参、不删参、不改名。`BuiltinVisionPlugin` 内部改为调用 `VisionService`，不再导入外部 workflow 实现。

### 4.3 结果边界

模块对宿主只输出：

- 已确认方向和 occurrence 的文字化结果。
- 视觉 Provider 的结构化理解。
- 已授权的商品候选和匹配分数。
- 既有消息、Ledger、Brain evidence 字段的兼容投影。
- 不含图片字节的模块审计与确定性失败状态。

模块不得输出客户可见回复，不得拥有 ready reply，不得调用发送链路。

图片字节、PIL 对象、截图、坐标和剪贴板载荷不得跨出一次 `VisionService` 调用；`finally` 中必须释放并清零可变内存。

---

## 5. 微信当前图片事务

一次有效事务必须满足：

1. 获得全局 RPA 锁。
2. 用 `session_key + conversation_type + target` 确认当前会话。
3. 获取一次当前窗口帧和 OCR items。
4. 由 vision 模块从结构位置识别图片候选和方向。
5. 唯一关联当前未处理 occurrence；歧义即失败。
6. 记录右键前剪贴板序号。
7. 右键目标图片并点击“复制”。
8. 验证剪贴板序号变化。
9. 只读取该当前序号的有效位图。
10. 在锁内完成图片内存对象接管；不得读取旧剪贴板。
11. 释放 RPA 锁后调用视觉 Provider；Provider 重试只能复用同一内存载荷，不得再次右键。
12. 生成文字理解、商品匹配和兼容投影。
13. 原子提交结果；失败不得把占位伪装成已识图消息。
14. 释放并清零图片内存。

禁止路径：

- 截图裁切识图。
- 保存聊天图片到本地再识图。
- 历史文件、商品缩略图或旧剪贴板回退。
- 未确认方向时猜测 customer/self。
- 一个 pending 身份盲点多张历史图片。
- Provider 失败后重新右键获取另一份图片。

---

## 6. 客户图片、我方图片和商品图片边界

### 6.1 客户图片

- 完成识图和商品匹配。
- 形成当前客户消息的文字事实和 Brain evidence。
- 是否回复、如何回复完全由 Brain 决定。

### 6.2 我方图片

- 同样完成右键复制和视觉理解。
- 记录 `sender=self` 的文字上下文。
- 不创建客户回复任务，不触发发送，不伪装成客户消息。

### 6.3 商品图片

- 原始图片、排序、上传、删除、展示和大风车字段继续由商品库拥有。
- vision 模块只负责读取图片引用、生成描述/指纹、匹配和返回索引扩展。
- 商品库通过 `ProductImageRepositoryPort` 提供数据，不允许 vision 直接 import `ProductMasterStore` 或大风车实现。
- 商品图片更新后由宿主调用 `index_product_images`；索引失败不得影响车辆基本资料保存。

---

## 7. 迁移与删除计划

### 阶段 A：特征锁定，不搬代码

1. 为当前已工作的行为增加 characterization tests。
2. 固化客户图片、我方图片、多图片、重复图片、无关图片、剪贴板失败、Provider 失败、车型匹配和多会话用例。
3. 固化所有旧 import path、函数签名和外层 payload 快照。
4. 记录当前真实微信手测所需证据，但不宣称自动测试等于真实桌面验收。

退出条件：迁移前行为和硬边界可重复验证。

### 阶段 B：建立独立核心和 ports

1. 新增 `contract.py`、`ports.py`、`service.py` 和目录骨架。
2. 实现内存资源生命周期和模块私有审计。
3. 新模块在无微信、无 PIL/Provider、无商品库的组合下可以被安全 import。
4. 第三方内存 host 可以直接运行纯合同测试。

退出条件：外部只依赖 API 和 ports，不依赖应用路径。

### 阶段 C：迁入理解与商品图片检索

1. 迁入 Provider、Prompt、结果归一化和 catalog assist。
2. 迁入图片 descriptor、fingerprint、indexer 和 matcher。
3. 迁入商品图片读取的端口适配，不迁移商品主数据所有权。
4. 旧 workflow/package/plugin 路径改为一行级兼容转发。

退出条件：`vision` 不再反向 import `workflows/customer_image_*` 或独立 `vehicle_image_retrieval` 实现。

### 阶段 D：迁入微信取图闭环

1. 从 `wechat_image_save_capture.py` 迁入结构定位、方向、菜单和复制事务。
2. 迁入当前剪贴板位图读取。
3. 删除保存文件、另存为、裁切和历史资产回退的生产实现。
4. 通过中性 ports 复用全局 RPA 锁、目标确认和窗口帧。

退出条件：直接调用 `VisionService.inspect_current_conversation` 可以完成完整当前剪贴板识图。

### 阶段 E：迁入 occurrence、去重和上下文投影

1. 迁入 Scheduler vision bridge 的图片身份、方向、freshness 和去重逻辑。
2. 迁入客户/我方图片分路。
3. 迁入 Ledger、Brain 和 catalog 的兼容投影生成。
4. 保持现有共享字段名、类型、默认值和含义不变。

退出条件：Scheduler、Ledger 和 Brain 不再解释图片专用状态，只处理模块返回的既有兼容结果。

### 阶段 F：切换生产调用并删除散落实现

1. `BuiltinVisionPlugin` 改为只调用 `VisionService`。
2. Scheduler/Listener 通过现有中性插件协议调用 vision。
3. 删除 Sidecar 中当前本地新增的图片消息解析、图片 action 实现和 `messages_payload()` 图片注入。
4. 删除 Connector 中图片事务实现；若旧公开方法属于冻结合同，只保留无业务逻辑的 vision 兼容门面。
5. 旧 `customer_image_*`、`wechat_image_save_capture`、`vehicle_image_retrieval*` import 路径只保留 re-export/facade，不保留第二份逻辑和状态。
6. 删除 Scheduler、Ledger、Brain 和 Prompt archive 内可迁移的图片专用 helper、判断和 fallback。

退出条件：除 vision 目录、兼容门面、通用字段透传和商品图片数据 CRUD 外，生产代码中不存在图片专用实现。

### 阶段 G：独立验收与收口

1. 执行全部单元、合同、插件矩阵、OCR/RPA、多会话、Brain First 和商品库测试。
2. 运行真实微信客户图片和我方图片手测。
3. 生成依赖方向、死代码、图片落盘和 PR 未触碰审计。
4. 确认所有失败路径释放锁和内存。

退出条件：本文第 9 节全部通过，才允许进入 PR 合并研究。

---

## 8. 兼容与删除规则

### 8.1 “删除实现”与“保留合同”同时成立

旧公开路径若被外部合同冻结，不直接删除符号，而是改为最薄门面：

```python
def legacy_entry(*args, **kwargs):
    return resolve_optional_capability("vision").run(...)
```

门面不得包含：

- 图片候选判断。
- 坐标计算。
- 剪贴板读取。
- Provider 调用。
- 商品匹配。
- 图片状态机。
- 自己的缓存、队列或重试。

实现只允许存在一份，且必须在 `optional_plugins/vision/` 内。

### 8.2 允许留在外部的最小内容

- 可选插件注册表中的 lazy factory path。
- 旧 import path 的 re-export/facade。
- Scheduler 对中性 `should_run/run` 的调用。
- Ledger 对已有通用消息结构的写入。
- Brain 对已有 evidence 字段的消费。
- 商品后台对上传、删除、展示和索引任务的调用。

这些外部位置不得自行理解或处理图片。

### 8.3 不新建第二套共享状态

- 不新增 Scheduler 图片队列。
- 不新增共享 JSON 状态字段。
- 不新增 Brain 输入字段。
- 不改变现有 message envelope、Ledger 和错误字段。
- vision 内部临时状态仅存在于本次调用内存或模块私有审计；不得成为跨模块事实源。

---

## 9. 验收矩阵

### 9.1 模块独立性

- 整体复制 `optional_plugins/vision` 后，通过实现 ports 可以独立调用。
- `vision/service.py` 不 import Sidecar、Connector、Scheduler、Ledger、Brain、语音或商品库实现。
- `plugin.py` 不再 import `workflows/customer_image_*`。
- core-only、core+voice、core+vision、core+both、第三方 vision、vision 依赖缺失全部可运行。
- 禁用 vision 后，文字、语音、调度和发送不受影响。

### 9.2 微信取图

- 客户单图、客户连续多图、我方单图、我方连续多图均能按方向处理。
- 同一 occurrence 最多右键一次。
- 目标会话不一致、方向不明或候选歧义时不右键。
- 剪贴板序号不变、变化后又被抢占、内容非位图时明确失败。
- 识图输入只来自本次当前剪贴板，不产生图片文件。
- 所有失败路径释放 RPA 锁和图片内存。

### 9.3 理解和商品匹配

- 正常图片、无关图片、截图、车辆图片和低信息图片均返回可审计文字结果。
- 无关图片可以被 Brain 作为当前会话事实处理，但模块不得自行写回复。
- 商品图片上传/同步后可以独立生成描述和索引。
- 客户图片命中商品时返回既有允许字段；低于阈值不强行匹配。
- 商品索引失败不影响商品资料保存和大风车同步。

### 9.4 上下文和回复边界

- 客户图片文字理解进入当前会话历史和 Brain evidence。
- 我方图片文字理解进入历史上下文，但不创建客户 reply task。
- 后续文字追问复用最近、方向明确的文字理解，不重新右键旧图片。
- 图片模块不生成、替换、拼接或润色客户可见回复。
- Brain 不获得图片字节、文件路径、坐标、剪贴板对象或未授权商品字段。

### 9.5 多会话与运行效率

- 捕获、理解、投影和发送保持相同 `session_key + conversation_type + target` 绑定。
- 两个会话同时有图片时不串图、不串上下文、不串商品匹配。
- Provider 调用不长期占用微信 RPA 锁。
- 无图片的普通文字轮次不加载视觉 Provider、不读剪贴板、不扫描图片候选。

### 9.6 静态边界

新增静态测试至少断言：

- Sidecar 和 Connector 不含可达的图片业务实现。
- Scheduler、Ledger、Brain 不 import vision 具体实现，只经中性协议或兼容投影。
- vision 与 voice 实现互不 import。
- 图片 Provider SDK、PIL、win32clipboard 只在 vision 能力懒加载后出现。
- 外部旧路径只包含门面/re-export，不包含第二份实现。
- 运行目录没有新增 PNG/JPG/WebP/BMP 或 base64 图片日志。

---

## 10. PR 冻结与后续接入门槛

### 10.1 本阶段硬禁止

- 不合并 PR #28。
- 不 checkout PR 分支。
- 不把 PR OCR/RPA 实现提前复制到当前 Sidecar。
- 不为适配 PR 修改当前模块外部字段。
- 不在完成 vision 独立验收前讨论冲突取舍。

### 10.2 vision 完成后的下一阶段

只有第 9 节全部通过后，才创建单独 PR 接入方案：

1. 把 PR 修改的 7 个文件整体视为只读上游。
2. 所有冲突选择 PR 内容，本地冲突实现不保留。
3. 校验 PR 文件与 head blob 逐字一致。
4. 只在 `optional_plugins/vision/integrations/` 新增或调整 PR 适配器。
5. vision 核心、API、Provider、商品匹配和投影不得因 PR 改写。
6. PR 遗留但不可达的旧图片代码不作为生产入口；不得为了清理它而修改 PR 文件。

---

## 11. 回滚与数据安全

- 每个阶段单独提交；失败只回滚该阶段。
- 在 production caller 切换前保留当前行为测试，不先删除旧实现。
- 切换成功并通过完整测试后，才删除散落实现。
- 不删除用户商品图片、图片描述索引、Ledger 历史文字理解或大风车原始图片字段。
- 旧状态读取必须幂等；不要求人工修改 JSON。
- 回滚不得恢复截图裁切、图片落盘、旧剪贴板或本地客户回复 fallback。

---

## 12. 开发前方案审计

| 审计项 | 结论 |
|---|---|
| 是否符合完全独立目标 | 通过；图片专用能力只有一个所有者，外部只提供中性端口 |
| 是否仍把图片能力塞进 Sidecar | 否；Sidecar 只作为通用 RPA host，图片 action 和业务实现迁出 |
| 是否可以被外部直接调用 | 通过；新增稳定 `VisionService` API，微信和内存图片均可调用 |
| 是否保持语音独立 | 通过；vision 与 voice 禁止互相 import，生命周期独立 |
| 是否改变 Brain 回复所有权 | 否；vision 只返回事实和证据，客户措辞仍由 Brain 独占 |
| 是否改变 Scheduler/Brain/RPA 外部合同 | 否；现有协议、字段和旧 import 通过兼容门面保持 |
| 是否重复实现完整微信 RPA | 否；窗口、OCR、锁和基础动作经中性 ports 复用 |
| 是否保留错误识图回退 | 否；只认本次右键复制后的当前剪贴板 |
| 是否包含商品图片匹配 | 是；描述、指纹、索引和匹配作为 vision 子能力收束 |
| 是否误把商品图片数据所有权搬走 | 否；商品库仍拥有原始图片和大风车字段 |
| 是否提前合并或修改朋友 PR | 否；PR 合并是 vision 完成后的独立阶段 |
| 是否有可验证的删除门槛 | 通过；静态边界、依赖方向、单一实现和不可达旧路径均有测试 |

开发前方案审计结论：思路可实施，没有发现必须修改 Brain、Scheduler、RPA 对外合同或朋友 PR 才能完成的阻塞项。实施必须遵循“先特征锁定、再迁入、后切换、最后删除”的顺序；不得一边搬迁一边在旧 Sidecar 继续增加图片补丁。

---

## 13. 历史图像文档优先级

自本文生效后，历史图像文档按以下规则阅读：

| 历史内容 | 状态 | 仍可使用 | 不得继续使用 |
|---|---|---|---|
| 2026-07-02 初版识图文档包 | 架构与实施方案废止 | 原始需求、Provider 调研、Brain First 原则 | 图片落盘、截图裁切、`image-save`、Sidecar 图片入口、外置 `customer_image_*` 实现布局 |
| 2026-07-09 媒体预览触发 | 部分废止 | 预览只作 capture signal、会话绑定 | 由 Scheduler/Sidecar 解释或生成图片 proxy |
| 2026-07-10 多模态上下文 | 部分废止 | 双方媒体都要形成连续文字上下文 | Scheduler 自有图片任务、图片实现散落到 Ledger/Brain/RPA |
| 2026-07-11 图片触发与身份 | 部分废止 | occurrence、freshness、方向和去重原则 | passive crop、图片归档、Sidecar/Connector/Scheduler 图片实现落点 |
| 2026-07-13 剪贴板瞬时理解 | 部分废止 | “只认本次当前剪贴板、不落盘”仍是硬规则 | Connector/Sidecar 图片事务及外部 workflow 所有权 |
| 2026-07-13 结构定位与稳健性 | 部分废止 | 结构位置优先、内容特征不得决定方向 | 把结构定位实现留在 `adapters/` 或 Scheduler |
| 2026-07-16 车源图片检索 | 部分废止 | 商品数据所有权、描述/指纹/阈值和失败降级 | 作为 vision 之外的第二个图片能力域或独立生产实现 |
| 2026-07-18 双向图片闭环 | 部分废止 | 客户/我方边界、Brain 上下文、原子提交和去重 | Sidecar occurrence、Scheduler 图片路由和散落模块落点 |

所有被标记的历史文档只保留复盘、需求来源、算法证据和旧测试背景。若它们与本文在模块所有权、目录、调用方向、图片 action 或生产数据流上冲突，必须无条件以本文为准。

---

## 14. 代码落地与交付审计（2026-07-18）

### 14.1 实际落点

- `optional_plugins/vision/api.py`、`service.py`、`ports.py` 成为可直接调用的稳定入口；公共 API 导入时不加载 PIL、Windows 剪贴板、默认微信实现或语音模块。
- `capture/transaction.py` 实现第三方中性端口闭环；`capture/wechat.py`、`capture/surface.py` 拥有当前微信结构定位、方向、右键复制和剪贴板时序实现。
- `understanding/` 拥有内存图片 Provider、Prompt、归一化和理解服务；只接受本次调用持有的内存载荷。
- `vehicle_retrieval/` 拥有商品图片描述、指纹、索引、匹配和宿主集成；纯检索核心没有主程序、PIL、文件或网络依赖。
- `occurrence.py` 与 `projection/` 拥有方向、身份、去重、freshness，以及既有 Message/Ledger/Brain/Catalog 字段的兼容投影。
- 旧 workflow、adapter、scheduler bridge、vehicle retrieval 和 portable package 路径均保留原路径，但已改为无状态兼容别名或同签名委托；不存在第二份实现。
- Connector 只保留冻结公开方法的无逻辑委托；Sidecar 中本地新增的 `image-save`、`image-clipboard-copy`、图片参数、图片消息注入和 vision import 已全部删除。旧保存、另存为、裁切、历史文件和旧剪贴板入口只在原兼容 import 路径 fail-closed，不再属于 Sidecar。
- 新增 `vision/integrations/wechat_worker.py` 作为 vision 自有的微信宿主适配器。它只复用 Sidecar 的通用窗口、会话确认、OCR、截图和鼠标原语，图片结构观察、方向判断、右键 Copy 和剪贴板代次证明均在 vision 内执行。
- 生产 `wechat_current.py` 不再调用 `connector.call_compat_sidecar()`，也不再构造任何 Sidecar 图片 action；因此未来 PR 可以整文件覆盖 Sidecar，后续只需在 vision 自有适配器内适配 PR 提供的中性原语。

### 14.2 自动化验收

以下测试在 `master`、HEAD `378cc3f7b3b24e88ff8d9f145c185bb5c48d509c` 的未提交工作区上通过：

| 验收组 | 结果 | 单次复测耗时 |
|---|---:|---:|
| 完全独立模块静态边界 + 中性 ports 端到端 | 6/6 | 1.211s |
| vision 自有微信 worker 模拟 | 3/3 | 通过 |
| 外部合同与旧结果形状 | 3/3 | 7.715s |
| 当前剪贴板图片路由 | 7/7 | 0.371s |
| 多会话调度、锁、freshness、发送隔离 | 175/175 | 8.107s |
| Win32 OCR/RPA/Sidecar 兼容 | 207/207 | 6.945s |
| 商品库 V2 与多图索引调用 | 11/11 | 0.732s |

此外已通过图片 Provider 合同、旧文件路径拒绝、双向图片方向、我方图片历史、Brain 证据、Brain preflight、插件组合、车型图片匹配、工作流逻辑和 Python 全量语法检查。

### 14.3 最终边界结论

- Connector、Scheduler、Brain、Ledger 的冻结公开方法、参数、字段和外层结果含义未变；Sidecar 的通用 OCR/RPA action 合同未变，已按仓库所有者明确指令删除不应存在于 Sidecar 的图片专用 action。
- Brain 仍是客户可见回复的唯一作者；vision 只输出文字理解、商品证据和兼容投影。
- 客户图片可进入回复轮；我方图片只进入上下文，不创建客户回复任务。
- 图片内容只存在于本次内存事务，返回前清零；本轮测试没有在 runtime 下生成 PNG/JPG/JPEG/WebP/BMP 文件。
- vision 与 voice 没有实现依赖；core-only、单插件、双插件、自定义插件和缺依赖组合测试通过。
- 当前仍在 `master`，未触碰 PR #28。下一阶段若合并 PR，必须另立适配方案并继续把 PR 文件视为只读上游。

### 14.4 严格 Sidecar 可整文件替换复审

上一轮验收仍允许 Sidecar 保留图片 action 的薄委托，这不满足“未来 PR 可整文件覆盖 Sidecar”的更严格标准。本轮复审据此撤销上一轮关于 Sidecar 已完全收束的结论，并完成根治：

1. Sidecar 不再定义、解析、分发或执行任何图片 action，不再向 `messages` 注入结构化图片 occurrence，也不再 import vision 或旧图片 adapter。
2. Connector 的 Sidecar 请求转换器不再认识图片 action 或图片参数；冻结图片方法仅调用 vision 自有集成入口。
3. 当前表面结构观察与当前图片右键 Copy 均由 `optional_plugins/vision/integrations/wechat_worker.py` 执行，且截图只作瞬时几何输入，不返回路径、坐标或图片字节。
4. Scheduler 只通过 absence-safe vision 兼容桥接取得现有消息合同形状的 observation；Sidecar 的普通 `messages` 返回不再携带图片识别职责。
5. 静态边界测试现在要求 Sidecar 中上述图片符号、action、参数和 import 为零，而不是允许“薄门面”。模拟测试覆盖客户/我方方向、无落盘结构观察、右键 Copy、剪贴板代次变化，以及生产集成不调用旧 Sidecar 图片 action。

### 14.5 最终散落实现与旧合同复核

本轮按“未来 PR 整文件覆盖 Sidecar”重新扫描全仓，而不是只检查主要调用链。结论如下：

- `wechat_win32_ocr_sidecar.py` 中图片专用 action、CLI 参数、消息注入、vision import、识图函数和图片兼容门面均为零。Sidecar 仍会为通用 OCR、窗口确认和发送安全采集瞬时屏幕，这是 OCR/RPA 自身能力，不是识图业务，也不会产出图片消息或调用 Vision Provider。
- `wechat_connector.py` 只保留冻结公开方法的同签名委托和旧裁切入口的 fail-closed 结果；无候选判断、结构定位、剪贴板读取、图片理解、商品匹配或图片状态机。
- `customer_service_scheduler.py` 只调用一次 `prepare_vision_scheduler_capture` 并把既有返回字段写回既有 payload/state；结构观察、方向裁决、placeholder、pending disposition 和客户/我方分流均由 `optional_plugins/vision/scheduler_capture.py` 持有。
- 旧 `workflows/customer_image_*`、`internal/scheduler/vision_bridge.py`、`adapters/wechat_image_save_capture.py` 和 vehicle retrieval 旧路径均为无实现兼容别名；它们只为冻结 import path 服务。
- `customer_service_settings.py` 中仍保留已有管理端配置字段，Brain/Ledger/Scheduler 中仍消费已有兼容字段。这些属于冻结宿主合同、配置和状态投影，不包含图片执行能力，不能误删或改名。
- 生产微信绑定对通用 OCR/RPA 原语的唯一依赖集中在 `optional_plugins/vision/integrations/wechat_worker.py`。因此未来 PR 可以原样覆盖 Sidecar；若 PR 的通用原语发生变化，只修改 vision 自有 integration adapter，不向 PR 文件补回图片代码。

2026-07-13 外部合同快照曾把 `wechat_win32_ocr_sidecar.execute_wechat_image_save` 错误冻结为 Sidecar 合同。仓库所有者已经明确要求 Sidecar 图片职责清零，因此本轮从该 Sidecar 快照中撤销此错误归属；原函数名、参数、默认值和失败语义继续在 `adapters/wechat_image_save_capture.py` 冻结保护。合同测试同时断言 Sidecar 不得重新导出该函数，避免以后因旧快照把图片实现塞回 Sidecar。

最终归属判定不是“仓库外部完全不出现 image/vision 字样”，而是：外部只允许冻结字段、管理配置、状态投影和无逻辑兼容门面；任何取图、方向判断、剪贴板、理解、图片生命周期、商品图片检索和 Scheduler 图片编排实现只能存在于 `optional_plugins/vision/`。当前静态边界与模拟测试均按此规则执行。
