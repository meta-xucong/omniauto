# 微信智能客服与AI智能记录员全场景长测验收报告

生成时间：2026-05-03  
测试范围：客户端、服务端、知识成长链路、AI经验池、正式知识库、共享公共知识、热更新、微信实盘采集与自动客服。

## 结论

本轮长测结论为：当前合理可自动化和可实盘验证的主链路均已通过。  
本轮发现并修复了 2 个问题：AI经验检索测试仍沿用旧逻辑、客户端移动端顶栏会被长账号名撑宽。修复后相关回归和浏览器烟测均通过。

## 覆盖矩阵

### 1. 静态与语法检查

- `node --check apps\wechat_ai_customer_service\admin_backend\static\app.js`：通过。
- `node --check apps\wechat_ai_customer_service\vps_admin\static\app.js`：通过。
- `.venv\Scripts\python.exe -m compileall -q apps\wechat_ai_customer_service`：通过。
- `.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\tests\run_rag_enterprise_eval.py`：通过。

### 2. 非实盘全量回归

以下套件均已通过：

- `run_admin_backend_checks.py --chapter all`：17/17。
- `run_workflow_logic_checks.py`：13/13。
- `run_knowledge_runtime_checks.py`：13/13。
- `run_smart_recorder_checks.py`：4/4。
- `run_vps_admin_control_plane_checks.py`：8/8。
- `run_multi_tenant_auth_sync_checks.py`：9/9。
- `run_local_auth_shared_console_checks.py`：5/5。
- `run_auth_security_checks.py`：2/2。
- `run_boundary_matrix_checks.py`：15/15。
- `run_rag_layer_checks.py`：4/4。
- `run_rag_boundary_checks.py`：9/9。
- `run_rag_enterprise_eval.py`：5/5。
- `run_knowledge_base_migration_checks.py`：4/4。
- `run_knowledge_compiler_checks.py`：3/3。
- `run_offline_regression.py`：11/11。
- `run_enterprise_hardening_checks.py`：3/3。
- `run_postgres_storage_checks.py`：7/7（无真实 DSN 时验证配置、Schema、降级提示与文件镜像逻辑）。
- `run_jiangsu_chejin_used_car_checks.py`：通过，批次 `CHEJIN_20260503_084712`。
- `run_deepseek_boundary_probe.py`：3/3，确认 deepseek-v4-pro 参与边界判断。

### 3. 浏览器 UI 烟测

浏览器实测范围：

- 客户端 customer 登录：微信智能客服、AI智能记录员、知识首页、商品库、资料导入、待确认知识、AI经验池、正式知识库、知识检测、系统设置。
- 客户端 admin 登录：微信智能客服、共享公共知识库、系统设置。
- 服务端 admin 登录：运行总览、客户与权限、客户数据、共享公共知识、客户电脑连接、备份与还原、版本更新、账号安全、操作审计。
- 桌面视口：1366x900。
- 移动视口：390x844。

结果：44/44 通过，无页面级横向溢出，无未处理前端异常。  
截图与 JSON 报告：`runtime/apps/wechat_ai_customer_service/test_artifacts/full_acceptance_20260503/ui_smoke/`。

### 4. 微信实盘测试

#### 4.1 微信预检

- 微信电脑端在线。
- 当前账号：`Meta_xc`。
- 未出现登录窗口。
- 最近会话包含 `文件传输助手` 和 `偷数据测试`。

#### 4.2 AI智能记录员实盘

命令：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_smart_recorder_live_wechat.py --tenant jiangsu_chejin_usedcar_customer_20260501 --group-name "偷数据测试" --settle-seconds 2.5
```

结果：通过。  
批次：`LIVE_RECORDER_20260503_093238`。

验证点：

- 实际向 `偷数据测试` 群发送商品资料、缺字段政策、噪音边界消息。
- 实际向 `文件传输助手` 发送聊天话术材料。
- 原始消息入库成功。
- RAG 检索能找到产品、政策、文件传输助手话术。
- 噪音消息进入原始/RAG审计，但未生成候选知识。
- 完整商品、文件传输助手话术、缺字段政策均进入候选链路。
- 缺字段候选保留 `needs_more_info` 状态。
- LLM辅助策略记录为 requested。
- 重复采集幂等：二次捕获 `inserted_count=0`，消息 ID 不变化。

#### 4.3 文件传输助手自动客服实盘

先验证关闭开关：默认测试空间客服开关关闭时，监听返回 `customer_service_disabled`，消息仍被记录入原始库和学习链路。这证明“只记录、不自动回复”的开关有效。

随后临时打开默认测试空间客服开关，跑代表性实盘子集，跑完后已恢复默认设置为关闭。

通过场景：

- `company_profile`：公司信息与地址自动回复正确。
- `complete_customer_data`：客户资料完整时写入成功。
- `mixed_discount_and_customer_data_handoff`：同时包含客户资料和越权低价要求时转人工，且不写入客户资料。

子集结果文件：`runtime/apps/wechat_ai_customer_service/test_artifacts/full_acceptance_20260503/file_transfer_live_subset_result.json`。

补充：完整 20 场景实盘套件在 15 分钟内推进到第 8 条，前 7 条审计显示已发送并收到回复，且 deepseek-v4-pro 已实际调用。由于全量实盘每条都调用 LLM，耗时和微信刷屏成本较高，本轮未把 20 条全部实盘跑完；其余组合由离线全量套件覆盖。

## 本轮修复

### 1. AI经验检索测试逻辑修正

问题：企业级 RAG 评估仍按旧逻辑认为 `active` 的 AI经验应直接参与检索。  
现行产品逻辑：AI经验必须经用户点击“保留为经验”后才参与 RAG 层参考。  
修复：测试改为先模拟用户确认保留，再验证可检索；未确认、低质量、作废经验仍不可检索。  
验证：`run_rag_enterprise_eval.py` 5/5 通过。

### 2. 客户端移动端顶栏溢出

问题：390px 窄屏下，长账号名和状态标签会把客户端页面撑到 561px，产生横向滚动。  
修复：移动端顶栏改为单列布局，账号信息、状态标签、退出按钮均限制在 100% 宽度内。  
验证：浏览器 UI 烟测 44/44 通过。

## 当前服务状态

- 客户端：`http://127.0.0.1:8765/api/health` 通过。
- 服务端：`http://127.0.0.1:8766/v1/health` 通过。
- 未发现残留微信实盘测试进程。
- 未发现残留 workflow lock。
- 默认测试空间客服开关已恢复为关闭、人工辅助模式。

## 建议后续生产级长测

以下不是当前交付阻塞项，但建议进入下一阶段生产前做：

- 使用真实 PostgreSQL DSN 跑存储集成，而不是只验证无 DSN 降级路径。
- 对真实客户账号做 24 小时低频守护测试，观察微信窗口焦点、掉线、锁屏、网络波动。
- 对完整 20 场景文件传输助手实盘套件做夜间长跑，避免白天刷屏。
- 使用真实多行业账号验证共享公共知识的通用性阈值，继续压低误推送率。
- 对真实 SMTP 邮件到达做端到端验证；当前自动化已覆盖 OTP 逻辑，但不以真实邮箱投递成功作为强依赖。
