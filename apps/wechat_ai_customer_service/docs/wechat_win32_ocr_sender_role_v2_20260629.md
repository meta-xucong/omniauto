# WeChat Windows OCR 发信人角色判定 V2 开发文档

## 1. 背景

本问题发生在 OmniAuto Windows OCR sidecar 解析微信聊天窗口时。旧逻辑把 OCR 文本框的
`left` 坐标作为强判定条件：只要文本框左边界超过 `self_left_min`，就直接认为该消息是
`self`。

这个规则在真实微信窗口里不可靠。左侧客户气泡有头像、气泡内边距和聊天区缩放差异，短文本
可能出现在聊天区中部；暗色微信里客户气泡又是深灰色，不能再依赖“左侧白气泡、右侧绿气泡”
这种只适合亮色主题的视觉规则。

## 2. 问题定义

旧逻辑会把左侧客户消息误识别为客服自己发出的消息。后端按既有约定把 `self` 存成
`sales_candidate`，最终表现为：客户说的话被记录成客服说的话，收发双方身份颠倒。

本次修复只处理 Windows OCR sidecar 的发信人角色识别，不改变后端字段含义、入库映射和客服
回复生成架构。

## 3. 设计原则

- `left` 坐标只能作为弱线索，不能单独决定 `self`。
- `self` 必须是右侧结构性结论：文本或气泡区域确实抵达右侧发送气泡区域，并且中心点处于
  右半区。
- 只看右边界也不够；输入框草稿可能从左侧开始铺到右侧，必须同时具备右侧起点和右侧结构。
- 对证据不足或冲突的消息，优先输出 `unknown`，不能冒险输出 `self`。
- 亮色和暗色微信使用同一套结构规则，不写两套主题分支。
- 不引入分辨率特化业务规则，所有阈值基于窗口宽度和聊天区分割线做相对判断。

## 4. V2 判定规则

### 4.1 自己发送的消息

满足以下结构特征时，判为 `self`：

- OCR 文本右边界抵达右侧 self lane。
- OCR 文本中心位于聊天区右半部分。
- OCR 文本左起点也落入右侧气泡文本起点范围。
- 对较短但明显右对齐的气泡，允许通过“右边界非常靠右 + 中心靠右”判为 `self`。
- 多行右侧 self 气泡的短尾行，如果与上一行 self 在垂直间隙和左缩进上都表现为同一气泡续行，
  可以继承上一行 `self`，但不能把独立消息合并进来。

### 4.2 客户或未知方向消息

满足以下任一情况时，不能判为 `self`：

- 只是 `left` 超过旧阈值，但文本右边界没有抵达右侧 self lane。
- 文本出现在聊天区中部，但不具备右侧气泡结构。
- 左侧客户气泡在亮色主题下呈白/浅灰，或在暗色主题下呈深灰。

## 5. 回归样本

- 亮色模式：左侧客户短消息，旧逻辑会因为 `left` 偏右误判，新逻辑必须输出非 `self`。
- 亮色模式：右侧绿色客服消息，新逻辑必须继续输出 `self`。
- 暗色模式：左侧深灰客户消息，新逻辑必须输出非 `self`。
- 暗色模式：右侧绿色客服消息，新逻辑必须继续输出 `self`。
- 历史样本：右侧长气泡虽然中心点接近旧阈值，也必须继续合并并判为 `self`。

## 6. 代码落地范围

- 修改 `wechat_win32_ocr_sidecar.py` 的发信人角色判定。
- 保留 `classify_message_side()` 对外函数名，避免破坏既有调用。
- 新增可审计字段：算法版本、置信度、判定证据。
- 在兼容性测试里加入亮色和暗色几何样本。

## 7. 验收标准

- 客户消息不会因为 OCR `left` 触发旧阈值而被判为 `self`。
- 明暗两种微信主题下，左侧客户消息都不会被当作客服消息。
- 明暗两种微信主题下，右侧客服消息仍能被识别为 `self`。
- 既有右侧长气泡 self 样本保持通过。
- 右侧多行 self 气泡的短尾行保持合并，不因 V2 保守判定被拆成客户消息。
- 不触发真实微信发送动作，不影响 Brain First 客服回复所有权。

## 8. 截图级 Replay

坐标级单元测试之外，还应支持本地截图级 replay：对真实微信截图运行 OCR，再把 OCR 结果送入
`parse_messages_from_ocr()`，只检查角色和几何摘要，不打印识别出的消息正文。

运行方式：

```powershell
$env:WECHAT_WIN32_OCR_SENDER_ROLE_LIGHT_SCREENSHOT = "<light screenshot path>"
$env:WECHAT_WIN32_OCR_SENDER_ROLE_DARK_SCREENSHOT = "<dark screenshot path>"
$env:WECHAT_WIN32_OCR_SENDER_ROLE_REPLAY_REQUIRE_INPUTS = "1"
$env:WECHAT_WIN32_OCR_SENDER_ROLE_REPLAY_REQUIRE_OCR = "1"
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_sender_role_screenshot_replay.py
```

验收要点：

- 亮色截图中至少有一条右侧消息判为 `self`，至少有一条左侧消息判为非 `self`。
- 暗色截图中至少有一条右侧消息判为 `self`，至少有一条左侧消息判为非 `self`。
- 对亮色截图里“旧 left 阈值会触发，但没有抵达右侧 self lane”的客户消息，必须保持非 `self`。
