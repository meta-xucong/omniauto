# marketplace_1688_research

这是一个用户批准的 OmniAuto 正式 `task_skill`。

- Runtime bundle: `.agents/skills/1688-marketplace-research/`
- App package: `apps/marketplace_1688_research/`
- Scope: 运行 1688 关键词调研任务，抓取前 N 页列表，补充详情抽样，生成完整 HTML 报告，并在验证出现时切换到人工接管
- Primary base workflow: `apps/marketplace_1688_research/workflows/base_1688_research.py`
- Main report template: `platform/src/omniauto/templates/reports/ecom_report.html.j2`
- Main artifacts: `runtime/apps/marketplace_1688_research/reports/1688_<slug>/`

## What This Skill Covers

- 1688 关键词搜索任务的标准化启动
- 普通 Chrome profile + CDP attach 的运行模式
- 前 N 页列表抓取
- 最低价样本详情补充
- 完整报告生成
- 黑底提示的人机验证接管
- 报告结构和布局问题复盘

## Boundaries

- This skill formalizes the 1688 marketplace research task family; it does not by itself promote the implementation into `platform/src/omniauto/skills/`.
- It must not be used to bypass captchas or evade site risk controls.
- Human verification handoff is part of the approved workflow boundary.

## Runtime Entry

For runtime behavior, use the bundle under:

- `apps/marketplace_1688_research/`
- `.agents/skills/1688-marketplace-research/`

The app package is the formal task implementation. The `.agents` bundle is the AI-facing operational skill and should point to the app entrypoints.
