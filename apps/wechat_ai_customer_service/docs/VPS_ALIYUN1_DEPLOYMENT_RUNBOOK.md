# 阿里云1 OmniAuto VPS 服务端部署记录

更新时间：2026-05-01

## 当前结论

阿里云1已经部署微信自动客服 VPS admin 服务端，并通过本机与公网 IP 健康检查。

- 公网访问：`http://139.196.101.174/`
- 健康检查：`http://139.196.101.174/v1/health`
- systemd 服务：`omniauto-vps-admin.service`
- 应用目录：`/opt/omniauto`
- 运行数据：`/opt/omniauto-runtime/vps_admin/control_plane.json`
- 服务日志：`/opt/omniauto-runtime/logs/vps-admin.log`
- 错误日志：`/opt/omniauto-runtime/logs/vps-admin.err.log`
- Nginx 配置：`/www/server/panel/vhost/nginx/omniauto.conf`

注意：截至本次部署，`alcochrom.cn` 和 `www.alcochrom.cn` 的 DNS 解析仍指向 `101.133.234.199`，`alcochrom.vip` 和 `www.alcochrom.vip` 指向 `47.101.209.149`，不是阿里云1的 `139.196.101.174`。域名切换前请使用公网 IP 测试。

## 部署内容

远端保留系统自带 Nginx/宝塔面板、Python 3.10、Git、curl 等基础组件，只为 VPS admin 安装最小 Python 依赖：

- `fastapi`
- `uvicorn`
- `openpyxl`
- `python-multipart`
- `httpx`，仅用于远端运行回归测试

没有安装桌面自动化、Playwright、OpenCV、Windows UI 自动化等 Local 客户端才需要的组件。

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
curl -sS -H 'Host: alcochrom.cn' http://127.0.0.1/v1/health
curl -k -sS -H 'Host: alcochrom.cn' https://127.0.0.1/v1/health
```

## 关键备份

旧环境没有直接删除，均已移动或复制到 root 下备份目录：

- 旧 ERP 项目与 systemd：`/root/omniauto_predeploy_backup_20260501_034658`
- 可疑 preload 组件：`/root/omniauto_predeploy_security_manual`
- Nginx 旧配置备份：`/root/omniauto_nginx_backup_20260501_044103`

## 安全发现

部署时发现服务器存在 `/etc/ld.so.preload`，内容指向 `/usr/local/lib/sshdd.so`，该预加载库会拦截文件操作，导致创建 `log/logs` 路径和 Git 的 `.git/logs` 失败。处理方式：

- 备份并禁用 `/usr/local/lib/sshdd.so`
- 清除 `/etc/ld.so.preload` 的 immutable 标记后移动到备份目录
- 验证 `mkdir /tmp/xlogs_after_clear` 正常

这类 preload 机制不应出现在正式商用环境中。正式承载客户数据前，建议优先做一次完整安全巡检，或者使用干净的新镜像重新部署。

## 已通过验证

远端服务：

```text
curl http://127.0.0.1:8766/v1/health
{"ok":true,"app":"wechat_ai_customer_service_vps_admin","version":"0.1.0"}
```

Nginx 本机代理：

```text
curl -H 'Host: alcochrom.cn' http://127.0.0.1/v1/health
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
