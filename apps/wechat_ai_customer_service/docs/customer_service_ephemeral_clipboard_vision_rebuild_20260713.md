# 微信客服识图模块：剪贴板瞬时理解重构开发文档（2026-07-13）

> [!WARNING]
> **文档状态：安全规则保留、模块落点已废止（2026-07-18）。** “只认本次右键复制后的当前剪贴板、不落盘、不裁切、不回退”仍是强制规则；Connector/Sidecar 图片事务、外部 workflow 所有权和散落调用方式不得继续扩展。端到端实现必须收束到 [完全独立图像识别模块改造方案](customer_service_absolute_independent_vision_module_refactor_plan_20260718.md) 规定的 vision 模块。

## 0. 文档地位与必须遵守的基线

本文是 `apps/wechat_ai_customer_service` 图片理解能力的重构规格，适用于 Chejin 及任何使用 Windows 微信 RPA 的租户。

它必须同时遵守：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)：`customer_service_brain` 是唯一客户可见回复作者；识图模块只能给出事实性理解结果和审计信息。
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)：视觉能力是独立、可选、懒加载的插件域；不得破坏 Scheduler、Brain、RPA、语音或外部调用方既有合同。

当旧的图片实现、测试或文档与本文冲突时，以下规则优先：**客户图片的内容来源只能是本次右键“复制”后、在同一 RPA 事务内读取到的当前 Windows 剪贴板图片；图片不得作为文件或持久化数据保存；持久化对象只允许是 LLM 已输出的文字/结构化理解结果。**

本文替代此前把 `visual_bubble_crop`、截图裁切或本地图片资产作为识图输入的设计。旧文件中的相关表述只保留作历史说明，不得继续作为实现依据。

## 1. 目标、非目标与硬规则

### 1.1 目标

为一条当前客户图片消息生成可靠的、可供 Brain 使用的文字理解结果，例如：

```json
{
  "vision_summary": "白色奥迪 A4L 车辆外观照，画面可见车头与侧前方。",
  "image_ocr_text": [],
  "entities": {"brand_candidates": ["奥迪"], "series_candidates": ["A4L"]},
  "intent_hints": {"needs_clarification": false}
}
```

该结果只能作为 Brain 的辅助证据；车型价格、库存、政策和承诺仍只能来自产品主数据与正式知识。

### 1.2 非目标

- 不建立聊天图片库、图片 RAG、图片训练集、缩略图库或图片留存档案。
- 不用截图裁切、颜色/纹理/语义特征来代替微信原图。
- 不根据识图结果直接生成、替换或发送客户可见回复。
- 不读取、恢复或复用历史轮次的图片。
- 己方图片不进入客户回复链路；当捕获到明确的己方图片消息时，可走同一“右键复制→当前剪贴板→内存理解”事务，且仅把文字理解写入会话上下文。

### 1.3 不可突破的操作规则

1. 图片内容输入只能来自**当前**剪贴板中的 `CF_DIB`/位图图片，且必须由本次复制动作产生。
2. 结构定位只用于确定右键目标；不能产出图片内容，也不能当作成功依据。
3. 不得把剪贴板图片写为 PNG/JPG/WebP/BMP、临时文件、缩略图、截图裁切、元数据旁路文件或 base64 日志。
4. 未验证复制成功、剪贴板未变化、剪贴板不是图片、图片解码失败、LLM 调用失败，均是明确失败；不得用裁切图、历史文件或旧剪贴板内容补救。
5. 一次图片信号最多进行一次物理右键复制事务。失败后由 Brain 基于事实性失败记录决定是否澄清；RPA 不得循环右键或自行写回复。
6. 识图完成后立刻释放内存中的图片字节和 PIL 对象；跨模块、跨任务、跨轮次只传递文字理解结果和无图片内容的事务审计。

## 2. 目标架构

```text
会话监控发现“当前客户图片”信号
        │
        ▼
视觉插件（懒加载，独立域）
  结构定位：当前会话 + 客户侧 + 最新媒体行
        │
        ▼
RPA 剪贴板事务（单锁、一次性）
  clipboard_seq_before
  → 右键目标 → 点击“复制” → clipboard_seq_after 必须变化
  → 只读取当前位图到内存
        │
        ▼
视觉 LLM（内存字节直传）
  图片字节不落盘、不进入 JSON 日志
        │
        ▼
文字化 VisionResult
  vision_summary / OCR 文本 / 实体 / 不确定性 / 事务审计
        │
        ▼
兼容桥接层
  保持既有 Brain 外层字段，去除 saved_image_path 等内容引用
        │
        ▼
customer_service_brain
  只依据授权文字证据形成客户可见回复
```

