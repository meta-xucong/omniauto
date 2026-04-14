---
name: deterministic-rpa-workflow
description: |
  指导 Kimi 将复杂浏览器自动化任务拆分为确定性 Workflow + AtomicStep 执行，
  禁止在运行时用 AI 做视觉决策或实时思考。适用于电商抓取、数据调研、报告生成等多步骤任务。
  触发条件：用户要求执行需要浏览器操作的复杂任务（如"抓取XX前N页并生成报告"、"调研某网站数据"）。
---

# 确定性 RPA 工作流

## 核心原则

接到复杂浏览器任务时，**禁止**让 AI 直接思考"点哪里、写什么"。必须先把任务拆成确定的 `AtomicStep` 链，再交由状态机执行。

## 执行顺序（不可跳过）

1. **URL 规律分析**
   - 检查目标网站是否支持通过 URL 参数完成"搜索 + 排序 + 翻页"
   - 例如 1688: `sortType=price_sort-asc&beginPage=1`
   - 能直接拼 URL 的，**绝不**让 AI 去点按钮

2. **模板选择**
   - 使用 `omniauto.templating.generator.TemplateGenerator`
   - 优先匹配 `task_type`:
     - 电商商品调研 → `ecom_product_research`
     - 通用列表抓取 → `generic_browser_scrape`
   - 查看 `src/omniauto/templates/workflows/` 下可用模板

3. **步骤拆分（固定 4 步）**
   - Step 1: 导航搜索页（含排序参数）
   - Step 2: 翻页抓取列表（每页后 `throttle_request`）
   - Step 3: 抽样进入详情页获取深度信息（`cooldown` 间隔）
   - Step 4: 清洗数据并生成报告（HTML/JSON）

4. **参数配置**
   - `inter_step_delay`: (2.0, 4.0) 或更高
   - `throttle_request`: 翻页间 4~8 秒
   - `cooldown`: 详情页间 5~10 秒

5. **生成并执行**
   - 生成 `.py` 脚本后，通过 `OmniAutoService.run_workflow()` 运行
   - 执行过程中 AI **不干预**状态机运行

## 约束清单

- [ ] 未用 AI 视觉识别按钮位置
- [ ] 未在运行时动态生成点击逻辑
- [ ] 所有 DOM 选择器在脚本中硬编码
- [ ] 步骤间有随机冷却
- [ ] 翻页有显式限速
- [ ] 报告由模板填充，非 LLM 生成文案

## 参考资料

- 1688 选择器与参数速查: [references/1688-selectors.md](references/1688-selectors.md)
- 反检测与冷却策略: [references/stealth-patterns.md](references/stealth-patterns.md)

## 模板骨架

当没有现成模板时，复制 [assets/workflow-template.py.j2](assets/workflow-template.py.j2) 并修改。
