# 阿里云1 OmniAuto VPS 服务端运维记录

更新时间：2026-05-01

## 当前状态

阿里云1现在只作为 OmniAuto 微信自动客服 VPS admin 服务端使用。

- 公网入口：`http://139.196.101.174/`
- 健康检查：`http://139.196.101.174/v1/health`
- systemd 服务：`omniauto-vps-admin.service`
- 应用目录：`/opt/omniauto`
- 运行数据：`/opt/omniauto-runtime/vps_admin/control_plane.json`
- 服务日志：`/opt/omniauto-runtime/logs/vps-admin.log`
- 错误日志：`/opt/omniauto-runtime/logs/vps-admin.err.log`
- Nginx 配置：`/www/server/panel/vhost/nginx/omniauto.conf`

未配置域名入口。Nginx 只保留公网 IP 与 default server 入口。

## 保留组件

服务器只保留当前运行所需组件：

- 系统自带 Nginx 与面板基础目录
- Python 3.10 与 `/opt/omniauto/.venv`
- Git、curl 等基础运维命令
- `/opt/omniauto`
- `/opt/omniauto-runtime`

VPS admin 最小 Python 依赖：

- `fastapi`
- `uvicorn`
- `openpyxl`
- `python-multipart`
- `httpx`，仅用于远端回归测试

未安装 Local 客户端侧的桌面自动化、Playwright、OpenCV、Windows UI 自动化等组件。

## 已清理内容

以下旧内容已从服务器删除：

- 旧业务项目与旧项目备份
- 旧 systemd 服务
- 旧 Nginx 站点配置与域名证书记录
- 旧开发工具草稿和缓存
- 旧可疑系统级组件及其备份
- 旧面板备份、旧站点目录、旧项目模板目录

当前 `/opt` 顶层应只保留：

```text
/opt/omniauto
/opt/omniauto-runtime
```

## 常用命令

查看服务：

```bash
systemctl status omniauto-vps-admin.service --no-pager --lines=80
```

重启服务：

```bash
systemctl restart omniauto-vps-admin.service
```

查看日志：

```bash
tail -120 /opt/omniauto-runtime/logs/vps-admin.err.log
tail -120 /opt/omniauto-runtime/logs/vps-admin.log
```

拉取最新代码并重启：

```bash
cd /opt/omniauto
git fetch origin master
git reset --hard origin/master
systemctl restart omniauto-vps-admin.service
curl -sS http://127.0.0.1:8766/v1/health
```

检查 Nginx：

```bash
/www/server/nginx/sbin/nginx -t -c /www/server/nginx/conf/nginx.conf
/www/server/nginx/sbin/nginx -s reload -c /www/server/nginx/conf/nginx.conf
curl -sS http://127.0.0.1/v1/health
```

## 当前 Nginx 入口

`/www/server/panel/vhost/nginx/omniauto.conf` 应保持为只代理到本机 OmniAuto：

```nginx
server {
    listen 80 default_server;
    server_name 139.196.101.174 _;

    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:8766;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 120s;
    }
}
```

## 已通过验证

远端服务：

```text
curl http://127.0.0.1:8766/v1/health
{"ok":true,"app":"wechat_ai_customer_service_vps_admin","version":"0.1.0"}
```

Nginx 本机代理：

```text
curl http://127.0.0.1/v1/health
{"ok":true,"app":"wechat_ai_customer_service_vps_admin","version":"0.1.0"}
```

公网 IP：

```text
curl http://139.196.101.174/v1/health
{"ok":true,"app":"wechat_ai_customer_service_vps_admin","version":"0.1.0"}
```

登录初始化接口：

```text
POST http://139.196.101.174/v1/auth/login/start
admin / 1234.abcd -> requires_initialization=true
```

远端回归测试：

```bash
/opt/omniauto/.venv/bin/python apps/wechat_ai_customer_service/tests/run_auth_security_checks.py
/opt/omniauto/.venv/bin/python apps/wechat_ai_customer_service/tests/run_vps_admin_control_plane_checks.py
```

两组测试均通过。
