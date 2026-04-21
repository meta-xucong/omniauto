# runtime/test_artifacts 说明

这里存放测试、验收、调试过程中产生的原始痕迹文件，不放正式业务结果。

## 典型内容

1. 截图
2. 临时 `docx` / `xlsx` / `txt`
3. 调试脚本
4. 状态库和运行快照
5. 历史测试残留文件

## 目录约定

1. `legacy_root/`
   - 历史上散落在项目根目录的测试产物
2. `manual_wps/`
   - WPS 相关人工验收与调试产物
3. `probes/`
   - 平台或代理运行时的探针目录、状态库、一次性诊断现场
4. `screenshots/browser/`
   - 浏览器引擎默认截图
5. `screenshots/visual/`
   - 视觉引擎默认截图
6. `verification/`
   - `workflows/verification/` 对应的验收产物
7. `pytest/`
   - `platform/tests/` 运行产物
8. `pytest/logs/`
   - pytest 文本日志和单次排障输出
9. `pytest-tmp/`
   - pytest 临时目录
10. `.pytest_cache/`
   - pytest cache 目录

## 规则

1. 测试和调试产物不要再写到仓库根目录。
2. 正式业务输出继续放到 `runtime/data/` 或 `runtime/outputs/`。
3. 这里不存平台源码和正式 workflow。
4. `runtime/test_artifacts/` 根部应尽量只保留 `README.md` 和稳定分区目录，不再散放零碎日志文件。
5. 一旦某次任务的经验值得长期保留，应把结论整理到 `knowledge/`，不要让 `runtime/test_artifacts/` 变成唯一记忆来源。