### 2.1 为什么“剪贴板瞬时读取”是唯一内容来源

裁切图不可避免会带入聊天背景、头像、气泡边框、屏幕缩放和其他消息；历史文件则可能属于旧轮次。剪贴板图片是微信在本次右键复制后给出的原始媒体数据，配合复制前后系统剪贴板序号变更，能够证明它属于本次物理操作。

不过剪贴板本身不能证明“右键是否点在正确消息上”。因此必须同时满足两组证据：

- **目标证据**：活动会话名称/句柄、客户侧头像列、最新媒体行、目标点位在结构边界内；
- **复制证据**：右键成功、菜单中识别到“复制”、菜单点击成功、`GetClipboardSequenceNumber` 在点击后变化、读取结果是有效图片。

缺任意一项即失败，不进入视觉 LLM。

## 3. 数据边界与持久化规则

### 3.1 可在内存中短暂存在的数据

- 微信窗口截图（只为本次结构定位，在内存中）；
- 当前剪贴板的图片对象/字节；
- 为视觉 API 编码的 base64 请求体；
- 本次请求完成前的本地尺寸、格式和像素安全校验数据。

这些对象不得被写入磁盘、state、ledger、prompt archive、异常日志或 sidecar stdout JSON。

### 3.2 允许持久化的数据

仅保存以下**文字或不含图片内容的审计元数据**：

```json
{
  "schema_version": 2,
  "message_id": "原有会话消息标识",
  "source": "clipboard_current_transaction",
  "captured_at": "2026-07-13T...",
  "transaction": {
    "status": "understood",
    "clipboard_sequence_changed": true,
    "menu_copy_confirmed": true
  },
  "understanding": {
    "vision_summary": "...",
    "image_ocr_text": ["..."],
    "classification": {},
    "entities": {},
    "intent_hints": {},
    "bridge": {},
    "catalog_alignment": {}
  }
}
```

允许保留的关联字段仅限会话 ID、消息 ID、时间、非内容性状态码和 LLM 输出文字。禁止持久化：文件路径、文件 hash、像素尺寸、截图边界、图片 MIME/base64、图片 URL、asset ID、图片列表、缩略图路径和原始 prompt。

### 3.3 Prompt archive 改造

图片域默认不得归档 `customer_image_understanding_prompt`、重试 prompt、图片路径、Provider 原始响应或视觉桥接中的原始资产字段。

如需要审计，只能写入精简后的 `customer_image_understanding_text_result`，内容为上述 `understanding` 与无图片内容事务状态。默认关闭旧的 `include_image_prompts`、`include_image_results`、`include_visual_bridge` 路径；不能仅靠配置约定，代码必须在图片域入口剥离图片内容后才允许写档。

## 4. 模块职责与改造范围

### 4.1 保持不变的外部边界

- `customer_service_brain`、Brain evidence 外层合同、回复队列、发送确认、会话绑定和 RPA 发送路径不改变。
- `OptionalCapabilityPlugin` 注册/懒加载协议不改变；核心仍只依赖中性协议。
- 语音插件不导入视觉实现，视觉插件不导入语音实现。
- 既有公开函数、CLI 名称、字段仍保留兼容门面；不允许调用方因本次内部重构改代码。

### 4.2 视觉插件的新内部模块

建议在 `optional_plugins/vision/` 内拆分，主程序只能经插件协议调用：

```text
optional_plugins/vision/
  plugin.py                    # 仅协议入口、懒加载
  trigger.py                   # 图片信号判定，不读剪贴板
  clipboard_transaction.py     # 右键复制、序号校验、内存读图
  clipboard_payload.py         # 内存图片安全编码与释放
  understanding.py             # 调用视觉 LLM，返回文字结果
  text_result_store.py         # 仅写文字理解结果
  compatibility.py             # 向旧 Brain bridge 输出兼容投影
```

`wechat_image_save_capture.py` 可保留为兼容门面，但其图片业务实现必须改为调用 `clipboard_transaction`；文件名和公开入口不变，不能再有保存图片的真实实现。

### 4.3 需要废止的行为

以下逻辑不得保留为可达生产分支：

