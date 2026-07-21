# 旧图片接口删除记录（2026-07-21）

本记录用于说明本轮针对旧图片接口的明确授权变更。它不是新的图片实现，也不改变当前独立 Vision 的对外能力。

必须同时遵守：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

## 变更决定

旧图片接口只会返回“已废弃/不支持”结果，不能完成当前要求的“右键复制→读取当前剪贴板→内存识图”闭环。继续保留这些名称会让调用者误以为可以使用，也会给 Sidecar、PR 适配器和 Vision 之间留下第二套入口。

因此本轮经仓库所有者明确授权，删除以下失效入口：

- PR/Sidecar 中的 `self_visual_image_messages_from_current_surface` 空门面；
- PR 运行时适配器中的 `run_customer_clipboard_image_transaction`、`run_self_clipboard_image_transaction` 空门面；
- `adapters/wechat_image_save_capture.py` 旧别名模块；
- Vision 捕获模块中的文件读取、另存为、裁切、归档、旧 `image-save` 和旧图片资产构造函数；
- Vision 消息投影中基于历史文件/截图/旧资产的废弃函数。

## 保留的唯一能力

当前 Vision 模块仍保留并继续测试：

- 当前聊天目标确认和会话绑定；
- 基于相对位置的结构观察；
- 右键点击图片并选择“复制”；
- 当前 Windows 剪贴板代次变化校验和内存读取；
- 客户图/我方图方向隔离、识图理解、Brain 文本投影和调度桥接。

`CapturedMessagesConnector.run_customer_clipboard_image_transaction` 是当前 Scheduler 的实际桥接方法，不能与已删除的 PR 空门面混淆；它仍由现有调度合同使用，未删除、未改签名、未改字段。

## 兼容性边界

这是一次经明确授权的删除性清理，不再承诺旧图片符号的外部兼容。未删除 Brain、Scheduler、RPA、Vision Host API 或当前 Vision 的独立插件协议；这些接口和字段继续保持原样。旧调用者必须迁移到 `optional_plugins.vision` 的当前能力入口，不能通过旧名称获得隐式回退。

## 验收要求

- 旧模块路径和旧符号不存在，调用会得到正常的导入/属性缺失，而不是进入另一条图片实现；
- 当前右键复制和剪贴板代次校验测试继续通过；
- Vision/Voice 可选插件隔离、Brain 唯一出话权、Scheduler/RPA 会话绑定不回归；
- PR 受控清单更新到本轮新的审计基线，不能把删除后的旧 blob 误报成当前源码；
- 不生成图片文件、不读取历史图片路径、不新增图片字段。
