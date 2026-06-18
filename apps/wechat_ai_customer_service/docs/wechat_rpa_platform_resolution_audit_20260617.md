# 微信操控分系统与多分辨率适配审计 2026-06-17

## 结论

当前微信操控能力本质上是 Windows 适配系统：Win32 窗口发现、前台激活、截图、OCR、鼠标键盘输入、发送、监听、加好友都围绕 Windows 微信桌面版实现。当前加好友对外稳定入口是 `add-friend-entry-click-plan`，在 Windows 上路由到 Windows 自适应实现；`add-friend-entry-click-plan-windows` 仅作为显式 Windows 别名保留，固定 1920x1080 参考路线应使用显式 reference route。

这次 Windows 真机修复解决了朋友在 Windows 1920x1080 上开发导致的入口坐标偏移问题：Windows 微信左侧搜索栏旁的加号不再使用靠近聊天分割线的旧点位，而是锚定左侧搜索框。实测手机号 `17756658083` 的加好友流程已经能进入搜索结果，并识别为 `already_friend`。

下一阶段不要继续按单个分辨率补坐标。应把微信操控拆成“平台适配器 + 设备画像 + 布局校准 + 动作回放验证”的体系，让每台客户电脑先生成自己的 UI 几何基线，再执行发送、监听、加好友等业务动作。

## 分系统审计

### 1. 平台路线与能力声明

现状：

- `add_friend_routes.py` 已声明 `ADD_FRIEND_MAIN_ROUTE = ADD_FRIEND_ENTRY_CLICK_ROUTE`，即对外稳定入口仍是 `add-friend-entry-click-plan`；`ADD_FRIEND_WINDOWS_ROUTE` 是显式 Windows 别名。
- `ADD_FRIEND_WINDOWS_1080P_REFERENCE_ROUTE` 保留原入口，用于对照 Windows 1920x1080 布局假设。
- `README.md` 与加好友验收文档已经标记：当前微信操控栈是 Windows 适配，不同分辨率/DPI/窗口尺寸需要布局校准，不能复用固定坐标。

风险：

- 目前只有加好友路线显式分出 Windows 自适应主路线和 Windows 1920x1080 固定布局 reference；其他微信操控能力虽然文档标记为 Windows，但代码边界仍集中在 `wechat_win32_ocr_sidecar.py`。
- 如果后续继续在流程代码里补某台机器的固定坐标，会重新形成分辨率混用。

建议：

- 保持 `wechat_win32_ocr_sidecar.py` 只代表 Windows 操控通道。
- 新增 1920x1080、1920x1200、DPI 缩放等差异时，不新增平台 adapter，而是新增设备画像和布局 profile，通过同一 `WeChatConnector` 契约接入。
- 每个动作 manifest 都要带 `platform`、`route_kind`、`official_main`、`calibration_required`。

### 2. 窗口发现与前台控制

现状：

- Windows 侧通过 Win32 枚举微信主窗口，并用 `validate_capture_geometry` / `validate_send_geometry` 排除最小化、离屏和过小窗口。
- 脚本可选择是否 normalize 窗口，Windows 加好友脚本默认不强制改用户窗口大小。

风险：

- 不同 DPI、多屏、窗口贴边、负坐标屏幕会影响截图坐标映射。
- 如果 normalize 默认开启，客户机器上可能改变用户窗口状态；如果默认关闭，布局差异会暴露给动作层。

建议：

- 将窗口发现输出升级为 `DeviceViewportProfile`：记录 OS、微信版本、窗口矩形、DPI scale、显示器 ID、截图尺寸、是否负坐标、是否最大化。
- 每次动作前校验 profile 是否变化；变化则进入重校准或降级为只读诊断。

### 3. 截图与 OCR

现状：

- 截图、OCR、区域识别都在 Windows sidecar 内完成。
- 加好友搜索结果已经能通过资料页上的 `发消息`、`语音聊天`、`视频聊天` 等信号判断 `already_friend`。

风险：

- OCR 文本可以证明“在哪里”，但不能稳定证明“按钮精确中心点在哪里”。
- 在不同主题、字体缩放、微信版本下，OCR 框可能漂移或漏字。

建议：

- OCR 作为语义确认层，不直接作为唯一点击依据。
- 引入截图视觉锚点：搜索框轮廓、加号按钮轮廓、聊天输入框、发送按钮、资料页主按钮。
- 点击后必须做状态回读：例如点击加号后要看到菜单；点击添加到通讯录后要看到验证申请页；否则撤销或重试候选点。

### 4. 几何与布局定位

