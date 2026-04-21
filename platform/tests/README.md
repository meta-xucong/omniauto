# platform/tests 说明

这里存放的是平台级自动化测试，不是面向最终用户的一次性任务脚本。

## 当前分层

- `unit/`
  - 单元测试
- `integration/`
  - 集成测试
- `e2e/`
  - 端到端测试

## 和 workflows/verification 的区别

- `platform/tests/`
  - 面向开发者和 CI
  - 使用 `pytest`
  - 目标是守住平台行为和能力边界
- `workflows/verification/`
  - 面向真实环境验收
  - 更像可直接运行的任务脚本
  - 目标是验证系统能否在真实网站或软件中完成任务

## 和 knowledge 的关系

当某次任务沉淀成长期经验后：

1. 任务记录和解释写进 `knowledge/`
2. 真的需要长期守住的行为补进 `platform/tests/`

换句话说：

- `knowledge/` 负责记忆和解释
- `platform/tests/` 负责回归保障
