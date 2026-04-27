# Runner Options

The standard runtime entry is:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\1688-marketplace-research\scripts\run-report.ps1 ...
```

## Parameters

- `-Keyword <string>`
  - required
  - the 1688 search keyword
- `-Pages <int>`
  - default `3`
  - number of list pages to scrape
- `-DetailSampleSize <int>`
  - default `27`
  - number of cheapest items to enrich with detail-page sampling
- `-TaskSlug <string>`
  - optional but recommended
  - controls:
    - generated workflow name
    - report directory name
  - final task folder becomes `runtime/data/reports/1688_<TaskSlug>/`
- `-ProfileDir <path>`
  - default `runtime/data/chrome_profile_1688_fresh_safe`
  - Chrome user-data directory used for CDP attach
- `-CdpPort <int>`
  - default `9232`
- `-Preview`
  - print the generated workflow path and final command without running
- `-SkipCloseout`
  - use only when debugging the wrapper or command generation

## Default Operating Mode

The wrapper always assumes:

- ordinary Chrome profile
- CDP attach
- no proxy unless the environment already sets one explicitly
- meaningful-only closeout

## Final Report Behavior

With `DetailSampleSize > 0`, the final report includes:

- stats cards
- full list table
- detail sample cards
- compact parameter chips
- clickable screenshot lightbox

With `DetailSampleSize = 0`, the report becomes a lighter list-focused report.