- `capture_visual_images()` 中 `capture_mode="crop"`、`side_filter="all"` 的生产调用；
- `save_visual_bubble_crop()`、`build_visual_bubble_archive_payload()`；
- `visual_bubble_crop`、`visual_bubbles_archived` 作为成功状态；
- `saved_image_path`、`bubble_crop_path`、`thumbnail_path` 的识图输入、状态复用或 Brain bridge 传递；
- `detect_customer_image_region()` 的截图裁切回退；
- `image_assets/`、`customer_image_understanding/` 图片目录与 `.meta.json` 写入；
- 旧的持久化 `self_image_context` 队列及其图片资产输入；己方图片只能以当前剪贴板内存事务产生文字上下文，不能创建回复任务或图片存档；
- 任何从 session ledger、payload、历史消息读取旧图片路径的分支。

不能直接删除冻结的公开符号。兼容门面应返回明确的非成功状态，例如 `image_capture_legacy_asset_rejected`，并在内部转到新事务；不能再返回裁切图或伪造成功资产。

## 5. 剪贴板事务详细设计

### 5.1 前置条件

1. 已通过活动会话校验，当前窗口与目标会话严格匹配；
2. 当前轮次具有新的客户图片信号及稳定 `pending_signal_id`；
3. 结构检测仅返回一个客户侧、最新可见媒体行候选；
4. 目标候选在聊天区、客户媒体列和对应头像列邻近约束中均成立；
5. 同一 `pending_signal_id` 未曾执行或完成图片事务。

任一前置条件不成立，返回无物理操作的事实状态，如 `image_clipboard_capture_not_eligible`。

### 5.2 原子步骤

在同一 `wechat_rpa_lock("image_clipboard_transaction")` 内执行：

1. 获取 `clipboard_sequence_before`；
2. 用结构候选的锚点右键；
3. 捕获菜单画面到**内存**并 OCR，确认复制菜单项；
4. 点击复制菜单项；
5. 轮询有限时间，要求 `clipboard_sequence_after != clipboard_sequence_before`；
6. 读取剪贴板，只接受有效位图或可解码图片；
7. 在内存中完成尺寸/解压炸弹/最大像素/最大请求体校验；
8. 将内存图片直接交给视觉 Provider；
9. 无论成功、失败或异常，关闭/清空图片对象和编码缓冲区；
10. 仅返回文字 `VisionResult` 和无图片内容的事务审计。

不得调用“另存为”，不得把路径粘贴到保存对话框，不能重试右键。若复制后读取到非图片，必须返回 `clipboard_current_content_not_image`，而非读取旧文件。

### 5.3 并发与剪贴板污染防护

- 图片复制、剪贴板读取和视觉请求准备处于单一会话锁内；其它微信 RPA 动作不得插入。
- 点击复制后只接受**序号已变化**的剪贴板内容；序号不变即拒绝，即便剪贴板上已有图片。
- Provider 请求前保留内存图片对象；Provider 返回后立即释放，不把 base64 放入日志或返回 payload。
- 人工或其他程序抢占剪贴板导致序号再次变化、无法读取或内容类型异常时，失败而不猜测。

## 6. Brain 与 Scheduler 的兼容接入

### 6.1 Scheduler

Scheduler 仅做三件事：

1. 把当前客户图片信号交给视觉插件；
2. 接收 `VisionResult` 的文字化投影；
3. 将其绑定到当前 `pending_signal_id`/session，并交给既有 Brain evidence seam。

Scheduler 不读取或保存图片，也不解析剪贴板；可通过中性视觉能力协议请求一次己方图片的上下文专用事务。该事务不得创建客户回复任务、不得发送消息，且仅接收文字 `VisionResult`。

图片事务失败时，Scheduler 仅附加事实性记录：`image_capture_status`、失败代码、当前消息 ID。对图片-only 回合，由 Brain 决定是否请求客户重发或描述图片；不得生成本地兜底话术。

### 6.2 Brain bridge

兼容层仍可以输出既有 `customer_image_understanding` 与 `visual_bridge_input` 外层键，但其内容只能来自 LLM 的文字结果。

禁止在桥接字段中输出：`saved_image_path`、`asset_id`、`image_assets`、`bubble_bounds`、`sha`、`thumbnail_path` 或图片数据。旧调用方若读取这些可选字段，收到空值/缺失字段时必须仍可工作；此变化需通过 characterization tests 证明。

### 6.3 Provider

将 Provider API 从 `image_paths: list[str]` 扩展为内部私有的内存图片载荷接口，例如 `image_payloads: list[ClipboardImagePayload]`。新的载荷对象不得可 JSON 序列化，也不得写入 trace。

