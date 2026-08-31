# 微信 OCR 多行气泡角色归属修复方案（简化止血版）

> 状态：已按本方案落代码并完成自动化验收。
> 日期：2026-08-31
> 目标：用最小改动解决私聊普通文本气泡多行识别不完整的问题。

本文必须遵守 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md) 和 [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)。本方案只修改 OCR 消息归组和角色继承，属于代码机制层；不生成客户可见文案，不改变 Brain、商品库、识图插件、发送策略或外部接口。

## 1. 修复范围

### 1.1 本次只解决

针对私聊中的普通文本消息，在同一张截图内：

- 一个气泡被 OCR 拆成两行或多行。
- 首行能够判定为客户或我方，后续行没有完整头像。
- 后续行因为文字长度、右边界或中心点不同，被几何规则判成另一侧。
- 最终同一气泡被拆组，部分文本被过滤，只剩第一行。

本次失败样本中的三行都属于同一个左侧 `customer` 气泡，修复后必须作为一条完整客户消息输出。

### 1.2 明确不解决

为了保持改动简单，本版暂不处理：

- 群聊发送者和 `group_member` 角色。
- 语音、图片、文件卡片和媒体混排。
- OCR 本身漏行、错字或截图上下边界裁切。
- 跨多张截图、跨滚动位置的消息拼接。
- 两个相邻气泡都没有头像且边界不清的极端情况。
- 无头像单行消息的现有最终头像门槛行为。

因此本方案的保证范围是：**私聊、普通文本、同一截图、空间上连续的同一气泡**。不能把本版描述成覆盖所有 OCR 多行场景。

## 2. 已确认的故障

失败样本的 OCR 结果本身是完整的：

```text
你不用帮我找你库里有的，我是要你给我根据市场的
公开信息，找几款合适的型号推给我，不要反复问重
复的问题
```

对应三行坐标和置信度：

| 行 | 坐标 | 置信度 |
| --- | --- | --- |
| 1 | `431,778 - 833,798` | `0.998` |
| 2 | `429,802 - 834,822` | `0.997` |
| 3 | `427,824 - 504,848` | `1.000` |

三行实际上都是客户消息。当前实现的问题是逐行先判角色，再按角色分组：

1. 第 1 行因头像证据判为 `customer`。
2. 第 2 行没有完整头像，因动态窗口边界和右侧几何条件误判为 `self`。
3. 第 3 行又被 `self` 续行逻辑吸收进我方组。
4. 第一行客户组被保留，第二、三行所在的无有效头像组被过滤。

根因不是 OCR 没识别出文字，也不是必须重新做头像识别，而是同一气泡内允许每一行独立改变角色。

## 3. 最小修复规则

### 3.1 只增加一个更优先的“同气泡续行”判断

保留现有 OCR 标准化和单行几何分类。单行分类仍然执行，但只作为候选证据。

在现有分组循环中，把新的普通文本续行判断放在以下逻辑之前：

- `self` 续行判断。
- `previous_side == side` 的普通同侧合并判断。
- 新组创建判断。

当前行满足以下条件时，直接并入上一候选气泡组：

1. 当前行和上一组最后一行都是普通文本。
2. 当前行没有检测到新的明确头像角色。
3. 垂直间距使用现有阈值，允许轻微重叠，最大不超过现有 `message_line_continues_previous_self_bubble` 的范围。
4. 当前行与上一行的左边界差值不超过现有 `32` 像素容差。
5. 当前行不在明确的标题、发送区或其他硬 UI 边界内。

不新增环境变量，不新增可调参数，不修改当前窗口尺寸和 OCR 阈值。

### 3.2 组内角色锁定

候选组一旦形成，角色只取一次：

1. 组内已有明确头像角色时，使用该头像角色。
2. 没有头像角色时，使用组首行已有的 `side` 作为临时锚点。
3. 后续连续行无论自己的几何 `side` 是什么，都继承组锚点。
4. 后续行不能把 `customer` 改成 `self`，也不能把 `self` 改成 `customer`。

本次样本的处理结果固定为：

```text
第 1 行：avatar_role=customer，建立 customer 组
第 2 行：满足续行条件，继承 customer
第 3 行：满足续行条件，继承 customer
最终：一条三行 customer 消息
```

### 3.3 明确头像作为新气泡边界

如果当前行检测到明确的 `self` 或 `customer` 头像角色，则默认开始新组，不因间距很小而继续并入上一组。这样可以避免两个相邻消息被误合并。

本版只对私聊使用 `customer/self`，不引入群聊角色判断。

## 4. 实现要求

### 4.1 修改位置

运行逻辑只修改：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py
```

同时更新对应的 OCR 兼容测试和 PR #28 blob 基线哈希，使仓库的冻结文件审计知道这是一次经过批准的后续上游修复：

- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
- `apps/wechat_ai_customer_service/adapters/wechat_pr28_runtime_adapter.py`

建议新增一个私有 helper，例如 `_message_line_continues_same_private_text_bubble(...)`，复用现有垂直间距和左边界判断。也可以在现有 `message_line_continues_previous_self_bubble(...)` 周围增加兼容包装，但不得删除或改变已有函数名、参数和调用合同。

### 4.2 分组顺序

普通文本分组使用以下优先级：

```text
语音专用续行判断
  -> 普通同气泡续行判断
  -> self 旧续行判断
  -> 同侧普通合并
  -> 新建气泡组
