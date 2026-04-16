# workflows 目录说明

这里是“任务脚本层”，不是框架源码层。

## 子目录

- `examples/`
  - 参考示例脚本。
  - 下面再按 `browser/`、`desktop/`、`scenarios/` 分类。

- `verification/`
  - 手动验收、真实场景测试脚本。
  - 下面再按 `browser/`、`marketplaces/` 分类。

- `generated/`
  - AI 或模板自动生成的脚本默认输出目录。
  - 下面再按 `browser/`、`desktop/`、`marketplaces/` 分类。

- `archive/`
  - 历史脚本归档。

## 使用约定

- 新生成的任务脚本：放 `generated/`
- 通用浏览器任务：优先放 `generated/browser/`
- 桌面/RPA任务：优先放 `generated/desktop/`
- 电商平台研究任务：优先放 `generated/marketplaces/`
- 想给用户演示的脚本：放 `examples/`
- 用来做真实验收的脚本：放 `verification/`
- 不再主推但要保留的旧脚本：放 `archive/`

## 推荐阅读顺序

1. 先看 `examples/browser/`
2. 再看 `examples/desktop/`
3. 需要完整场景时看 `examples/scenarios/`
4. 做真实验收时看 `verification/`
