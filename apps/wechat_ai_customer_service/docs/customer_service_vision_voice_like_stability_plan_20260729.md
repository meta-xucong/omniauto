# WeChat 客服 Vision 极简图片组与有限回溯方案

日期：2026-07-30
状态：方案审计通过；允许按本文 Phase 1B 开工，未完成模拟门禁前不得启动真实微信手测
实现范围：`apps/wechat_ai_customer_service/optional_plugins/vision/**`
测试范围：Vision 专项测试和既有合同门禁

本方案必须同时遵守：

- [`customer_visible_reply_ownership_baseline.md`](customer_visible_reply_ownership_baseline.md)
- [`customer_service_external_contract_and_optional_plugin_baseline.md`](customer_service_external_contract_and_optional_plugin_baseline.md)

## 1. 当前基线

本轮错误方向已经收束：

- GitHub 共同基线为 `0d1ce30e`。
- 本地通过 `07af5711` 撤销了此前扩散到 Monitor、Workflow、复杂 store、quiet 和多阶段 budget 的 Vision 大改。
- 非 Vision 运行代码与共同基线无内容差异。
- 当前唯一待接线的新增运行代码是 Vision 私有纯算法：
  `optional_plugins/vision/capture/visual_anchor.py`。
- 该算法及其专项测试已经覆盖：当前客户 turn 内 1-3 张图、跨帧一对一匹配、同图纵向移动、同内容重复发送、wrong scope、processed/consumed、超过 3 张和歧义 fail-closed。
- 纯算法尚未接入 scheduler、RPA、剪贴板或 provider。

工作区中的 compiled data、learning pack 和换行状态不是本方案内容，不得清理、重写或提交到本轮实现。

## 2. 本轮只解决两个问题

1. 客户发一张图片后紧接几条文字，图片被顶偏或顶出当前帧时，Vision 仍能在有限范围内找回并识别。
2. 当前客户 turn 内同时存在 2-3 张图片时，不再猜其中一张；按聊天顺序处理整组图片，一次交给现有 Vision provider。

稳定单图必须继续走快速路径。普通文字、Voice、自定义 Vision 插件和无 Vision 配置不得改变。

## 3. 明确不做

本轮不恢复或新增以下机制：

- 不修改 `session_monitor.py`，不保留或改写 media kind。
- 不修改 `customer_service_scheduler.py`、`listen_and_reply.py`、Brain 或 Voice。
- 不建立 persistent occurrence store、claim、TTL cache 或跨事务图片状态。
- 不建立 surface quiet 状态机、轮询稳态或多阶段 deadline/budget。
- 不建立通用 action guard、分辨率适配或第二套发送窗口校验。
- 不在 provider 返回后再次扫描聊天区，不做递归 delta 循环。
- 不新增 provider 重试策略。
- 不跨多张截图拼接一个 2-3 图组；本阶段整组必须在同一张选定截图中完整可见。
- 不修改 scheduler/Brain/message/proxy/transaction 的公共形状。

最后一条是本轮最重要的复杂度边界：跨帧算法只用于确认同一 occurrence 在滚动或 fresh reanchor 后仍是同一张图，不负责把多张不同时可见的图片拼成一组。

## 4. 为什么无需修改 Monitor

共同基线已经具备中立入口：每次真实 scheduler capture 都会通过现有 Vision bridge 调用
`optional_plugins/vision/scheduler_capture.py::prepare_scheduler_capture()`。

基线 Vision scheduler hook 在后续文字覆盖侧栏 `[图片]` 预览后，仍会观察当前聊天 surface。因此本轮只需把该 Vision 私有观察从“当前帧一次”扩展为“当前帧优先，失败后有限向上回溯”。

边界必须诚实：如果上游没有任何当前 pending，当前帧和有限回溯范围也没有可证明的客户图片，Vision 无法凭空知道更早曾发过图片。此时不得猜测，也不得为此修改 Monitor；按原纯文字路径处理。只要 Vision 已严格确认当前视觉 turn，后续取得图片或理解失败就必须在 Brain 前终止本轮。

## 5. 唯一主链

```text
Vision scheduler locate
  -> 当前帧找完整的本轮客户图片组
  -> 找不到才有限向上回溯
  -> 找到 1-3 张：投影既有 structural occurrence + 既有 image proxy
  -> 找不到或歧义：不猜

Vision runtime acquire
  -> 用同一个 matcher 重新定位同一图片组
  -> 当前帧唯一单图：直接复制快路
  -> 回溯图或多图：一次 fresh reanchor
  -> 按上到下逐张复制并校验剪贴板内容
  -> 1-3 张全部成功：一次 batch provider 调用
  -> 任一失败：释放整组图片，Brain 前 fail-closed
```