现状：

- `session_split_x`、`search_box_point_for_geometry`、`add_friend_windows_plus_button_point_for_geometry` 等函数按窗口宽高和上下限推算点位。
- Windows 加号点已从旧的 `split_x - 16` 改为搜索框锚定点，在 981x860 窗口落在约 x=302。

风险：

- 这是“几何启发式”，不是“机器自适应模型”。在极窄窗口、高 DPI、微信 UI 改版、侧边栏宽度变化时仍可能偏。
- `jitter_window_image_click_surface_point` 中的 `plus_entry_button` 角色仍按靠近 split 的旧条件识别，Windows 新点位通常会落入 `search_or_header_window`，当前能用但元数据不够准确。

建议：

- 把“布局点位函数”从业务流程里抽成 `WechatLayoutModel`。
- 每个点位返回 `point + confidence + evidence + fallback_candidates`，不要只返回 `(x, y)`。
- 对加好友入口至少保留三类候选：搜索框右侧视觉锚点、OCR/图像加号候选、比例 fallback。按置信度排序点击，并用菜单回读验证。

### 5. 动作执行与防风控节奏

现状：

- 加好友流程已有分步 pause、随机 jitter、失败截图和 HTML 复盘。
- Windows 脚本默认聚焦微信，但不默认做 render recovery 和窗口 normalize。

风险：

- 多次错误点击比一次失败更危险，尤其客户机器分辨率未知时。
- 如果状态验证不够强，可能把错误点击后的页面当成下一步继续执行。

建议：

- 默认启用“单步确认”：每个关键点击后必须看到下一状态证据。
- 对未知设备第一次运行走 dry-run calibration，只截图/OCR/规划，不发送、不点击最终确认。
- 客户现场失败时优先产出诊断包，而不是继续重复点击。

### 6. 业务流程层

现状：

- `run_add_friend_entry_click_plan_flow` 已根据 route 选择 Windows 1920x1080 reference 或 Windows locator。
- `WeChatConnector.add_friend` 已走 Windows 主 action。

风险：

- 业务流程层仍能直接调用具体 locator 方法，长期会把平台差异泄漏进流程层。

建议：

- 流程层只依赖能力接口，例如 `layout.locate("add_friend.plus_entry")`。
- Windows/Windows 1920x1080/未来 UIA/视觉模型分别实现 locator，不让业务步骤知道平台坐标。

### 7. 结果契约与诊断产物

现状：

- 加好友结果已经补充 `ok` 字段。
- 运行产物按路线区分到 `runtime/add_friend_entry_click_plan_windows` 与 `runtime/add_friend_entry_click_plan_windows_1080p_reference`。

风险：

- 成功识别 `already_friend` 时，部分中间事件名仍可能带 failure 语义，复盘时容易误读。
- 诊断报告记录了截图和 OCR，但尚未形成可复用的设备校准 profile。

建议：

- 把每次 live run 的 geometry、DPI、窗口状态、关键 locator 证据沉淀为 `wechat_device_profile.json`。
- 报告中区分 `business_result`、`step_status`、`diagnostic_warning`，避免“已是好友”的业务完成被中间失败字样污染。

### 8. 测试覆盖

现状：

- `run_add_friend_package_smoke.py` 覆盖路线 manifest、脚本、artifact scope、Windows/Windows 1920x1080 加号分离。
- `run_wechat_win32_ocr_compat_checks.py` 覆盖 Windows 加号点、already_friend 识别、connector action、几何 guard、发送候选点。

风险：

- 当前多分辨率测试仍主要是几个固定 geometry 样例。
- 缺少来自真实客户机器的 profile replay。

建议：

- 增加参数化矩阵：1366x768、1440x900、1536x864@125%、1920x1080@100/125/150%、2560x1440、双屏负坐标、窄窗口、最大化。
- 每个 live 失败包都能转成离线 replay fixture，回归时重放截图/OCR/geometry。

## 面向不同客户电脑的适配思路

### 第一层：设备画像

首次运行前执行 `wechat profile probe`，只读采集：

- OS 与平台：Windows。
- 微信客户端版本与窗口标题。
- 屏幕数量、主屏分辨率、DPI scale、任务栏位置。
- 微信窗口矩形、客户区尺寸、是否最大化、是否负坐标。
- 截图尺寸与窗口客户区坐标映射。
- OCR 可见文本、主要 UI 锚点、当前页面状态。

输出：

