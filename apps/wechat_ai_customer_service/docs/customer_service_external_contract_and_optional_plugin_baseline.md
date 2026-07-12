# 微信客服对外合同冻结与可选插件隔离基线

本文服从并引用 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)。本基线属于项目兼容性和代码机制层规则，不改变 Brain First、商品库、正式知识、RPA 安全边界或客户可见回复所有权。

## 1. 适用原因

OmniAuto 已被外部开发者引用。外部调用方可能依赖当前变量名、导入路径、函数签名、返回字段、配置、状态文件或接口行为，但这些调用方不一定存在于当前仓库中。

因此，不能以“仓库内没有引用”为依据修改对外合同。所有未知外部消费者默认存在。

## 2. 冻结范围

以下内容默认全部冻结：

- 模块间通讯变量和常量名称。
- Python/JavaScript 导出符号和导入路径。
- 类名、函数名、参数名、参数顺序和默认值。
- 返回 dict/JSON 的字段名、类型、含义、可空性和默认值。
- API route、HTTP method、请求和响应字段。
- CLI 命令、参数和输出字段。
- 配置键、环境变量和默认行为。
- event/action/reason/state/error code 名称。
- 状态文件路径、顶层结构和外部可读取字段。
- connector、sidecar、Brain bridge 和插件挂载接口。
- artifact 目录、文件命名和第三方可消费的审计字段。

内部私有实现可以重构，但不得让调用方修改代码才能继续工作。

## 3. 兼容式重构规则

### 3.1 门面保持不变

拆分大文件时，原模块必须继续保留原函数、类和 import path：

```python
# 原入口保持不变
def select_batch_details(*args, **kwargs):
    return _batch_selection.select_batch_details(*args, **kwargs)
```

可以使用：

- facade。
- wrapper。
- re-export。
- alias。
- adapter。

不允许移动实现后要求外部调用方同步修改 import。

### 3.2 字段只增不改

确需新增字段时：

1. 字段必须 optional。
2. 旧调用方完全忽略它时行为不变。
3. 缺失时有与旧版本一致的默认行为。
4. 不能复用旧字段表达新含义。
5. 必须增加 contract test。

字段重命名不能直接执行。如确有必要，必须先同时输出旧字段和新字段，提供明确兼容期，并由仓库所有者批准下线旧字段。

### 3.3 行为同样属于合同

即使字段名不变，下列变化也属于潜在破坏：

- 从 optional 变成 required。
- 从空字符串变成 null，或相反。
- 改变默认超时、重试次数或错误码。
- 改变列表顺序、状态含义或发送确认语义。
- 原本模块缺失可运行，改成模块缺失启动失败。
- 原本同步返回，改成必须异步等待。

这些变化必须按破坏性合同变更处理。

## 4. 语音插件独立基线

语音模块是可选能力域，不是主程序必选依赖。

语音模块独立负责：

- 语音气泡识别。
- 客户与我方语音转文字动作。
- 转写结果提取和语音 provenance。
- 语音模块自身的重试、审计和可用性状态。

语音模块不得：

- import 识图模块实现。
- 依赖图片模型、图片库、剪贴板图片处理或视觉 provider。
- 直接修改识图配置和状态。
- 生成客户可见回复。
- 拥有主调度器或 Brain 状态。

第三方可以不加载内置语音模块，也可以挂载自己的语音插件。主程序必须继续运行。

## 5. 识图插件独立基线

识图模块是另一个可选能力域，与语音模块严格隔离。

识图模块独立负责：

- 图片气泡识别和资产保存。
- 客户与我方图片的 occurrence/asset 元数据。
- 视觉模型调用和结构化理解结果。
- 客户图片到现有 Brain bridge 的兼容结果。
- 我方图片只补上下文、不触发客户回复的边界。

识图模块不得：

- import 语音模块实现。
- 依赖语音转写、音频库或语音配置。
- 直接修改语音状态。
- 生成客户可见回复。
- 拥有主调度器或 Brain 状态。

