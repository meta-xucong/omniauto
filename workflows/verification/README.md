# verification 目录说明

这里存放真实验收脚本，不是 `pytest` 自动化测试。

## 子目录

- `browser/`
  - 浏览器类验收脚本。
- `marketplaces/`
  - 电商/平台类验收脚本。

## 命名规则

- 优先使用 `*_smoke.py`
- 表示这是手动或真实环境下的冒烟验收脚本
- 避免和 `platform/tests/` 里的 `test_*.py` 混淆

## 产物存放规则

- 验收脚本产生的截图、临时文件和调试产物，统一放到 `runtime/test_artifacts/`
- 不再写入项目根目录
- 如需细分，优先使用 `runtime/test_artifacts/verification/...`
