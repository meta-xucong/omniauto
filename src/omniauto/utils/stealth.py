"""反检测配置与行为模拟参数."""

STEALTH_CONFIG = {
    # 浏览器启动参数
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-web-security",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-infobars",
        "--window-size=1920,1080",
        "--start-maximized",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    ],
    # 脚本注入（覆盖检测点）
    "scripts": [
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en'] });
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        """
    ],
    # 行为模拟参数
    "behavior": {
        "mouse_curve": "bezier",
        "click_delay": (0.1, 0.3),
        "typing_interval": (0.05, 0.15),
    },
}