```

普通同气泡续行成功后，必须把当前行的 `side` 写成组锚点角色，并追加现有证据字段，例如：

```text
multiline_bubble_role_inherited
bubble_role_anchor=customer
```

不能只追加审计证据，却继续保留当前行错误的 `side`。

### 4.3 最终消息使用组角色

生成最终消息时，`side`、`sender`、`sender_role` 和角色证据必须使用组锚点结果。不能再以当前行自己的几何判断覆盖组角色。

本版不改变无头像单行消息的最终头像门槛，也不调整输入框、媒体或群聊策略。唯一例外是：私聊普通文本已经形成两行或以上、且组内角色已锁定的气泡，即使头像没有被当前截图识别出来，也允许使用组角色通过最终门槛。这是为了避免本次三行消息在归组正确后仍被最后一道头像检查丢弃。

## 5. 伪代码

```python
for item in sorted(rows, key=message_order):
    current_avatar_role = avatar_role(item)

    if not grouped:
        grouped.append([item])
        continue

    group = grouped[-1]
    previous = group[-1]

    if is_voice_continuation(item, group):
        append_with_parent_role(item, group)
        continue

    if current_avatar_role:
        grouped.append([item])
        continue

    if is_same_private_text_bubble_line(item, previous):
        anchor_role = first_avatar_role(group) or group[0]["side"]
        append(item, side=anchor_role)
        continue

    if old_self_continuation(item, previous):
        append_with_side(item, "self")
        continue

    if old_same_side_merge(item, previous):
        append(item, side=group[0]["side"])
        continue

    grouped.append([item])
```

伪代码只表达本次排序和角色继承原则。已有语音、文件、标题、底部区域和最终消息清理逻辑继续保留。

## 6. 测试计划

### 6.1 必测用例

1. 真实失败样本：三行全部输出为一条 `customer` 消息，内容完整。
2. 第一行客户头像，第二行几何上误判 `self`，第三行较短：仍输出一条 `customer` 消息。
3. 第一行我方头像，后续多行几何位置变化：仍输出一条 `self` 消息。
4. 无头像的普通多行消息：在带截图解析中，组角色锁定后仍能保留；无头像单行消息继续遵守原头像门槛。
5. 两个相邻消息各自有明确头像：不能合并。
6. 单行客户和单行我方消息：结果不变。
7. 现有语音转写、文件卡片和输入框残留测试：结果不变。

### 6.2 真实样本

使用既有失败样本重放：

- 截图：`C:\Users\T14S\Desktop\case\车金测试\worker_package\release\data\artifacts\wechat_c2\messages\20260831_005006_locate-20260831_005006-f6f71529\send_guard_1788108607516.png`
- OCR 审核：`C:\Users\T14S\Desktop\case\车金测试\worker_package\release\data\artifacts\wechat_c2\sessions\20260831_004944\sessions_review.json`
- 当前输出：`C:\Users\T14S\Desktop\case\车金测试\worker_package\release\data\artifacts\wechat_c2\messages\20260831_005006_locate-20260831_005006-f6f71529\wechat_messages_frame_review.json`

验收必须满足：

- 只有一条对应客户消息。
- `side == "customer"`。
- `content` 包含三行完整文本。
- 不出现第二条 `self` 消息。
- 不触发 Brain、发送或客户可见回复副作用。

### 6.3 验证命令

```powershell
python -m py_compile apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py
python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py
python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py
git diff --check
```

## 7. 审计标准

落代码后只检查以下几点：

- 普通同气泡续行判断是否在 `self` 续行之前。
- 组内后续行是否强制继承锚点角色。
- 明确头像是否能阻止两个相邻气泡合并。
- 最终消息是否使用组角色，而不是某一行的临时 `side`。
- 是否没有修改 Brain、识图、RPA 发送和外部字段合同。
- 是否没有把群聊或媒体逻辑混入本次止血补丁。

## 8. 已知限制与回滚

本版是止血方案，不承诺解决无头像相邻气泡、群聊、媒体混排、OCR 漏行或跨帧拼接。无头像多行消息如果被错误地聚合，仍可能存在边界风险；本版只保证已满足连续条件且角色已锁定的私聊普通文本组不再被头像门槛丢弃。如果这些场景后续仍有问题，应另立方案，不能继续堆叠本 helper 的阈值。

如果真实样本或回归测试失败，回滚只涉及 sidecar 内部的分组顺序、角色继承和对应测试，不涉及数据库、VPS、worker 配置、API key 或外部服务。

## 9. 结论

本版只做一件事：

```text
同一私聊普通文本气泡一旦确认连续，整组沿用首行/头像锚点角色。
```

它能直接防住本次“三行客户消息被拆成 customer + self + 丢弃”的主要故障，改动小、回归面窄，适合先止血；但它不是完整的通用 OCR 气泡分割框架。

## 10. 实施记录

已完成的代码行为：

- 私聊普通文本在 `self` 续行和同侧合并之前执行同气泡连续判断。
- 同气泡后续行继承首行或头像锚点的 `customer/self` 角色。
- 明确头像行开启新私聊气泡组。
- 已锁定的私聊多行组在无头像证据时不再被最终头像门槛直接丢弃；单行无头像行为保持不变。
- 保持现有函数名、调用签名、消息字段、Brain、RPA 发送和可选插件合同不变。

已通过的验证：

- `py_compile`：sidecar、兼容测试和 PR #28 runtime adapter 通过。
- `run_wechat_win32_ocr_compat_checks.py`：244/244 通过。
- 真实失败截图重放：1 条 `customer` 消息、3 个 OCR 行项、内容长度 52。
- `run_customer_service_absolute_vision_module_boundary_checks.py`：9/9 通过。
- `run_customer_service_optional_plugin_matrix_checks.py`：7/7 通过。
- `run_customer_service_multimodal_session_context_checks.py`：7/7 通过。
- `run_brain_first_static_architecture_audit.py`：9/9 通过。
- `run_workflow_logic_checks.py`：128/128 通过。
- `git diff --check`：通过。
