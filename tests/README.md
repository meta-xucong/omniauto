# tests 目录说明

这里放的是“自动化代码测试”，不是用户任务脚本。

## 当前分层

- `unit/`
  - 单元测试

- `integration/`
  - 集成测试

- `e2e/`
  - 端到端测试

## 和 workflows/verification 的区别

- `tests/`
  - 面向开发者和 CI
  - 用 `pytest` 跑

- `workflows/verification/`
  - 面向真实场景验收
  - 更像“可执行任务脚本”