第三方可以不加载内置识图模块，也可以挂载自己的识图插件。主程序必须继续运行。

## 6. 允许共享的最小协议

两个插件可以共享一个纯协议模块，但协议模块必须满足：

- 不 import 任意语音或识图实现。
- 不依赖音频、图片、OCR、剪贴板、模型 SDK 或 provider。
- 只定义 capability、context、result、error 和 lifecycle 等中性接口。
- 插件实现通过 lazy loader 或显式注册挂载。
- scheduler/Brain bridge 只依赖协议，不依赖具体插件。

建议中性协议只包含：

```python
class OptionalCapabilityPlugin(Protocol):
    name: str

    def available(self) -> bool: ...
    def should_run(self, context: dict) -> dict: ...
    def run(self, context: dict) -> dict: ...
```

协议返回值进入 compatibility adapter，再映射到现有语音或识图字段。不能借插件化重命名现有共享字段。

## 7. 推荐内部目录

```text
apps/wechat_ai_customer_service/
  optional_plugins/
    contract.py
    registry.py
    loader.py
    voice/
      plugin.py
      trigger.py
      transcription.py
      compatibility.py
    vision/
      plugin.py
      trigger.py
      capture.py
      understanding.py
      compatibility.py
```

`voice` 与 `vision` 必须可以分别复制、安装、禁用、替换和测试。

## 8. 大文件拆分规则

允许并鼓励拆分：

- `customer_service_scheduler.py`
- `customer_service_scheduler_state.py`
- `listen_and_reply.py`
- Win32/OCR sidecar 中相互独立的纯逻辑。

推荐先抽取纯函数和独立 service，再保留原门面：

```text
customer_service_scheduler.py
  -> scheduler/capture_pipeline.py
  -> scheduler/freshness.py
  -> scheduler/send_pipeline.py
  -> scheduler/recovery.py
  -> scheduler/context_bridge.py

listen_and_reply.py
  -> reply_runtime/batch_selection.py
  -> reply_runtime/message_normalization.py
  -> reply_runtime/context_builder.py
  -> reply_runtime/brain_bridge.py
  -> reply_runtime/send_orchestration.py
  -> reply_runtime/legacy_state_compat.py
```

第一阶段只搬实现，不改函数签名、字段和行为。行为优化必须在后续独立变更中进行，便于定位回归。

## 9. 必须通过的兼容矩阵

每次涉及插件、主调度器或模块拆分时，至少验证：

1. core only。
2. core + 内置语音。
3. core + 内置识图。
4. core + 内置语音 + 内置识图。
5. core + 第三方语音实现。
6. core + 第三方识图实现。
7. 语音依赖缺失，但 core 和识图正常。
8. 识图依赖缺失，但 core 和语音正常。
9. 旧 import path 和公开函数仍可调用。
10. 旧输入 payload 得到同结构、同语义输出。
11. 旧状态文件无需人工修改即可读取。
12. Brain First 和多会话绑定测试继续通过。

## 10. 破坏性变更审批

只有在原合同确实无法保留时，才允许提出破坏性变更。提案必须明确：

- 旧名称、字段或接口。
- 新名称、字段或接口。
- 为什么 facade/adapter 无法解决。
- 哪些外部调用方受影响。
- 兼容期和双轨方案。
- 迁移工具、测试和回滚方案。
- 旧合同下线日期。

未得到仓库所有者对以上内容的明确批准前，不得落实现有合同的删除、重命名或语义变化。

## 11. 当前实施方向

当前阶段采用“兼容门面 + 内部小模块 + 独立可选插件 + 现有框架内收拢”的方式。

不采用大规模替换 scheduler、ledger、Brain bridge、状态字段或对外接口的方案。此前统一账本审计中的大框架替换内容仅保留为长期风险分析和未来可选研究，不作为当前获批实施路线。

当前优化、减负和拆分顺序以 [customer_service_contract_preserving_optimization_and_slimming_audit_20260713.md](customer_service_contract_preserving_optimization_and_slimming_audit_20260713.md) 为实施依据。
