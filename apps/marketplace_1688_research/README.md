# 1688 Marketplace Research App

This app package is the formal home for the OmniAuto 1688 keyword research workflow.

Use this package for:

- 1688 keyword research configuration.
- Base and generated research workflows.
- Report runner scripts.
- Closeout helpers.
- Offline checks.
- Task-specific documentation.

The historical generated workflows under `workflows/generated/marketplaces/` remain available for compatibility, but new development should prefer this app package.

## Main Entrypoints

```powershell
powershell -ExecutionPolicy Bypass -File apps/marketplace_1688_research/scripts/run-report.ps1 -Keyword 色谱柱 -Pages 3 -DetailSampleSize 27 -TaskSlug sepuzhu_3
```

Preview without launching a browser:

```powershell
powershell -ExecutionPolicy Bypass -File apps/marketplace_1688_research/scripts/run-report.ps1 -Keyword 测试 -Pages 1 -DetailSampleSize 0 -TaskSlug preview -Preview
```

