# test_artifacts 目录说明

这个目录专门存放测试、验收、调试过程中产生的文件。

包括但不限于：

1. 截图
2. 临时 `docx` / `xlsx` / `txt`
3. 调试脚本
4. 历史测试遗留文件

## 目录约定

1. `legacy_root/`
历史上散落在项目根目录中的测试产物，统一迁到这里。

2. `manual_wps/`
WPS 相关人工验收或调试时生成的临时文档。

3. `screenshots/browser/`
浏览器引擎在未显式指定路径时生成的默认截图。

4. `screenshots/visual/`
视觉引擎在未显式指定路径时生成的默认截图。

5. `verification/`
`workflows/verification/` 里的验收脚本产物。

6. `pytest/`
`tests/` 里的自动化测试产物。

## 规则

1. 测试产物不要再写到项目根目录。
2. 正式业务输出继续放到各自原本的业务目录，例如 `outputs/`、`data/reports/`。
3. 这里只放测试和调试过程文件。
