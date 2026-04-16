# OmniAuto 开发架构与实施指南

> 版本: `v1.1`
> 目标: 用最少的理解成本，让开发者、AI 助手、普通用户都能快速看懂 OmniAuto 的目录边界与开发落点。

---

## 1. 这份文档回答什么

这份文档只回答 4 个问题：

1. 核心程序在哪里
2. 用户任务脚本在哪里
3. 自动化代码测试在哪里
4. AI Skill 在哪里，以及为什么会有两个相关目录

这份文档不改变系统架构，只解释当前结构。

---

## 2. 当前项目总结构

```text
D:\AI\AI_RPA
├── README.md
├── PROJECT_STRUCTURE.md
├── docs/
├── src/
│   └── omniauto/
├── workflows/
│   ├── examples/
│   ├── verification/
│   ├── generated/
│   └── archive/
├── tests/
├── skills/
├── .agents/
│   └── skills/
├── data/
├── outputs/
└── tools/
```

---

## 3. 目录边界

### 3.1 `src/omniauto/`

这里是核心 RPA 程序目录。

这里放的是：

- 状态机
- 浏览器引擎
- 视觉引擎
- 硬输入引擎
- 服务层
- Agent Runtime
- 脚本生成器
- 校验器
- 模板系统
- 原子步骤库

一句话理解：

`src/omniauto/` 是产品本体。

### 3.2 `workflows/`

这里是用户任务脚本层。

这里不放框架源码，只放任务脚本。

当前分为：

- `workflows/examples/`
  - 参考示例脚本
  - 帮助用户理解“这个系统能怎么写、怎么跑”
- `workflows/verification/`
  - 真实场景验收脚本
  - 用于手动验收、冒烟验证、边界测试
- `workflows/generated/`
  - 自动生成脚本目录
  - 是 AI 或模板的产物目录
- `workflows/archive/`
  - 历史脚本归档

### 3.3 `tests/`

这里是自动化代码测试目录。

这里放的是：

- `unit/`
- `integration/`
- `e2e/`

一句话理解：

- `tests/` 给开发者和 CI
- `workflows/verification/` 给真实业务验收

### 3.4 `skills/` 与 `.agents/skills/`

这两个目录职责不同。

- `skills/`
  - 用户可读导航层
  - 目的是让人快速找到 Skill，并看懂它是干什么的
- `.agents/skills/`
  - AI 工具运行时真正生效的 Skill 目录
  - 这是 Codex / Kimi / Claude 类工具链的兼容目录

为什么保留两层：

- 不破坏现有 AI 工具运行时兼容性
- 同时提升用户对目录结构的直观理解

---

## 4. `workflows/` 的推荐阅读顺序

如果是第一次接触项目，建议按这个顺序看：

1. `workflows/examples/browser/`
2. `workflows/examples/desktop/`
3. `workflows/examples/scenarios/`
4. `workflows/verification/`
5. `workflows/generated/`

---

## 5. `workflows/generated/` 的任务类型分层

当前 `generated/` 再按任务类型分为：

- `workflows/generated/browser/`
  - 通用浏览器任务
- `workflows/generated/desktop/`
  - 桌面/RPA 自动化任务
- `workflows/generated/marketplaces/`
  - 电商平台任务

当前默认约定：

- Agent Runtime 自动生成的通用任务，默认落到 `workflows/generated/browser/`
- 模板生成的电商研究任务，默认落到 `workflows/generated/marketplaces/`
- `workflows/generated/desktop/` 先作为桌面自动生成任务的保留目录

---

## 6. 核心模块职责

### 6.1 从用户指令到执行结果的主链路

主链路通常是：

1. `agent_runtime.py`
2. `service.py`
3. `orchestration/generator.py` 或 `templating/generator.py`
4. `orchestration/validator.py`
5. `core/state_machine.py`
6. `engines/browser.py` / `engines/visual.py` / `hard_input/engine.py`

### 6.2 关键模块说明

- `core/state_machine.py`
  - 确定性执行层
  - 负责步骤执行、重试、状态持久化、断点恢复
- `service.py`
  - 统一业务入口
  - CLI、API、MCP 都通过这里调用
- `agent_runtime.py`
  - 自然语言任务入口
  - 负责规划、生成、校验、执行、自修复
- `orchestration/generator.py`
  - 通用脚本生成器
  - 当前更偏向浏览器任务
- `templating/generator.py`
  - 模板式工作流生成器
  - 当前更适合电商研究等结构稳定任务
- `orchestration/validator.py`
  - 静态安全校验器
  - 负责拦截危险调用和硬编码敏感信息
- `engines/browser.py`
  - 浏览器自动化引擎
- `engines/visual.py`
  - 视觉自动化引擎
- `hard_input/engine.py`
  - 更底层的硬输入兜底引擎

---

## 7. 自动化代码测试和真实验收脚本的区别

这部分最容易混淆。

### 7.1 `tests/`

特点：

- 面向开发者
- 面向 CI
- 使用 `pytest`
- 用来验证代码正确性

示例命令：

```bash
uv run pytest tests -q
```

### 7.2 `workflows/verification/`

特点：

- 面向真实环境
- 面向业务验收
- 更像可直接运行的任务脚本
- 用来验证产品是否真的能在目标软件或网站中完成任务

示例命令：

```bash
uv run python workflows/verification/browser/baidu_smoke.py
uv run python workflows/verification/marketplaces/1688_smoke.py
```

---

## 8. 推荐命名规则

### 8.1 示例脚本

推荐使用：

- `baidu_search.py`
- `httpbin_demo.py`
- `wps_word_visual.py`
- `hn_to_word.py`

命名原则：

- 简短
- 直接描述任务
- 不带无意义前缀

### 8.2 验收脚本

推荐使用：

- `*_smoke.py`

例如：

- `baidu_smoke.py`
- `1688_smoke.py`

这样可以和 `tests/test_*.py` 明确区分。

---

## 9. 生成脚本的推荐落点

### 9.1 通用浏览器任务

```bash
uv run omni generate "访问百度并搜索关键词" --output workflows/generated/browser/my_task.py
```

### 9.2 电商平台研究任务

建议通过模板生成，并落到：

- `workflows/generated/marketplaces/`

### 9.3 桌面任务

后续若接入桌面任务自动生成，建议落到：

- `workflows/generated/desktop/`

---

## 10. Skill 的使用约定

### 10.1 用户查看入口

用户先看：

- `skills/README.md`
- `skills/deterministic-rpa-workflow/README.md`

### 10.2 运行时入口

AI 工具运行时实际读取：

- `.agents/skills/deterministic-rpa-workflow/SKILL.md`

### 10.3 原则

- 用户入口负责可读性
- 运行时入口负责兼容性
- 两者职责不同，不应该混用

---

## 11. 当前开发建议

如果要继续扩展项目，推荐遵循下面的落点：

1. 核心逻辑改动放 `src/omniauto/`
2. 自动化代码测试放 `tests/`
3. 新增示例脚本放 `workflows/examples/`
4. 新增真实验收脚本放 `workflows/verification/`
5. 自动生成产物放 `workflows/generated/`
6. 用户可读 Skill 说明放 `skills/`
7. 运行时 Skill 资产放 `.agents/skills/`

---

## 12. 一句话总结

现在的 OmniAuto 结构可以用一句话概括：

- `src/omniauto/` 是程序本体
- `workflows/` 是用户任务脚本层
- `tests/` 是开发测试层
- `skills/` 是用户可读导航层
- `.agents/skills/` 是 AI 运行时技能层