locate 与 acquire 必须调用同一个 Vision 私有 collector 和同一个 `visual_anchor` matcher。允许因为冻结的 scheduler/runtime 边界而重复截图，不允许写两套选择算法，也不允许用持久 store 偷渡 bounds、crop 或 fingerprint。

## 6. 当前 turn 与图片组判定

### 6.1 硬门槛

每个候选必须同时满足：

- request 和 candidate 都有非空且一致的 `session_key`、`target_identity`、`conversation_type`。
- side 为 `customer`。
- 不跨最近的 self reply 边界。
- 未 processed、未 consumed。
- 有 structural/stable/relation 身份之一；图片内容 fingerprint 不能单独证明 occurrence 身份。

候选自己的 scope 不得从 request 静默补齐后再冒充已确认。语义 `conversation_type` 只供 Vision matcher 使用；物理微信 target validation 继续使用现有 PR28 identity projection，不改通用 RPA 合同。

### 6.2 成员资格

允许确认图片属于当前 customer turn 的证据只有：

1. 显式图片 pending 下，当前帧恰好只有一张合格客户图片，这是旧单图快路。
2. 图片与当前 customer turn 中唯一正文锚点存在确定的 preceding/following relation。
3. 有可见 self reply 边界，图片位于该边界之后且当前 customer turn 内没有新的 self reply。

多图不得仅因为“都在当前屏幕上”就自动归为一组。2-3 张图至少要由正文关系或 self 边界证明属于同一 turn。重复侧栏 preview、模糊包含匹配、最下面、最新、面积最大和 y 坐标都不能破除成员歧义。

y 坐标只在成员资格已经确定后用于同一截图内从上到下排序。

### 6.3 跨帧匹配

`match_visual_occurrence_groups()` 用一对一全局匹配完成 fresh reanchor：

- 同一图上下移动仍是同一 occurrence。
- 同内容再次发送且 occurrence 身份不同，仍是两张图。
- fingerprint 相同但 occurrence 关系不唯一时 fail-closed。
- fresh frame 出现额外候选、候选缺失或映射不唯一时，不点击。

现有 Phase 1A matcher 的职责到此为止。collector 负责先建立 turn 边界和候选 scope，再把合格候选交给 matcher；不得反过来让 matcher猜 turn。

## 7. 有限回溯

只复用 Voice 已验证的流程思想，不 import Voice 实现：

```text
capture -> OCR -> parse -> detect -> match
  -> 未找到：向上滚动一次
  -> 再 capture/OCR/parse/detect/match
  -> 找到即停
  -> finally 恢复最新位置
```

固定内部上限，不新增公共配置：

- 显式图片/media pending：最多向上滚动 6 次、最多 8 张截图、总时长最多 12 秒。
- 后续文字覆盖图片预览后的 normal 多文字 fallback：仅在当前 customer turn 至少 2 条未处理真实客户文字且首条正文锚点唯一时启用；最多向上滚动 2 次、最多 3 张截图、总时长最多 6 秒。
- 普通单条文字继续旧 current-surface observe，不进入 bounded backsearch。
- 只有实际发生滚动才执行 restore latest。

每一帧都必须重新确认当前 target/session；右键前再确认一次 focus/target。回溯中发现 wrong session、self boundary 冲突、超过 3 张或歧义，立即 fail-closed。

本轮不设置 quiet budget、copy budget、restore budget 等子预算。只有一个总时长、滚动数和截图数。

## 8. 复制和剪贴板一致性

### 8.1 单图快路

显式图片 pending、当前帧唯一合格客户图、未滚动且 target/focus 未变化时，复用当前截图直接执行旧物理动作：

- 右键一次。
- 确认本次右键后出现的“复制图片”菜单。
- 菜单点击一次。
- clipboard generation 必须变化。
- bitmap 必须可读。

不额外跑 quiet，不多做一轮 OCR。

### 8.2 回溯或多图

回溯找到图片，或图片组含 2-3 张时，只做一次 fresh reanchor。fresh frame 必须与选中组一对一匹配且顺序不变；否则在剩余总预算内重新定位一次，仍不成立就失败。

确认后在同一 Vision 私有 worker、同一 RPA lease 和同一选定截图中，按上到下逐张执行旧复制动作。任一张失败，整组失败，不把部分图片交给 provider。

