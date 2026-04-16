# hard_input 模块说明

## 模块定位

`hard_input` 是 OmniAuto 的**可选硬输入兜底模块**，与 `engines/visual.py`（基于 pyauto-desktop）并行存在，但物理隔离在独立目录中，避免代码与依赖混在一起。

## 核心能力

基于 [Interception](https://github.com/oblitum/Interception) 内核驱动，在 Windows 键盘/鼠标 Class Driver 下层注入输入事件。对用户态应用（包括 Qt、Chromium、游戏反作弊）而言，这些输入与真实硬件键盘/鼠标无法区分。

## 适用场景

- WPS 文字（`wps.exe`）等 Qt+WebView 应用拒绝接受 `SendInput` 合成输入时。
- 银行客户端、游戏、高安全级别桌面软件。
- 作为所有用户态自动化失效后的最终兜底。

## 环境要求

1. **安装 Interception 驱动**
   ```powershell
   .\tools\interception_bin\Interception\command line installer\install-interception.exe /install
   ```
   需要管理员权限，**安装后必须重启系统**。

2. **Python 依赖**
   ```bash
   uv pip install interception-python
   ```

## 使用方式

```python
from omniauto.hard_input import HardInputEngine

engine = HardInputEngine().start()
engine.click(x=500, y=300)
engine.type_text("Hello World", ensure_english=True)
engine.hotkey("ctrl", "s")
```

## 接口兼容

`HardInputEngine` 暴露的方法与 `VisualEngine` 保持一致：
- `start()`
- `click(x, y, button, pre_delay, duration)`
- `move_to(x, y, duration)`
- `type_text(text, interval, ensure_english)`
- `press(key)`
- `hotkey(*keys)`
- `scroll(amount)`
- `ensure_english_input(...)`

## 注意事项

- `keyboard.sys` / `mouse.sys` 这类内核驱动名称极易触发 360、火绒、Windows Defender 的误报。
- Interception 在部分远程桌面（RDP）环境下可能导致黑屏或断连。
- Windows 11 + HVCI（内存完整性）环境可能需要关闭测试模式或禁用驱动签名强制。
