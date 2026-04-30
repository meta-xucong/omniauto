# 账号安全与商用准备清单

## 1. 已落地能力

### 1.1 密码修改

服务端 VPS 控制台和本地 Local 客户端都提供“账号安全”页面：

- VPS：`账号安全 -> 修改管理员密码`
- Local：`账号安全 -> 修改当前登录账号密码`

接口：

```text
POST /v1/auth/change-password/start
POST /v1/auth/change-password/verify
POST /api/auth/change-password/start
POST /api/auth/change-password/verify
```

修改密码需要当前有效 session、当前密码和邮箱验证码。新密码要求至少 8 位，并同时包含字母和数字。修改后会撤销同账号的其他 session，当前界面会提示重新登录。旧的直接改密接口仅保留为开发兼容入口；启用邮箱验证码后会拒绝直接改密。

admin 账号仍是唯一通用管理员。初始密码来自环境变量或默认开发密码；首次通过控制台修改后，VPS 会在服务端状态中保存覆盖后的哈希密码。商用时必须把状态文件纳入加密备份，否则丢失 VPS 状态后会回退到环境变量密码。

### 1.2 邮箱验证码登录

新增两段式登录：

```text
POST /v1/auth/login/start
POST /v1/auth/login/bind-email/start
POST /v1/auth/login/verify
POST /api/auth/login/start
POST /api/auth/login/bind-email/start
POST /api/auth/login/verify
```

开启 `WECHAT_EMAIL_OTP_REQUIRED=1` 后，旧的直登接口不会再签发 session，必须先用账号密码发起登录，再输入邮箱验证码换取 session。

如果 customer/guest 尚未绑定邮箱，登录时会在账号密码通过后要求填写绑定邮箱，再发送验证码；客户端不配置 SMTP，只负责填写账号绑定邮箱。登录验证码通过时可勾选“登录后 30 天内信任此设备”，同一账号同一浏览器设备在有效期内可跳过邮箱验证码。

VPS customer/guest 账号支持 `email` 字段。Local 默认账号也支持邮箱环境变量：

```text
WECHAT_VPS_ADMIN_EMAIL=admin@example.com
WECHAT_LOCAL_ADMIN_EMAIL=admin@example.com
WECHAT_LOCAL_TEST01_EMAIL=test01@example.com
WECHAT_LOCAL_CUSTOMER_EMAIL=customer@example.com
WECHAT_LOCAL_GUEST_EMAIL=guest@example.com
```

admin 必须有邮箱，默认可通过 `WECHAT_VPS_ADMIN_EMAIL` 或 VPS 控制台的账号安全流程维护。

### 1.3 首次登录初始化

新增独立初始化页，账号密码校验通过后，如果账号尚未完成初始化，会先进入初始化页，不能直接进入控制台。

初始化要求：

- customer/guest：必须修改初始密码、绑定邮箱，并通过邮箱验证码确认。
- VPS admin：必须修改初始密码、绑定管理员邮箱，并设置 SMTP 与邮箱验证码参数；完成后用新密码重新登录。
- Local admin：必须修改初始密码、绑定管理员邮箱，并通过邮箱验证码确认；SMTP 发信配置仍由 VPS 管理控制台统一维护，Local 不保存客户可见的 SMTP 密码。

接口：

```text
POST /v1/auth/initialize/start
POST /v1/auth/initialize/verify
POST /api/auth/initialize/start
POST /api/auth/initialize/verify
```

初始化完成后会写入 `initialized_at`、新密码哈希和绑定邮箱。后续仍可在“账号安全”页面改密码、换邮箱或调整 SMTP 配置；初始化页只负责首次使用拦截，不取代控制台里的长期维护入口。

## 2. 邮件发送配置

生产环境建议在 VPS 控制台 `账号安全 -> SMTP 与邮箱验证码` 配置真实 SMTP。也可以用环境变量作为初始默认值：

```text
WECHAT_EMAIL_OTP_REQUIRED=1
WECHAT_EMAIL_SMTP_HOST=smtp.example.com
WECHAT_EMAIL_SMTP_PORT=587
WECHAT_EMAIL_SMTP_USERNAME=notice@example.com
WECHAT_EMAIL_SMTP_PASSWORD=<smtp-password>
WECHAT_EMAIL_SMTP_USE_TLS=1
WECHAT_EMAIL_FROM=notice@example.com
WECHAT_EMAIL_OTP_TTL_MINUTES=10
WECHAT_EMAIL_OTP_MAX_ATTEMPTS=5
WECHAT_TRUSTED_DEVICE_DAYS=30
```

本地开发或无 SMTP 时，验证码会写入 outbox 文件：

```text
WECHAT_EMAIL_OUTBOX_PATH=runtime/apps/wechat_ai_customer_service/auth/email_outbox.jsonl
```

测试环境可临时打开：

```text
WECHAT_EMAIL_OTP_DEBUG=1
```

打开后接口响应会返回 `debug_code`，方便自动化测试。商用环境必须关闭。

## 3. 商用还应补齐的模块

### P0 上线前必须补齐

- HTTPS：VPS 控制台、Local 到 VPS 通信必须走 HTTPS。
- SMTP 正式通道：配置独立发信域名、退信监控和发送限速。
- 密钥与配置管理：admin 初始密码、SMTP 密码、node enrollment token 不应写在代码或普通文档中。
- 登录风控：同账号/同 IP 多次失败锁定，异常地区或设备登录提醒。
- 审计检索：支持按账号、动作、时间筛选导出审计日志。
- 备份加密：客户数据包、共享知识包、VPS 状态文件都应加密备份。
- 恢复演练：每次版本发版前至少做一次 dry-run restore 和可读数据核验。

### P1 第一批付费客户前建议补齐

- 会话管理：查看当前账号登录设备，支持踢下线和全部退出。
- 管理员高危操作二次确认：备份全部数据、还原、推送更新、删除客户数据时二次验证码。
- 安装器：自动安装 Python/Node/运行时依赖、注册启动脚本、写入 VPS 地址。
- 更新回滚：客户端更新失败后自动回滚到上一版本。
- 客户授权有效期：guest 授权可设置过期时间。
- 数据保留策略：备份保留天数、最大保留份数、到期自动清理。

### P2 规模化运营时补齐

- 多租户计费与服务到期控制。
- 工单与告警中心。
- 操作员分级权限，而不是所有内部人员共用唯一 admin。
- 数据导出水印与下载审批。
- 数据库迁移到 PostgreSQL，并保留 JSON 镜像作为调试和灾备层。
- 灰度发布、发布签名、客户端更新包完整性校验。

## 4. 本地验证建议

本地模拟足够验证账号安全逻辑：

1. 启用 `WECHAT_EMAIL_OTP_REQUIRED=1` 和 `WECHAT_EMAIL_OTP_DEBUG=1`。
2. 启动 VPS 与 Local。
3. 分别登录 admin、test01。
4. 确认旧直登接口无法绕过验证码。
5. 修改密码后，用旧密码登录失败，用新密码可重新发送验证码。
6. 检查 outbox 是否记录了验证码邮件。

真实 VPS 测试用于验证网络、HTTPS、SMTP、域名、系统服务、跨机器备份和更新下载，不必阻塞当前功能开发。
