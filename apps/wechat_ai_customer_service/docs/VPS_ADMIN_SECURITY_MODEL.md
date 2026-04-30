# VPS Admin 安全模型

## 1. 唯一通用 admin

admin 是平台级 root 身份：

- 唯一。
- 通用。
- 隐藏。
- 不入 customer/guest 用户表。
- 不通过 API 创建。
- 不允许 customer 或 guest 感知。
- 可登录 VPS。
- 可登录任意 local。

生产环境 admin 凭据必须由 VPS 环境变量、密钥管理服务或加密配置提供：

```text
WECHAT_VPS_ADMIN_USERNAME
WECHAT_VPS_ADMIN_PASSWORD
WECHAT_VPS_ADMIN_USER_ID
```

当前代码为了本地开发提供默认密码 `1234.abcd`。上线前必须覆盖。

## 2. 身份边界

### 2.1 admin

admin 是平台操作者身份，不属于任何 customer tenant。它的 `tenant_ids` 固定为 `["*"]`。

禁止事项：

- 禁止把 admin 写入用户表。
- 禁止在 customer-facing 页面展示 admin。
- 禁止通过 customer API 修改 admin。
- 禁止把 admin 作为 tenant 成员同步给客户。

### 2.2 customer

customer 是租户所有者或运营者身份，必须绑定明确的 tenant。

允许：

- 修改自己 tenant 的私有知识。
- 上传共享知识候选。
- 配置自己 tenant 是否自动云备份。

禁止：

- 修改共享全局知识。
- 管理其他 tenant。
- 发布版本。
- 下发 local 节点全局命令。

### 2.3 guest

guest 是只读授权身份，必须绑定明确 tenant。

允许：

- 读取授权 tenant 的允许范围内容。

禁止：

- 写入任何知识。
- 提交备份或恢复。
- 修改同步设置。
- 管理用户。

## 3. 会话与登录

VPS 登录返回 `AuthSession`：

```json
{
  "session_id": "...",
  "token": "...",
  "user": {
    "user_id": "platform-admin",
    "role": "admin",
    "tenant_ids": ["*"]
  },
  "active_tenant_id": "default",
  "source": "vps"
}
```

local 端开启 `WECHAT_VPS_BASE_URL` 后，登录会先请求 VPS。若 VPS 通过 admin 登录，local 端应按隐藏 admin 上下文授予最高权限。

建议生产策略：

- admin 登录强制 HTTPS。
- admin 可加 TOTP 或硬件密钥。
- session token 最长 12 小时。
- 高危动作二次确认。
- 备份恢复、发布更新必须写审计。

## 4. local 节点安全

local 节点注册需要 enrollment token：

```text
WECHAT_VPS_NODE_ENROLLMENT_TOKEN
```

注册成功后 VPS 返回 `node_token`。local 后续心跳、命令轮询、结果回传必须带：

```http
X-Node-Token: <node-token>
```

建议：

- node token 可轮换。
- node token 不写入日志。
- VPS 限制每个 node 的 tenant 访问范围。
- 命令只发给匹配 tenant 和 node 的 local。

## 5. 命令安全

命令状态机：

```text
queued -> sent -> succeeded
queued -> sent -> failed
```

高危命令：

- `backup_all`
- `restore_backup`
- `push_update`

这些命令必须满足：

- actor 是 admin。
- target node 明确。
- target tenant 明确，或 scope 为 all 且有额外审计。
- restore 默认 dry-run。
- push_update 必须包含签名更新包信息。

## 6. 共享知识发布安全

共享知识发布必须经过 proposal -> review -> patch 流程。

不建议 customer 直接写共享库，因为共享知识会影响所有客户。正确流程是：

1. customer/local 提交 proposal。
2. VPS 保存来源、tenant、内容、差异。
3. AI 可以辅助整理，但只能产出候选。
4. admin 人审。
5. 接受后生成 patch。
6. local 拉取 patch 并执行本地 preview。
7. preview 通过后 apply。

patch 限制：

- 仅允许白名单操作。
- 当前只允许 `upsert_json`。
- 只允许写 JSON。
- 禁止路径逃逸。
- 生产环境必须签名。

## 7. 备份与恢复安全

备份建议：

- tenant 私有备份默认加密。
- shared 全局备份独立保留。
- 备份包包含 manifest、digest、创建时间、scope、tenant。
- VPS 只保存备份索引和对象存储地址，不在控制面 JSON 中保存大文件。

恢复建议：

- 默认 dry-run。
- 恢复前自动创建保护性本地快照。
- 恢复包必须校验 digest。
- 恢复后运行知识库完整性检查。
- 支持一键回滚到恢复前快照。

## 8. 审计与告警

必须审计：

- admin login
- tenant create/update/disable
- user create/update/delete
- node register/heartbeat anomaly
- command create/result
- backup request
- restore request
- shared proposal review
- release create

建议告警：

- admin 异地登录
- 短时间多次登录失败
- 大批量备份
- restore 非 dry-run
- push_update stable channel
- node 长时间离线

## 9. 上线前阻断项

上线前必须完成：

- 覆盖默认 admin 密码。
- 配置 HTTPS。
- 配置 enrollment token。
- 配置备份加密。
- 配置审计保留策略。
- 对真实 restore 保持关闭，直到 dry-run、快照、回滚测试通过。
- 对 push_update 使用签名包，禁止执行未签名 artifact。
