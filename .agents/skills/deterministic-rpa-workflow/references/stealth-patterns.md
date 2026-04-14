# 反检测与冷却策略参考

## StealthBrowser 启动参数

已内置在项目 `src/omniauto/utils/stealth.py` 中，关键项：
- `channel='chrome'`：使用系统真实 Chrome，指纹更自然
- `locale='zh-CN'`, `timezone_id='Asia/Shanghai'`
- 上海地理位置 `{31.2304, 121.4737}`
- 注入脚本覆盖 `navigator.webdriver`、`window.chrome.csi`、`plugins`、`RTCPeerConnection`

## 冷却 API

```python
# 通用操作后阅读/思考时间
await browser.cooldown(min_sec=1.5, max_sec=4.0)

# 翻页/连续请求限速
await browser.throttle_request(min_sec=3.0, max_sec=8.0)
```

## Workflow 步骤间延迟

```python
workflow = Workflow(
    steps=[...],
    inter_step_delay=(2.0, 4.0),  # 步骤完成后随机 sleep 2~4 秒
)
```

## 推荐参数矩阵

| 场景 | inter_step_delay | throttle_request | cooldown |
|------|------------------|------------------|----------|
| 单页抓取 | (1.5, 3.5) | 不使用 | 不使用 |
| 多页列表（≤5页） | (2.0, 4.0) | 4~8s | 不使用 |
| 多页+详情页抽样 | (2.0, 4.0) | 4~8s | 5~10s |
| 高频连续（>10页） | (3.0, 5.0) | 6~12s | 8~15s |

## 异常兜底

- 触发登录页：StealthBrowser `auto_handle_login=True` 会自动检测并弹窗等待
- 触发 CAPTCHA：`AuthManager.wait_for_intervention()` 轮询，超时 300 秒
- 详情页异常：用 `try/except` 包裹，记录 error 后继续下一项
