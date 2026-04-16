# 从哪里开始看

如果你是第一次打开这个项目，建议按下面顺序看：

1. [README.md](/D:/AI/AI_RPA/README.md)
了解项目目标、核心能力和基础用法。

2. [PROJECT_STRUCTURE.md](/D:/AI/AI_RPA/PROJECT_STRUCTURE.md)
快速看懂每个目录分别放什么内容。

3. [src/omniauto](/D:/AI/AI_RPA/src/omniauto)
这里是核心 RPA 程序本体。

4. [workflows/README.md](/D:/AI/AI_RPA/workflows/README.md)
这里看用户任务脚本怎么分类、怎么使用。

5. [workflows/examples/README.md](/D:/AI/AI_RPA/workflows/examples/README.md)
这里看最容易上手的示例脚本。

6. [workflows/verification/README.md](/D:/AI/AI_RPA/workflows/verification/README.md)
这里看真实场景验收脚本，不和自动化代码测试混在一起。

7. [workflows/generated/README.md](/D:/AI/AI_RPA/workflows/generated/README.md)
这里看 AI 自动生成的任务脚本默认会落到哪里。

8. [skills/README.md](/D:/AI/AI_RPA/skills/README.md)
这里看给 AI 的 Skill 有哪些、分别负责什么。

9. [docs/development.md](/D:/AI/AI_RPA/docs/development.md)
如果要继续开发、扩展模板、补测试，从这里开始。

## 一句话理解这套结构

- 核心程序在 [src/omniauto](/D:/AI/AI_RPA/src/omniauto)
- 用户任务脚本在 [workflows](/D:/AI/AI_RPA/workflows)
- 自动生成脚本在 [workflows/generated](/D:/AI/AI_RPA/workflows/generated)
- 自动化代码测试在 [tests](/D:/AI/AI_RPA/tests)
- 测试产物统一放在 `test_artifacts/`
- 用户可读 Skill 导航在 [skills](/D:/AI/AI_RPA/skills)
- AI 运行时 Skill 在 `.agents/skills/`

## 如果你只想快速试一下

1. 先看 [workflows/examples/README.md](/D:/AI/AI_RPA/workflows/examples/README.md)
2. 再挑一个示例脚本运行
3. 需要验收时，再看 [workflows/verification/README.md](/D:/AI/AI_RPA/workflows/verification/README.md)

## 测试产物放哪里

所有测试、验收、调试阶段产生的截图和临时文件，统一放到 `test_artifacts/`，不再写入项目根目录。
