# 江苏车金二手车演示数据与长测报告 2026-05-03

## 结论

本轮已把 `jiangsu_chejin_usedcar_customer_20260501` 补成可演示的二手车专用 customer 数据空间，并完成离线、接口、共享公共知识链路和微信实盘烟测。当前可交付给客户演示。

本轮额外修复了一个运行时读取问题：商品专属问答/规则/解释已经保存到 `product_item_knowledge`，但 `KnowledgeRuntime.list_items("product_faq")` 这类通用列表读取不到。已在 `apps/wechat_ai_customer_service/workflows/knowledge_runtime.py` 增加文件存储下的商品专属知识列表读取逻辑，并通过回归。

## 演示账号

- 账号：`jiangsu_chejin_usedcar_customer_20260501`
- 密码：`chejin.20260501`
- 展示名：`江苏车金二手车测试客户 2026-05-01`
- 邮箱：`jiangsu-chejin-usedcar@example.local`

## 新增材料覆盖

新增脚本：`apps/wechat_ai_customer_service/tests/seed_jiangsu_chejin_used_car_demo.py`

资料覆盖范围：

- 车辆商品：轿车、SUV、MPV、新能源、豪华车、高端车、已售归档样本。
- 政策规则：过户资料、二手车销售统一发票、订金/定金边界、金融审批、置换、检测报告、事故水泡火烧、调表、抵押查封、异地迁入、新能源电池、试驾、售后、投诉、隐私资料等。
- 客服话术：预算推荐、车型对比、置换、预约、金融、发票、异地、事故、电池、已售替代、投诉、售后、人工转接等。
- 商品专属知识：每个重点商品配套专属问答、风险规则和讲解重点。
- 原始记录：模拟微信群、文件传输助手、私聊线索、置换线索，进入原始消息库并触发 RAG/候选链路。
- RAG资料：车辆库存总表、交易规则手册、销售话术库、风险边界矩阵。
- 共享候选：使用 mock VPS 检查 customer 正式知识向共享公共知识候选提炼时，不泄露私有客户信息。

## 当前数据量

截至本轮长测结束，二手车账号主要数据量：

- 商品资料：27 条
- 政策规则：31 条
- 聊天话术：38 条
- 商品专属问答：19 条
- 商品专属规则：19 条
- 商品专属解释：19 条
- RAG 来源：78 条
- AI经验：66 条
- 原始微信消息：142 条
- 原始会话：10 个
- 待确认知识：42 条
- 已通过候选：3 条
- 已驳回候选：1 条

## 行业规则依据

演示规则主要参考以下公开官方来源，并在系统内转换为“客户可读”的提醒和转人工边界：

- 商务部《二手车流通管理办法》发布说明：强调不得隐瞒车辆真实情况、保证来源合法、提供质量保证和售后服务，并按规定开具统一发票。
  https://tfs.mofcom.gov.cn/fgsjk/flfg/sclt/tdspgl/art/2005/art_63f1d0ed4eb64a599fea698a765d78c4.html
- 中国政府网《机动车登记规定》：转让登记涉及交验机动车、提交身份证明/所有权转让凭证/机动车登记证书/行驶证、登记证书签注、号牌和行驶证重新核发等。
  https://www.gov.cn/gongbao/content/2022/content_5682413.htm
- 国家税务总局关于二手车销售发票的说明：二手车经销纳税人销售二手车需开具二手车销售统一发票。
  https://www.chinatax.gov.cn/chinatax/n810351/n810906/c5149727/content.html

## 已运行测试

全部通过：

- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\seed_jiangsu_chejin_used_car_demo.py --verify-only`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_jiangsu_chejin_used_car_checks.py`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_jiangsu_chejin_used_car_checks.py --live-wechat --group-name "偷数据测试"`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_knowledge_runtime_checks.py`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_layer_checks.py`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_multi_tenant_auth_sync_checks.py`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_vps_admin_control_plane_checks.py`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter all`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_smart_recorder_checks.py`
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_local_auth_shared_console_checks.py`

实盘微信结果：

- 微信账号在线，识别用户：`Meta_xc`
- 已向 `偷数据测试` 群发送二手车商品、政策、噪音边界样本。
- 已向 `文件传输助手` 发送二手车线索咨询样本。
- 记录员成功捕获并写入原始消息库。
- RAG 搜索命中本批次内容。
- 自动客服对文件传输助手样本生成回复并走高风险转人工边界。
- 重复知识被去重，没有产生重复候选堆积。

LLM状态：

- 当前默认模型：`deepseek-v4-pro`
- API Key 已配置。
- 二手车账号中已有 12 个原始消息批次记录为 `llm_assist_policy.requested = true`，说明“原始消息到候选知识”的 LLM 辅助链路已真实触发过。

## 可演示重点

建议演示路径：

1. 使用二手车 customer 账号登录客户端。
2. 先看商品库：库存车辆已经覆盖多价位、多能源、多车型和已售归档。
3. 再看正式知识库：政策规则和聊天话术已拆分，专属商品知识已挂到具体商品。
4. 打开 AI 经验池：可以看到原始消息和资料经 RAG 形成的经验。
5. 打开待确认知识：可以看到从资料/聊天/RAG 提炼出的候选知识，适合演示人工确认晋升。
6. 打开 AI 智能记录员：可以看到 `偷数据测试`、`文件传输助手` 等真实/模拟会话记录。
7. 在微信里继续发送二手车样本，可观察记录员捕获、RAG学习、候选知识变化。

## 残余说明

本轮没有发现需要停机修复的严重问题。实盘烟测通过后，系统仍保留“高风险内容转人工”的边界：金融包过、事故赔付、订金可退、异地迁入、三电权益、抵押查封等内容不会由 AI 自动承诺。
