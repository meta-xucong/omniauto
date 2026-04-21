# OmniAuto 开发指南

这份文档解释平台层应该如何扩展，以及每类改动应该落到哪里。

## 目录边界

```text
platform/
├─ src/omniauto/
├─ tests/
├─ tools/
└─ docs/
```

- `platform/src/omniauto/`
  - 平台本体代码
- `platform/tests/`
  - 平台长期回归测试
- `platform/tools/`
  - 维护与诊断工具
- `platform/docs/`
  - 平台技术文档

## 关键模块

- `platform/src/omniauto/core/`
  - 状态机、上下文、异常
- `platform/src/omniauto/engines/`
  - 浏览器、视觉、硬输入等执行引擎
- `platform/src/omniauto/orchestration/`
  - 任务生成、校验、守护节点
- `platform/src/omniauto/recovery/`
  - 运行时恢复、人工接管、恢复规则
- `platform/src/omniauto/templates/`
  - 可复用模板
- `platform/src/omniauto/templating/`
  - 模板生成与注册

## 平台改动原则

1. `platform/` 不是临时任务实验区。
2. 一次性任务优先落到 `workflows/temporary/` 或 `workflows/generated/`。
3. 只有用户明确要求时，才把任务经验正式吸收进 `platform/src/`。
4. 平台代码一旦变化，优先评估是否需要同步更新 `platform/tests/` 和 `knowledge/capabilities/`。

## 平台测试和任务验收的区别

- `platform/tests/`
  - 验证平台代码行为
  - 适合 CI 和持续回归
- `workflows/verification/`
  - 验证真实场景任务是否打通
  - 适合业务验收和环境检查

## 常用命令

```bash
uv run pytest platform/tests -q
uv run pytest platform/tests --collect-only -q
uv run omni validate workflows/generated/browser/my_task.py
```

## 变更落点建议

1. 核心逻辑改动放 `platform/src/omniauto/`
2. 平台回归测试放 `platform/tests/`
3. 临时任务脚本放 `workflows/temporary/`
4. 生成任务脚本放 `workflows/generated/`
5. 任务复盘和经验沉淀放 `knowledge/`
6. 只有用户批准后，才升级到 `skills/` 或继续硬化进 `platform/`
