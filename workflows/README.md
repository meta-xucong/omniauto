# workflows 目录说明

这里是任务脚本层，不是平台源码层。

## 子目录

- `temporary/`
  - 一次性、探索性、偶尔使用的任务脚本
- `generated/`
  - AI 或模板生成后，仍值得保留的任务脚本
- `verification/`
  - 真实环境验收脚本
- `examples/`
  - 给人和 AI 参考的示例
- `archive/`
  - 历史归档脚本

## 默认落点

1. 一次性或探索性任务先放 `temporary/`
2. 结构较完整、后续还可能复用的生成任务放 `generated/`
3. 真实环境验收脚本放 `verification/`
4. 需要演示系统能力时放 `examples/`
5. 不再推荐但要保留历史痕迹时放 `archive/`

## 和 knowledge 的关系

- `workflows/` 保存可执行脚本
- `knowledge/` 保存这些脚本背后的任务记录、模式、经验和能力解释

## 和 platform 的关系

- `platform/` 是长期基础设施
- `workflows/` 是调用这些基础设施完成具体任务的脚本层
