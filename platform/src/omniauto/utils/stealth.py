"""反检测配置与行为模拟参数."""

STEALTH_CONFIG = {
    # 浏览器启动参数
    # 注意: --window-size 在运行时由 StealthBrowser.start() 动态注入, 以确保与 viewport 严格一致
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-background-timer-throttling",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
    ],
    # 脚本注入（覆盖检测点）
    "scripts": [
        # 0. 隐藏 Chrome automation 信息条（兼容多种版本）
        """
        (function() {
            const hideBar = function() {
                const style = document.createElement('style');
                style.textContent = `
                    .topbar.testtopbar,
                    body > div[style*="--enable-automation"],
                    body > div[style*="margin-top: 50px"][style*="height: 50px"] {
                        display: none !important;
                    }
                    body { margin-top: 0 !important; padding-top: 0 !important; }
                `;
                document.head.appendChild(style);
            };
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', hideBar);
            } else {
                hideBar();
            }
        })();
        """,
        # 1. navigator.webdriver
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
        delete navigator.__proto__.webdriver;
        """,
        # 2. window.chrome 完整性
        """
        window.chrome = window.chrome || {};
        window.chrome.runtime = window.chrome.runtime || {
            OnInstalledReason: {CHROME_UPDATE: "chrome_update", SHARED_MODULE_UPDATE: "shared_module_update", INSTALL: "install", UPDATE: "update"},
            OnRestartRequiredReason: {APP_UPDATE: "app_update", OS_UPDATE: "os_update", PERIODIC: "periodic"},
            PlatformArch: {ARM: "arm", ARM64: "arm64", MIPS: "mips", MIPS64: "mips64", MIPS64EL: "mips64el", MIPSEL: "mipsel", X86_32: "x86-32", X86_64: "x86-64"},
            PlatformNaclArch: {ARM: "arm", MIPS64: "mips64", MIPS64EL: "mips64el", MIPSEL: "mipsel", Mips32: "mips32", Mips64: "mips64", Mips64el: "mips64el", Mipsel: "mipsel", X86_32: "x86-32", X86_64: "x86-64"},
            PlatformOs: {ANDROID: "android", CROS: "cros", LINUX: "linux", MAC: "mac", OPENBSD: "openbsd", WIN: "win"},
            RequestUpdateCheckStatus: {NO_UPDATE: "no_update", THROTTLED: "throttled", UPDATE_AVAILABLE: "update_available"}
        };
        if (!window.chrome.csi) {
            window.chrome.csi = function() {};
        }
        if (!window.chrome.loadTimes) {
            window.chrome.loadTimes = function() {
                return {
                    commitLoadTime: performance.timing ? performance.timing.connectEnd / 1000 : 0,
                    connectionInfo: 'h2',
                    finishDocumentLoadTime: 0,
                    finishLoadTime: 0,
                    firstPaintAfterLoadTime: 0,
                    firstPaintTime: 0,
                    navigationType: 'Other',
                    npnNegotiatedProtocol: 'h2',
                    requestTime: performance.timing ? performance.timing.requestStart / 1000 : 0,
                    startLoadTime: performance.timing ? performance.timing.navigationStart / 1000 : 0,
                    wasAlternateProtocolAvailable: false,
                    wasFetchedViaSpdy: true,
                    wasNpnNegotiated: true
                };
            };
        }
        if (!window.chrome.app) {
            window.chrome.app = {
                isInstalled: false,
                InstallState: {DISABLED: "disabled", INSTALLED: "installed", NOT_INSTALLED: "not_installed"},
                RunningState: {CANNOT_RUN: "cannot_run", READY_TO_RUN: "ready_to_run", RUNNING: "running"},
                getDetails: function() { return null; },
                getIsInstalled: function() { return false; },
                installState: function() { return "not_installed"; },
                runningState: function() { return "running"; }
            };
        }
        """,
        # 3. navigator.plugins / mimeTypes 真实模拟
        """
        (function() {
            const pluginData = [
                {name: "Chrome PDF Plugin", filename: "internal-pdf-viewer", description: "Portable Document Format", version: "undefined", length: 1},
                {name: "Chrome PDF Viewer", filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai", description: "Portable Document Format", version: "undefined", length: 1},
                {name: "Native Client", filename: "internal-nacl-plugin", description: "", version: "undefined", length: 2}
            ];
            function createFakePlugins() {
                const plugins = [];
                pluginData.forEach((p, index) => {
                    const plugin = {
                        name: p.name,
                        filename: p.filename,
                        description: p.description,
                        version: p.version,
                        length: p.length,
                        item: function(idx) { return this[idx]; },
                        namedItem: function(name) { return this[name]; }
                    };
                    for (let i = 0; i < p.length; i++) {
                        plugin[i] = {
                            description: p.description,
                            filename: p.filename,
                            length: 0,
                            name: p.name,
                            item: function() { return null; },
                            namedItem: function() { return null; }
                        };
                    }
                    plugins.push(plugin);
                });
                plugins.length = pluginData.length;
                plugins.item = function(idx) { return this[idx]; };
                plugins.namedItem = function(name) {
                    return this.find(p => p.name === name) || null;
                };
                plugins.refresh = function() {};
                return plugins;
            }
            const fakePlugins = createFakePlugins();
            Object.defineProperty(navigator, 'plugins', {
                get: () => fakePlugins,
                configurable: true
            });
            const mimeTypes = {
                length: 2,
                item: function(idx) { return this[idx] || null; },
                namedItem: function(name) { return this[name] || null; },
                0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format", enabledPlugin: fakePlugins[0]},
                1: {type: "application/pdf", suffixes: "pdf", description: "Portable Document Format", enabledPlugin: fakePlugins[1]}
            };
            Object.defineProperty(navigator, 'mimeTypes', {
                get: () => mimeTypes,
                configurable: true
            });
        })();
        """,
        # 4. Permissions.query 覆盖
        """
        const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
        if (originalQuery) {
            window.navigator.permissions.query = (parameters) => {
                if (parameters && parameters.name === 'notifications') {
                    return Promise.resolve({ state: window.Notification ? window.Notification.permission : 'default', onchange: null });
                }
                if (parameters && parameters.name === 'midi') {
                    return Promise.resolve({ state: 'prompt', onchange: null });
                }
                if (parameters && parameters.name === 'clipboard-read') {
                    return Promise.resolve({ state: 'prompt', onchange: null });
                }
                return originalQuery(parameters);
            };
        }
        """,
        # 5. 语言与硬件指纹
        """
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en'],
            configurable: true
        });
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8,
            configurable: true
        });
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8,
            configurable: true
        });
        Object.defineProperty(navigator, 'maxTouchPoints', {
            get: () => 0,
            configurable: true
        });
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32',
            configurable: true
        });
        """,
        # screen 尺寸一致性
        """
        (function() {
            const width = window.innerWidth || 1920;
            const height = window.innerHeight || 1080;
            try {
                Object.defineProperty(screen, 'availWidth', { get: () => width, configurable: true });
                Object.defineProperty(screen, 'availHeight', { get: () => height - 40, configurable: true });
                Object.defineProperty(screen, 'width', { get: () => width, configurable: true });
                Object.defineProperty(screen, 'height', { get: () => height, configurable: true });
            } catch (e) {}
        })();
        """,
        # 6. 清理 WebDriver / CDC 痕迹
        """
        (function() {
            const keysToDelete = Object.keys(window).filter(k => k.startsWith('cdc_') || k.startsWith('__webdriver'));
            keysToDelete.forEach(k => {
                try { delete window[k]; } catch (e) {}
            });
            if (window.document && window.document.documentElement) {
                const attrs = window.document.documentElement.getAttributeNames();
                attrs.forEach(a => {
                    if (a.toLowerCase().includes('webdriver') || a.toLowerCase().includes('driver-evaluate') || a.toLowerCase().includes('selenium')) {
                        window.document.documentElement.removeAttribute(a);
                    }
                });
            }
        })();
        """,
        # 7. Canvas / WebGL 指纹噪声（改变指纹哈希，不影响视觉）
        """
        (function() {
            const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
            CanvasRenderingContext2D.prototype.getImageData = function(...args) {
                const imageData = originalGetImageData.apply(this, args);
                if (imageData && imageData.data && imageData.data.length > 0) {
                    imageData.data[0] = (imageData.data[0] + 1) % 256;
                }
                return imageData;
            };
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(...args) {
                if (this.width > 0 && this.height > 0) {
                    const ctx = this.getContext('2d');
                    if (ctx) {
                        const imageData = ctx.getImageData(0, 0, this.width, this.height);
                        if (imageData && imageData.data && imageData.data.length > 0) {
                            imageData.data[0] = (imageData.data[0] + 1) % 256;
                            ctx.putImageData(imageData, 0, 0);
                            const result = originalToDataURL.apply(this, args);
                            imageData.data[0] = (imageData.data[0] - 1 + 256) % 256;
                            ctx.putImageData(imageData, 0, 0);
                            return result;
                        }
                    }
                }
                return originalToDataURL.apply(this, args);
            };
        })();
        """,
        # WebGL 厂商/渲染器指纹覆盖
        """
        (function() {
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
                    return 'Intel Inc.';
                }
                if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
                    return 'Intel Iris Xe Graphics';
                }
                return getParameter(parameter);
            };
            if (window.WebGL2RenderingContext) {
                const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
                WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel Iris Xe Graphics';
                    return getParameter2(parameter);
                };
            }
        })();
        """,
        # 8. RTCPeerConnection 保护（避免某些覆盖导致的异常）
        """
        if (window.RTCPeerConnection) {
            const OriginalRTCPeerConnection = window.RTCPeerConnection;
            window.RTCPeerConnection = function(...args) {
                return new OriginalRTCPeerConnection(...args);
            };
            window.RTCPeerConnection.prototype = OriginalRTCPeerConnection.prototype;
        }
        """,
        # 9. Notification permission 自然化
        """
        if (window.Notification && !window.Notification.permission) {
            Object.defineProperty(window.Notification, 'permission', {
                get: () => 'default',
                configurable: true
            });
        }
        """,
    ],
    # 行为模拟参数
    "behavior": {
        "mouse_curve": "bezier",
        "click_delay": (0.1, 0.3),
        "typing_interval": (0.05, 0.15),
    },
}