### 8.3 内容一致性弱校验

点击前对目标图片内缩后的 screenshot crop 计算 transaction-local fingerprint；复制后对 clipboard bitmap 做同样归一化。最小校验采用：

- orientation 一致；
- 宽高比相对误差不超过 18%；
- 64-bit dHash 汉明距离不超过 16；
- 3x3 RGB 粗颜色网格的平均通道差不超过固定私有阈值。

这些是 Vision 私有常量，不是配置项。fingerprint 只能阻止明显复制错图，不能决定图片属于哪个 turn，也不能区分同内容重复发送的两个 occurrence。

fingerprint 不一致时，只允许 fresh reanchor 同一 occurrence 后重试该图片一次。第二次仍不一致，或无法唯一 reanchor，整组失败；不得换候选偷试。

## 9. 跨进程图片传递

现有公开 `copy-current-image` worker CLI 和 `run_clipboard_image_transaction()` 语义保持不变，继续服务旧单图调用。

新图片组路径使用一个 Vision 私有 worker 入口，不给旧 worker CLI 新增参数或 operation。父进程只通过该私有入口的 stdin 发送单次 transaction request；不得新增环境变量、配置项或复用 `source_preview` 偷渡内部控制字段。该私有 worker 在同一进程内完成逐图复制、读取和 fingerprint 校验，然后只通过 stdout 向 Vision 父进程返回：

- 1-3 个经过大小限制的 PNG base64 私有 payload；
- 既有高层 transaction 成功/失败审计。

每张解码后不得超过现有 `MAX_IMAGE_PAYLOAD_BYTES`，整组 encoded wire payload 上限固定为 12 MiB。超限整组失败。

父进程立即解码为现有 `EphemeralClipboardImage`，调用 provider 后逐个 release。所有 base64、crop、bounds、fingerprint、anchor 和 matcher 结果必须在 Vision facade 返回前递归剥离，且不得写日志、文件、scheduler state、message、Brain evidence 或公共 transaction。

采用私有 worker 是为了同时满足：旧 worker CLI 不变、多图只回溯一次、每张 clipboard bitmap 能在下一次复制覆盖前被读取。不得改成临时图片文件、公共 CLI 参数或跨进程 persistent store。

## 10. Provider 与 Brain

- 1-3 张校验通过的图片按聊天顺序一次性传给现有 `maybe_run_customer_image_understanding()`。
- runtime 必须在调用前显式校验数量为 1-3，不能依赖 provider 内部静默切片。
- 正常单图和正常多图都只有一次 provider 调用。
- 本轮不做 provider 返回后的第二轮 surface 扫描。
- provider 失败、空 summary 或整组任一图片失败时，不生成部分 visual evidence。
- Vision 不生成客户可见回复；Brain 仍是唯一回复作者。

共同基线 Workflow 在文本 batch 非空时不会只因 `adoptable=False` 自动停下。因此只在以下条件同时成立时，Vision 使用 neutral optional dispatcher 已保留的异常传播语义，在 Brain 前终止当前 task：

1. scheduler/runtime 已严格确认当前 turn 存在必要客户图片；
2. acquire、clipboard 校验或 provider 最终失败。

该异常为 Vision 私有实现细节，不新增公共 reason、payload 字段或外部必填参数。普通文字、没有当前图片证据、历史图片、另一 session、缺 Vision 插件和 custom Vision 插件不得触发。

编码前先做 characterization test：若该异常不能沿现有调用链稳定产生 `Brain=0、ready reply=0、send=0`，立即停止实现并重新审计；不得修改 Workflow 来补洞。

## 11. 最小文件范围

允许修改的运行文件仅限：

- `optional_plugins/vision/capture/visual_anchor.py`
- `optional_plugins/vision/capture/wechat.py`
- 至多一个新的小型 Vision 私有 fingerprint/collector helper
- `optional_plugins/vision/integrations/wechat_current.py`
- `optional_plugins/vision/integrations/wechat_worker.py` 的复用 helper；旧 CLI 行为不变
- 至多一个新的 Vision 私有 group worker 入口
- `optional_plugins/vision/scheduler_capture.py`
- `optional_plugins/vision/runtime.py`

禁止修改：

- `admin_backend/services/session_monitor.py`
- `admin_backend/services/customer_service_scheduler.py`
- `workflows/listen_and_reply.py`
- `internal/vision_bridge.py`
- `optional_plugins/dispatch.py`
- Voice、Brain、product master、通用 RPA adapter