```json
{
  "platform": "windows",
  "wechat_client": "desktop",
  "window": {"width": 981, "height": 860, "left": -22, "top": 0},
  "display": {"dpi_scale": 1.25, "monitor_count": 2},
  "layout_family": "windows_wechat_sidebar_search_v1",
  "calibration_status": "ready"
}
```

### 第二层：布局校准

对每台机器生成 `WechatLayoutModel`：

- 搜索框：优先图像/轮廓检测，其次 OCR 区域，最后几何 fallback。
- 左侧会话栏边界：通过搜索框、会话列表文本、右侧聊天标题共同推断。
- 加号按钮：搜索框右侧视觉锚点 + 小范围候选点扫描，点击后用菜单出现确认。
- 输入框与发送按钮：优先 UIA 控件，失败再用几何候选点。
- 资料页按钮：OCR/视觉按钮区域优先，几何只兜底。

校准结果要有置信度：

```json
{
  "anchors": {
    "add_friend.plus_entry": {
      "point": [302, 70],
      "confidence": 0.86,
      "evidence": ["search_box_anchor", "menu_readback_passed"]
    }
  }
}
```

### 第三层：动作回放验证

正式动作前先跑低风险回放：

- `status`：确认窗口可见、OCR 可读、不是登录/白屏/小窗。
- `layout self-check`：确认搜索框、会话栏、输入框、发送按钮、加号入口。
- `add_friend dry-plan`：只规划加好友路径，不点击最终发送。
- `safe click verification`：每个关键点点击后必须有状态回读，不满足就停止。

### 第四层：客户机器 profile 缓存

每台电脑保存一个 profile：

- 路径建议：`runtime/apps/wechat_ai_customer_service/device_profiles/{machine_id}/wechat_layout_profile.json`。
- profile key：平台、微信版本、DPI、窗口尺寸、布局 family、校准时间。
- 当窗口尺寸、DPI、微信版本变化超过阈值时自动失效。
- 失败 run 自动附带 profile，便于远程诊断和离线 replay。

### 第五层：平台适配器矩阵

建议目标结构：

```text
WeChatConnector
  -> WindowsWin32OcrAdapter
       -> WindowsWechatLayoutModel
       -> WindowsDeviceProfile
       -> WindowsWechatLayoutProfile(1920x1080)
       -> WindowsWechatLayoutProfile(1920x1200)
       -> WindowsWechatLayoutProfile(custom_dpi)
```

业务动作只说“打开搜索”“点击加好友入口”“输入验证消息”“点击发送”，不直接关心坐标。坐标、控件、截图、OCR、Accessibility 都留在平台适配器内部。

## 分阶段落地路线

### Phase 1：当前 Windows 路线收口

- 保持 `add-friend-entry-click-plan` 为对外稳定主路线，Windows 内部实现继续演进。
- 修正 `plus_entry_button` jitter 角色，使 Windows 新加号点也按加号按钮保护边界处理。
- 把 `already_friend` 的中间事件名从 failure 语义整理成 completed/terminal profile state。

### Phase 2：设备画像与报告沉淀

- 增加 `wechat_device_profile.json` 产物。
- status/capabilities/add_friend 报告统一输出 profile 摘要。
- 文档中新增“客户机器首次接入检查表”。

### Phase 3：布局模型抽象

- 新建 `wechat_layout_model.py`。
- 把 `session_split_x`、搜索框、输入框、发送按钮、加好友入口等 locator 收拢。
- locator 返回候选点、置信度、证据和验证方式。

### Phase 4：多分辨率 replay 测试

- 增加几何矩阵单测。
- 把 live 失败包转 fixture 的工具补上。
- 每个 locator 必须在 fixture 上有 expected region，而不是单点固定值。

### Phase 5：Windows 多分辨率 profile 化

- 不再复用某一台机器的固定坐标。
- 优先调研 Windows UIA 能否直接定位微信控件；能用控件时优先用控件，不能用时再用视觉/OCR。
- 对 1920x1080、1920x1200、DPI 缩放、窗口最大化/非最大化统一按“设备画像 + 布局校准 + 回读验证”的同一模型实现。

## 验收标准

- Windows 主路线在当前机器继续通过加好友 live 测试。
- 同一套 add_friend 流程在至少 5 类窗口尺寸/DPI fixture 下能规划正确候选区域。
- 客户机器首次运行必须先生成 profile；未校准不得执行最终发送/确认动作。
- 每次失败都能复盘：设备画像、窗口几何、关键锚点、点击点、点击后状态、OCR 证据齐全。
- Windows 1920x1080/1920x1200 等差异只通过布局 profile 接入，不在业务流程内混入固定坐标。