兼容门面可暂时保留旧 `image_paths` 参数供外部导入和测试使用，但生产调用必须拒绝路径输入并返回 `legacy_image_path_input_rejected`。清理期结束前，旧函数只能用于隔离的历史兼容测试，不能被 listener/scheduler/插件调用。

## 7. 迁移计划

### 阶段 A：合同与测试先行

1. 新增本文规则的 contract tests，先让现有实现暴露失败；
2. 建立 `ClipboardTransactionResult` 与 `VisionTextResult` 的中性、无图片内容合同；
3. 增加禁止写图、禁止路径复用、禁止裁切成功状态的静态/运行时检查；
4. 保留旧 API 的 facade 和 reason code 映射，不删除公开导入路径。

### 阶段 B：实现瞬时剪贴板事务

1. 实现剪贴板序号读取、复制动作证据、内存图像读取和 finally 清理；
2. 让视觉 Provider 接收内存载荷；
3. 让视觉插件只返回文字 `VisionResult`；
4. 先在不发送模式下跑真实微信回放，确认磁盘没有新图片文件。

### 阶段 C：切换主路径并封死旧路径

1. Scheduler 从 `capture_visual_images()` 切换到中性视觉插件调用；
2. 删除生产调用到裁切/资产/历史路径的所有边；
3. 移除旧 self image context 图片入队；保留可选的、当前剪贴板文字上下文事务；
4. 将图片 prompt archive 改为文字结果归档；
5. 对既有运行目录执行只读盘点；历史图片不再被加载，不在本任务中擅自删除。

### 阶段 D：审计与交付

1. 运行 unit、contract、插件隔离、多会话和真实回放测试；
2. 从一次真实图片事件的日志证明：右键、复制、序号变化、内存理解、仅文字落盘；
3. 检查运行目录无新 `.png/.jpg/.jpeg/.webp/.bmp/.meta.json` 图片产物；
4. 确认 Brain/RPA 外层 fixture 不变、无跨会话发送、无本地客户回复。

## 8. 必须新增的验收测试

### 8.1 图片来源与无落盘

- 客户图片：右键复制后序号变化、内存图片被 Provider 收到、只保存文字结果；
- 剪贴板原有旧图片但复制未改变序号：必须失败，不调用 Provider；
- 右键菜单没有复制项：必须失败，不裁切、不另存为；
- 复制后剪贴板是文本/文件列表/空：必须失败，不复用旧文件；
- 全流程扫描临时目录、tenant runtime、prompt archive：不得出现任何本次图片文件、base64 或图片路径；
- Provider 成功、失败、超时、异常时，都验证内存对象释放且无图片落盘。

### 8.2 会话和方向

- 同屏客户与己方各有图片：客户图片与己方图片必须按方向分开选择，不能互相误复制；
- 只有己方图片：可执行一次上下文专用视觉理解并记录文字结果，但不得入回复队列、不得发送消息；
- 多会话切换/标题不匹配：不右键、不读取剪贴板；
- 同一 `pending_signal_id` 多次轮询：最多一次物理事务、最多一次文字理解结果；
- 新图片到来后：旧理解结果不被复用，必须重新完成当前剪贴板事务。

### 8.3 Brain 和合同

- Brain 只能接收文字化 `VisionTextResult`，不含路径、asset、hash、边界或图片数据；
- 图片理解失败时，结果只含事实性失败码；客户可见措辞必须来自 Brain；
- 原有 `ProductMasterStore`、RPA send、session ledger、scheduler、可选语音/视觉矩阵和多会话 fixtures 均保持通过；
- 静态 forbidden-import 检查确认核心不导入具体视觉 Provider、视觉不导入语音。

## 9. 完成定义（Definition of Done）

只有同时满足以下条件，才能宣告本次升级完成：

- 生产识图路径没有任何截图裁切、图片文件保存、资产复用或己方图片理解；
- 所有视觉输入均可追溯到一次当前剪贴板复制事务，且有序号变更证据；
- 磁盘、ledger 和 prompt archive 中只保留 LLM 文字理解结果及无图片内容的最小事务状态；
- 图片失败不会静默丢弃客户回合，也不会产生本地客户可见回复；
- Brain、Scheduler、RPA 的对外工作方式与既有兼容合同通过回归测试；
- 在真实微信一次客户图片测试中，观察到“复制 → 当前剪贴板 → LLM → 文字结果”，且运行目录没有新图像文件。