实现代码在现有 Phase 1A 之外预计净增不超过约 600 行。超过 800 行，或需要新增第二个状态模块、公共字段、公共 CLI 参数时，必须停下重新审计，不得继续补代码。

## 12. 最小测试矩阵

1. Phase 1A 纯算法测试继续全部通过。
2. 显式单图当前帧：0 scroll、0 fresh OCR、右键/菜单各一次、provider 一次。
3. 图片后 5 条文字且图片离开当前帧：有限上滚找回，restore latest，provider 一次。
4. 同一截图内当前 turn 2 张和 3 张图：按上到下全部复制，一次 batch provider。
5. 历史图 + self reply + 当前图：只处理当前图。
6. 多图没有正文/self 边界、两组平分或超过 3 张：不点击、不调用 provider。
7. 同图滚动后位置变化：fresh reanchor 成功；同内容重发仍保留两个 occurrence。
8. clipboard mismatch：只重试同一 occurrence 一次；第二次失败时 provider 为 0。
9. 组内任一张复制失败、wire 超限或 restore 失败：释放全部图片，provider 为 0。
10. strict visual failure 经真实 neutral dispatch/未改 Workflow 链路后，Brain=0、ready reply=0、send=0。
11. 普通文字、旧 no-pending/signal-only、无 Vision、custom Vision 行为不变。
12. public worker CLI、Vision facade、message/transaction/Brain evidence 无新增字段；私有字段递归不泄漏。
13. multi-session wrong target/session 不点击；Vision 不 import Voice。

模拟测试至少连续跑三轮，结果一致后才允许真实微信手测。真实手测顺序固定为：

1. 单图。
2. 单图后立即 5 条文字。
3. 同一 customer turn 连续 2 张图。

任一步失败立即停止 listener，不继续发送下一组消息。

## 13. 实施顺序与停点

### Phase 1B-0：先证明 Vision-only fail-stop 可行

- 不改运行代码，先补 characterization test。
- 让测试 Vision plugin 在“已确认必要图片但取得证据失败”处抛出私有异常。
- 走真实 neutral dispatch 和未改 Workflow 调用链，断言 Brain=0、ready reply=0、send=0。
- 同时断言普通文字、无 Vision 和 custom Vision 旧返回不受影响。

只有该测试证明现有异常传播链可用，才允许进入 Phase 1B-1。若不成立，方案自动退回审查，不得修改 Workflow、dispatcher 或公共合同补洞。

### Phase 1B-1：先闭合定位

- 把现有 Phase 1A matcher 接到 Vision 私有 current-frame collector。
- 加入固定 6/8/12 有限回溯和 restore。
- scheduler hook 只投影既有 structural occurrence + 既有 proxy。
- 先跑纯 locate 测试，不做右键。

### Phase 1B-2：再闭合复制

- 保留旧单图快路。
- 实现同一截图内 1-3 图逐张复制、fingerprint 校验和一次 mismatch retry。
- 私有 worker 传回 ephemeral payload；父进程递归清理。

### Phase 1B-3：最后接 provider 和 fail-stop

- 1-3 图一次 batch provider。
- 整组失败不产生部分 evidence。
- 完成 Brain=0/ready=0/send=0 characterization。
- 三轮模拟门禁通过后回传审查，未经复审不得启动微信。

每个 Phase 完成后都要给审查员看 scoped diff 和测试结果。不得把后续 Phase 的代码提前混入。

## 14. 审计结论

结论：**A，可以按本文开工 Phase 1B。**

审计确认：

- 方案只在 Vision 运行域实现，没有恢复此前越界的 Monitor/Workflow/Brain 改造。
- 直接复用 Voice 的有限截图回溯思想，但不 import Voice，也没有复制 Voice 专用字段。
- 现有 Phase 1A 纯 matcher 得到明确职责，不承担 RPA、store 或调度状态。
- 单图保持快路；多图只扩展为同一截图内的 1-3 图组，不引入开放循环。
- clipboard fingerprint 是复制后的弱安全门，不参与 turn 归属，避免再次把 hash 当身份。
- 失败阻断先以现有异常传播链做 characterization；验证失败即停，不允许向 Workflow 扩散。
- 固定限制、文件范围、行数上限和三轮模拟门禁足以阻止实现再次膨胀。

开工口令：**方案确定，可以指挥主线先执行 Phase 1B-0；只有 Vision-only fail-stop characterization 通过后，才可继续 Phase 1B-1。Phase 1B-1 只完成定位与模拟测试，然后停下回传审查。**
