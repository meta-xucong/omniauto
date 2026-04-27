# Usage Examples

Use these examples when invoking the `1688-marketplace-research` skill from conversation or when running the wrapper script directly.

## 1. Standard 3-Page Report

User-facing invocation:

```text
使用 1688-marketplace-research skill，搜索关键词“色谱柱”，抓前三页，保留 27 个详情抽样，生成完整报告；遇到验证时切到人工接管。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\1688-marketplace-research\scripts\run-report.ps1 -Keyword 色谱柱 -Pages 3 -DetailSampleSize 27 -TaskSlug sepuzhu_3
```

Default behavior:

- The wrapper generates a task-specific workflow under `runtime/generated_workflows/marketplaces/`.
- It runs through ordinary Chrome profile + CDP attach.
- Meaningful-only knowledge closeout is enabled by default.

## 2. Another Keyword With The Same Final Report Format

User-facing invocation:

```text
使用 1688-marketplace-research skill，搜索“童装”，抓前三页，生成和色谱柱同结构的完整报告。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\1688-marketplace-research\scripts\run-report.ps1 -Keyword 童装 -Pages 3 -DetailSampleSize 27 -TaskSlug tongzhuang_3
```

## 3. List-Only Report

User-facing invocation:

```text
使用 1688-marketplace-research skill，只抓列表，不补详情页抽样，生成一个轻量报告。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\1688-marketplace-research\scripts\run-report.ps1 -Keyword 色谱柱 -Pages 3 -DetailSampleSize 0 -TaskSlug sepuzhu_list_only
```

## 4. Preview Only

User-facing invocation:

```text
使用 1688-marketplace-research skill，先预览这次会生成什么 workflow 和命令，不要真正启动。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\1688-marketplace-research\scripts\run-report.ps1 -Keyword 色谱柱 -Pages 3 -DetailSampleSize 27 -TaskSlug sepuzhu_preview -Preview
```

## 5. Debug Wrapper Without Knowledge Closeout

Use this only when checking the wrapper itself.

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\1688-marketplace-research\scripts\run-report.ps1 -Keyword 色谱柱 -Pages 3 -DetailSampleSize 27 -TaskSlug sepuzhu_debug -SkipCloseout
```

## 6. Diagnose Latest Report Without New Run

User-facing invocation:

```text
使用 1688-marketplace-research skill，只检查最新一次 1688 报告为什么不完整，不启动新任务。
```

Inspect:

- `runtime/data/reports/1688_<slug>/run_status.json`
- `runtime/data/reports/1688_<slug>/report_data.json`
- `runtime/data/reports/1688_<slug>/report.html`
- `runtime/data/reports/1688_<slug>/manual_handoff.json`
- `runtime/data/reports/1688_<slug>/browser_artifacts/`

## Recommended Invocation Pattern

When speaking to the AI, prefer this format:

```text
使用 1688-marketplace-research skill，关键词=<关键词>，页数=<N>，详情抽样=<M>，报告要求=<完整/轻量>，遇到验证=<人工接管>。
```
