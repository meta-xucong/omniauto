# archive 目录说明

这个目录存放的是历史脚本、过渡脚本、或保留参考用的旧任务。

它们的特点是：

1. 不作为当前主推荐入口
2. 不参与 `tests/` 里的自动化代码测试
3. 主要用于回溯思路、保留历史产物、或临时迁移兼容

## 当前命名规则

为了和 `workflows/examples/`、`workflows/verification/`、`workflows/generated/` 保持一致，这里的脚本已经统一为简洁的英文 `snake_case` 命名。

当前文件包括：

1. `google_search_kimi_agent.py`
2. `scheduled_tasks_agent.py`
3. `queue_agent.py`
4. `hacker_news_top5_to_excel_agent.py`

## 旧文件名对照

1. `agent_打开Chrome浏览器_访问Google_搜索kimi.py` -> `google_search_kimi_agent.py`
2. `agent_查看当前有哪些定时任务.py` -> `scheduled_tasks_agent.py`
3. `agent_查看队列.py` -> `queue_agent.py`
4. `agent_访问_Hacker_News_抓取前5条标题保存成Excel.py` -> `hacker_news_top5_to_excel_agent.py`

## 使用建议

如果你是第一次了解项目，优先看：

1. [README.md](/D:/AI/AI_RPA/README.md)
2. [START_HERE.md](/D:/AI/AI_RPA/START_HERE.md)
3. [workflows/examples/README.md](/D:/AI/AI_RPA/workflows/examples/README.md)

只有在需要查看历史实现、迁移旧任务、或排查兼容问题时，再进入这个目录。
