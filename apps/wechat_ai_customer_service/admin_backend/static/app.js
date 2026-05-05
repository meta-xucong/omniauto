const state = {
  authToken: localStorage.getItem("localAuthToken") || "",
  activeView: "customer_service",
  overview: null,
  customerService: null,
  customerServiceRuntime: null,
  customerServiceRuntimeTimer: null,
  customerServiceRuntimeBusy: false,
  productCatalog: null,
  selectedProduct: null,
  productDetailMode: "view",
  productDetailScopedKnowledge: {},
  productScopedEditor: null,
  categories: [],
  activeCategoryId: "",
  categoryItems: [],
  selectedKnowledge: null,
  knowledgeMode: "view",
  generatorSession: null,
  generatorMessages: [],
  selectedCandidate: null,
  learningInProgress: false,
  uploadInProgress: false,
  activeIntakeTab: "uploads",
  recorderSummary: null,
  recorderConversations: [],
  recorderMessages: [],
  selectedRecorderConversation: null,
  activeReferenceTab: "experiences",
  productScopedEditContext: null,
  diagnosticHighlight: null,
  ragStatus: null,
  ragHits: [],
  ragExperiences: [],
  ragExperienceExpanded: loadStringSet("ragExperienceExpanded"),
  ragInterpretationLoadingIds: new Set(),
  ragActionLoadingIds: new Map(),
  candidateActionLoadingIds: new Map(),
  ragAnalytics: null,
  auth: null,
  tenants: [],
  activeTenantId: localStorage.getItem("localActiveTenantId") || "",
  syncStatus: null,
  startupSyncTimer: null,
  loginChallenge: null,
  initChallenge: null,
  passwordChallenge: null,
  emailChallenge: null,
  security: null,
  platformSafetyRules: null,
  platformUnderstandingRules: null,
};
const localDeviceId = getOrCreateDeviceId("localConsoleDeviceId");

const titles = {
  customer_service: "微信智能客服",
  knowledge_center: "知识成长中心",
  product_catalog: "商品库",
  overview: "总览",
  knowledge: "正式知识库",
  intake: "资料导入",
  recorder: "AI智能记录员",
  ai_reference: "RAG经验池",
  diagnostics: "知识检测",
  settings: "系统设置",
  versions: "备份还原",
  security: "账号安全",
};

const viewAliases = {
  overview: {view: "knowledge_center"},
  generator: {view: "intake", group: "intake", tab: "generator"},
  uploads: {view: "intake", group: "intake", tab: "uploads"},
  candidates: {view: "intake", group: "intake", tab: "candidates"},
  rag: {view: "ai_reference", group: "reference", tab: "sources"},
  rag_experiences: {view: "ai_reference", group: "reference", tab: "experiences"},
  versions: {view: "settings"},
  security: {view: "settings"},
};

const templateLabels = {
  default: "默认回复",
  quote: "报价回复",
  discount_policy: "议价回复",
  logistics: "物流回复",
  after_sales: "售后回复",
  notes: "内部备注",
};

const optionLabels = {
  policy_type: {
    company: "公司信息",
    invoice: "开票",
    payment: "付款",
    logistics: "物流",
    after_sales: "售后",
    discount: "优惠议价",
    sample: "样品",
    installation: "安装",
    contract: "合同",
    manual_required: "必须人工确认",
    other: "其他",
  },
  risk_level: {normal: "普通", warning: "需关注", high: "高风险"},
  record_type: {product: "商品", inventory: "库存", price: "价格", customer: "客户", order: "订单", other: "其他"},
  sync_status: {imported: "已导入", linked: "已关联", ignored: "已忽略", error: "异常"},
  applicability_scope: {global: "全部商品通用", product_category: "某类商品适用", specific_product: "指定商品适用"},
};

const fieldLabelOverrides = {
  price_tiers: "批量价格",
  reply_templates: "客服回复内容",
  risk_rules: "风险提醒",
  policy_type: "规则类别",
  min_quantity: "起订量",
  unit_price: "单价",
  allow_auto_reply: "允许自动回复",
  requires_handoff: "需要人工确认",
  handoff_reason: "人工确认原因",
  operator_alert: "提醒人工客服",
  fields: "字段内容",
  additional_details: "补充信息",
  applicability_scope: "适用范围",
  product_id: "关联商品 ID",
  product_category: "关联商品类目",
  alias_keywords: "别名关键词",
  specs: "规格参数",
  source_title: "来源标题",
  batch_token: "批次标识",
  risk_level: "风险等级",
  customer_message: "客户怎么问",
  service_reply: "AI怎么回",
  intent_tags: "客户意图",
  tone_tags: "表达特点",
  linked_categories: "关联栏目",
  linked_item_ids: "关联知识",
  usable_as_template: "是否可作为话术模板",
};

function selectView(view, options = {}) {
  const target = viewAliases[view] || {view};
  if (target.group === "intake") state.activeIntakeTab = target.tab;
  if (target.group === "reference") state.activeReferenceTab = target.tab;
  const activeView = target.view;
  state.activeView = activeView;
  if (activeView !== "knowledge" || !options.keepKnowledgeContext) state.productScopedEditContext = null;
  if (activeView !== "knowledge" || !options.keepDiagnosticHighlight) state.diagnosticHighlight = null;
  const requestedView = view || activeView;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.view === requestedView || (!viewAliases[requestedView] && item.dataset.view === activeView));
  });
  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.classList.toggle("is-visible", panel.dataset.panel === activeView);
  });
  document.getElementById("view-title").textContent = titles[activeView] || "总览";
  syncWorkflowTabs();
}

function syncWorkflowTabs() {
  document.querySelectorAll('[data-intake-tab]').forEach((section) => {
    section.classList.toggle("is-visible", section.dataset.intakeTab === state.activeIntakeTab);
  });
  document.querySelectorAll('[data-reference-tab]').forEach((section) => {
    section.classList.toggle("is-visible", section.dataset.referenceTab === state.activeReferenceTab);
  });
  document.querySelectorAll('.workflow-tab[data-group="intake"]').forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === state.activeIntakeTab);
  });
  document.querySelectorAll('.workflow-tab[data-group="reference"]').forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === state.activeReferenceTab);
  });
}

async function refreshHealth() {
  const pill = document.getElementById("health-pill");
  try {
    const payload = await apiGet("/api/health");
    pill.textContent = payload.ok ? "本地已连接" : "异常";
    pill.classList.toggle("is-ok", Boolean(payload.ok));
  } catch (error) {
    pill.textContent = "未连接";
    pill.classList.remove("is-ok");
  }
}

function apiHeaders(extra = {}) {
  const headers = {...extra};
  if (state.activeTenantId) headers["X-Tenant-ID"] = state.activeTenantId;
  if (state.authToken) headers.Authorization = `Bearer ${state.authToken}`;
  return headers;
}

async function apiGet(path) {
  const response = await fetch(path, {headers: apiHeaders()});
  if (!response.ok) throw new Error(await responseErrorMessage(response, path));
  return response.json();
}

async function apiJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: apiHeaders({"Content-Type": "application/json", ...(options.headers || {})}),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 405) throw new Error("当前本地服务可能还没重启到最新版本，请重启管理台服务后再试。");
    throw new Error(formatApiError(payload, `${path} ${response.status}`));
  }
  return payload;
}

async function responseErrorMessage(response, path) {
  if (response.status === 405) return "当前本地服务可能还没重启到最新版本，请重启管理台服务后再试。";
  const payload = await response.json().catch(() => ({}));
  return formatApiError(payload, `${path} ${response.status}`);
}

function formatApiError(payload, fallback) {
  const detail = payload?.detail;
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  return detail.message || JSON.stringify(detail);
}

function initializeLocalLogin() {
  document.body.classList.toggle("auth-locked", !state.authToken);
  const form = document.getElementById("local-login-form");
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    loginLocal(new FormData(form)).catch((error) => showLoginMessage(error.message));
  });
  document.getElementById("local-login-reset")?.addEventListener("click", resetLocalLoginChallenge);
  document.getElementById("local-init-form")?.addEventListener("submit", (event) => initializeLocalAccount(event).catch((error) => showInitMessage(error.message)));
  document.getElementById("local-init-back")?.addEventListener("click", resetLocalInitialization);
  if (state.authToken) {
    bootstrapAuthenticatedApp().catch((error) => {
      showLoginMessage(error.message || "登录状态已失效，请重新登录。");
      lockLocalConsole();
    });
  }
}

async function loginLocal(form) {
  if (state.loginChallenge) {
    if (state.loginChallenge.mode === "bind_email") {
      const response = await fetch("/api/auth/login/bind-email/start", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({challenge_id: state.loginChallenge.challenge_id, email: form.get("bind_email")}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.detail || "邮箱绑定验证发起失败，请检查邮箱。");
      }
      state.loginChallenge.mode = "verify";
      document.getElementById("local-login-bind-email-field")?.classList.add("is-hidden");
      document.getElementById("local-login-code-field")?.classList.remove("is-hidden");
      document.getElementById("local-login-trust-field")?.classList.remove("is-hidden");
      document.getElementById("local-login-submit").textContent = "验证并登录";
      showLoginMessage(
        payload.debug_code
          ? `验证码已生成：${payload.debug_code}。生产环境会发送到 ${payload.masked_email || "绑定邮箱"}。`
          : `验证码已发送到 ${payload.masked_email || "绑定邮箱"}，请输入后登录。`
      );
      return;
    }
    const response = await fetch("/api/auth/login/verify", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        challenge_id: state.loginChallenge.challenge_id,
        code: form.get("email_code"),
        trust_device: Boolean(form.get("trust_device")),
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.detail || "验证码错误或已过期，请重新获取。");
    }
    await completeLocalLogin(payload.session);
    return;
  }
  const response = await fetch("/api/auth/login/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      username: form.get("username"),
      password: form.get("password"),
      device_id: localDeviceId,
      device_name: browserDeviceName(),
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.detail || "登录失败，请检查账号和密码。");
  }
  if (!payload.requires_verification && payload.session) {
    await completeLocalLogin(payload.session);
    return;
  }
  if (payload.requires_initialization) {
    showLocalInitialization(payload);
    return;
  }
  state.loginChallenge = {challenge_id: payload.challenge_id, mode: payload.requires_email_binding ? "bind_email" : "verify"};
  if (payload.requires_email_binding) {
    document.getElementById("local-login-bind-email-field")?.classList.remove("is-hidden");
    document.getElementById("local-login-code-field")?.classList.add("is-hidden");
    document.getElementById("local-login-trust-field")?.classList.add("is-hidden");
    document.getElementById("local-login-submit").textContent = "发送邮箱验证码";
    showLoginMessage(payload.message || "这个账号还没有绑定邮箱，请填写邮箱后获取验证码。");
  } else {
    document.getElementById("local-login-bind-email-field")?.classList.add("is-hidden");
    document.getElementById("local-login-code-field")?.classList.remove("is-hidden");
    document.getElementById("local-login-trust-field")?.classList.remove("is-hidden");
    document.getElementById("local-login-submit").textContent = "验证并登录";
    showLoginMessage(
      payload.debug_code
        ? `验证码已生成：${payload.debug_code}。生产环境会发送到 ${payload.masked_email || "绑定邮箱"}。`
        : `验证码已发送到 ${payload.masked_email || "绑定邮箱"}，请输入后登录。`
    );
  }
  document.getElementById("local-login-reset")?.classList.remove("is-hidden");
}

function showLocalInitialization(payload) {
  state.initChallenge = {challenge_id: payload.challenge_id, role: payload.role || "customer", mode: "start"};
  document.body.classList.add("auth-locked", "auth-initializing");
  const isAdmin = state.initChallenge.role === "admin";
  const intro = document.getElementById("local-init-intro");
  if (intro) {
    intro.textContent = isAdmin
      ? "admin 首次进入客户端前必须修改密码并绑定邮箱。SMTP 发信配置在 VPS 管理控制台统一设置，Local 不保存客户可见的 SMTP 密码。"
      : "首次使用前必须修改密码并绑定邮箱。完成后需要用新密码重新登录。";
  }
  document.getElementById("local-init-code-field")?.classList.add("is-hidden");
  document.getElementById("local-init-submit").textContent = "发送初始化验证码";
  hideLoginMessage();
  showInitMessage(payload.message || "请完成首次初始化。");
}

async function initializeLocalAccount(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  if (!state.initChallenge) throw new Error("初始化会话已失效，请返回登录重新开始。");
  if (state.initChallenge.mode === "verify") {
    const response = await fetch("/api/auth/initialize/verify", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({challenge_id: state.initChallenge.challenge_id, code: form.get("email_code")}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) throw new Error(payload.detail || "验证码错误或已过期。");
    formElement.reset();
    resetLocalInitialization({silent: true});
    resetLocalLoginChallenge({silent: true});
    showLoginMessage("初始化已完成，请使用新密码重新登录。登录时仍需要邮箱验证码。");
    return;
  }
  if (form.get("new_password") !== form.get("confirm_password")) {
    throw new Error("两次输入的新密码不一致。");
  }
  const response = await fetch("/api/auth/initialize/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      challenge_id: state.initChallenge.challenge_id,
      email: form.get("email"),
      new_password: form.get("new_password"),
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) throw new Error(payload.detail || "初始化验证码发送失败。");
  state.initChallenge.mode = "verify";
  document.getElementById("local-init-code-field")?.classList.remove("is-hidden");
  document.getElementById("local-init-submit").textContent = "验证并完成初始化";
  showInitMessage(
    payload.debug_code
      ? `验证码已生成：${payload.debug_code}。生产环境会发送到 ${payload.masked_email || "绑定邮箱"}。`
      : `验证码已发送到 ${payload.masked_email || "绑定邮箱"}，请输入后完成初始化。`
  );
}

function resetLocalInitialization(options = {}) {
  state.initChallenge = null;
  document.body.classList.remove("auth-initializing");
  if (!state.authToken) document.body.classList.add("auth-locked");
  document.getElementById("local-init-code-field")?.classList.add("is-hidden");
  document.getElementById("local-init-submit").textContent = "发送初始化验证码";
  const codeInput = document.getElementById("local-init-form")?.querySelector("[name='email_code']");
  if (codeInput) codeInput.value = "";
  if (!options.silent) hideInitMessage();
}

async function completeLocalLogin(session) {
  state.authToken = session?.token || "";
  if (!state.authToken) throw new Error("登录成功但没有返回会话 token。");
  const storedTenantId = localStorage.getItem("localActiveTenantId") || "";
  state.activeTenantId = session?.user?.role === "admin" && storedTenantId ? storedTenantId : session?.active_tenant_id || state.activeTenantId || "";
  localStorage.setItem("localAuthToken", state.authToken);
  if (state.activeTenantId) localStorage.setItem("localActiveTenantId", state.activeTenantId);
  document.body.classList.remove("auth-locked");
  resetLocalLoginChallenge({silent: true});
  hideLoginMessage();
  await bootstrapAuthenticatedApp();
}

function resetLocalLoginChallenge(options = {}) {
  state.loginChallenge = null;
  const form = document.getElementById("local-login-form");
  document.getElementById("local-login-bind-email-field")?.classList.add("is-hidden");
  document.getElementById("local-login-code-field")?.classList.add("is-hidden");
  document.getElementById("local-login-trust-field")?.classList.add("is-hidden");
  document.getElementById("local-login-reset")?.classList.add("is-hidden");
  document.getElementById("local-login-submit").textContent = "登录";
  const codeInput = form?.querySelector("[name='email_code']");
  if (codeInput) codeInput.value = "";
  const emailInput = form?.querySelector("[name='bind_email']");
  if (emailInput) emailInput.value = "";
  const trustInput = form?.querySelector("[name='trust_device']");
  if (trustInput) trustInput.checked = false;
  if (!options.silent) hideLoginMessage();
}

async function bootstrapAuthenticatedApp() {
  await refreshAccountContext();
  await registerLocalNode().catch((error) => console.warn("register local node failed", error));
  scheduleStartupSync();
  scheduleCustomerServiceRuntimePolling();
  await Promise.all([loadOverview().catch(console.error), loadKnowledge().catch(console.error), refreshRagExperienceBadge().catch(console.error)]);
  await loadCustomerService().catch(console.error);
  renderGenerator();
  activateHashView();
}

async function logoutLocal() {
  if (state.authToken) {
    await fetch("/api/auth/logout", {method: "POST", headers: apiHeaders()}).catch(() => {});
  }
  lockLocalConsole();
}

function lockLocalConsole() {
  if (state.startupSyncTimer) {
    clearTimeout(state.startupSyncTimer);
    state.startupSyncTimer = null;
  }
  if (state.customerServiceRuntimeTimer) {
    clearInterval(state.customerServiceRuntimeTimer);
    state.customerServiceRuntimeTimer = null;
  }
  state.authToken = "";
  state.auth = null;
  state.security = null;
  state.initChallenge = null;
  state.passwordChallenge = null;
  state.emailChallenge = null;
  state.activeTenantId = "";
  document.getElementById("local-password-code-field")?.classList.add("is-hidden");
  document.getElementById("local-email-code-field")?.classList.add("is-hidden");
  resetLocalLoginChallenge({silent: true});
  resetLocalInitialization({silent: true});
  localStorage.removeItem("localAuthToken");
  localStorage.removeItem("localActiveTenantId");
  document.body.classList.add("auth-locked");
}

function showLoginMessage(text) {
  const element = document.getElementById("login-message");
  if (!element) return;
  element.textContent = text;
  element.classList.remove("is-hidden");
}

function hideLoginMessage() {
  const element = document.getElementById("login-message");
  if (!element) return;
  element.textContent = "";
  element.classList.add("is-hidden");
}

function showInitMessage(text) {
  const element = document.getElementById("local-init-message");
  if (!element) return;
  element.textContent = text;
  element.classList.remove("is-hidden");
}

function hideInitMessage() {
  const element = document.getElementById("local-init-message");
  if (!element) return;
  element.textContent = "";
  element.classList.add("is-hidden");
}

function getOrCreateDeviceId(key) {
  let value = localStorage.getItem(key);
  if (!value) {
    value = `device_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(key, value);
  }
  return value;
}

function loadStringSet(key) {
  try {
    const values = JSON.parse(localStorage.getItem(key) || "[]");
    if (!Array.isArray(values)) return new Set();
    return new Set(values.map((value) => String(value || "").trim()).filter(Boolean));
  } catch {
    return new Set();
  }
}

function saveStringSet(key, values) {
  localStorage.setItem(key, JSON.stringify([...values].slice(-200)));
}

function browserDeviceName() {
  const platform = navigator.platform || "Browser";
  const language = navigator.language || "";
  return `${platform} ${language}`.trim();
}

async function registerLocalNode() {
  if (!state.syncStatus?.vps_configured) return;
  const result = await apiJson("/api/sync/register-node", {
    method: "POST",
    body: JSON.stringify({display_name: `${state.auth?.session?.user?.display_name || state.auth?.session?.user?.user_id || "Local"} 客户端`}),
  });
  if (result.ok && result.node) {
    state.syncStatus.node = result.node;
    renderAccountContext();
  }
}

function scheduleStartupSync() {
  if (state.startupSyncTimer) {
    clearTimeout(state.startupSyncTimer);
    state.startupSyncTimer = null;
  }
  if (!state.syncStatus?.vps_configured) return;
  runStartupSync({startup: true}).catch((error) => {
    console.warn("startup sync failed", error);
  }).finally(() => {
    scheduleNextStartupSync();
  });
}

function scheduleNextStartupSync() {
  if (!state.syncStatus?.vps_configured) return;
  if (state.startupSyncTimer) clearTimeout(state.startupSyncTimer);
  state.startupSyncTimer = setTimeout(() => {
    state.startupSyncTimer = null;
    runStartupSync({startup: false}).catch((error) => {
      console.warn("periodic sync failed", error);
    }).finally(() => {
      scheduleNextStartupSync();
    });
  }, nextSharedSyncDelayMs());
}

function nextSharedSyncDelayMs() {
  const cache = state.syncStatus?.shared_cloud_cache || {};
  if (!cache.exists || cache.valid === false) return 60 * 1000;
  const refreshAt = Date.parse(cache.refresh_after_at || "");
  if (Number.isFinite(refreshAt)) {
    return clampSyncDelay(refreshAt - Date.now());
  }
  const refreshSeconds = Number(cache.refresh_after_seconds || 0);
  if (Number.isFinite(refreshSeconds) && refreshSeconds > 0) {
    return clampSyncDelay(refreshSeconds * 1000);
  }
  return 5 * 60 * 1000;
}

function clampSyncDelay(value) {
  const delay = Number.isFinite(value) ? value : 5 * 60 * 1000;
  return Math.max(60 * 1000, Math.min(10 * 60 * 1000, delay));
}

async function runStartupSync({startup = false} = {}) {
  if (!state.syncStatus?.vps_configured) return;
  const commandResult = await pollSyncCommands();
  handleSyncCommandOutcome(commandResult, {startup});
  const results = await Promise.allSettled([syncSharedCloudSnapshot(), checkSyncUpdate(), syncFormalSharedCandidates()]);
  if (results[0]?.status === "fulfilled") updateSharedCloudCacheStatus(results[0].value);
  const failed = results.filter((item) => item.status === "rejected");
  if (failed.length) {
    console.warn("some startup sync tasks failed", failed);
  }
}

async function pollSyncCommands() {
  return apiJson("/api/sync/commands/poll", {method: "POST", body: "{}"});
}

async function syncSharedCloudSnapshot({force = false} = {}) {
  return apiJson("/api/sync/shared/cloud-snapshot", {
    method: "POST",
    body: JSON.stringify({force}),
  });
}

function updateSharedCloudCacheStatus(payload = {}) {
  if (!state.syncStatus) state.syncStatus = {};
  const previous = state.syncStatus.shared_cloud_cache || {};
  state.syncStatus.shared_cloud_cache = {
    ...previous,
    exists: Boolean(payload.cached ?? previous.exists),
    valid: payload.cache_valid ?? previous.valid,
    version: payload.snapshot_version || previous.version || "",
    item_count: payload.item_count ?? previous.item_count ?? 0,
    category_count: payload.category_count ?? previous.category_count ?? 0,
    ttl_seconds: payload.ttl_seconds ?? previous.ttl_seconds ?? 0,
    refresh_after_seconds: payload.refresh_after_seconds ?? previous.refresh_after_seconds ?? 0,
    issued_at: payload.issued_at || previous.issued_at || "",
    refresh_after_at: payload.refresh_after_at || previous.refresh_after_at || "",
    expires_at: payload.expires_at || previous.expires_at || "",
    lease_id: payload.lease_id || previous.lease_id || "",
    cache_policy_mode: payload.cache_policy_mode || previous.cache_policy_mode || "",
    requires_cloud_refresh: payload.requires_cloud_refresh ?? previous.requires_cloud_refresh ?? true,
  };
}

function handleSyncCommandOutcome(payload, {startup = false} = {}) {
  const patchCommands = (payload?.commands || []).filter((item) => item?.type === "pull_shared_patch");
  if (!patchCommands.length) return;
  const results = payload?.results || [];
  const failed = results.filter((item) => item?.accepted === false || item?.result?.ok === false || item?.error);
  const succeeded = results.length - failed.length;
  if (failed.length) {
    console.warn("shared cloud snapshot refresh command failed", {failed, startup});
    return;
  }
  if (succeeded) {
    console.info("shared cloud snapshot refresh command finished", {succeeded, startup});
  }
}

async function checkSyncUpdate() {
  return apiGet("/api/sync/update/check");
}

async function syncFormalSharedCandidates() {
  return apiJson("/api/sync/shared/formal-candidates", {
    method: "POST",
    body: JSON.stringify({use_llm: true, only_unscanned: true, limit: 30}),
  });
}

async function refreshAccountContext() {
  const [auth, tenants, sync, security] = await Promise.all([
    apiGet("/api/auth/me").catch(() => ({ok: false})),
    apiGet("/api/tenants").catch(() => ({ok: false, items: []})),
    apiGet("/api/sync/status").catch(() => ({ok: false, mode: "unknown"})),
    apiGet("/api/auth/security").catch(() => ({ok: false, security: {}})),
  ]);
  state.auth = auth.auth || null;
  state.tenants = tenants.items || [];
  const authTenantId = auth.auth?.tenant_id || auth.auth?.session?.active_tenant_id || tenants.active_tenant_id || "";
  const tenantIds = state.tenants.map((item) => item.tenant_id).filter(Boolean);
  const role = auth.auth?.session?.user?.role || auth.auth?.role || "";
  const storedTenantId = localStorage.getItem("localActiveTenantId") || "";
  if (role === "admin") {
    const selectedTenantId = state.activeTenantId || storedTenantId || authTenantId || "";
    state.activeTenantId = tenantIds.includes(selectedTenantId) ? selectedTenantId : authTenantId || tenantIds[0] || "default";
  } else {
    const userTenantIds = auth.auth?.session?.user?.tenant_ids || [];
    const ownTenantId = authTenantId || userTenantIds[0] || tenantIds[0] || "default";
    state.activeTenantId = tenantIds.includes(ownTenantId) ? ownTenantId : tenantIds[0] || ownTenantId;
  }
  if (state.activeTenantId) localStorage.setItem("localActiveTenantId", state.activeTenantId);
  state.syncStatus = sync;
  state.security = security.security || {};
  renderAccountContext();
  renderLocalSecurity();
}

function renderAccountContext() {
  const user = state.auth?.session?.user || {};
  const role = user.role || state.auth?.role || "local";
  const roleNames = {admin: "管理员", customer: "客户", guest: "访客", local: "本地"};
  const accountName = user.username || user.display_name || user.user_id || "未登录";
  const activeTenant = state.tenants.find((item) => item.tenant_id === state.activeTenantId) || {};
  const displayTenant = activeTenant.display_name || state.activeTenantId || "default";
  const display = document.getElementById("current-account-space");
  const accountLabel = document.getElementById("current-account-label");
  const tenantSelect = document.getElementById("tenant-select");
  if (display) {
    display.classList.toggle("is-admin", role === "admin");
    display.querySelector("span").textContent = role === "admin" ? "客户数据" : "当前账号";
    display.title =
      role === "admin"
        ? "管理员可以切换本机不同客户的数据空间。切换后，知识库、记录员消息、商品库和设置都会随之切换。"
        : "当前登录账号对应的数据空间。一个客户账号只看自己的知识库、原始消息、记录员消息和设置。";
  }
  if (accountLabel) {
    accountLabel.textContent = `${accountName} · ${displayTenant}`;
    accountLabel.classList.toggle("is-hidden", role === "admin");
  }
  if (tenantSelect) {
    tenantSelect.classList.toggle("is-hidden", role !== "admin");
    tenantSelect.innerHTML = (state.tenants.length ? state.tenants : [{tenant_id: state.activeTenantId || "default", display_name: displayTenant}])
      .map((item) => {
        const tenantId = item.tenant_id || "default";
        const name = item.display_name || tenantId;
        return `<option value="${escapeHtml(tenantId)}"${tenantId === state.activeTenantId ? " selected" : ""}>${escapeHtml(name)}</option>`;
      })
      .join("");
  }
  document.getElementById("auth-pill").textContent = `${roleNames[role] || role}：${accountName}`;
  const nodeText = state.syncStatus?.node?.node_id ? "VPS 已连接" : "VPS 已配置";
  document.getElementById("sync-pill").textContent = state.syncStatus?.vps_configured ? nodeText : "本地模式";
}

function renderLocalSecurity() {
  const panel = document.getElementById("local-security-summary");
  if (!panel) return;
  const security = state.security || {};
  panel.innerHTML = `
    <div>
      <span>当前绑定邮箱</span>
      <strong>${escapeHtml(security.masked_email || security.email || "未绑定")}</strong>
    </div>
    <div>
      <span>邮箱验证码</span>
      <strong>${security.otp_required === false ? "未强制" : "已启用"}</strong>
    </div>
    <div>
      <span>信任设备</span>
      <strong>${escapeHtml(String(security.trusted_device_days || 30))} 天</strong>
    </div>
  `;
}

async function loadPlatformSafetyRules() {
  const payload = await apiGet("/api/system/platform-safety-rules");
  state.platformSafetyRules = payload;
  renderPlatformSafetyRules();
}

async function loadPlatformUnderstandingRules() {
  const payload = await apiGet("/api/system/platform-understanding-rules");
  state.platformUnderstandingRules = payload;
  renderPlatformUnderstandingRules();
}

function renderPlatformSafetyRules() {
  const payload = state.platformSafetyRules || {};
  const item = payload.item || {};
  const summary = document.getElementById("platform-safety-summary");
  const editor = document.getElementById("platform-safety-json");
  const saveButton = document.getElementById("save-platform-safety");
  const promptRules = Array.isArray(item.prompt_rules) ? item.prompt_rules : [];
  const guardTerms = item.guard_terms && typeof item.guard_terms === "object" ? item.guard_terms : {};
  const enabledRules = promptRules.filter((rule) => rule?.enabled !== false).length;
  const termCount = Object.values(guardTerms).reduce((total, value) => total + (Array.isArray(value) ? value.length : 0), 0);
  if (summary) {
    summary.innerHTML = `
      <div>
        <span>规则文件</span>
        <strong>${escapeHtml(payload.path || "未配置")}</strong>
      </div>
      <div>
        <span>生效提示规则</span>
        <strong>${enabledRules} 条</strong>
      </div>
      <div>
        <span>底线词条</span>
        <strong>${termCount} 个</strong>
      </div>
      <div>
        <span>编辑权限</span>
        <strong>${payload.editable ? "admin 可编辑" : "只读"}</strong>
      </div>
    `;
  }
  if (editor) {
    editor.value = JSON.stringify(item, null, 2);
    editor.readOnly = !payload.editable;
  }
  if (saveButton) {
    saveButton.disabled = !payload.editable;
    saveButton.title = payload.editable ? "保存平台底线规则" : "只有 admin 可以编辑平台底线规则";
  }
}

function renderPlatformUnderstandingRules() {
  const payload = state.platformUnderstandingRules || {};
  const item = payload.item || {};
  const summary = document.getElementById("platform-understanding-summary");
  const editor = document.getElementById("platform-understanding-json");
  const saveButton = document.getElementById("save-platform-understanding");
  const intentKeywords = item.intent_keywords && typeof item.intent_keywords === "object" ? item.intent_keywords : {};
  const intentCount = Object.values(intentKeywords).reduce((total, value) => total + (Array.isArray(value) ? value.length : 0), 0);
  const productKeywords = item.product_knowledge_keywords && typeof item.product_knowledge_keywords === "object" ? item.product_knowledge_keywords : {};
  const productCount = Object.values(productKeywords).reduce((total, value) => total + (Array.isArray(value) ? value.length : 0), 0);
  const semantic = item.semantic_equivalents && typeof item.semantic_equivalents === "object" ? item.semantic_equivalents : {};
  const semanticCount = Object.keys(semantic).length;
  const rag = item.rag && typeof item.rag === "object" ? item.rag : {};
  const ragCount = Object.values(rag).reduce((total, value) => total + (Array.isArray(value) ? value.length : 0), 0);
  const customerLabels = item.customer_data_field_labels && typeof item.customer_data_field_labels === "object" ? item.customer_data_field_labels : {};
  const customerLabelCount = Object.values(customerLabels).reduce((total, value) => total + (Array.isArray(value) ? value.length : 0), 0);
  if (summary) {
    summary.innerHTML = `
      <div>
        <span>词典文件</span>
        <strong>${escapeHtml(payload.path || "未配置")}</strong>
      </div>
      <div>
        <span>意图词</span>
        <strong>${intentCount} 个</strong>
      </div>
      <div>
        <span>商品理解词</span>
        <strong>${productCount} 个</strong>
      </div>
      <div>
        <span>检索近义词</span>
        <strong>${semanticCount} 组</strong>
      </div>
      <div>
        <span>RAG词条</span>
        <strong>${ragCount} 个</strong>
      </div>
      <div>
        <span>资料字段别名</span>
        <strong>${customerLabelCount} 个</strong>
      </div>
      <div>
        <span>编辑权限</span>
        <strong>${payload.editable ? "admin 可编辑" : "只读"}</strong>
      </div>
    `;
  }
  if (editor) {
    editor.value = JSON.stringify(item, null, 2);
    editor.readOnly = !payload.editable;
  }
  if (saveButton) {
    saveButton.disabled = !payload.editable;
    saveButton.title = payload.editable ? "保存平台通用理解词典" : "只有 admin 可以编辑平台通用理解词典";
  }
}

async function savePlatformSafetyRules() {
  const editor = document.getElementById("platform-safety-json");
  if (!editor) return;
  let item;
  try {
    item = JSON.parse(editor.value || "{}");
  } catch (error) {
    alert(`规则内容不是合法 JSON：${error.message}`);
    return;
  }
  const payload = await apiJson("/api/system/platform-safety-rules", {
    method: "PUT",
    body: JSON.stringify({item}),
  });
  state.platformSafetyRules = payload;
  renderPlatformSafetyRules();
  alert("平台底线规则已保存。");
}

async function savePlatformUnderstandingRules() {
  const editor = document.getElementById("platform-understanding-json");
  if (!editor) return;
  let item;
  try {
    item = JSON.parse(editor.value || "{}");
  } catch (error) {
    alert(`词典内容不是合法 JSON：${error.message}`);
    return;
  }
  const payload = await apiJson("/api/system/platform-understanding-rules", {
    method: "PUT",
    body: JSON.stringify({item}),
  });
  state.platformUnderstandingRules = payload;
  renderPlatformUnderstandingRules();
  alert("平台通用理解词典已保存。");
}

async function loadCustomerService() {
  const [settingsPayload, runtimePayload, overviewPayload] = await Promise.all([
    apiGet("/api/customer-service/settings"),
    apiGet("/api/customer-service/runtime/status").catch(() => ({item: null})),
    apiGet("/api/knowledge/overview").catch(() => ({counts: {}})),
  ]);
  state.customerService = settingsPayload.item || {};
  state.customerServiceRuntime = runtimePayload.item || state.customerServiceRuntime || {};
  renderCustomerService(overviewPayload.counts || {});
  renderCustomerServiceRuntime();
}

function renderCustomerService(counts = {}) {
  const item = state.customerService || {};
  const settings = item.settings || {};
  const modeSelect = document.getElementById("customer-service-mode");
  if (modeSelect) {
    modeSelect.innerHTML = (item.reply_modes || [])
      .map((mode) => `<option value="${escapeHtml(mode.id)}">${escapeHtml(mode.label)}</option>`)
      .join("");
    modeSelect.value = settings.reply_mode || "manual_assist";
  }
  setChecked("customer-service-enabled", Boolean(settings.enabled));
  setChecked("customer-record-messages", settings.record_messages !== false);
  setChecked("customer-auto-learn", settings.auto_learn !== false);
  setChecked("customer-use-llm", settings.use_llm !== false);
  setChecked("customer-rag-enabled", settings.rag_enabled !== false);
  setChecked("customer-data-capture", settings.data_capture_enabled !== false);
  setChecked("customer-handoff", settings.handoff_enabled !== false);
  setChecked("customer-operator-alert", settings.operator_alert_enabled !== false);
  document.getElementById("customer-service-status").textContent = item.status || "未配置";
  document.getElementById("customer-service-cards").innerHTML = `
    <div class="metric-card"><span>${settings.enabled ? "开" : "关"}</span><label>客服开关</label></div>
    <div class="metric-card"><span>${escapeHtml(modeSelect?.selectedOptions?.[0]?.textContent || "未选择")}</span><label>当前模式</label></div>
    <div class="metric-card"><span>${counts.pending_candidates ?? 0}</span><label>待确认知识</label></div>
    <div class="metric-card"><span>${counts.raw_messages ?? 0}</span><label>已记录消息</label></div>
  `;
  renderCustomerServiceRuntime();
}

async function refreshCustomerServiceRuntime(options = {}) {
  if (!state.authToken) return;
  try {
    const payload = await apiGet("/api/customer-service/runtime/status");
    state.customerServiceRuntime = payload.item || {};
    renderCustomerServiceRuntime();
  } catch (error) {
    if (!options.silent) console.warn(error);
  }
}

function renderCustomerServiceRuntime() {
  const runtime = state.customerServiceRuntime || {};
  const stateName = runtime.state || "stopped";
  const stateLabel = runtimeStateLabel(stateName);
  const stateMessage = runtime.message || "";
  const dotClasses = `service-state-dot is-${escapeHtml(stateName)}`;
  const panel = document.getElementById("customer-service-runtime-card");
  if (panel) {
    panel.className = `runtime-status-card is-${stateName}`;
    panel.innerHTML = `
      <div class="runtime-status-main">
        <span class="${dotClasses}"></span>
        <div>
          <strong>${escapeHtml(stateLabel)}</strong>
          <p>${escapeHtml(stateMessage || "等待状态更新")}</p>
          ${runtime.last_target ? `<small>最近会话：${escapeHtml(runtime.last_target)}${runtime.model_tier ? ` · 模型：${escapeHtml(runtime.model_tier)}` : ""}${runtime.rag_hit_count !== undefined && runtime.rag_hit_count !== null ? ` · RAG命中：${escapeHtml(String(runtime.rag_hit_count))}` : ""}</small>` : ""}
        </div>
      </div>
      <div class="button-row compact-actions">
        <button class="primary-button compact-button customer-runtime-start" ${!state.authToken || runtime.running || state.customerServiceRuntimeBusy ? "disabled" : ""}>启动</button>
        <button class="secondary-button compact-button customer-runtime-stop" ${!state.authToken || !runtime.running || state.customerServiceRuntimeBusy ? "disabled" : ""}>停止</button>
      </div>
    `;
    panel.querySelector(".customer-runtime-start")?.addEventListener("click", () => startCustomerServiceRuntime().catch((error) => alert(error.message)));
    panel.querySelector(".customer-runtime-stop")?.addEventListener("click", () => stopCustomerServiceRuntime().catch((error) => alert(error.message)));
  }
  const floating = document.getElementById("customer-service-float");
  if (floating) {
    floating.className = `customer-service-float is-${stateName}`;
    floating.innerHTML = `
      <div class="float-status-line">
        <span class="${dotClasses}"></span>
        <div>
          <strong>${escapeHtml(stateLabel)}</strong>
          <small>${escapeHtml(shortBusinessText(stateMessage || "", 58))}</small>
        </div>
      </div>
      <div class="float-actions">
        <button class="primary-button iconish-button customer-runtime-start" title="启动微信自动客服" ${!state.authToken || runtime.running || state.customerServiceRuntimeBusy ? "disabled" : ""}>开</button>
        <button class="secondary-button iconish-button customer-runtime-stop" title="停止微信自动客服" ${!state.authToken || !runtime.running || state.customerServiceRuntimeBusy ? "disabled" : ""}>停</button>
      </div>
    `;
    floating.querySelector(".customer-runtime-start")?.addEventListener("click", () => startCustomerServiceRuntime().catch((error) => alert(error.message)));
    floating.querySelector(".customer-runtime-stop")?.addEventListener("click", () => stopCustomerServiceRuntime().catch((error) => alert(error.message)));
  }
}

function runtimeStateLabel(stateName) {
  if (stateName === "thinking") return "思考中";
  if (stateName === "idle") return "空闲";
  return "已停止";
}

async function startCustomerServiceRuntime() {
  state.customerServiceRuntimeBusy = true;
  renderCustomerServiceRuntime();
  try {
    const payload = await apiJson("/api/customer-service/runtime/start", {method: "POST", body: JSON.stringify({})});
    if (payload.ok === false) throw new Error(payload.message || "自动客服启动失败");
    state.customerServiceRuntime = payload.item || {};
  } finally {
    state.customerServiceRuntimeBusy = false;
    await refreshCustomerServiceRuntime({silent: true});
  }
}

async function stopCustomerServiceRuntime() {
  state.customerServiceRuntimeBusy = true;
  renderCustomerServiceRuntime();
  try {
    const payload = await apiJson("/api/customer-service/runtime/stop", {method: "POST", body: JSON.stringify({})});
    if (payload.ok === false) throw new Error(payload.message || "自动客服停止失败");
    state.customerServiceRuntime = payload.item || {};
  } finally {
    state.customerServiceRuntimeBusy = false;
    await refreshCustomerServiceRuntime({silent: true});
  }
}

function scheduleCustomerServiceRuntimePolling() {
  if (state.customerServiceRuntimeTimer) clearInterval(state.customerServiceRuntimeTimer);
  if (!state.authToken) return;
  refreshCustomerServiceRuntime({silent: true});
  state.customerServiceRuntimeTimer = setInterval(() => refreshCustomerServiceRuntime({silent: true}), 3000);
}

async function saveCustomerServiceSettings() {
  const payload = await apiJson("/api/customer-service/settings", {
    method: "PUT",
    body: JSON.stringify({
      enabled: document.getElementById("customer-service-enabled")?.checked,
      reply_mode: document.getElementById("customer-service-mode")?.value || "manual_assist",
      record_messages: document.getElementById("customer-record-messages")?.checked,
      auto_learn: document.getElementById("customer-auto-learn")?.checked,
      use_llm: document.getElementById("customer-use-llm")?.checked,
      rag_enabled: document.getElementById("customer-rag-enabled")?.checked,
      data_capture_enabled: document.getElementById("customer-data-capture")?.checked,
      handoff_enabled: document.getElementById("customer-handoff")?.checked,
      operator_alert_enabled: document.getElementById("customer-operator-alert")?.checked,
    }),
  });
  state.customerService = payload.item || {};
  renderCustomerService((state.overview || {}).counts || {});
}

async function loadOverview() {
  const [knowledge, system] = await Promise.all([
    apiGet("/api/knowledge/overview"),
    apiGet("/api/system/status").catch(() => ({ok: false})),
  ]);
  state.overview = knowledge;
  const counts = knowledge.counts || {};
  document.getElementById("metric-products").textContent = counts.products ?? "-";
  document.getElementById("metric-candidates").textContent = counts.pending_candidates ?? "-";
  updateCandidateCountBadge(counts.pending_candidates ?? 0);
  document.getElementById("metric-diagnostics").textContent = system.ok ? "正常" : "待查";
  document.getElementById("overview-cards").innerHTML = `
    <div class="metric-card"><span>${counts.categories ?? 0}</span><label>知识门类</label></div>
    <div class="metric-card"><span>${counts.products ?? 0}</span><label>商品知识</label></div>
    <div class="metric-card"><span>${counts.faqs ?? 0}</span><label>规则问答</label></div>
    <div class="metric-card"><span>${counts.style_examples ?? 0}</span><label>话术样例</label></div>
    <div class="metric-card"><span>${counts.pending_candidates ?? 0}</span><label>待审核候选</label></div>
    <div class="metric-card"><span>${counts.new_knowledge ?? 0}</span><label>新加入知识</label></div>
    <div class="metric-card"><span>${counts.raw_messages ?? 0}</span><label>原始消息</label></div>
    <div class="metric-card"><span>${system.ok ? "正常" : "异常"}</span><label>系统状态</label></div>
  `;
}

async function loadKnowledge() {
  const payload = await apiGet("/api/knowledge/categories");
  state.categories = payload.items || [];
  const selectable = knowledgeCategoryOptions();
  if ((!state.activeCategoryId || !selectable.some((item) => item.id === state.activeCategoryId)) && selectable.length) {
    state.activeCategoryId = selectable[0].id;
  }
  renderCategorySelect();
  renderGeneratorCategorySelect();
  await loadCategoryItems();
}

function renderCategorySelect() {
  const select = document.getElementById("category-select");
  select.innerHTML = knowledgeCategoryOptions()
    .map((category) => {
      const suffix = category.scope === "tenant_product" ? "（从商品详情进入）" : "";
      return `<option value="${escapeHtml(category.id)}">${escapeHtml(category.name || category.id)}${suffix} (${category.item_count || 0})</option>`;
    })
    .join("");
  select.value = state.activeCategoryId;
}

function visibleKnowledgeCategories() {
  return state.categories.filter((category) => category.scope !== "tenant_product");
}

function knowledgeCategoryOptions() {
  const visible = visibleKnowledgeCategories();
  const active = categoryById(state.activeCategoryId);
  const scopedContextOpen = state.productScopedEditContext?.categoryId === active?.id
    || (state.diagnosticHighlight?.targets || []).some((target) => String(target).startsWith(`${active?.id}/`));
  if (active?.scope === "tenant_product" && scopedContextOpen && !visible.some((item) => item.id === active.id)) {
    return [active, ...visible];
  }
  return visible;
}

function renderGeneratorCategorySelect() {
  const select = document.getElementById("generator-category");
  if (!select) return;
  select.innerHTML = `<option value="">自动判断门类</option>` + state.categories
    .map((category) => `<option value="${escapeHtml(category.id)}">${escapeHtml(category.name || category.id)}</option>`)
    .join("");
}

async function loadCategoryItems() {
  if (!state.activeCategoryId) return;
  const payload = await apiGet(`/api/knowledge/categories/${encodeURIComponent(state.activeCategoryId)}/items`);
  state.categoryItems = sortKnowledgeItemsForReview(payload.items || []);
  state.selectedKnowledge = state.categoryItems[0] || null;
  state.knowledgeMode = "view";
  renderKnowledgeList();
  renderKnowledgeDetail();
}

function sortKnowledgeItemsForReview(items = []) {
  return [...items].sort((left, right) => {
    const unreadDiff = (knowledgeItemIsUnread(left) ? 0 : 1) - (knowledgeItemIsUnread(right) ? 0 : 1);
    if (unreadDiff) return unreadDiff;
    return knowledgeReviewTimestamp(right) - knowledgeReviewTimestamp(left);
  });
}

function knowledgeItemIsUnread(item) {
  return Boolean(item?.review_state?.is_new);
}

function knowledgeReviewTimestamp(item) {
  const reviewState = item?.review_state || {};
  const value = knowledgeItemIsUnread(item)
    ? reviewState.marked_at || reviewState.updated_at || item?.updated_at || item?.created_at || ""
    : reviewState.read_at || reviewState.updated_at || reviewState.marked_at || item?.updated_at || item?.created_at || "";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function activeCategory() {
  return state.categories.find((item) => item.id === state.activeCategoryId) || null;
}

function categoryById(categoryId) {
  return state.categories.find((item) => item.id === categoryId) || null;
}

function isProductScopedCategory(category) {
  const categoryId = typeof category === "string" ? category : category?.id;
  const record = typeof category === "string" ? categoryById(category) : category;
  return record?.scope === "tenant_product" || ["product_faq", "product_rules", "product_explanations"].includes(categoryId);
}

function productDisplayName(productId) {
  const id = String(productId || "");
  if (!id) return "";
  const selected = state.selectedProduct;
  if (selected?.id === id) return selected.display?.name || selected.data?.name || id;
  const product = (state.productCatalog?.items || []).find((item) => item.id === id);
  return product?.display?.name || product?.data?.name || id;
}

function productCatalogItems() {
  return state.productCatalog?.items || [];
}

function productCategoryChoices(currentValue = "") {
  const values = new Set();
  for (const item of productCatalogItems()) {
    const category = item.display?.category || item.data?.category || "";
    if (category && category !== "未分类") values.add(String(category));
  }
  if (currentValue) values.add(String(currentValue));
  return Array.from(values).sort((a, b) => a.localeCompare(b, "zh-CN"));
}

function productIdSelectHtml(field, value, renderOptions = {}) {
  const id = `data-${field.id}`;
  const selectedValue = String(value || "");
  const readonly = renderOptions.readonlyFields?.has?.(field.id);
  const products = productCatalogItems();
  const hasSelected = products.some((item) => String(item.id) === selectedValue);
  const options = [
    `<option value="">自动匹配或不指定商品</option>`,
    ...products.map((item) => {
      const label = `${item.display?.name || item.data?.name || item.id} · ${item.display?.sku || item.id}`;
      return `<option value="${escapeHtml(item.id)}" ${String(item.id) === selectedValue ? "selected" : ""}>${escapeHtml(label)}</option>`;
    }),
    selectedValue && !hasSelected ? `<option value="${escapeHtml(selectedValue)}" selected>未在商品库找到：${escapeHtml(selectedValue)}</option>` : "",
  ].join("");
  return `
    <label class="form-field" data-field="${escapeHtml(field.id)}" data-kind="product_select">
      <span>${escapeHtml(fieldLabel(field))}${field.required ? " *" : ""}</span>
      <select id="${escapeHtml(id)}" ${readonly ? "disabled" : ""}>${options}</select>
      <small>从当前商品库选择，系统保存商品 ID；不用手动输入编号。</small>
    </label>
  `;
}

function productCategorySelectHtml(field, value, renderOptions = {}) {
  const id = `data-${field.id}`;
  const selectedValue = String(value || "");
  const readonly = renderOptions.readonlyFields?.has?.(field.id);
  const options = [
    `<option value="">全部类目或自动匹配</option>`,
    ...productCategoryChoices(selectedValue).map((category) => `<option value="${escapeHtml(category)}" ${category === selectedValue ? "selected" : ""}>${escapeHtml(category)}</option>`),
  ].join("");
  return `
    <label class="form-field" data-field="${escapeHtml(field.id)}" data-kind="product_category_select">
      <span>${escapeHtml(fieldLabel(field))}${field.required ? " *" : ""}</span>
      <select id="${escapeHtml(id)}" ${readonly ? "disabled" : ""}>${options}</select>
      <small>从商品库已有类目里选择；没有类目时先到商品库维护。</small>
    </label>
  `;
}

function knowledgeProductName(item) {
  const productId = item?.data?.product_id || state.productScopedEditContext?.productId || "";
  return productDisplayName(productId) || productId || "未指定商品";
}

function knowledgeScopeBadges(category, item) {
  if (!category || !item) return [];
  const data = item.data || {};
  if (isProductScopedCategory(category)) {
    return [{label: `只用于：${knowledgeProductName(item)}`, tone: "info"}];
  }
  if (category.id === "products") return [{label: "同步到商品库", tone: "info"}];
  if (!["chats", "policies"].includes(category.id)) return [];
  const scope = data.applicability_scope || "global";
  if (scope === "specific_product") return [{label: `指定商品：${productDisplayName(data.product_id) || data.product_id || "未填写"}`, tone: "info"}];
  if (scope === "product_category") return [{label: `商品类目：${data.product_category || "未填写"}`, tone: "info"}];
  return [{label: "全部商品通用", tone: "ok"}];
}

function knowledgeContextNoticeHtml(category, item, options = {}) {
  if (!category || !item) return "";
  const data = item.data || {};
  if (isProductScopedCategory(category)) {
    return `
      <div class="helper-card context-card">
        <strong>这条内容只属于「${escapeHtml(knowledgeProductName(item))}」。</strong>
        <span>${options.editing ? "商品 ID 已锁定，避免把专属问答误改成别的商品；正文和触发词可以直接修改。" : "客户问到这个商品时，它才会参与客服回复。点击编辑后只需要改标题、触发词和回复内容。"}</span>
      </div>
    `;
  }
  if (category.id === "products") {
    return `
      <div class="helper-card context-card">
        <strong>商品资料会同步显示在商品库。</strong>
        <span>库存、在售/归档和常用运营动作建议优先在商品库操作；这里适合补充规格、物流、售后和高级字段。</span>
      </div>
    `;
  }
  if (["chats", "policies"].includes(category.id)) {
    const badge = knowledgeScopeBadges(category, item)[0]?.label || "全部商品通用";
    const tip = data.applicability_scope === "specific_product"
      ? "这条知识只在关联商品被识别出来时参与回复。"
      : data.applicability_scope === "product_category"
        ? "这条知识只在对应商品类目被识别出来时参与回复。"
        : "这条知识会作为通用话术或规则参与回复。";
    return `
      <div class="helper-card context-card">
        <strong>${escapeHtml(badge)}</strong>
        <span>${escapeHtml(tip)}${options.editing ? " 如果只适用于某个商品，请在下方设置适用范围和关联商品。" : ""}</span>
      </div>
    `;
  }
  return "";
}

function renderKnowledgeList() {
  const query = (document.getElementById("knowledge-search").value || "").trim().toLowerCase();
  const category = activeCategory();
  const titleField = category?.schema?.item_title_field || "title";
  const subtitleField = category?.schema?.item_subtitle_field || "";
  const list = document.getElementById("knowledge-list");
  const filtered = sortKnowledgeItemsForReview(state.categoryItems.filter((item) => {
    const text = `${item.id} ${businessSearchText(item.data || {})}`.toLowerCase();
    return !query || text.includes(query);
  }));
  list.innerHTML = filtered
    .map((item, index) => {
      const title = item.data?.[titleField] || item.id;
      const subtitle = subtitleField ? item.data?.[subtitleField] : item.status;
      const active = state.selectedKnowledge?.id === item.id ? " is-selected" : "";
      const highlighted = diagnosticTargetMatches(category?.id, item.id) ? " diagnostic-highlight" : "";
      const badges = [...(item.display_badges || []), ...knowledgeScopeBadges(category, item)];
      return `
        <button class="record-row${active}${highlighted}" data-index="${index}">
          <strong>${escapeHtml(title)}</strong>
          <span>${escapeHtml(item.id)} · ${escapeHtml(subtitle || item.status || "")}</span>
          ${badgeListHtml(badges)}
        </button>
      `;
    })
    .join("");
  list.querySelectorAll(".record-row").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedKnowledge = filtered[Number(button.dataset.index)];
      state.knowledgeMode = "view";
      renderKnowledgeList();
      renderKnowledgeDetail();
    });
  });
  if (!filtered.length) {
    list.innerHTML = `<div class="empty-state">没有匹配结果</div>`;
  }
}

function renderKnowledgeDetail() {
  const detail = document.getElementById("knowledge-detail");
  const category = activeCategory();
  const item = state.selectedKnowledge;
  updateKnowledgeButtons();
  if (!category) {
    detail.innerHTML = `<div class="empty-state">暂无知识门类</div>`;
    return;
  }
  if (!item) {
    detail.innerHTML = `<div class="empty-state">当前门类暂无条目，点击“新增知识”开始添加。</div>`;
    return;
  }
  detail.innerHTML = state.knowledgeMode === "view" ? knowledgeReadonlyHtml(category, item) : knowledgeFormHtml(category, item);
  bindDynamicEditors(detail);
  detail.querySelector(".knowledge-acknowledge")?.addEventListener("click", () => acknowledgeKnowledgeItem().catch((error) => alert(error.message)));
}

async function loadProductCatalog(options = {}) {
  const payload = await apiGet("/api/product-console/catalog?include_archived=true");
  state.productCatalog = payload;
  const items = payload.items || [];
  if (state.selectedProduct?.id && !items.some((item) => item.id === state.selectedProduct.id)) {
    state.selectedProduct = null;
    state.productDetailMode = "view";
    state.productScopedEditor = null;
  }
  state.selectedProduct = state.selectedProduct || items.find((item) => item.status === "active") || items[0] || null;
  renderProductCatalog();
  if (options.loadDetail !== false && state.selectedProduct?.id) {
    await loadProductDetail(state.selectedProduct.id);
  }
}

function renderProductCatalog() {
  const payload = state.productCatalog || {};
  const counts = payload.counts || {};
  document.getElementById("product-catalog-cards").innerHTML = `
    <div class="metric-card"><span>${counts.active ?? 0}</span><label>在售商品</label></div>
    <div class="metric-card"><span>${counts.in_stock ?? 0}</span><label>有库存</label></div>
    <div class="metric-card"><span>${counts.sold_out ?? 0}</span><label>无库存</label></div>
    <div class="metric-card"><span>${counts.archived ?? 0}</span><label>已归档</label></div>
  `;
  renderProductCatalogList();
  renderProductCatalogDetail();
}

function renderProductCatalogList() {
  const list = document.getElementById("product-catalog-list");
  const items = state.productCatalog?.items || [];
  list.innerHTML = items.map((item, index) => {
    const display = item.display || {};
    const active = state.selectedProduct?.id === item.id ? " is-selected" : "";
    const badges = [
      {label: display.stock_label || "库存未填写", tone: item.stock_state === "in_stock" ? "ok" : item.stock_state === "archived" ? "muted" : "warning"},
      {label: `${(item.scoped_counts || {}).product_faq || 0} 问答`, tone: "info"},
      {label: `${(item.scoped_counts || {}).product_rules || 0} 规则`, tone: "info"},
    ];
    return `
      <button class="record-row product-row${active}" data-index="${index}">
        <strong>${escapeHtml(display.name || item.id)}</strong>
        <span>${escapeHtml(display.sku || item.id)} · ${escapeHtml(display.category || "未分类")} · ${escapeHtml(formatProductPrice(display))}</span>
        ${badgeListHtml(badges)}
      </button>
    `;
  }).join("") || `<div class="empty-state">暂无商品。可以点击“新增商品”，或在上方用一句话添加。</div>`;
  list.querySelectorAll(".product-row").forEach((button) => {
    button.addEventListener("click", async () => {
      const item = items[Number(button.dataset.index)];
      state.selectedProduct = item || null;
      state.productDetailMode = "view";
      state.productScopedEditor = null;
      await loadProductDetail(item?.id);
    });
  });
}

async function loadProductDetail(productId) {
  if (!productId) {
    renderProductCatalogDetail();
    return;
  }
  const payload = await apiGet(`/api/product-console/products/${encodeURIComponent(productId)}`);
  state.selectedProduct = payload.item || state.selectedProduct;
  state.productDetailScopedKnowledge = payload.scoped_knowledge || {};
  renderProductCatalogList();
  renderProductCatalogDetail();
}

function renderProductCatalogDetail(scopedKnowledge = null) {
  const detail = document.getElementById("product-catalog-detail");
  const item = state.selectedProduct;
  if (!item) {
    detail.innerHTML = `<div class="empty-state">请选择一个商品。</div>`;
    return;
  }
  const data = item.data || {};
  const display = item.display || {};
  if (scopedKnowledge) state.productDetailScopedKnowledge = scopedKnowledge;
  const scoped = scopedKnowledge || state.productDetailScopedKnowledge || {};
  if (state.productDetailMode === "edit") {
    detail.innerHTML = productEditFormHtml(item, scoped);
    bindProductDetailEditors(detail);
    return;
  }
  detail.innerHTML = `
    <div class="read-head">
      <div>
        <p class="eyebrow">商品详情</p>
        <h2>${escapeHtml(display.name || data.name || item.id)}</h2>
        ${badgeListHtml([
          {label: display.stock_label || "库存未填写", tone: item.stock_state === "in_stock" ? "ok" : item.stock_state === "archived" ? "muted" : "warning"},
          {label: item.status === "archived" ? "已归档" : "在售", tone: item.status === "archived" ? "muted" : "ok"},
        ])}
      </div>
      <div class="read-actions">
        <button class="secondary-button product-edit-form" type="button">编辑详情</button>
        <button class="secondary-button product-open-formal" type="button">高级结构化编辑</button>
        <button class="secondary-button danger-button product-archive" type="button">${item.status === "archived" ? "重新上架" : "归档"}</button>
      </div>
    </div>
    <div class="summary-table product-summary-table">
      <div><span>价格</span><strong>${escapeHtml(formatProductPrice(display))}</strong></div>
      <div><span>库存</span><strong>${escapeHtml(display.stock_label || "未填写")}</strong></div>
      <div><span>SKU</span><strong>${escapeHtml(display.sku || item.id)}</strong></div>
      <div><span>类目</span><strong>${escapeHtml(display.category || "未分类")}</strong></div>
    </div>
    <div class="inventory-tools">
      <button class="secondary-button product-stock-decrease" type="button">卖出 1 件</button>
      <button class="secondary-button product-stock-increase" type="button">补货 1 件</button>
      <label class="form-field inline-field"><span>库存改为</span><input id="product-stock-set-value" type="number" min="0" placeholder="数量" /></label>
      <button class="primary-button product-stock-set" type="button">保存库存</button>
    </div>
    <div class="read-grid">
      ${productInfoField("客户常用叫法", (data.aliases || []).join("、"))}
      ${productInfoField("规格参数", data.specs)}
      ${productInfoField("发货/物流", data.shipping_policy)}
      ${productInfoField("售后/保修", data.warranty_policy)}
      ${productInfoField("风险提醒", (data.risk_rules || []).join("、"))}
    </div>
    ${productReplyTemplatesReadonlyHtml(data.reply_templates, display.name || data.name || item.id)}
    <div class="product-scoped-panel">
      <div class="section-heading">
        <div>
          <span>商品专属知识</span>
          <strong>这些内容只会在客户问到这个商品时参与回答；和上面的客服回复内容同属当前商品，但不会互相覆盖。</strong>
        </div>
      </div>
      ${productScopedHtml("商品专属问答", "product_faq", scoped.product_faq || [], "answer", display.name || data.name || item.id)}
      ${productScopedHtml("商品专属规则", "product_rules", scoped.product_rules || [], "answer", display.name || data.name || item.id)}
      ${productScopedHtml("商品专属解释", "product_explanations", scoped.product_explanations || [], "content", display.name || data.name || item.id)}
      ${productScopedEditorHtml()}
    </div>
  `;
  detail.querySelector(".product-stock-decrease")?.addEventListener("click", () => adjustProductInventory("sell", 1));
  detail.querySelector(".product-stock-increase")?.addEventListener("click", () => adjustProductInventory("increase", 1));
  detail.querySelector(".product-stock-set")?.addEventListener("click", () => {
    const quantity = Number(document.getElementById("product-stock-set-value")?.value || 0);
    adjustProductInventory("set", quantity);
  });
  detail.querySelector(".product-archive")?.addEventListener("click", () => {
    const operation = item.status === "archived" ? "activate" : "archive";
    if (operation === "archive" && !confirm("确认把这个商品归档吗？归档后不会作为在售商品参与客服回答。")) return;
    adjustProductInventory(operation, 0);
  });
  detail.querySelector(".product-edit-form")?.addEventListener("click", () => {
    state.productDetailMode = "edit";
    state.productScopedEditor = null;
    renderProductCatalogDetail();
  });
  detail.querySelector(".product-open-formal")?.addEventListener("click", () => openSelectedProductInFormalKnowledge());
  detail.querySelectorAll(".product-scoped-edit").forEach((button) => {
    button.addEventListener("click", () => openProductScopedInlineEditor(button.dataset.category, button.dataset.itemId));
  });
  detail.querySelectorAll(".product-scoped-new").forEach((button) => {
    button.addEventListener("click", () => openProductScopedInlineEditor(button.dataset.category, ""));
  });
  bindProductScopedEditor(detail);
}

function productInfoField(label, value) {
  if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) return "";
  return `<div class="read-field wide-field"><span>${escapeHtml(label)}</span><p>${escapeHtml(value)}</p></div>`;
}

function productReplyTemplatesReadonlyHtml(value, productName) {
  const templates = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const entries = Object.entries(templates).filter(([, inner]) => !isEmpty(inner));
  return `
    <div class="read-field wide-field product-template-read">
      <span>客服回复内容</span>
      <p>这些默认回复绑定在「${escapeHtml(productName || "当前商品")}」上；客户问到这个商品时可作为基础话术。需要更精确触发词时，用下方“商品专属问答/规则/解释”。</p>
      ${entries.length ? `
        <div class="variable-table">
          <div class="variable-table-head"><strong>场景</strong><strong>回复内容</strong></div>
          ${entries.map(([key, inner]) => `
            <div class="variable-table-row">
              <code>${escapeHtml(templateLabels[key] || key)}</code>
              <span>${escapeHtml(displayBusinessValue(inner))}</span>
            </div>
          `).join("")}
        </div>
      ` : `<div class="empty-state compact-empty">当前商品没有单独填写默认回复，将使用通用话术或 AI 经验。</div>`}
    </div>
  `;
}

function productEditFormHtml(item, scoped) {
  const data = item.data || {};
  const productName = data.name || item.display?.name || item.id;
  return `
    <div class="read-head">
      <div>
        <p class="eyebrow">编辑商品资料</p>
        <h2>${escapeHtml(productName || item.id)}</h2>
        ${badgeListHtml([{label: "在商品库内编辑", tone: "info"}, {label: item.status === "archived" ? "已归档" : "在售", tone: item.status === "archived" ? "muted" : "ok"}])}
      </div>
      <div class="read-actions">
        <button class="primary-button product-detail-save" type="button">保存商品资料</button>
        <button class="secondary-button product-detail-cancel" type="button">取消</button>
      </div>
    </div>
    <div class="helper-card context-card product-edit-help">
      <strong>这里只改当前商品。</strong>
      <span>商品名称、价格、库存、物流、售后和客服回复内容会同步影响商品库；下方商品专属问答/规则/解释仍然单独维护，但都归属同一件商品。</span>
    </div>
    <div class="form-grid product-detail-form">
      ${productTextInput("product-data-name", "商品名称 *", data.name || "")}
      ${productTextInput("product-data-sku", "型号/SKU", data.sku || "")}
      ${productTextInput("product-data-category", "商品类目", data.category || "")}
      ${productTextInput("product-data-unit", "计价单位", data.unit || "")}
      ${productTextInput("product-data-price", "基础价格", data.price ?? "", "number")}
      ${productTextInput("product-data-inventory", "库存", data.inventory ?? "", "number")}
      ${productTextarea("product-data-aliases", "客户常用叫法", displayTags(data.aliases), "一行一个，或用逗号分隔")}
      ${productTextarea("product-data-specs", "规格参数", data.specs || "")}
      ${productTextarea("product-data-shipping", "发货/物流", data.shipping_policy || "")}
      ${productTextarea("product-data-warranty", "售后/保修", data.warranty_policy || "")}
      ${productTextarea("product-data-risk", "风险提醒", displayTags(data.risk_rules), "一行一个，或用逗号分隔")}
      ${productReplyTemplateEditorHtml(data.reply_templates, productName)}
    </div>
    <div class="product-scoped-panel">
      <div class="section-heading">
        <div>
          <span>商品专属知识</span>
          <strong>下面三类是带触发词的专属知识，和“客服回复内容”同属当前商品，但不会互相覆盖。</strong>
        </div>
      </div>
      ${productScopedHtml("商品专属问答", "product_faq", (scoped || {}).product_faq || [], "answer", productName)}
      ${productScopedHtml("商品专属规则", "product_rules", (scoped || {}).product_rules || [], "answer", productName)}
      ${productScopedHtml("商品专属解释", "product_explanations", (scoped || {}).product_explanations || [], "content", productName)}
      ${productScopedEditorHtml()}
    </div>
  `;
}

function productTextInput(id, label, value, type = "text") {
  return `
    <label class="form-field product-short-field">
      <span>${escapeHtml(label)}</span>
      <input id="${escapeHtml(id)}" type="${escapeHtml(type)}" value="${escapeHtml(value ?? "")}" />
    </label>
  `;
}

function productTextarea(id, label, value, placeholder = "") {
  return `
    <label class="form-field wide-field">
      <span>${escapeHtml(label)}</span>
      <textarea id="${escapeHtml(id)}" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value || "")}</textarea>
    </label>
  `;
}

function productReplyTemplateEditorHtml(value, productName) {
  const templates = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const keys = Array.from(new Set([...Object.keys(templateLabels), ...Object.keys(templates)]));
  return `
    <div class="form-field wide-field reply-template-editor product-reply-template-editor">
      <span>客服回复内容</span>
      <div class="object-guide">这些是「${escapeHtml(productName || "当前商品")}」的默认商品话术；它们和下方商品专属知识都绑定当前商品。需要“客户问到某个关键词才用”的内容，请放到商品专属问答/规则/解释。</div>
      ${keys.map((key) => `
        <label class="nested-field">
          <span>${escapeHtml(templateLabels[key] || key)}</span>
          <textarea data-product-template-key="${escapeHtml(key)}">${escapeHtml(templates[key] || "")}</textarea>
        </label>
      `).join("")}
    </div>
  `;
}

function bindProductDetailEditors(root) {
  root.querySelector(".product-detail-save")?.addEventListener("click", () => saveProductDetailForm().catch((error) => alert(error.message)));
  root.querySelector(".product-detail-cancel")?.addEventListener("click", () => {
    state.productDetailMode = "view";
    state.productScopedEditor = null;
    renderProductCatalogDetail();
  });
  root.querySelectorAll(".product-scoped-edit").forEach((button) => {
    button.addEventListener("click", () => openProductScopedInlineEditor(button.dataset.category, button.dataset.itemId));
  });
  root.querySelectorAll(".product-scoped-new").forEach((button) => {
    button.addEventListener("click", () => openProductScopedInlineEditor(button.dataset.category, ""));
  });
  bindProductScopedEditor(root);
}

async function saveProductDetailForm() {
  const original = state.selectedProduct;
  if (!original?.id) return;
  const data = {
    ...(original.data || {}),
    name: document.getElementById("product-data-name")?.value.trim() || "",
    sku: document.getElementById("product-data-sku")?.value.trim() || "",
    category: document.getElementById("product-data-category")?.value.trim() || "",
    unit: document.getElementById("product-data-unit")?.value.trim() || "",
    price: numberOrNull(document.getElementById("product-data-price")?.value),
    inventory: numberOrNull(document.getElementById("product-data-inventory")?.value),
    aliases: splitTags(document.getElementById("product-data-aliases")?.value || ""),
    specs: document.getElementById("product-data-specs")?.value.trim() || "",
    shipping_policy: document.getElementById("product-data-shipping")?.value.trim() || "",
    warranty_policy: document.getElementById("product-data-warranty")?.value.trim() || "",
    risk_rules: splitTags(document.getElementById("product-data-risk")?.value || ""),
    reply_templates: collectProductReplyTemplates(),
  };
  if (!data.name) throw new Error("商品名称不能为空。");
  const item = {
    ...original,
    category_id: "products",
    id: original.id,
    status: original.status || "active",
    data,
    runtime: original.runtime || {allow_auto_reply: true, requires_handoff: false, risk_level: "normal"},
  };
  await apiJson(`/api/knowledge/categories/products/items/${encodeURIComponent(original.id)}`, {
    method: "PUT",
    body: JSON.stringify(item),
  });
  state.productDetailMode = "view";
  state.productScopedEditor = null;
  await Promise.all([loadProductCatalog({loadDetail: false}), loadOverview().catch(() => {})]);
  await loadProductDetail(original.id);
}

function collectProductReplyTemplates() {
  const item = {};
  document.querySelectorAll("[data-product-template-key]").forEach((input) => {
    const value = input.value.trim();
    if (value) item[input.dataset.productTemplateKey] = value;
  });
  return item;
}

function productScopedHtml(title, categoryId, items, bodyField, productName) {
  return `
    <section class="product-scoped-section">
      <div class="product-scoped-section-head">
        <h3>${escapeHtml(title)}</h3>
        <button class="secondary-button product-scoped-new" type="button" data-category="${escapeHtml(categoryId)}">新增</button>
      </div>
      ${items.length ? items.map((item) => {
        const data = item.data || {};
        const productId = data.product_id || state.selectedProduct?.id || "";
        return `
          <div class="compact-row product-scoped-row">
            <div>
              <strong>${escapeHtml(data.title || item.id)}</strong>
              <span>归属商品：${escapeHtml(productName || productId || "未指定")} · ${escapeHtml((data.keywords || []).join("、") || "未设置触发词")}</span>
              <p>${escapeHtml(data[bodyField] || data.answer || data.content || "")}</p>
            </div>
            <button class="secondary-button product-scoped-edit" type="button" data-category="${escapeHtml(categoryId)}" data-item-id="${escapeHtml(item.id)}" data-product-id="${escapeHtml(productId)}">编辑</button>
          </div>
        `;
      }).join("") : `<div class="empty-state">暂无${escapeHtml(title)}。</div>`}
    </section>
  `;
}

function openProductScopedInlineEditor(categoryId, itemId) {
  const items = (state.productDetailScopedKnowledge || {})[categoryId] || [];
  const item = itemId ? items.find((entry) => entry.id === itemId) : null;
  state.productScopedEditor = {
    categoryId,
    itemId: item?.id || "",
    item: item || null,
  };
  renderProductCatalogDetail();
}

function productScopedEditorHtml() {
  const editor = state.productScopedEditor;
  const product = state.selectedProduct;
  if (!editor || !product?.id) return "";
  const categoryId = editor.categoryId;
  const item = editor.item || {};
  const data = item.data || {};
  const productName = product.display?.name || product.data?.name || product.id;
  const bodyField = productScopedBodyField(categoryId);
  const bodyLabel = categoryId === "product_explanations" ? "说明内容 *" : "标准回复 *";
  return `
    <div class="product-scoped-editor">
      <div class="section-heading">
        <div>
          <span>${escapeHtml(productScopedCategoryTitle(categoryId))}</span>
          <strong>${editor.itemId ? "编辑" : "新增"}「${escapeHtml(productName)}」的专属内容</strong>
        </div>
      </div>
      <div class="helper-card context-card">
        <strong>这条内容只会绑定当前商品。</strong>
        <span>商品 ID 已固定为 ${escapeHtml(product.id)}；保存后仍显示在商品详情里，客户问到当前商品并命中触发词时才会参与回复。</span>
      </div>
      <div class="form-grid product-scoped-form">
        <label class="form-field">
          <span>标题 *</span>
          <input id="product-scoped-title" value="${escapeHtml(data.title || "")}" />
        </label>
        <label class="form-field">
          <span>归属商品</span>
          <input id="product-scoped-product-id" value="${escapeHtml(product.id)}" readonly />
        </label>
        ${productTextarea("product-scoped-keywords", "触发关键词", displayTags(data.keywords), "一行一个，或用逗号分隔")}
        ${categoryId === "product_faq" ? productTextarea("product-scoped-question", "客户问题", data.question || "") : ""}
        ${productTextarea("product-scoped-body", bodyLabel, data[bodyField] || data.answer || data.content || "")}
        ${categoryId === "product_rules" ? `
          <label class="checkbox-line"><input id="product-scoped-auto" type="checkbox" ${data.allow_auto_reply !== false ? "checked" : ""} /> 允许自动回复</label>
          <label class="checkbox-line"><input id="product-scoped-handoff" type="checkbox" ${data.requires_handoff ? "checked" : ""} /> 必须转人工</label>
          <label class="form-field">
            <span>转人工原因</span>
            <input id="product-scoped-handoff-reason" value="${escapeHtml(data.handoff_reason || "")}" />
          </label>
        ` : ""}
      </div>
      <div class="button-row product-scoped-editor-actions">
        <button class="primary-button product-scoped-save" type="button">保存专属知识</button>
        <button class="secondary-button product-scoped-cancel" type="button">取消</button>
        ${editor.itemId ? `<button class="secondary-button danger-button product-scoped-delete" type="button">归档删除</button>` : ""}
      </div>
    </div>
  `;
}

function bindProductScopedEditor(root) {
  root.querySelector(".product-scoped-save")?.addEventListener("click", () => saveProductScopedInlineEditor().catch((error) => alert(error.message)));
  root.querySelector(".product-scoped-cancel")?.addEventListener("click", () => {
    state.productScopedEditor = null;
    renderProductCatalogDetail();
  });
  root.querySelector(".product-scoped-delete")?.addEventListener("click", () => deleteProductScopedInlineItem().catch((error) => alert(error.message)));
}

async function saveProductScopedInlineEditor() {
  const editor = state.productScopedEditor;
  const product = state.selectedProduct;
  if (!editor?.categoryId || !product?.id) return;
  const categoryId = editor.categoryId;
  const bodyField = productScopedBodyField(categoryId);
  const title = document.getElementById("product-scoped-title")?.value.trim() || "";
  const body = document.getElementById("product-scoped-body")?.value.trim() || "";
  if (!title) throw new Error("标题不能为空。");
  if (!body) throw new Error(categoryId === "product_explanations" ? "说明内容不能为空。" : "标准回复不能为空。");
  const data = {
    ...(editor.item?.data || {}),
    product_id: product.id,
    title,
    keywords: splitTags(document.getElementById("product-scoped-keywords")?.value || ""),
    [bodyField]: body,
  };
  if (categoryId === "product_faq") {
    data.question = document.getElementById("product-scoped-question")?.value.trim() || "";
  }
  if (categoryId === "product_rules") {
    data.allow_auto_reply = Boolean(document.getElementById("product-scoped-auto")?.checked);
    data.requires_handoff = Boolean(document.getElementById("product-scoped-handoff")?.checked);
    data.handoff_reason = document.getElementById("product-scoped-handoff-reason")?.value.trim() || "";
  }
  const itemId = editor.itemId || clientSafeId(`${product.id}-${categoryId}-${title}`, `${categoryId}-${Date.now()}`);
  const item = {
    ...(editor.item || {}),
    schema_version: 1,
    category_id: categoryId,
    id: itemId,
    status: "active",
    source: editor.item?.source || {type: "product_catalog"},
    data,
    runtime: {
      allow_auto_reply: categoryId === "product_rules" ? data.allow_auto_reply !== false : true,
      requires_handoff: categoryId === "product_rules" ? Boolean(data.requires_handoff) : false,
      risk_level: categoryId === "product_rules" && data.requires_handoff ? "high" : "normal",
    },
  };
  const path = editor.itemId
    ? `/api/knowledge/categories/${encodeURIComponent(categoryId)}/items/${encodeURIComponent(itemId)}`
    : `/api/knowledge/categories/${encodeURIComponent(categoryId)}/items`;
  await apiJson(path, {method: editor.itemId ? "PUT" : "POST", body: JSON.stringify(item)});
  state.productScopedEditor = null;
  await Promise.all([loadProductDetail(product.id), loadOverview().catch(() => {})]);
}

async function deleteProductScopedInlineItem() {
  const editor = state.productScopedEditor;
  const product = state.selectedProduct;
  if (!editor?.categoryId || !editor.itemId || !product?.id) return;
  if (!confirm("确认归档这条商品专属知识吗？")) return;
  await apiJson(`/api/knowledge/categories/${encodeURIComponent(editor.categoryId)}/items/${encodeURIComponent(editor.itemId)}`, {method: "DELETE"});
  state.productScopedEditor = null;
  await Promise.all([loadProductDetail(product.id), loadOverview().catch(() => {})]);
}

function productScopedCategoryTitle(categoryId) {
  return {
    product_faq: "商品专属问答",
    product_rules: "商品专属规则",
    product_explanations: "商品专属解释",
  }[categoryId] || categoryId || "商品专属知识";
}

function productScopedBodyField(categoryId) {
  return categoryId === "product_explanations" ? "content" : "answer";
}

function clientSafeId(value, fallback) {
  const normalized = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_.-]+/g, "_")
    .replace(/^[_ .-]+|[_ .-]+$/g, "")
    .slice(0, 96);
  return normalized || fallback;
}

function formatProductPrice(display) {
  if (!display || display.price === undefined || display.price === null || display.price === "") return "未填写价格";
  return `${display.price}${display.unit ? ` / ${display.unit}` : ""}`;
}

async function adjustProductInventory(operation, quantity) {
  if (!state.selectedProduct?.id) return;
  const payload = await apiJson(`/api/product-console/products/${encodeURIComponent(state.selectedProduct.id)}/inventory`, {
    method: "POST",
    body: JSON.stringify({operation, quantity}),
  });
  state.selectedProduct = payload.item || state.selectedProduct;
  await Promise.all([loadProductCatalog({loadDetail: false}), loadOverview().catch(() => {})]);
  await loadProductDetail(state.selectedProduct.id);
}

async function runProductCommand() {
  const input = document.getElementById("product-command-input");
  const message = (input?.value || "").trim();
  if (!message) return;
  const payload = await apiJson("/api/product-console/command", {
    method: "POST",
    body: JSON.stringify({message, use_llm: true}),
  });
  if (payload.action === "draft_product" && payload.session) {
    state.generatorSession = payload.session;
    state.generatorMessages = payload.session.history || [];
    state.activeIntakeTab = "generator";
    selectView("generator");
    renderGenerator();
    return;
  }
  if (input) input.value = "";
  await Promise.all([loadProductCatalog({loadDetail: false}), loadOverview().catch(() => {})]);
  if (payload.item?.id) await loadProductDetail(payload.item.id);
  else if (state.selectedProduct?.id) await loadProductDetail(state.selectedProduct.id);
}

function openNewProductGenerator() {
  state.activeIntakeTab = "generator";
  selectView("generator");
  const select = document.getElementById("generator-category");
  if (select) select.value = "products";
  document.getElementById("generator-input")?.focus();
}

function openSelectedProductInFormalKnowledge() {
  if (!state.selectedProduct?.id) return;
  state.activeCategoryId = "products";
  selectView("knowledge");
  loadKnowledge().then(() => {
    state.selectedKnowledge = state.categoryItems.find((item) => item.id === state.selectedProduct.id) || state.selectedKnowledge;
    state.knowledgeMode = "view";
    renderKnowledgeList();
    renderKnowledgeDetail();
  }).catch((error) => alert(error.message));
}

function openProductScopedKnowledge(categoryId, itemId, productId) {
  if (!categoryId || !itemId) return;
  state.productScopedEditContext = {
    categoryId,
    itemId,
    productId: productId || state.selectedProduct?.id || "",
    productName: state.selectedProduct?.display?.name || state.selectedProduct?.data?.name || productId || "",
  };
  state.activeCategoryId = categoryId;
  selectView("knowledge", {keepKnowledgeContext: true});
  loadKnowledge().then(() => {
    state.selectedKnowledge = state.categoryItems.find((item) => item.id === itemId) || state.categoryItems[0] || null;
    state.knowledgeMode = "view";
    renderKnowledgeList();
    renderKnowledgeDetail();
  }).catch((error) => alert(error.message));
}

function updateKnowledgeButtons() {
  const editing = state.knowledgeMode !== "view";
  setHidden("save-knowledge-item", !editing);
  setHidden("cancel-knowledge-edit", !editing);
  setHidden("edit-knowledge-item", editing || !state.selectedKnowledge?.id);
  setHidden("archive-knowledge-item", editing || !state.selectedKnowledge?.id);
}

function knowledgeReadonlyHtml(category, item) {
  const rows = buildReadonlyRows(category, item);
  const runtime = item.runtime || {};
  const reviewState = item.review_state || {};
  const contextBadges = knowledgeScopeBadges(category, item);
  const highlighted = diagnosticTargetMatches(category?.id, item.id) ? " diagnostic-highlight" : "";
  return `
    <div class="read-head${highlighted}">
      <div>
        <p class="eyebrow">${escapeHtml(category.name || category.id)}</p>
        <h2>${escapeHtml(primaryTitle(category, item))}</h2>
        ${badgeListHtml([...(item.display_badges || []), ...contextBadges])}
      </div>
      <div class="read-actions">
        ${reviewState.is_new ? `<button class="secondary-button knowledge-acknowledge" type="button">已阅</button>` : ""}
        <span class="status-chip ${item.status === "archived" ? "warning" : "ok"}">${item.status === "archived" ? "已归档" : "启用中"}</span>
      </div>
    </div>
    ${knowledgeContextNoticeHtml(category, item)}
    <div class="summary-table">
      <div><span>知识 ID</span><strong>${escapeHtml(item.id)}</strong></div>
      <div><span>自动回复</span><strong>${runtime.allow_auto_reply !== false ? "允许" : "关闭"}</strong></div>
      <div><span>转人工</span><strong>${runtime.requires_handoff ? "需要" : "不需要"}</strong></div>
      <div><span>风险等级</span><strong>${escapeHtml(runtime.risk_level || "normal")}</strong></div>
    </div>
    <div class="read-grid">
      ${rows.join("")}
    </div>
  `;
}

function buildReadonlyRows(category, item) {
  const data = item.data || {};
  return (category.schema?.fields || [])
    .filter((field) => !isEmpty(data[field.id]))
    .map((field) => readFieldHtml(field, data[field.id]));
}

function readFieldHtml(field, value) {
  const wide = field.type === "long_text" || field.type === "object" || field.type === "table" || field.type === "tags";
  return `
    <div class="read-field ${wide ? "wide-field" : ""}">
      <span>${escapeHtml(fieldLabel(field))}</span>
      ${fieldValueHtml(field, value)}
    </div>
  `;
}

function fieldValueHtml(field, value) {
  if (field.type === "boolean") {
    return `<p>${value ? "是" : "否"}</p>`;
  }
  if (field.type === "single_select") {
    return `<p>${escapeHtml(optionLabel(field.id, value))}</p>`;
  }
  if (field.type === "tags") {
    return `<div class="chip-list">${(Array.isArray(value) ? value : splitTags(value)).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>`;
  }
  if (field.type === "table") {
    const columns = field.columns || [];
    return `
      <div class="display-table">
        <div class="display-table-head">${columns.map((column) => `<strong>${escapeHtml(column.label || column.id)}</strong>`).join("")}</div>
        ${(Array.isArray(value) ? value : []).map((row) => `
          <div class="display-table-row">${columns.map((column) => `<span>${escapeHtml(row?.[column.id] ?? "")}</span>`).join("")}</div>
        `).join("")}
      </div>
    `;
  }
  if (field.type === "object") {
    return objectValueHtml(value);
  }
  return `<p>${escapeHtml(value)}</p>`;
}

function objectValueHtml(value) {
  const entries = Object.entries(value || {});
  if (!entries.length) return `<p>无</p>`;
  return `
    <div class="variable-table">
      <div class="variable-table-head"><strong>变量名</strong><strong>对应内容</strong></div>
      ${entries.map(([key, inner]) => `
        <div class="variable-table-row">
          <code>${escapeHtml(templateLabels[key] || key)}</code>
          <span>${escapeHtml(displayBusinessValue(inner))}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function primaryTitle(category, item) {
  const titleField = category?.schema?.item_title_field || "title";
  return item.data?.[titleField] || item.id || "未命名知识";
}

function knowledgeFormHtml(category, item) {
  const fields = category.schema?.fields || [];
  const runtime = item.runtime || {};
  const readonlyFields = isProductScopedCategory(category) ? new Set(["product_id"]) : new Set();
  return `
    ${knowledgeContextNoticeHtml(category, item, {editing: true})}
    <div class="form-summary">
      <label class="form-field">
        <span>知识 ID</span>
        <input id="field-id" value="${escapeHtml(item.id || "")}" ${item.id && state.knowledgeMode !== "new" ? "readonly" : ""} />
      </label>
      <label class="form-field">
        <span>状态</span>
        <select id="field-status">
          <option value="active" ${item.status !== "archived" ? "selected" : ""}>启用</option>
          <option value="archived" ${item.status === "archived" ? "selected" : ""}>归档</option>
        </select>
      </label>
      <label class="checkbox-line"><input id="runtime-auto" type="checkbox" ${runtime.allow_auto_reply !== false ? "checked" : ""} /> 允许自动回复</label>
      <label class="checkbox-line"><input id="runtime-handoff" type="checkbox" ${runtime.requires_handoff ? "checked" : ""} /> 必须转人工</label>
    </div>
    <div class="form-grid" id="knowledge-form" data-category="${escapeHtml(category.id)}">
      ${fields.map((field) => fieldHtml(field, item.data?.[field.id], {readonlyFields, categoryId: category.id, productName: knowledgeProductName(item)})).join("")}
    </div>
  `;
}

function fieldHtml(field, value, renderOptions = {}) {
  const id = `data-${field.id}`;
  const label = `${fieldLabel(field)}${field.required ? " *" : ""}`;
  const readonly = renderOptions.readonlyFields?.has?.(field.id);
  if (field.id === "product_id") {
    return productIdSelectHtml(field, value, renderOptions);
  }
  if (field.id === "product_category") {
    return productCategorySelectHtml(field, value, renderOptions);
  }
  if (field.type === "boolean") {
    return `<label class="checkbox-line" data-field="${escapeHtml(field.id)}"><input id="${escapeHtml(id)}" type="checkbox" ${value ? "checked" : ""} ${readonly ? "disabled" : ""} /> ${escapeHtml(label)}</label>`;
  }
  if (field.type === "single_select") {
    const choices = field.options || [];
    return `
      <label class="form-field" data-field="${escapeHtml(field.id)}" data-kind="single_select">
        <span>${escapeHtml(label)}</span>
        <select id="${escapeHtml(id)}" ${readonly ? "disabled" : ""}>${choices.map((option) => `<option value="${escapeHtml(option)}" ${option === value ? "selected" : ""}>${escapeHtml(optionLabel(field.id, option))}</option>`).join("")}</select>
      </label>
    `;
  }
  if (field.type === "tags") {
    return `
      <label class="form-field wide-field" data-field="${escapeHtml(field.id)}" data-kind="tags">
        <span>${escapeHtml(label)}</span>
        <textarea id="${escapeHtml(id)}" placeholder="可用逗号、顿号或换行分隔" ${readonly ? "readonly" : ""}>${escapeHtml(displayTags(value))}</textarea>
      </label>
    `;
  }
  if (field.type === "table") {
    return tableFieldHtml(field, Array.isArray(value) ? value : []);
  }
  if (field.type === "object") {
    return objectFieldHtml(field, value && typeof value === "object" && !Array.isArray(value) ? value : {}, renderOptions);
  }
  if (field.type === "long_text") {
    return `
      <label class="form-field wide-field" data-field="${escapeHtml(field.id)}" data-kind="long_text">
        <span>${escapeHtml(label)}</span>
        <textarea id="${escapeHtml(id)}" ${readonly ? "readonly" : ""}>${escapeHtml(value || "")}</textarea>
      </label>
    `;
  }
  return `
    <label class="form-field" data-field="${escapeHtml(field.id)}" data-kind="${escapeHtml(field.type || "short_text")}">
      <span>${escapeHtml(label)}</span>
      <input id="${escapeHtml(id)}" value="${escapeHtml(value ?? "")}" ${readonly ? "readonly" : ""} />
    </label>
  `;
}

function tableFieldHtml(field, rows) {
  const columns = field.columns || [
    {id: "name", label: "名称", type: "short_text"},
    {id: "value", label: "内容", type: "short_text"},
  ];
  const safeRows = rows.length ? rows : field.id === "price_tiers" ? [{min_quantity: "", unit_price: ""}] : [{}];
  return `
    <div class="form-field wide-field table-editor" data-field="${escapeHtml(field.id)}" data-kind="table">
      <span>${escapeHtml(fieldLabel(field))}${field.required ? " *" : ""}</span>
      <div class="mini-table" data-columns="${escapeHtml(columns.map((column) => column.id).join(","))}">
        <div class="mini-table-head">${columns.map((column) => `<strong>${escapeHtml(column.label || column.id)}</strong>`).join("")}<strong></strong></div>
        <div class="mini-table-body">
          ${safeRows.map((row) => tableRowHtml(columns, row)).join("")}
        </div>
      </div>
      <button class="secondary-button mini-add" type="button">${field.id === "price_tiers" ? "新增价格档" : "新增一行"}</button>
    </div>
  `;
}

function tableRowHtml(columns, row) {
  return `
    <div class="mini-table-row">
      ${columns.map((column) => `<input data-column="${escapeHtml(column.id)}" data-type="${escapeHtml(column.type || "short_text")}" value="${escapeHtml(row?.[column.id] ?? "")}" />`).join("")}
      <button class="secondary-button mini-remove" type="button">删除</button>
    </div>
  `;
}

function objectFieldHtml(field, value, options = {}) {
  if (field.id === "reply_templates") {
    const keys = Array.from(new Set([...Object.keys(templateLabels), ...Object.keys(value)]));
    return `
      <div class="form-field wide-field reply-template-editor" data-field="${escapeHtml(field.id)}" data-kind="object">
        <span>${escapeHtml(fieldLabel(field))}</span>
        <div class="object-guide">这些是「${escapeHtml(options.productName || "当前商品")}」的可选客服回复模板。留空表示使用通用话术或 AI 经验，不会影响商品基础资料。</div>
        ${keys.map((key) => `
          <label class="nested-field">
            <span>${escapeHtml(templateLabels[key] || key)}</span>
            <textarea data-template-key="${escapeHtml(key)}">${escapeHtml(value[key] || "")}</textarea>
          </label>
        `).join("")}
      </div>
    `;
  }
  const entries = Object.entries(value);
  const rows = entries.length ? entries : [["", ""]];
  return `
    <div class="form-field wide-field object-editor" data-field="${escapeHtml(field.id)}" data-kind="object">
      <span>${escapeHtml(fieldLabel(field))}</span>
      <div class="object-guide">左侧变量名用于系统识别，已有变量不可改；右侧填写给客户看的内容。</div>
      <div class="object-rows">
        ${rows.map(([key, val]) => objectRowHtml(key, val, Boolean(key))).join("")}
      </div>
      <button class="secondary-button object-add" type="button">新增字段</button>
    </div>
  `;
}

function objectRowHtml(key, value, locked = false) {
  return `
    <div class="object-row">
      <input data-object-key value="${escapeHtml(key)}" placeholder="变量名" ${locked ? "readonly" : ""} />
      <input data-object-value value="${escapeHtml(value)}" placeholder="内容" />
      ${locked ? `<span class="lock-note">固定</span>` : `<button class="secondary-button object-remove" type="button">删除</button>`}
    </div>
  `;
}

function bindDynamicEditors(root) {
  root.querySelectorAll(".mini-add").forEach((button) => {
    button.addEventListener("click", () => {
      const editor = button.closest(".table-editor");
      const columns = (editor.querySelector(".mini-table").dataset.columns || "").split(",").filter(Boolean)
        .map((id) => ({id, label: id, type: id.includes("price") ? "money" : "number"}));
      editor.querySelector(".mini-table-body").insertAdjacentHTML("beforeend", tableRowHtml(columns, {}));
      bindDynamicEditors(editor);
    });
  });
  root.querySelectorAll(".mini-remove").forEach((button) => {
    button.onclick = () => button.closest(".mini-table-row").remove();
  });
  root.querySelectorAll(".object-add").forEach((button) => {
    button.onclick = () => {
      button.closest(".object-editor").querySelector(".object-rows").insertAdjacentHTML("beforeend", objectRowHtml("", ""));
      bindDynamicEditors(button.closest(".object-editor"));
    };
  });
  root.querySelectorAll(".object-remove").forEach((button) => {
    button.onclick = () => button.closest(".object-row").remove();
  });
}

function collectKnowledgeForm() {
  const category = activeCategory();
  if (!category) throw new Error("没有选中门类");
  const existing = state.selectedKnowledge || {data: {}, runtime: {}};
  const data = {};
  for (const field of category.schema?.fields || []) {
    data[field.id] = collectFieldValue(field);
  }
  validateClientKnowledge(category, data);
  return {
    ...existing,
    id: document.getElementById("field-id").value.trim(),
    category_id: category.id,
    status: document.getElementById("field-status").value,
    data,
    runtime: {
      allow_auto_reply: document.getElementById("runtime-auto").checked,
      requires_handoff: document.getElementById("runtime-handoff").checked,
      risk_level: document.getElementById("runtime-handoff").checked ? "high" : existing.runtime?.risk_level || "normal",
    },
  };
}

function collectFieldValue(field, root = document) {
  const scope = root || document;
  const wrapper = scope.querySelector(`[data-field="${cssEscape(field.id)}"]`);
  const element = wrapper?.querySelector(`#${cssEscape(`data-${field.id}`)}`) || scope.querySelector(`#${cssEscape(`data-${field.id}`)}`);
  if (field.type === "boolean") return Boolean(element?.checked);
  if (field.type === "number" || field.type === "money") return numberOrNull(element?.value);
  if (field.type === "tags") return splitTags(element?.value || "");
  if (field.type === "table") return collectTableValue(wrapper);
  if (field.type === "object") return collectObjectValue(wrapper);
  return (element?.value || "").trim();
}

function collectTableValue(wrapper) {
  if (!wrapper) return [];
  return Array.from(wrapper.querySelectorAll(".mini-table-row"))
    .map((row) => {
      const item = {};
      row.querySelectorAll("[data-column]").forEach((input) => {
        const type = input.dataset.type || "short_text";
        item[input.dataset.column] = type === "number" || type === "money" ? numberOrNull(input.value) : input.value.trim();
      });
      return item;
    })
    .filter((row) => Object.values(row).some((value) => value !== "" && value !== null));
}

function collectObjectValue(wrapper) {
  if (!wrapper) return {};
  if (wrapper.classList.contains("reply-template-editor")) {
    const item = {};
    wrapper.querySelectorAll("[data-template-key]").forEach((input) => {
      const value = input.value.trim();
      if (value) item[input.dataset.templateKey] = value;
    });
    return item;
  }
  const item = {};
  wrapper.querySelectorAll(".object-row").forEach((row) => {
    const key = row.querySelector("[data-object-key]").value.trim();
    const value = row.querySelector("[data-object-value]").value.trim();
    if (key && value) item[key] = value;
  });
  return item;
}

function validateClientKnowledge(category, data) {
  for (const field of category.schema?.fields || []) {
    if (field.required && isEmpty(data[field.id])) throw new Error(`${fieldLabel(field)} 不能为空`);
  }
  if (Array.isArray(data.price_tiers)) {
    let previousQuantity = 0;
    let previousPrice = Infinity;
    data.price_tiers.forEach((row, index) => {
      const quantity = Number(row.min_quantity);
      const price = Number(row.unit_price);
      if (!Number.isFinite(quantity) || !Number.isFinite(price)) throw new Error(`第 ${index + 1} 档阶梯价格缺少数量或价格`);
      if (quantity <= previousQuantity) throw new Error(`第 ${index + 1} 档数量必须高于上一档`);
      if (price >= previousPrice) throw new Error(`第 ${index + 1} 档价格必须低于上一档`);
      previousQuantity = quantity;
      previousPrice = price;
    });
  }
}

async function saveKnowledgeItem() {
  const item = collectKnowledgeForm();
  if (!item.id) throw new Error("知识 ID 不能为空");
  const exists = state.knowledgeMode !== "new" && Boolean(state.selectedKnowledge?.id);
  const categoryId = encodeURIComponent(state.activeCategoryId);
  const path = exists
    ? `/api/knowledge/categories/${categoryId}/items/${encodeURIComponent(item.id)}`
    : `/api/knowledge/categories/${categoryId}/items`;
  await apiJson(path, {method: exists ? "PUT" : "POST", body: JSON.stringify(item)});
  state.knowledgeMode = "view";
  await Promise.all([loadKnowledge(), loadOverview(), refreshProductCatalogIfNeeded(item.category_id).catch(() => {})]);
}

function newKnowledgeItem() {
  const category = activeCategory();
  if (!category) return;
  const data = {};
  for (const field of category.schema?.fields || []) {
    data[field.id] = defaultFieldValue(field);
  }
  state.selectedKnowledge = {
    schema_version: 1,
    category_id: category.id,
    id: "",
    status: "active",
    source: {type: "admin_form"},
    data,
    runtime: {allow_auto_reply: true, requires_handoff: false, risk_level: "normal"},
  };
  state.knowledgeMode = "new";
  renderKnowledgeDetail();
}

function editKnowledgeItem() {
  if (!state.selectedKnowledge) return;
  state.knowledgeMode = "edit";
  renderKnowledgeDetail();
}

function cancelKnowledgeEdit() {
  state.knowledgeMode = "view";
  renderKnowledgeDetail();
}

async function archiveKnowledgeItem() {
  if (!state.selectedKnowledge?.id) return;
  if (!confirm("确认归档这条知识吗？")) return;
  const categoryId = state.activeCategoryId;
  await apiJson(`/api/knowledge/categories/${encodeURIComponent(state.activeCategoryId)}/items/${encodeURIComponent(state.selectedKnowledge.id)}`, {method: "DELETE"});
  await Promise.all([loadKnowledge(), loadOverview(), refreshProductCatalogIfNeeded(categoryId).catch(() => {})]);
}

async function refreshProductCatalogIfNeeded(categoryId) {
  if (categoryId === "products" || isProductScopedCategory(categoryId)) {
    await loadProductCatalog({loadDetail: false});
  }
}

async function createCustomCategory() {
  const id = prompt("门类 ID：小写英文、数字、下划线或连字符");
  if (!id) return;
  const name = prompt("门类名称", id) || id;
  const customFields = prompt("自定义字段，可用逗号分隔；留空则使用“标题/内容”模板", "");
  await apiJson("/api/knowledge/categories", {
    method: "POST",
    body: JSON.stringify({
      id,
      name,
      description: "用户自定义知识门类",
      participates_in_reply: true,
      fields: buildCustomCategoryFields(customFields || ""),
    }),
  });
  state.activeCategoryId = id;
  await loadKnowledge();
}

function buildCustomCategoryFields(text) {
  const labels = splitTags(text).slice(0, 12);
  if (!labels.length) return undefined;
  const fields = [
    {id: "title", label: "标题", type: "short_text", required: true, searchable: true, form_order: 10},
  ];
  labels.forEach((label, index) => {
    const id = safeFieldId(label, `field_${index + 1}`);
    if (id === "title" || fields.some((field) => field.id === id)) return;
    fields.push({id, label, type: "long_text", required: false, searchable: true, form_order: 20 + index * 10});
  });
  if (fields.length === 1) {
    fields.push({id: "content", label: "内容", type: "long_text", required: false, searchable: true, form_order: 20});
  }
  return fields;
}

function safeFieldId(label, fallback) {
  const ascii = String(label || "").toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  return /^[a-z][a-z0-9_]{0,40}$/.test(ascii) ? ascii : fallback;
}

async function sendGeneratorMessage() {
  const input = document.getElementById("generator-input");
  const message = input.value.trim();
  if (!message) return;
  state.generatorMessages.push({role: "user", content: message});
  renderGenerator();
  const preferred = document.getElementById("generator-category").value;
  const payload = state.generatorSession
    ? await apiJson(`/api/generator/sessions/${encodeURIComponent(state.generatorSession.session_id)}/messages`, {method: "POST", body: JSON.stringify({message})})
    : await apiJson("/api/generator/sessions", {method: "POST", body: JSON.stringify({message, preferred_category_id: preferred})});
  state.generatorSession = payload.session;
  state.generatorMessages.push({role: "assistant", content: generatorReplyText(payload.session)});
  input.value = "";
  renderGenerator();
}

function generatorReplyText(session) {
  if (!session) return "";
  if (session.status === "ready") return "信息已整理完整，可以确认保存。";
  if (session.status === "saved") return "已经保存到正式知识库。";
  return session.question || "还需要继续补充关键信息。";
}

function renderGenerator() {
  const chat = document.getElementById("generator-chat");
  chat.innerHTML = state.generatorMessages.length
    ? state.generatorMessages.map((msg) => `<div class="chat-bubble ${msg.role}">${escapeHtml(msg.content)}</div>`).join("")
    : `<div class="empty-state">输入一段自然语言，系统会自动整理成可入库的知识。</div>`;
  const summary = document.getElementById("generator-summary");
  const session = state.generatorSession;
  if (!session) {
    summary.innerHTML = "";
    document.getElementById("confirm-generator").disabled = true;
    return;
  }
  const warnings = session.warnings || [];
  summary.innerHTML = `
    <div class="status-card ${session.status === "ready" ? "ok" : "warning"}">
      <strong>${escapeHtml(session.category_name || session.category_id || "待判断")}</strong>
      <span>${escapeHtml(session.provider || "local")} · ${escapeHtml(session.status)}</span>
    </div>
    ${warnings.length ? `<div class="warning-list">${warnings.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    <div class="summary-table generator-table">
      ${(session.summary_rows || []).map((row) => `<div><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(row.value)}</strong></div>`).join("")}
    </div>
    ${generatorDraftEditorHtml(session)}
  `;
  bindDynamicEditors(summary);
  summary.querySelector("#save-generator-draft")?.addEventListener("click", () => updateGeneratorDraft().catch((error) => alert(error.message)));
  document.getElementById("confirm-generator").disabled = session.status !== "ready";
}

function generatorDraftEditorHtml(session) {
  const category = categoryById(session.category_id);
  const item = session.draft_item || {};
  if (!category || !item.data || session.status === "saved") return "";
  const fields = category.schema?.fields || [];
  return `
    <div class="generator-editor">
      <div class="editor-head">
        <div>
          <strong>可编辑草稿</strong>
          <span>不满意的话术或字段可以先改，保存后系统会重新校验。</span>
        </div>
      </div>
      <div class="form-grid generator-draft-form" id="generator-draft-form" data-category="${escapeHtml(category.id)}">
        ${fields.map((field) => fieldHtml(field, item.data?.[field.id])).join("")}
      </div>
      <button class="secondary-button" id="save-generator-draft" type="button">保存修改并重新校验</button>
    </div>
  `;
}

function resetGenerator() {
  state.generatorSession = null;
  state.generatorMessages = [];
  document.getElementById("generator-input").value = "";
  renderGenerator();
}

async function updateGeneratorDraft() {
  const session = state.generatorSession;
  if (!session?.session_id) return;
  const category = categoryById(session.category_id);
  const form = document.getElementById("generator-draft-form");
  if (!category || !form) throw new Error("没有可编辑的知识草稿");
  const data = {};
  for (const field of category.schema?.fields || []) {
    data[field.id] = collectFieldValue(field, form);
  }
  validateClientKnowledge(category, data);
  const payload = await apiJson(`/api/generator/sessions/${encodeURIComponent(session.session_id)}/draft`, {
    method: "PATCH",
    body: JSON.stringify({data}),
  });
  state.generatorSession = payload.session;
  state.generatorMessages.push({role: "assistant", content: generatorReplyText(payload.session)});
  renderGenerator();
}

async function confirmGenerator() {
  if (!state.generatorSession?.session_id) return;
  if (!confirm("确认保存这条知识到正式知识库吗？")) return;
  const payload = await apiJson(`/api/generator/sessions/${encodeURIComponent(state.generatorSession.session_id)}/confirm`, {method: "POST"});
  state.generatorSession = payload.session;
  state.generatorMessages.push({role: "assistant", content: "已保存到正式知识库。"});
  renderGenerator();
  await Promise.all([loadOverview(), loadKnowledge()]);
}

async function uploadSelectedFile() {
  if (state.uploadInProgress) return;
  const fileInput = document.getElementById("upload-file");
  const files = Array.from(fileInput.files || []);
  if (!files.length) {
    return;
  }
  setUploadBusy(true, files.length);
  const form = new FormData();
  form.append("kind", document.getElementById("upload-kind").value);
  files.forEach((file) => form.append("files", file));
  try {
    const response = await fetch("/api/uploads/batch", {method: "POST", body: form});
    if (!response.ok) throw new Error(await responseErrorMessage(response, "/api/uploads/batch"));
    const payload = await response.json();
    const failures = (payload.results || []).filter((item) => !item.ok);
    fileInput.value = "";
    await loadUploads();
    if (failures.length) {
      alert(`有 ${failures.length} 个文件上传失败：\n${failures.map((item) => `${item.filename || "未命名文件"}：${item.message || "未知错误"}`).join("\n")}`);
    }
  } catch (error) {
    document.getElementById("upload-list").innerHTML = `<div class="status-card error"><strong>上传失败</strong><span>${escapeHtml(error.message || "请稍后重试")}</span></div>`;
    throw error;
  } finally {
    setUploadBusy(false);
  }
}

async function loadUploads() {
  const payload = await apiGet("/api/uploads");
  const list = document.getElementById("upload-list");
  list.innerHTML = (payload.items || [])
    .map((item) => `
      <div class="record-row upload-row">
        <div>
          <strong>${escapeHtml(item.filename)}</strong>
          <span>${escapeHtml(item.kind)} · ${item.learned ? "已学习" : "未学习"} · ${formatBytes(item.size || 0)}</span>
        </div>
        <button class="secondary-button danger-button upload-delete" data-upload-id="${escapeHtml(item.upload_id)}" data-filename="${escapeHtml(item.filename)}">删除</button>
      </div>
    `)
    .join("") || `<div class="empty-state">暂无上传</div>`;
  list.querySelectorAll(".upload-delete").forEach((button) => {
    button.addEventListener("click", () => deleteUpload(button.dataset.uploadId, button.dataset.filename).catch((error) => alert(error.message)));
  });
}

function setUploadBusy(isBusy, fileCount = 0) {
  state.uploadInProgress = isBusy;
  const fileInput = document.getElementById("upload-file");
  const kindSelect = document.getElementById("upload-kind");
  if (fileInput) fileInput.disabled = isBusy;
  if (kindSelect) kindSelect.disabled = isBusy;
  if (isBusy) {
    document.getElementById("upload-list").innerHTML = `
      <div class="status-card loading">
        <strong><span class="loading-spinner" aria-hidden="true"></span>正在上传</strong>
        <span>已选择 ${fileCount} 个文件，上传完成后会自动出现在下方列表。</span>
      </div>
    `;
  }
}

async function deleteUpload(uploadId, filename) {
  if (!uploadId) return;
  const label = filename || uploadId;
  if (!confirm(`确认删除上传资料「${label}」？\n\n这会删除原始上传文件和上传记录；如果它已经生成候选，候选审核记录不会被自动删除。`)) return;
  await apiJson(`/api/uploads/${encodeURIComponent(uploadId)}`, {method: "DELETE"});
  await loadUploads();
}

async function loadRagStatus() {
  const [payload, analytics] = await Promise.all([
    apiGet("/api/rag/status"),
    apiGet("/api/rag/analytics").catch(() => null),
  ]);
  state.ragStatus = payload;
  state.ragAnalytics = analytics;
  renderRagStatus();
  renderRagAnalytics();
}

function renderRagStatus() {
  const status = state.ragStatus || {};
  const experienceCounts = status.experience_counts || {};
  document.getElementById("rag-status-cards").innerHTML = [
    ["资料源", status.source_count ?? 0],
    ["切片", status.chunk_count ?? 0],
    ["索引", status.index_exists ? "正常" : "未建立"],
    ["对话经验", experienceCounts.active ?? 0],
  ]
    .map(([label, value]) => `<div class="metric-card"><span>${escapeHtml(value)}</span><label>${escapeHtml(label)}</label></div>`)
    .join("");
}

function renderRagAnalytics() {
  const panel = document.getElementById("rag-analytics");
  if (!panel) return;
  const analytics = state.ragAnalytics;
  if (!analytics?.ok) {
    panel.innerHTML = `<div class="empty-state">暂无运营分析数据。</div>`;
    return;
  }
  const audit = analytics.audit || {};
  const counters = audit.counters || {};
  const formalization = analytics.formalization_candidates || [];
  panel.innerHTML = `
    <div class="record-row">
      <strong>运营概览</strong>
      <span>参考资料应答 ${escapeHtml(counters.rag_reply_applied ?? 0)} 次 · 命中证据 ${escapeHtml(counters.rag_evidence_hit ?? 0)} 次 · 记录经验 ${escapeHtml(counters.rag_experience_recorded ?? 0)} 条</span>
      <p>建议转正式知识：${escapeHtml(formalization.length)} 条。参考资料只作为辅助证据，正式规则需走“知识录入与学习”。</p>
    </div>
  `;
}

async function rebuildRag() {
  const payload = await apiJson("/api/rag/rebuild", {method: "POST", body: JSON.stringify({})});
  await loadRagStatus();
  document.getElementById("rag-results").innerHTML = `<div class="status-card ok"><strong>索引已重建</strong><span>当前索引片段数：${escapeHtml(payload.entry_count ?? 0)}</span></div>`;
}

async function searchRag() {
  const query = document.getElementById("rag-query").value.trim();
  if (!query) {
    document.getElementById("rag-results").innerHTML = `<div class="empty-state">请输入要检索的问题。</div>`;
    return;
  }
  const payload = await apiJson("/api/rag/search", {
    method: "POST",
    body: JSON.stringify({
      query,
      product_id: document.getElementById("rag-product-id").value.trim(),
      limit: 8,
    }),
  });
  state.ragHits = payload.hits || [];
  renderRagResults(payload);
}

function renderRagResults(payload) {
  const hits = payload.hits || [];
  document.getElementById("rag-results").innerHTML = hits.length
    ? hits.map((hit) => `
        <div class="record-row rag-hit">
          <div>
            <strong>${escapeHtml(hit.category || hit.source_type || "资料片段")} · ${escapeHtml(hit.score)}</strong>
            <span>${escapeHtml(hit.product_id || "未指定商品")} · ${escapeHtml(hit.chunk_id || "")}</span>
            <p>${escapeHtml(hit.text || "")}</p>
          </div>
        </div>
      `).join("")
    : `<div class="empty-state">没有检索到相关资料片段。</div>`;
}

async function loadRagStatus() {
  const [payload, analytics, sources] = await Promise.all([
    apiGet("/api/rag/status"),
    apiGet("/api/rag/analytics").catch(() => null),
    apiGet("/api/rag/sources?limit=80").catch(() => ({ok: false, sources: [], chunks: []})),
  ]);
  state.ragStatus = payload;
  state.ragAnalytics = analytics;
  state.ragSources = sources.sources || [];
  state.ragChunks = sources.chunks || [];
  renderRagStatus();
  renderRagAnalytics();
  renderRagSources(sources);
}

function renderRagStatus() {
  const status = state.ragStatus || {};
  const experienceCounts = status.experience_counts || {};
  document.getElementById("rag-status-cards").innerHTML = [
    ["资料源", status.source_count ?? 0],
    ["切片", status.chunk_count ?? 0],
    ["索引", status.index_exists ? "正常" : "未建立"],
    ["对话经验", experienceCounts.active ?? 0],
  ]
    .map(([label, value]) => `<div class="metric-card"><span>${escapeHtml(value)}</span><label>${escapeHtml(label)}</label></div>`)
    .join("");
}

function renderRagAnalytics() {
  const panel = document.getElementById("rag-analytics");
  if (!panel) return;
  const analytics = state.ragAnalytics;
  if (!analytics?.ok) {
    panel.innerHTML = `<div class="empty-state">暂无运营分析数据。</div>`;
    return;
  }
  const audit = analytics.audit || {};
  const counters = audit.counters || {};
  const formalization = analytics.formalization_candidates || [];
  panel.innerHTML = `
    <div class="record-row reference-summary">
      <div>
        <strong>运营概览</strong>
        <span>参考资料应答 ${escapeHtml(counters.rag_reply_applied ?? 0)} 次 · 命中证据 ${escapeHtml(counters.rag_evidence_hit ?? 0)} 次 · 记录经验 ${escapeHtml(counters.rag_experience_recorded ?? 0)} 条</span>
        <p>建议转正式知识：${escapeHtml(formalization.length)} 条。参考资料和对话经验只做辅助，正式规则仍走“待确认知识”。</p>
      </div>
    </div>
  `;
}

function renderRagSources(payload = {}) {
  const sources = payload.sources || state.ragSources || [];
  const chunks = payload.chunks || state.ragChunks || [];
  const sourcePanel = document.getElementById("rag-source-list");
  const chunkPanel = document.getElementById("rag-chunk-list");
  if (sourcePanel) {
    sourcePanel.innerHTML = sources.length
      ? `
        <div class="section-mini-title">已导入资料源</div>
        ${sources.map((source) => `
          <div class="record-row rag-source-row">
            <div>
              <strong>${escapeHtml(sourceLabel(source))}</strong>
              <span>${escapeHtml(source.category || "未分类")} · ${escapeHtml(source.product_id || "未指定商品")} · ${escapeHtml(source.chunk_count ?? 0)} 个切片</span>
              <p>${escapeHtml(shortPath(source.source_path || ""))}</p>
            </div>
          </div>
        `).join("")}
      `
      : `<div class="empty-state">暂无已导入的参考资料。上传资料并 AI 整理后，这里会显示资料源和切片概况。</div>`;
  }
  if (chunkPanel) {
    chunkPanel.innerHTML = chunks.length
      ? `
        <div class="section-mini-title">资料切片预览</div>
        ${chunks.slice(0, 12).map((chunk) => `
          <details class="record-row rag-chunk-row">
            <summary>${escapeHtml(chunk.category || chunk.source_type || "资料片段")} · ${escapeHtml(chunk.chunk_id || "")}</summary>
            <p>${escapeHtml(chunk.text || "")}</p>
          </details>
        `).join("")}
      `
      : `<div class="empty-state">暂无资料切片。点击“重建索引”可重新生成。</div>`;
  }
}

async function loadRagExperiences() {
  const payload = await apiGet("/api/rag/experiences?status=active&limit=200");
  state.ragExperiences = payload.items || [];
  updateRagExperienceCountBadge(unreviewedRagExperienceCount(state.ragExperiences));
  renderRagExperiences(payload);
  ensureRagExperienceInterpretations(state.ragExperiences).catch((error) => console.warn("rag experience interpretation failed", error));
}

async function refreshRagExperienceBadge() {
  const payload = await apiGet("/api/rag/experiences?status=active&limit=200");
  state.ragExperiences = payload.items || [];
  updateRagExperienceCountBadge(unreviewedRagExperienceCount(state.ragExperiences));
}

function interpretationNeedsRefresh(item) {
  const ai = item?.ai_interpretation || {};
  return !ai.meaning || !ai.version || !ai.source_fingerprint;
}

async function ensureRagExperienceInterpretations(items = []) {
  if (state.ragInterpretationInProgress) return;
  const ids = items.filter(interpretationNeedsRefresh).map((item) => item.experience_id).filter(Boolean).slice(0, 40);
  if (!ids.length) return;
  state.ragInterpretationInProgress = true;
  try {
    const payload = await apiJson("/api/rag/experiences/interpret", {
      method: "POST",
      body: JSON.stringify({experience_ids: ids, force: false, limit: ids.length}),
    });
    mergeInterpretedExperiences(payload.items || []);
  } finally {
    state.ragInterpretationInProgress = false;
  }
}

async function interpretRagExperience(experienceId, options = {}) {
  if (!experienceId) return;
  if (state.ragInterpretationLoadingIds.has(experienceId)) return;
  state.ragInterpretationLoadingIds.add(experienceId);
  renderRagExperiences({items: state.ragExperiences});
  try {
    const payload = await apiJson(`/api/rag/experiences/${encodeURIComponent(experienceId)}/interpret`, {
      method: "POST",
      body: JSON.stringify({force: options.force !== false}),
    });
    mergeInterpretedExperiences(payload.item ? [payload.item] : []);
  } finally {
    state.ragInterpretationLoadingIds.delete(experienceId);
    renderRagExperiences({items: state.ragExperiences});
  }
}

function mergeInterpretedExperiences(items = []) {
  if (!items.length) return;
  const byId = new Map(items.map((item) => [item.experience_id, item]));
  state.ragExperiences = (state.ragExperiences || []).map((item) => {
    const updated = byId.get(item.experience_id);
    return updated ? {...item, ...updated, ai_interpretation: updated.ai_interpretation} : item;
  });
  renderRagExperiences({items: state.ragExperiences});
}

function renderRagExperiences(payload = {}) {
  const items = payload.items || state.ragExperiences || [];
  const counts = payload.counts || {};
  const relationCounts = payload.relation_counts || {};
  const qualityCounts = payload.quality_counts || {};
  const retrievalCounts = payload.retrieval_counts || {};
  const cards = document.getElementById("rag-experience-cards");
  if (cards) {
    cards.innerHTML = [
      ["正在使用", counts.active ?? 0],
      ["可参考", retrievalCounts.retrievable ?? 0],
      ["需要看看", qualityCounts.low ?? 0],
      ["已停用", qualityCounts.blocked ?? 0],
      ["可转待确认", relationCounts.promotion_candidate ?? 0],
      ["系统自动保留", relationCounts.auto_kept_experience ?? 0],
      ["已保留", relationCounts.kept_experience ?? 0],
      ["正式库已覆盖", relationCounts.covered_by_formal ?? 0],
      ["已转待确认", counts.promoted ?? 0],
      ["已废弃", counts.discarded ?? 0],
      ["总经验", counts.total ?? items.length],
    ]
      .map(([label, value]) => `<div class="metric-card"><span>${escapeHtml(value)}</span><label>${escapeHtml(label)}</label></div>`)
      .join("");
  }
  const list = document.getElementById("rag-experience-list");
  if (!list) return;
  const sortedItems = sortRagExperiencesForReview(items);
  list.innerHTML = sortedItems.length
    ? sortedItems.map((item) => {
        const hit = item.rag_hit || {};
        const source = experienceSourceText(item, hit);
        const usageText = experienceUsageText(item);
        const relation = item.formal_relation || item.status || "novel";
        const match = item.formal_match || {};
        const quality = item.quality || {};
        const qualityBand = quality.band || "unknown";
        const qualityReasons = Array.isArray(quality.reasons) ? quality.reasons : [];
        const isHandled = ragExperienceIsHandled(item, relation);
        const canAct = (item.status || "active") === "active" && !isHandled;
        let canPromote = canAct && relation !== "covered_by_formal" && relation !== "conflicts_formal";
        const retrievalAllowed = experienceRetrievalAllowed(item, quality);
        const readableSummary = readableExperienceSummary(item, hit);
        const displayState = ragExperienceDisplayState(item, relation);
        const experienceId = String(item.experience_id || "");
        const isExpanded = state.ragExperienceExpanded.has(experienceId);
        const interpretation = item.ai_interpretation || {};
        const aiRecommendedPromotion = interpretation.recommended_action === "promote_to_pending" && interpretation.promotion_allowed !== false;
        canPromote = canAct && aiRecommendedPromotion && relation !== "covered_by_formal" && relation !== "conflicts_formal";
        const compactAction = interpretation.action_label || actionLabelFromValue(interpretation.recommended_action) || (canPromote ? "建议审核是否升级" : "建议人工查看");
        const compactMeaning = interpretation.meaning || "等待AI重新理解后显示这条经验的大概意思。";
        const compactReason = interpretation.action_reason || compactMeaning;
        const isInterpreting = state.ragInterpretationLoadingIds.has(experienceId);
        const activeAction = state.ragActionLoadingIds.get(experienceId) || "";
        const isActionLoading = Boolean(activeAction);
        return `
          <div class="record-row rag-experience-row readable-experience-row is-experience-${escapeHtml(displayState)}" data-experience-id="${escapeHtml(experienceId)}" data-review-state="${escapeHtml(displayState)}" data-collapsed="${isExpanded ? "false" : "true"}">
            <div class="rag-experience-main">
              <div class="experience-collapse-head">
                <button type="button" class="experience-collapse-toggle rag-experience-toggle" data-id="${escapeHtml(experienceId)}" aria-expanded="${isExpanded ? "true" : "false"}">
                  <span class="collapse-caret" aria-hidden="true"></span>
                  <strong>AI经验：${escapeHtml(readableSummary)}</strong>
                  <span class="toggle-copy">${isExpanded ? "收起" : "展开"}</span>
                </button>
                <span class="relation-chip relation-${escapeHtml(relation)}">${escapeHtml(relationText(relation))}</span>
              </div>
              <div class="quality-line" title="${escapeHtml(qualityReasons.join("；"))}">
                <span class="quality-chip quality-${escapeHtml(qualityBand)}">${escapeHtml(qualityText(qualityBand))}</span>
                <span class="status-chip ${retrievalAllowed ? "ok" : "warning"}">${escapeHtml(experienceParticipationText(item, quality))}</span>
              </div>
              <span class="experience-meta-line">${escapeHtml(source)} · ${escapeHtml(usageText)} · ${escapeHtml(item.updated_at || item.created_at || "")}</span>
              <div class="experience-compact-summary">
                <span class="experience-action-chip">${escapeHtml(compactAction)}</span>
                <p>${escapeHtml(shortBusinessText(compactReason, 140))}</p>
              </div>
              <div class="experience-collapsible-body">
                <div class="experience-readable-form">
                  ${renderExperienceReadableBody(item)}
                </div>
                ${renderExperienceSourceDetails(item, hit, match)}
              </div>
            </div>
            <div class="inline-actions">
              ${canAct ? `<button class="secondary-button rag-experience-interpret ${isInterpreting ? "is-loading" : ""}" data-id="${escapeHtml(item.experience_id || "")}" ${isInterpreting || isActionLoading ? "disabled" : ""}>${isInterpreting ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>整理中</span>` : "AI重新整理"}</button>` : ""}
              ${canPromote ? `<button class="primary-button rag-experience-promote ${activeAction === "promote" ? "is-loading" : ""}" data-id="${escapeHtml(item.experience_id || "")}" ${isActionLoading ? "disabled" : ""}>${activeAction === "promote" ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>升级中</span>` : "升级为待确认知识"}</button>` : ""}
              ${canAct ? `<button class="secondary-button rag-experience-keep ${activeAction === "keep" ? "is-loading" : ""}" data-id="${escapeHtml(item.experience_id || "")}" ${isActionLoading ? "disabled" : ""}>${activeAction === "keep" ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>保存中</span>` : "保留为经验"}</button>` : ""}
              ${canAct ? `<button class="secondary-button rag-experience-discard ${activeAction === "discard" ? "is-loading" : ""}" data-id="${escapeHtml(item.experience_id || "")}" ${isActionLoading ? "disabled" : ""}>${activeAction === "discard" ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>废弃中</span>` : "废弃"}</button>` : ""}
              ${isHandled ? `<button class="secondary-button rag-experience-reopen ${activeAction === "reopen" ? "is-loading" : ""}" data-id="${escapeHtml(item.experience_id || "")}" ${isActionLoading ? "disabled" : ""}>${activeAction === "reopen" ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>恢复中</span>` : "重新待处理"}</button>` : ""}
            </div>
          </div>
        `;
      }).join("")
    : `<div class="empty-state">暂无对话经验。系统只有在客服使用参考资料成功回复后，才会在这里生成概括。</div>`;
  list.querySelectorAll(".rag-experience-discard").forEach((button) => {
    button.addEventListener("click", () => discardRagExperience(button.dataset.id).catch((error) => alert(error.message)));
  });
  list.querySelectorAll(".rag-experience-promote").forEach((button) => {
    button.addEventListener("click", () => promoteRagExperience(button.dataset.id).catch((error) => alert(error.message)));
  });
  list.querySelectorAll(".rag-experience-keep").forEach((button) => {
    button.addEventListener("click", () => keepRagExperience(button.dataset.id).catch((error) => alert(error.message)));
  });
  list.querySelectorAll(".rag-experience-reopen").forEach((button) => {
    button.addEventListener("click", () => reopenRagExperience(button.dataset.id).catch((error) => alert(error.message)));
  });
  list.querySelectorAll(".rag-experience-save").forEach((button) => {
    button.addEventListener("click", () => saveRagExperiencePoint(button).catch((error) => alert(error.message)));
  });
  list.querySelectorAll(".rag-experience-interpret").forEach((button) => {
    button.addEventListener("click", () => interpretRagExperience(button.dataset.id, {force: true}).catch((error) => alert(error.message)));
  });
  list.querySelectorAll(".rag-experience-toggle").forEach((button) => {
    button.addEventListener("click", () => toggleRagExperience(button));
  });
}

function toggleRagExperience(button) {
  const row = button.closest(".rag-experience-row");
  if (!row) return;
  const id = button.dataset.id || row.dataset.experienceId || "";
  const nextExpanded = row.dataset.collapsed !== "false";
  row.dataset.collapsed = nextExpanded ? "false" : "true";
  button.setAttribute("aria-expanded", nextExpanded ? "true" : "false");
  const label = button.querySelector(".toggle-copy");
  if (label) label.textContent = nextExpanded ? "收起" : "展开";
  if (id) {
    if (nextExpanded) {
      state.ragExperienceExpanded.add(id);
    } else {
      state.ragExperienceExpanded.delete(id);
    }
    saveStringSet("ragExperienceExpanded", state.ragExperienceExpanded);
  }
}

async function promoteRagExperience(experienceId) {
  if (!experienceId) return;
  if (state.ragActionLoadingIds.has(experienceId)) return;
  if (!confirm("确认把这条经验转为“待确认知识”？它仍需要人工审核后才会进入正式知识库。")) return;
  state.ragActionLoadingIds.set(experienceId, "promote");
  renderRagExperiences({items: state.ragExperiences});
  try {
    const payload = await apiJson(`/api/rag/experiences/${encodeURIComponent(experienceId)}/promote`, {
      method: "POST",
      body: JSON.stringify({source: "admin_console"}),
    });
    if (!payload.ok) throw new Error(payload.message || "经验升级失败");
    await Promise.all([
      loadRagExperiences(),
      loadRagStatus().catch(() => {}),
      loadCandidates().catch(() => {}),
      loadOverview().catch(() => {}),
    ]);
  } finally {
    state.ragActionLoadingIds.delete(experienceId);
    renderRagExperiences({items: state.ragExperiences});
  }
}

async function discardRagExperience(experienceId) {
  if (!experienceId) return;
  if (state.ragActionLoadingIds.has(experienceId)) return;
  if (!confirm("确认废弃这条对话经验？废弃后不会再参与参考检索。")) return;
  state.ragActionLoadingIds.set(experienceId, "discard");
  renderRagExperiences({items: state.ragExperiences});
  try {
    await apiJson(`/api/rag/experiences/${encodeURIComponent(experienceId)}/discard`, {
      method: "POST",
      body: JSON.stringify({reason: "discarded in admin"}),
    });
    await Promise.all([loadRagExperiences(), loadRagStatus().catch(() => {})]);
  } finally {
    state.ragActionLoadingIds.delete(experienceId);
    renderRagExperiences({items: state.ragExperiences});
  }
}

async function keepRagExperience(experienceId) {
  if (!experienceId) return;
  if (state.ragActionLoadingIds.has(experienceId)) return;
  state.ragActionLoadingIds.set(experienceId, "keep");
  renderRagExperiences({items: state.ragExperiences});
  try {
    await apiJson(`/api/rag/experiences/${encodeURIComponent(experienceId)}/keep`, {
      method: "POST",
      body: JSON.stringify({reason: "kept in experience layer"}),
    });
    await Promise.all([loadRagExperiences(), loadRagStatus().catch(() => {})]);
  } finally {
    state.ragActionLoadingIds.delete(experienceId);
    renderRagExperiences({items: state.ragExperiences});
  }
}

async function reopenRagExperience(experienceId) {
  if (!experienceId) return;
  if (state.ragActionLoadingIds.has(experienceId)) return;
  state.ragActionLoadingIds.set(experienceId, "reopen");
  renderRagExperiences({items: state.ragExperiences});
  try {
    await apiJson(`/api/rag/experiences/${encodeURIComponent(experienceId)}/reopen`, {
      method: "POST",
      body: JSON.stringify({reason: "reopened in admin"}),
    });
    await Promise.all([loadRagExperiences(), loadRagStatus().catch(() => {}), loadCandidates().catch(() => {})]);
  } finally {
    state.ragActionLoadingIds.delete(experienceId);
    renderRagExperiences({items: state.ragExperiences});
  }
}

async function saveRagExperiencePoint(button) {
  const experienceId = button?.dataset?.id || "";
  if (!experienceId) return;
  const row = button.closest(".rag-experience-row");
  const pointInputs = [...(row?.querySelectorAll(".rag-experience-point-input") || [])];
  const points = pointInputs.map((input) => input.value.trim()).filter(Boolean);
  const textarea = row?.querySelector(".rag-experience-reply");
  const replyText = points.length ? points.join("\n") : textarea?.value?.trim() || "";
  if (!replyText) {
    alert("回答要点不能为空。");
    return;
  }
  await apiJson(`/api/rag/experiences/${encodeURIComponent(experienceId)}`, {
    method: "PATCH",
    body: JSON.stringify({reply_text: replyText}),
  });
  await Promise.all([loadRagExperiences(), loadRagStatus().catch(() => {})]);
}

function renderExperienceReadableBody(item) {
  return renderAiInterpretation(item);
}

function renderAiInterpretation(item) {
  const ai = item.ai_interpretation || {};
  if (!ai.meaning) {
    return `
      <div class="ai-interpretation-card is-pending">
        <span>AI重新理解</span>
        <p>系统正在让大模型重新读这条经验，稍后会显示它大概是什么意思，以及建议你怎么处理。</p>
      </div>
    `;
  }
  const providerText = ai.provider === "local_fallback" ? "本地兜底，未调用大模型" : `大模型整理${ai.model ? ` · ${ai.model}` : ""}`;
  return `
    <div class="ai-interpretation-card ${ai.provider === "local_fallback" ? "is-fallback" : "is-model"}">
      <div class="ai-interpretation-head">
        <span>AI重新理解</span>
        <em>${escapeHtml(providerText)}</em>
      </div>
      <p>${escapeHtml(ai.meaning)}</p>
      <div class="interpretation-recommendation">
        <b>${escapeHtml(ai.action_label || actionLabelFromValue(ai.recommended_action))}</b>
        <small>${escapeHtml(ai.action_reason || "")}</small>
      </div>
      ${renderFormalKnowledgeComparison(ai.formal_knowledge_comparison)}
      ${Array.isArray(ai.what_to_check) && ai.what_to_check.length ? `
        <div class="interpretation-mini-list">
          <strong>你主要核对</strong>
          ${ai.what_to_check.map((item) => `<small>${escapeHtml(item)}</small>`).join("")}
        </div>
      ` : ""}
      ${Array.isArray(ai.risk_notes) && ai.risk_notes.length ? `
        <div class="interpretation-mini-list warning">
          <strong>风险提醒</strong>
          ${ai.risk_notes.map((item) => `<small>${escapeHtml(item)}</small>`).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

function renderFormalKnowledgeComparison(comparison = {}) {
  if (!comparison || typeof comparison !== "object") return "";
  const level = comparison.overlap_level || "none";
  const hasMatch = comparison.matched_title || comparison.matched_item_id || level !== "none";
  if (!hasMatch) return "";
  const levelText = {
    high: "和正式知识高度重合",
    medium: "和正式知识部分相近",
    low: "找到弱相关正式知识",
    none: "未发现明显重合",
  }[level] || "正式知识比对";
  const similarity = comparison.similarity !== null && comparison.similarity !== undefined ? `相似度 ${comparison.similarity}` : "";
  return `
    <div class="formal-comparison-card overlap-${escapeHtml(level)}">
      <div class="formal-comparison-head">
        <b>${escapeHtml(levelText)}</b>
        ${similarity ? `<em>${escapeHtml(similarity)}</em>` : ""}
      </div>
      ${comparison.matched_title ? `<p>相近正式知识：${escapeHtml(comparison.matched_title)}${comparison.matched_category ? `（${escapeHtml(comparison.matched_category)}）` : ""}</p>` : ""}
      ${comparison.conclusion ? `<p>${escapeHtml(comparison.conclusion)}</p>` : ""}
      ${Array.isArray(comparison.same_points) && comparison.same_points.length ? `
        <div class="interpretation-mini-list">
          <strong>重合点</strong>
          ${comparison.same_points.map((item) => `<small>${escapeHtml(item)}</small>`).join("")}
        </div>
      ` : ""}
      ${Array.isArray(comparison.differences) && comparison.differences.length ? `
        <div class="interpretation-mini-list warning">
          <strong>差异点</strong>
          ${comparison.differences.map((item) => `<small>${escapeHtml(item)}</small>`).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

function renderExperienceSourceDetails(item, hit = {}, match = {}) {
  const hasReplyExperience = item.source !== "intake";
  return `
    <details class="experience-editor">
      <summary>${hasReplyExperience ? "查看来源 / 修改原始要点" : "查看来源和原始内容"}</summary>
      <div class="experience-point-editor">
        ${renderExperienceReadableSourceContent(item, hit)}
        ${match.item_id ? `<div><span>正式库相近内容</span><p>${escapeHtml(`已有相近正式知识「${match.title || match.item_id || ""}」，位置 ${match.category_id || ""}/${match.item_id || ""}`)}</p></div>` : ""}
        ${hasReplyExperience ? `
          <div>
            <span>手动修改原始回答要点</span>
            ${renderExperiencePointEditor(item.reply_text || "")}
          </div>
          <div class="inline-actions">
            <button class="secondary-button rag-experience-save" data-id="${escapeHtml(item.experience_id || "")}">保存要点</button>
          </div>
        ` : ""}
      </div>
    </details>
  `;
}

function renderExperienceReadableSourceContent(item, hit = {}) {
  const primaryText = String(item.evidence_excerpt || item.reply_text || item.summary || "");
  const sourceData = normalizeExperienceSourceData(readableSourceData(primaryText, item));
  const hitData = readableSourceData(hit.text || "", {});
  const cards = [];
  const mode = experienceSourceMode(item, sourceData);
  const customerMessage = sourceData.customer_message || sourceData.question || item.question || "";
  const serviceReply = sourceData.service_reply || sourceData.reply || sourceData.answer || "";
  const productName = sourceData.name || sourceData.product_name || "";
  const policyTitle = sourceData.title || sourceData.policy_type || sourceData.handoff_reason || "";

  cards.push(sourceReadableCard("来源渠道", experienceSourceChannelText(item)));
  const originDetail = experienceSourceOriginDetail(item);
  if (originDetail) cards.push(sourceReadableCard("来源说明", originDetail));

  if (mode === "dialogue") {
    if (customerMessage) cards.push(sourceReadableCard("客户怎么问的", customerMessage));
    if (serviceReply) cards.push(sourceReadableCard("AI怎么回的", serviceReply));
  } else if (mode === "product") {
    if (productName || sourceData.sku) {
      cards.push(sourceReadableCard("商品对象", readableSourceFieldSummary(sourceData, ["name", "sku", "category", "product_category"])));
    }
    cards.push(sourceReadableCard("商品核心信息", readableSourceFieldSummary(sourceData, ["price", "unit", "inventory", "specs", "shipping_policy", "warranty_policy"])));
    if (!isEmpty(sourceData.alias_keywords) || !isEmpty(sourceData.keywords)) {
      cards.push(sourceReadableCard("关键词/别名", readableSourceFieldSummary(sourceData, ["alias_keywords", "keywords"])));
    }
    if (serviceReply || sourceData.answer) cards.push(sourceReadableCard("建议回复要点", serviceReply || sourceData.answer));
  } else if (mode === "policy") {
    if (policyTitle || sourceData.source_title) cards.push(sourceReadableCard("规则名称", policyTitle || sourceData.source_title));
    if (!isEmpty(sourceData.keywords)) cards.push(sourceReadableCard("触发条件", displayBusinessValue(sourceData.keywords)));
    if (sourceData.answer || serviceReply) cards.push(sourceReadableCard("规则内容", sourceData.answer || serviceReply));
    const runtimeRule = sourceRuntimeRuleSummary(sourceData);
    if (runtimeRule) cards.push(sourceReadableCard("执行边界", runtimeRule));
  } else {
    if (customerMessage) cards.push(sourceReadableCard("客户怎么问的", customerMessage));
    if (serviceReply) cards.push(sourceReadableCard("AI怎么回的", serviceReply));
    if (productName || sourceData.sku || sourceData.price || sourceData.inventory) {
      cards.push(sourceReadableCard("识别到的商品信息", readableSourceFieldSummary(sourceData, ["name", "sku", "category", "price", "unit", "inventory", "shipping_policy", "warranty_policy"])));
    }
    if (policyTitle || sourceData.keywords || sourceData.requires_handoff) {
      cards.push(sourceReadableCard("识别到的规则线索", readableSourceFieldSummary(sourceData, ["title", "policy_type", "answer", "keywords", "requires_handoff", "handoff_reason"])));
    }
  }
  const tags = readableSourceTags(sourceData);
  if (tags) cards.push(sourceReadableCard("系统识别出的标签", tags));
  const scope = readableSourceScope(sourceData);
  if (scope) cards.push(sourceReadableCard("适用范围", scope));
  if (item.ai_interpretation?.meaning) cards.push(sourceReadableCard("AI重新理解", item.ai_interpretation.meaning));
  if (!cards.length && primaryText) cards.push(sourceReadableCard("整理后的来源内容", readableSourcePlainText(primaryText)));

  const hitText = hit.text && hit.text !== primaryText ? readableSourcePlainText(hit.text) : "";
  if (hitText) cards.push(sourceReadableCard("命中的参考资料", hitText));
  if (!cards.length) cards.push(`<div class="empty-state compact-empty">暂无可展示的来源内容。</div>`);

  const rawText = primaryText || hit.text || "";
  const technicalRaw = rawText
    ? `<details class="raw-source-details source-technical-details"><summary>查看技术原文（排查用）</summary><div><span>系统保存的原始记录</span><p>${escapeHtml(shortBusinessText(rawText, 1200))}</p></div></details>`
    : "";
  return `${cards.join("")}${technicalRaw}`;
}

function normalizeExperienceSourceData(data) {
  const normalized = {...(data || {})};
  for (const key of ["keywords", "intent_tags", "tone_tags", "linked_categories", "linked_item_ids", "alias_keywords"]) {
    if (typeof normalized[key] === "string") normalized[key] = splitTags(normalized[key]);
  }
  for (const key of ["allow_auto_reply", "requires_handoff", "operator_alert", "usable_as_template"]) {
    const parsed = parseBooleanLike(normalized[key]);
    if (parsed !== null) normalized[key] = parsed;
  }
  return normalized;
}

function parseBooleanLike(value) {
  if (value === true || value === false) return value;
  const text = String(value || "").trim().toLowerCase();
  if (!text) return null;
  if (["true", "1", "yes", "y", "是", "需要", "允许"].includes(text)) return true;
  if (["false", "0", "no", "n", "否", "不需要", "不允许"].includes(text)) return false;
  return null;
}

function displayYesNo(value) {
  const parsed = parseBooleanLike(value);
  if (parsed === true) return "是";
  if (parsed === false) return "否";
  return "未标注";
}

function experienceSourceMode(item, sourceData = {}) {
  if (item.source !== "intake") return "dialogue";
  const kind = intakeExperienceKind(item, sourceData || {});
  if (kind === "product") return "product";
  if (kind === "policy" || kind === "handoff_rule") return "policy";
  if (kind === "chat_template") return "dialogue";
  return "material";
}

function experienceSourceChannelText(item) {
  if (item.source !== "intake") return "客服对话回复沉淀（RAG命中后生成）";
  const origin = item.original_source || {};
  const sourceType = String(item.source_type || origin.type || "");
  const labels = {
    raw_upload: "上传资料学习",
    deepseek_upload_learning: "上传资料学习",
    raw_wechat_group: "微信群聊学习",
    raw_wechat_private: "微信私聊学习",
    raw_wechat_file_transfer: "文件传输助手学习",
    wechat_raw_message: "微信转写学习",
    manual_admin_entry: "后台手动录入学习",
    product_doc: "商品文档学习",
    policy_doc: "规则文档学习",
    chat_log: "话术文档学习",
    manual: "手册文档学习",
    demo_material: "演示资料学习",
  };
  return labels[sourceType] || `资料学习（${sourceType || "未标注来源"}）`;
}

function experienceSourceOriginDetail(item) {
  const original = item.original_source && typeof item.original_source === "object" ? item.original_source : {};
  const parts = [
    original.file_name || "",
    original.title || "",
    original.conversation_id || "",
    original.raw_batch_id || "",
    original.session_id || "",
    original.batch_token || "",
  ].filter((value) => String(value || "").trim());
  if (!parts.length) return "";
  return parts.map((value) => shortBusinessText(String(value), 72)).join(" · ");
}

function sourceRuntimeRuleSummary(data = {}) {
  const lines = [];
  if (!isEmpty(data.policy_type)) lines.push(`规则类别：${optionLabel("policy_type", data.policy_type) || data.policy_type}`);
  if (!isEmpty(data.allow_auto_reply)) lines.push(`允许自动回复：${displayYesNo(data.allow_auto_reply)}`);
  if (!isEmpty(data.requires_handoff)) lines.push(`必须转人工：${displayYesNo(data.requires_handoff)}`);
  if (!isEmpty(data.operator_alert)) lines.push(`提醒人工客服：${displayYesNo(data.operator_alert)}`);
  if (!isEmpty(data.risk_level)) lines.push(`风险等级：${optionLabel("risk_level", data.risk_level) || data.risk_level}`);
  if (!isEmpty(data.handoff_reason)) lines.push(`人工确认原因：${data.handoff_reason}`);
  return lines.join("\n");
}

function sourceReadableCard(label, value) {
  const text = shortMultilineBusinessText(displayBusinessValue(value), 900);
  if (!text) return "";
  return `
    <div class="source-readable-card">
      <span>${escapeHtml(label)}</span>
      <p>${escapeHtml(text)}</p>
    </div>
  `;
}

function shortMultilineBusinessText(value, maxLength = 360) {
  const text = String(value || "")
    .split(/\r?\n+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n");
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trim()}...`;
}

function readableSourceData(text, item = {}) {
  const parsed = parseExperiencePayload(text || "");
  let data = {};
  if (Array.isArray(parsed.value)) data = parsed.value.find((entry) => entry && typeof entry === "object") || {};
  else if (parsed.value && typeof parsed.value === "object" && !parsed.value.raw_text) data = parsed.value;
  data = {...data, ...extractJsonLikeSourceFields(String(text || ""))};
  const dialogue = item.source_dialogue && typeof item.source_dialogue === "object" ? item.source_dialogue : {};
  if (!data.customer_message && dialogue.customer_message) data.customer_message = dialogue.customer_message;
  if (!data.service_reply && dialogue.service_reply) data.service_reply = dialogue.service_reply;
  const transcript = extractTranscriptDialogue(String(text || ""));
  if (!data.customer_message && transcript.customer_message) data.customer_message = transcript.customer_message;
  if (!data.service_reply && transcript.service_reply) data.service_reply = transcript.service_reply;
  return data;
}

function extractJsonLikeSourceFields(text) {
  const fields = {};
  const stringKeys = [
    "customer_message", "service_reply", "question", "reply", "answer", "name", "product_name", "sku", "category",
    "unit", "shipping_policy", "warranty_policy", "title", "source_title", "policy_type", "handoff_reason", "applicability_scope",
    "product_id", "product_category", "risk_level", "specs", "batch_token",
  ];
  for (const key of stringKeys) {
    const match = text.match(new RegExp(`"${key}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`));
    if (match) fields[key] = decodeJsonLikeString(match[1]);
  }
  for (const key of ["price", "inventory"]) {
    const match = text.match(new RegExp(`"${key}"\\s*:\\s*(-?\\d+(?:\\.\\d+)?)`));
    if (match) fields[key] = match[1];
  }
  for (const key of ["usable_as_template", "requires_handoff", "allow_auto_reply", "operator_alert"]) {
    const match = text.match(new RegExp(`"${key}"\\s*:\\s*(true|false)`));
    if (match) fields[key] = match[1] === "true";
  }
  for (const key of ["intent_tags", "tone_tags", "linked_categories", "linked_item_ids", "keywords", "alias_keywords"]) {
    const match = text.match(new RegExp(`"${key}"\\s*:\\s*\\[([^\\]]*)\\]`));
    if (!match) continue;
    const values = [];
    for (const item of match[1].matchAll(/"((?:\\.|[^"\\])*)"/g)) {
      values.push(decodeJsonLikeString(item[1]));
    }
    if (values.length) fields[key] = values;
  }
  return fields;
}

function decodeJsonLikeString(value) {
  const text = String(value || "");
  try {
    return JSON.parse(`"${text.replace(/\r?\n/g, "\\n")}"`);
  } catch {
    return text.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  }
}

function extractTranscriptDialogue(text) {
  const customer = [];
  const replies = [];
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const withoutTime = rawLine.replace(/^\[[^\]]+\]\s*/, "").trim();
    const match = withoutTime.match(/^([^:：]{1,30})[:：]\s*(.+)$/);
    if (!match) continue;
    const sender = match[1].trim();
    const content = match[2].trim();
    if (!content || sender === "system") continue;
    if (sender === "self" || content.includes("[车金AI]")) replies.push(content.replace(/^\[车金AI\]\s*/, ""));
    else customer.push(content);
  }
  return {
    customer_message: customer.join("\n"),
    service_reply: replies.join("\n"),
  };
}

function readableSourceFieldSummary(data, keys) {
  return keys
    .map((key) => {
      const value = data?.[key];
      if (isEmpty(value)) return "";
      return `${fieldLabel({id: key, label: key})}：${displayBusinessValue(value)}`;
    })
    .filter(Boolean)
    .join("\n");
}

function readableSourceTags(data) {
  const parts = [];
  if (!isEmpty(data.intent_tags)) parts.push(`客户意图：${displayBusinessValue(data.intent_tags)}`);
  if (!isEmpty(data.tone_tags)) parts.push(`表达特点：${displayBusinessValue(data.tone_tags)}`);
  if (!isEmpty(data.linked_categories)) parts.push(`关联栏目：${displayBusinessValue(data.linked_categories)}`);
  if (!isEmpty(data.linked_item_ids)) parts.push(`关联知识：${displayBusinessValue(data.linked_item_ids)}`);
  if (!isEmpty(data.keywords)) parts.push(`触发词：${displayBusinessValue(data.keywords)}`);
  return parts.join("\n");
}

function readableSourceScope(data) {
  const scope = data.applicability_scope ? optionLabel("applicability_scope", data.applicability_scope) : "";
  const product = [data.product_id, data.product_category].filter((value) => String(value || "").trim()).join(" / ");
  return [scope, product ? `关联商品：${product}` : ""].filter(Boolean).join("\n");
}

function readableSourcePlainText(text) {
  const data = readableSourceData(text, {});
  const parts = [];
  if (data.customer_message) parts.push(`客户怎么问：${displayBusinessValue(data.customer_message)}`);
  if (data.service_reply || data.answer) parts.push(`AI怎么回：${displayBusinessValue(data.service_reply || data.answer)}`);
  const tags = readableSourceTags(data);
  if (tags) parts.push(tags);
  if (parts.length) return parts.join("\n");
  return readableExperiencePointText(text, 900);
}

function parseExperiencePayload(value) {
  const text = String(value || "").trim();
  if (!text) return {value: {}, text: ""};
  if (/^[\[{]/.test(text)) {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === "object") return {value: parsed, text};
    } catch {
      // Fall through to loose field parsing.
    }
  }
  const fields = {};
  const segments = text.split(/\r?\n+|；|;/g).map((item) => item.trim()).filter(Boolean);
  for (const segment of segments) {
    const match = segment.match(/^([^:：]{1,36})[:：]\s*(.+)$/);
    if (!match) continue;
    const key = normalizeExperienceFieldKey(match[1]);
    if (!key) continue;
    fields[key] = match[2].trim();
  }
  return {value: Object.keys(fields).length ? fields : {raw_text: text}, text};
}

function normalizeExperienceFieldKey(key) {
  const text = String(key || "").trim();
  const map = {
    资料来源: "source_title",
    商品资料: "source_title",
    政策规则: "source_title",
    测试批次: "batch_token",
    商品: "name",
    商品名称: "name",
    车辆: "name",
    车源: "name",
    编号: "sku",
    型号: "sku",
    类目: "category",
    商品类目: "category",
    价格: "price",
    报价: "price",
    单位: "unit",
    库存: "inventory",
    关键词: "keywords",
    标签: "intent_tags",
    发货说明: "shipping_policy",
    发货: "shipping_policy",
    物流: "shipping_policy",
    "物流/过户": "shipping_policy",
    看车说明: "shipping_policy",
    售后说明: "warranty_policy",
    售后: "warranty_policy",
    售后风险: "warranty_policy",
    "售后/风险": "warranty_policy",
    车况说明: "warranty_policy",
    规格: "specs",
    规格参数: "specs",
    别名关键词: "alias_keywords",
    推荐话术: "service_reply",
    标准说明: "answer",
    规则: "title",
    客户: "customer_message",
    客服: "service_reply",
    客户问题: "customer_message",
    客户问法: "customer_message",
    客服回复: "service_reply",
    建议回复: "service_reply",
    标准回复: "service_reply",
    标题: "title",
    规则名称: "title",
    规则类型: "policy_type",
    回复内容: "answer",
    答案: "answer",
    规则内容: "answer",
    触发词: "keywords",
    触发关键词: "keywords",
    允许自动回复: "allow_auto_reply",
    必须转人工: "requires_handoff",
    提醒人工客服: "operator_alert",
    风险等级: "risk_level",
  };
  if (map[text]) return map[text];
  return text.replace(/\s+/g, "_");
}

function intakeExperienceKind(item, value) {
  const data = Array.isArray(value) ? value[0] || {} : value || {};
  const text = JSON.stringify(value || {}, null, 0) + " " + String(item.summary || "");
  if (Number(item.candidate_count || 0) === 0 && !hasBusinessFields(data)) return "noise";
  if (truthyDataValue(data.requires_handoff) || data.handoff_reason || /转人工|人工确认|贷款包过|金融|首付|月供|电池检测/.test(text)) return "handoff_rule";
  if (data.name || data.sku || data.price || data.inventory || data.category) return "product";
  if (data.customer_message || data.service_reply) return "chat_template";
  if (data.title || data.policy_type || data.answer || data.keywords) return "policy";
  return "lead";
}

function hasBusinessFields(data) {
  return ["name", "sku", "price", "inventory", "customer_message", "service_reply", "title", "answer", "handoff_reason"].some((key) => !isEmpty(data?.[key]));
}

function truthyDataValue(value) {
  return value === true || value === "true" || value === "是" || value === "需要" || value === 1 || value === "1";
}

function sourceLabel(source) {
  return [source.source_type || "资料源", source.source_id || ""].filter(Boolean).join(" · ");
}

function experienceSourceText(item, hit = {}) {
  if (item.source === "intake") {
    const origin = item.original_source || {};
    const sourceType = item.source_type || origin.type || "intake";
    const sourceLabels = {
      raw_upload: "导入资料",
      deepseek_upload_learning: "导入资料",
      raw_wechat_group: "微信群聊",
      raw_wechat_private: "微信私聊",
      raw_wechat_file_transfer: "文件传输助手",
      wechat_raw_message: "微信转写",
      manual_admin_entry: "后台手动录入",
      product_doc: "商品文档",
      policy_doc: "规则文档",
      chat_log: "对话文档",
      manual: "手册文档",
    };
    const detail = origin.file_name || origin.conversation_id || origin.raw_batch_id || shortPath(item.source_path || origin.path || "");
    return [sourceLabels[sourceType] || sourceType, detail, `${item.candidate_count ?? 0} 条AI线索`].filter(Boolean).join(" · ");
  }
  return [hit.category || hit.source_type || "RAG片段", hit.product_id || "未指定商品"].filter(Boolean).join(" · ");
}

function experienceUsageText(item) {
  if (item.source === "intake") return `关联 ${item.candidate_count ?? 0} 条AI线索`;
  return `使用 ${(item.usage || {}).reply_count ?? 1} 次`;
}

function readableExperienceSummary(item, hit = {}) {
  if (item.ai_interpretation?.meaning) return shortBusinessText(item.ai_interpretation.meaning, 150);
  if (item.source === "intake") {
    const source = experienceSourceText(item, hit).split(" · ")[0] || "资料";
    const parsed = parseExperiencePayload(item.reply_text || item.evidence_excerpt || "");
    const kind = intakeExperienceKind(item, parsed.value);
    const data = Array.isArray(parsed.value) ? parsed.value[0] || {} : parsed.value || {};
    if (kind === "product") return `从${source}识别到商品资料：${shortBusinessText(displayBusinessValue(data.name || data.sku || "未命名商品"), 80)}`;
    if (kind === "handoff_rule") return `从${source}识别到转人工规则：${shortBusinessText(displayBusinessValue(data.title || data.handoff_reason || "需人工确认"), 80)}`;
    if (kind === "chat_template") return `从${source}识别到客服话术`;
    if (kind === "policy") return `从${source}识别到政策规则：${shortBusinessText(displayBusinessValue(data.title || data.policy_type || "待命名规则"), 80)}`;
    if (kind === "noise") return `从${source}识别到疑似无效内容`;
    const count = Number(item.candidate_count || 0);
    if (count > 0) return `从${source}整理出 ${count} 条可审核内容`;
    return `从${source}保留了一条可参考经验`;
  }
  const raw = String(item.summary || "").trim();
  if (!raw) return "未生成概括";
  return shortBusinessText(raw.replace(/^Intake\s*->\s*RAG experience:\s*/i, ""), 160);
}

function readableQualityReason(value) {
  const text = String(value || "").trim();
  const translations = {
    "intake material is stored as RAG experience first": "这条内容只是先放进AI经验池，尚未允许参与回答",
    "formal knowledge still requires pending-candidate review": "要变成正式知识，需要先点“升级为待确认知识”，再人工审核入库",
    "intake experiences are not used for autonomous reply retrieval before review": "未确认前不会参与RAG经验参考，也不会自动回答客户",
    "尚未人工确认保留在经验层": "还没有点击“保留为经验”，不会参与RAG经验参考",
    "暂不参与 RAG 经验检索": "当前暂不参与RAG经验参考",
    "允许参与 RAG 经验检索": "已允许作为RAG经验参考",
  };
  return translations[text] || text;
}

function experienceUsageExplanation(item, quality = {}) {
  if (item.source === "intake") {
    const parsed = parseExperiencePayload(item.reply_text || item.evidence_excerpt || "");
    const kind = intakeExperienceKind(item, parsed.value);
    if (kind === "noise") return "这条内容不会参与客户回答。它看起来不像业务知识，确认无用后可以直接废弃。";
    return "这是从资料或聊天记录整理出的审核线索，不会直接参与客户回答。觉得有价值时，点“升级为待确认知识”，再用表单核对后进入正式知识库。";
  }
  if (experienceReviewStatus(item) === "auto_kept") {
    if (experienceRetrievalAllowed(item, quality)) {
      return "系统判断这条经验低风险、可复用，已自动保留在RAG经验层。之后客户问到相近问题时，AI可以把它当辅助参考；如果你想进一步变成正式知识，先点“重新待处理”，再决定是否升级。";
    }
    return "系统已自动保留这条经验，但当前证据或质量还不够稳定，所以暂时不会参与RAG参考。";
  }
  if (experienceReviewStatus(item) !== "kept") {
    return "这条经验还没有人工确认，系统不会拿它自动回答客户，也不会作为RAG参考。确认无误后，点“保留为经验”，它才可能作为AI参考。";
  }
  if (experienceRetrievalAllowed(item, quality)) {
    return "你已确认保留为经验。之后客户问到相近问题时，AI可以把它作为辅助参考；如果要变成正式结构化知识，还需要点“升级为待确认知识”并人工审核入库。";
  }
  return "你已确认保留为经验，但系统判断证据或质量还不够稳定，所以暂时不会参与RAG参考或自动回答。";
}

function readableExperiencePointText(value, maxLength = 420) {
  let text = String(value || "");
  text = text.replace(/；?\s*raw_text\s*[:：].*$/i, "");
  const replacements = [
    [/\bname\s*[:：]/gi, "商品名称："],
    [/\bsku\s*[:：]/gi, "型号/SKU："],
    [/\bcategory\s*[:：]/gi, "商品类目："],
    [/\bprice\s*[:：]/gi, "价格："],
    [/\bunit\s*[:：]/gi, "单位："],
    [/\binventory\s*[:：]/gi, "库存："],
    [/\bshipping_policy\s*[:：]/gi, "发货说明："],
    [/\bwarranty_policy\s*[:：]/gi, "售后说明："],
    [/\bcustomer_message\s*[:：]/gi, "客户问题："],
    [/\bservice_reply\s*[:：]/gi, "客服回复："],
    [/\banswer\s*[:：]/gi, "回复内容："],
    [/\bkeywords\s*[:：]/gi, "触发词："],
    [/\btitle\s*[:：]/gi, "标题："],
  ];
  for (const [pattern, replacement] of replacements) {
    text = text.replace(pattern, replacement);
  }
  return shortBusinessText(text, maxLength);
}

function experiencePointItems(value) {
  const readable = readableExperiencePointText(value, 1200);
  if (!readable) return [];
  let points = readable
    .split(/\r?\n+|[；;]\s*|(?:。|！|!|？|\?)\s*/g)
    .map((line) => line.replace(/^[\s\-*•·、，,.。；;]*(?:\d+|[一二三四五六七八九十]+)?[\s、.)）:-]*/g, "").trim())
    .filter(Boolean);
  if (points.length <= 1 && readable.length > 120) {
    points = readable
      .split(/，|,|、/g)
      .map((line) => line.trim())
      .filter((line) => line.length >= 8);
  }
  if (!points.length) points = [readable];
  const deduped = [];
  for (const point of points) {
    if (deduped.some((existing) => existing === point)) continue;
    deduped.push(shortBusinessText(point, 180));
    if (deduped.length >= 8) break;
  }
  return deduped;
}

function renderExperiencePointList(value) {
  const points = experiencePointItems(value);
  if (!points.length) return `<div class="empty-state compact-empty">暂无明确要点</div>`;
  return `
    <div class="experience-point-list">
      ${points.map((point, index) => `
        <div class="experience-point-item">
          <b>要点 ${index + 1}</b>
          <p>${escapeHtml(point)}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function renderExperiencePointEditor(value) {
  const points = experiencePointItems(value);
  const editablePoints = [...points, "", ""].slice(0, Math.max(points.length + 1, 3));
  return `
    <div class="experience-point-editor-list">
      ${editablePoints.map((point, index) => `
        <label class="form-field experience-point-field">
          <span>要点 ${index + 1}</span>
          <textarea class="rag-experience-point-input" rows="2" placeholder="例如：客户问到付款方式时，先说明支持对公转账。">${escapeHtml(point)}</textarea>
        </label>
      `).join("")}
    </div>
  `;
}

function shortBusinessText(value, maxLength = 360) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trim()}...`;
}

function shortPath(value) {
  const text = String(value || "");
  if (!text) return "";
  const parts = text.split(/[\\/]+/);
  return parts.slice(-3).join("/");
}

function qualityText(value) {
  return {
    high: "很可靠",
    medium: "可参考",
    low: "需要人工看看",
    blocked: "已停用",
    unknown: "未评估",
  }[value] || value || "未评估";
}

function experienceReviewStatus(item) {
  return String((item?.experience_review || {}).status || "");
}

function ragExperienceDisplayState(item, relationValue = "") {
  const status = String(item?.status || "active");
  const relation = String(relationValue || item?.formal_relation || status || "");
  const reviewStatus = experienceReviewStatus(item);
  if (status === "discarded" || relation === "discarded") return "discarded";
  if (status === "promoted" || relation === "promoted") return "promoted";
  if (reviewStatus === "auto_kept" || relation === "auto_kept_experience") return "auto_kept";
  if (reviewStatus === "kept" || relation === "kept_experience") return "kept";
  if (reviewStatus === "auto_triaged") return "auto_triaged";
  return "pending";
}

function ragExperienceIsHandled(item, relationValue = "") {
  return ragExperienceDisplayState(item, relationValue) !== "pending";
}

function ragExperienceTimestamp(item) {
  const value = Date.parse(item?.updated_at || item?.created_at || "");
  return Number.isFinite(value) ? value : 0;
}

function sortRagExperiencesForReview(items = []) {
  const stateRank = {pending: 0, auto_kept: 1, kept: 2, promoted: 3, auto_triaged: 4, discarded: 5};
  return [...items].sort((left, right) => {
    const leftState = ragExperienceDisplayState(left, left?.formal_relation || left?.status);
    const rightState = ragExperienceDisplayState(right, right?.formal_relation || right?.status);
    const rankDiff = (stateRank[leftState] ?? 9) - (stateRank[rightState] ?? 9);
    if (rankDiff) return rankDiff;
    return ragExperienceTimestamp(right) - ragExperienceTimestamp(left);
  });
}

function experienceRetrievalAllowed(item, quality = {}) {
  if (String(item?.status || "active") !== "active") return false;
  if (item?.source === "intake") return false;
  const reviewStatus = experienceReviewStatus(item);
  if (!["kept", "auto_kept"].includes(reviewStatus)) return false;
  if (reviewStatus === "kept" && !item?.reviewed_by_user) return false;
  return Boolean(quality?.retrieval_allowed);
}

function relationText(value) {
  return {
    novel: "新经验",
    covered_by_formal: "正式库已有",
    supports_formal: "可补充正式库",
    conflicts_formal: "疑似冲突",
    auto_kept_experience: "系统自动保留",
    kept_experience: "已保留在经验层",
    promotion_candidate: "建议转待确认",
    promoted: "已转待确认",
    discarded: "已废弃",
  }[value] || value || "未判断";
}

function actionText(value) {
  return {
    keep_as_rag_experience: "保留为经验，作为辅助表达参考。",
    keep_low_priority_or_discard: "正式知识已经覆盖，可降低优先级或废弃。",
    keep_as_supporting_expression: "可保留为正式知识的表达补充。",
    manual_review_conflict: "疑似和正式知识冲突，建议人工检查后处理。",
    promote_to_review_candidate: "建议升级为待确认知识，由人工审核后再入库。",
    system_auto_kept_as_experience: "系统已自动保留为经验，作为低风险辅助参考。",
    kept_as_experience: "已由人工确认保留为经验，不再作为新经验提醒。",
    already_promoted: "已升级为待确认知识。",
    already_discarded: "已废弃。",
  }[value] || value || "保持观察。";
}

function actionLabelFromValue(value) {
  return {
    promote_to_pending: "建议升级为待确认知识",
    keep_as_experience: "建议保留为经验",
    discard: "建议废弃",
    manual_review: "建议人工检查",
    already_covered: "正式知识库可能已覆盖",
    needs_more_info: "需要补充信息后再判断",
  }[value] || "建议人工检查";
}

function experienceStatusText(value) {
  return {promoted: "已升级", discarded: "已废弃", active: "默认采纳"}[value] || value || "默认采纳";
}

function experienceParticipationText(item, quality = {}) {
  if (item.source === "intake") return "审核线索，不直接回答";
  if (experienceReviewStatus(item) === "auto_triaged") return "系统已自动降噪，不参与回答";
  if (experienceReviewStatus(item) === "auto_kept") {
    return experienceRetrievalAllowed(item, quality) ? "系统自动保留，可作为RAG参考" : "系统自动保留，暂不参与回答";
  }
  const kept = experienceReviewStatus(item) === "kept";
  if (!kept) return "未确认，不参与回答";
  return experienceRetrievalAllowed(item, quality) ? "已确认，可作为RAG参考" : "已确认，但暂不参与回答";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function runLearning() {
  if (state.learningInProgress) return;
  const uploads = await apiGet("/api/uploads");
  const uploadIds = (uploads.items || []).filter((item) => !item.learned).map((item) => item.upload_id);
  if (!uploadIds.length) {
    document.getElementById("candidate-detail").innerHTML = `<div class="empty-state">没有待整理的上传资料。</div>`;
    selectView("rag_experiences");
    await loadRagExperiences();
    return;
  }
  setLearningBusy(true, uploadIds.length);
  try {
    const payload = await apiJson("/api/learning/jobs", {method: "POST", body: JSON.stringify({upload_ids: uploadIds, use_llm: true})});
    const skipped = Number(payload.job?.skipped_duplicate_count || 0);
    const skippedText = skipped ? `；已自动跳过 ${skipped} 条重复内容` : "";
    const ragCount = payload.job?.rag_experience_count ?? 0;
    renderCandidatePlaceholder("ok", "分析完成", `已整理出 ${ragCount} 条RAG经验${payload.job.candidate_count ? `，包含 ${payload.job.candidate_count} 条AI线索` : ""}${skippedText}。请到RAG经验池查看AI建议，再决定是否升级为待确认知识。`);
    selectView("rag_experiences");
    await loadRagExperiences();
  } catch (error) {
    renderCandidatePlaceholder("error", "分析失败", error.message || "请查看后台服务状态后重试。");
    throw error;
  } finally {
    setLearningBusy(false);
  }
}

async function loadCandidates() {
  if (!state.productCatalog) {
    await loadProductCatalog({loadDetail: false}).catch(() => {});
  }
  const payload = await apiGet("/api/candidates?status=pending");
  state.candidates = payload;
  const list = document.getElementById("candidate-list");
  const items = payload.items || [];
  const selectedId = state.selectedCandidate?.candidate_id || "";
  const selectedItem = items.find((item) => item.candidate_id === selectedId) || items[0] || null;
  state.selectedCandidate = selectedItem;
  updateCandidateCountBadge(items.length);
  list.innerHTML = (payload.items || [])
    .map((item, index) => {
      const candidateId = String(item.candidate_id || "");
      const activeAction = state.candidateActionLoadingIds.get(candidateId) || "";
      const isActionLoading = Boolean(activeAction);
      return `
        <div class="record-row candidate-row${state.selectedCandidate?.candidate_id === item.candidate_id ? " is-selected" : ""}" data-index="${index}">
          <button class="link-button candidate-select" data-index="${index}" ${isActionLoading ? "disabled" : ""}>
            <strong>${escapeHtml(candidateTitle(item))}</strong>
            <span>${escapeHtml(item.proposal?.summary || "")}${candidateIsIncomplete(item) ? " · 待补充" : ""}</span>
            <span class="source-line">来源：${escapeHtml(candidateSourceText(item))}</span>
            ${badgeListHtml(item.display_badges || [])}
          </button>
          <div class="inline-actions">
            <button class="secondary-button candidate-reject ${activeAction === "reject" ? "is-loading" : ""}" data-id="${escapeHtml(candidateId)}" ${isActionLoading ? "disabled" : ""}>${activeAction === "reject" ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>拒绝中</span>` : "拒绝"}</button>
            <button class="primary-button candidate-apply ${activeAction === "apply" ? "is-loading" : ""}" data-id="${escapeHtml(candidateId)}" ${item.can_promote === false || candidateIsIncomplete(item) || isActionLoading ? "disabled" : ""}>${activeAction === "apply" ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>入库中</span>` : "应用"}</button>
          </div>
        </div>
      `;
    })
    .join("") || `<div class="empty-state">暂无待审核候选</div>`;
  list.querySelectorAll(".candidate-select").forEach((button) => {
    button.addEventListener("click", () => {
      const item = payload.items[Number(button.dataset.index)];
      state.selectedCandidate = item;
      renderCandidateListSelection();
      renderCandidateDetail(item);
    });
  });
  list.querySelectorAll(".candidate-apply").forEach((button) => {
    button.addEventListener("click", () => applyCandidate(button.dataset.id).catch((error) => alert(error.message)));
  });
  list.querySelectorAll(".candidate-reject").forEach((button) => {
    button.addEventListener("click", () => rejectCandidate(button.dataset.id).catch((error) => alert(error.message)));
  });
  if (state.selectedCandidate) renderCandidateDetail(state.selectedCandidate);
  else clearCandidateDetail("暂无待审核候选");
}

function renderCandidateListSelection() {
  document.querySelectorAll("#candidate-list .candidate-row").forEach((row) => {
    const index = Number(row.dataset.index);
    const item = state.candidates?.items?.[index];
    row.classList.toggle("is-selected", Boolean(item && item.candidate_id === state.selectedCandidate?.candidate_id));
  });
}

function setLearningBusy(isBusy, uploadCount = 0) {
  state.learningInProgress = isBusy;
  const buttons = [document.getElementById("run-learning"), document.getElementById("run-learning-from-candidates")].filter(Boolean);
  for (const button of buttons) {
    button.disabled = isBusy;
    button.textContent = isBusy ? "整理中..." : "整理未处理资料";
  }
  if (isBusy) {
    renderCandidatePlaceholder(
      "loading",
      "正在整理上传资料",
      `正在分析 ${uploadCount} 个文件，整理出的内容会先进入RAG经验池。`
    );
  }
}

function renderCandidatePlaceholder(type, title, message) {
  const spinner = type === "loading" ? `<span class="loading-spinner" aria-hidden="true"></span>` : "";
  document.getElementById("candidate-detail").innerHTML = `
    <div class="status-card ${escapeHtml(type)}">
      <strong>${spinner}${escapeHtml(title)}</strong>
      <span>${escapeHtml(message)}</span>
    </div>
  `;
}

function clearCandidateDetail(message = "请选择左侧候选查看详情。") {
  state.selectedCandidate = null;
  document.getElementById("candidate-detail").innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function candidateTitle(item) {
  const patch = item.proposal?.formal_patch || {};
  const categoryId = patch.target_category || item.proposal?.target_category || "";
  const category = categoryById(categoryId);
  const data = patch.item?.data || item.proposal?.suggested_fields || {};
  const titleField = category?.schema?.item_title_field || "title";
  const title = data[titleField] || data.name || data.title || data.customer_message || item.proposal?.summary || item.candidate_id;
  return `${category?.name || categoryId || "知识"}：${title}`;
}

function candidateSourceText(item) {
  const summary = item?.source_summary || {};
  const parts = [summary.module, summary.channel, summary.detail].filter((part) => String(part || "").trim());
  if (parts.length) return parts.join(" · ");
  const sourceType = item?.source?.type || "";
  return sourceType ? sourceType : "未标注";
}

function updateCandidateCountBadge(count) {
  const value = Number(count || 0);
  for (const badge of [document.getElementById("candidate-tab-badge"), document.getElementById("candidate-nav-badge")]) {
    if (!badge) continue;
    badge.textContent = value > 99 ? "99+" : String(value);
    badge.classList.toggle("is-hidden", value <= 0);
  }
}

function updateRagExperienceCountBadge(count) {
  const value = Number(count || 0);
  for (const badge of [document.getElementById("rag-experience-tab-badge"), document.getElementById("rag-experience-nav-badge")]) {
    if (!badge) continue;
    badge.textContent = value > 99 ? "99+" : String(value);
    badge.classList.toggle("is-hidden", value <= 0);
  }
}

function unreviewedRagExperienceCount(items = []) {
  return items.filter((item) => {
    const status = String(item?.status || "active");
    if (status !== "active") return false;
    return !["kept", "auto_kept", "auto_triaged"].includes(experienceReviewStatus(item));
  }).length;
}

function candidateIsIncomplete(item) {
  return item?.intake?.status === "needs_more_info" || item?.review?.completeness_status === "needs_more_info";
}

function renderCandidateDetail(item) {
  const patch = item.proposal?.formal_patch || {};
  const intake = item.intake || {};
  const categoryId = patch?.target_category || item.proposal?.target_category || "";
  const category = categoryById(categoryId);
  const readable = candidateReadableSummary(item, category);
  const candidateId = String(item.candidate_id || "");
  const activeAction = state.candidateActionLoadingIds.get(candidateId) || "";
  const isActionLoading = Boolean(activeAction);
  const detail = document.getElementById("candidate-detail");
  detail.innerHTML = `
    <div class="approval-card ${candidateIsIncomplete(item) ? "warning" : ""}">
      <div>
        <p class="eyebrow">AI建议加入这条知识</p>
        <h2>${escapeHtml(readable.title)}</h2>
        <p>${escapeHtml(readable.summary)}</p>
        ${badgeListHtml(item.display_badges || [])}
      </div>
      <div class="approval-actions">
        <button class="primary-button candidate-apply-detail ${activeAction === "apply" ? "is-loading" : ""}" data-id="${escapeHtml(candidateId)}" ${item.can_promote === false || candidateIsIncomplete(item) || isActionLoading ? "disabled" : ""}>${activeAction === "apply" ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>入库中</span>` : "确认加入知识库"}</button>
        <button class="secondary-button candidate-reject-detail ${activeAction === "reject" ? "is-loading" : ""}" data-id="${escapeHtml(candidateId)}" ${isActionLoading ? "disabled" : ""}>${activeAction === "reject" ? `<span class="loading-spinner button-spinner" aria-hidden="true"></span><span>处理中</span>` : "不要这条"}</button>
      </div>
    </div>
    <div class="plain-fact-grid">
      <div><span>知识类型</span><strong>${escapeHtml(readable.type)}</strong></div>
      <div><span>从哪里来</span><strong>${escapeHtml(candidateSourceText(item))}</strong></div>
      <div><span>当前状态</span><strong>${escapeHtml(candidateIsIncomplete(item) ? "还缺信息" : "内容已完善")}</strong></div>
      <div><span>确认后放到</span><strong>${escapeHtml(readable.target)}</strong></div>
    </div>
    ${candidateMissingHtml(item)}
    ${candidatePreviewHtml(item, category)}
    ${candidateLlmAssistHtml(item)}
    ${candidateRagEvidenceHtml(item)}
    ${candidateSupplementHtml(item, patch)}
  `;
  bindDynamicEditors(detail);
  detail.querySelector(".candidate-apply-detail")?.addEventListener("click", (event) => {
    applyCandidate(event.currentTarget.dataset.id).catch((error) => alert(error.message));
  });
  detail.querySelector(".candidate-reject-detail")?.addEventListener("click", (event) => {
    rejectCandidate(event.currentTarget.dataset.id).catch((error) => alert(error.message));
  });
  detail.querySelector(".candidate-category-change")?.addEventListener("click", () => {
    changeCandidateCategory(item.candidate_id).catch((error) => alert(error.message));
  });
  detail.querySelector(".candidate-supplement-save")?.addEventListener("click", () => {
    saveCandidateSupplement(item.candidate_id, patch.target_category).catch((error) => alert(error.message));
  });
}

function candidateLlmAssistHtml(item) {
  const assist = item.review?.llm_assist || {};
  if (!assist.policy_version) return "";
  const status = assist.status || "";
  const usedModel = status === "model_generated";
  const statusText = {
    model_generated: "已用大模型辅助判断",
    rule_fallback_after_llm: "已尝试大模型，当前为规则兜底",
    rule_only_disabled_by_request: "本次未启用大模型，仅规则兜底",
  }[status] || "AI辅助状态已记录";
  const reason = assist.reason || (usedModel ? "大模型已参与分类、提取和审核建议。" : "大模型不可用或未返回合格结果，系统保留规则结果供人工确认。");
  return `
    <div class="status-card ${usedModel ? "ok" : "warning"}">
      <strong>${escapeHtml(statusText)}</strong>
      <span>${escapeHtml(reason)}</span>
      ${assist.recommended_action ? `<small>AI建议：${escapeHtml(actionLabelFromValue(assist.recommended_action))}</small>` : ""}
    </div>
  `;
}

function candidateRagEvidenceHtml(item) {
  const evidence = item.review?.rag_evidence || {};
  const hits = evidence.hits || [];
  if (!evidence.enabled) return "";
  return `
    <details class="candidate-rag">
      <summary>查看AI参考来源</summary>
      ${hits.length ? hits.map((hit) => `
        <div class="read-field wide-field rag-hit">
          <span>${escapeHtml(hit.category || "资料片段")} · ${escapeHtml(hit.score || "")}</span>
          <p>${escapeHtml(readableSourcePlainText(hit.text || ""))}</p>
        </div>
      `).join("") : `<div class="empty-state">没有可展示的参考资料片段。</div>`}
    </details>
  `;
}

function candidateSupplementHtml(item, patch) {
  const categoryId = patch?.target_category || item.proposal?.target_category || "";
  const category = categoryById(categoryId);
  const data = patch?.item?.data || item.proposal?.suggested_fields || {};
  if (!category?.schema?.fields) {
    return `
      <div class="status-card warning">
        <strong>无法补充</strong>
        <span>当前候选没有匹配到可编辑的知识门类，请先确认目标库是否存在。</span>
      </div>
    `;
  }
  const missing = new Set([...(item.intake?.missing_fields || []), ...(item.review?.missing_fields || [])]);
  const fields = category.schema.fields.map((field) => missing.has(field.id) ? {...field, required: true} : field);
  const readonlyFields = isProductScopedCategory(category) ? new Set(["product_id"]) : new Set();
  const categoryOptions = candidateEditableCategories(categoryId)
    .map((candidateCategory) => `<option value="${escapeHtml(candidateCategory.id)}" ${candidateCategory.id === categoryId ? "selected" : ""}>${escapeHtml(candidateCategory.name || candidateCategory.id)}</option>`)
    .join("");
  return `
    <details class="candidate-supplement-panel candidate-edit-details">
      <summary class="candidate-edit-summary">
        <div>
          <span>修改这条知识</span>
          <strong>有错就直接改；缺信息就补上。保存后系统会重新判断是否可以加入知识库。</strong>
        </div>
        <span class="candidate-edit-toggle">点击展开</span>
      </summary>
      <div class="candidate-edit-body">
        <div class="candidate-category-tools">
          <label class="form-field">
            <span>这条知识的类型</span>
            <select id="candidate-category-target">${categoryOptions}</select>
          </label>
          <button class="secondary-button candidate-category-change" type="button">换成这个类型</button>
          <div class="category-help-line">商品专属问答、规则、解释必须先绑定到某个商品，不能在这里随意切换；请从商品库的商品详情里编辑。</div>
        </div>
        <div id="candidate-supplement-form" class="form-grid" data-candidate-id="${escapeHtml(item.candidate_id)}" data-category="${escapeHtml(categoryId)}">
          ${fields.map((field) => fieldHtml(field, data?.[field.id], {readonlyFields, categoryId: category.id, productName: productDisplayName(data?.product_id) || data?.product_id || ""})).join("")}
        </div>
        <div class="inline-actions candidate-supplement-actions">
          <button class="primary-button candidate-supplement-save" type="button">保存修改</button>
        </div>
      </div>
    </details>
  `;
}

async function changeCandidateCategory(candidateId) {
  const select = document.getElementById("candidate-category-target");
  const targetCategory = select?.value || "";
  if (!targetCategory) throw new Error("请选择目标类型");
  const payload = await apiJson(`/api/candidates/${encodeURIComponent(candidateId)}/category`, {
    method: "POST",
    body: JSON.stringify({target_category: targetCategory}),
  });
  if (!payload.ok) throw new Error(payload.message || "候选类型切换失败");
  state.selectedCandidate = payload.item;
  renderCandidateDetail(payload.item);
  await loadCandidates();
}

async function saveCandidateSupplement(candidateId, categoryId) {
  const category = categoryById(categoryId);
  const form = document.getElementById("candidate-supplement-form");
  if (!category || !form) throw new Error("没有找到候选补充表单");
  const data = {};
  for (const field of category.schema?.fields || []) {
    data[field.id] = collectFieldValue(field, form);
  }
  validateClientKnowledge(category, data);
  const payload = await apiJson(`/api/candidates/${encodeURIComponent(candidateId)}/supplement`, {
    method: "POST",
    body: JSON.stringify({data}),
  });
  if (!payload.ok) throw new Error(payload.message || "候选补充失败");
  state.selectedCandidate = payload.item;
  renderCandidateDetail(payload.item);
  await loadCandidates();
}

async function applyCandidate(candidateId) {
  if (!candidateId) return;
  if (state.candidateActionLoadingIds.has(candidateId)) return;
  if (!confirm(`确认应用候选 ${candidateId}？应用前会自动创建备份。`)) return;
  state.candidateActionLoadingIds.set(candidateId, "apply");
  if (state.selectedCandidate?.candidate_id === candidateId) renderCandidateDetail(state.selectedCandidate);
  await loadCandidates().catch(() => {});
  try {
    const payload = await apiJson(`/api/candidates/${encodeURIComponent(candidateId)}/apply`, {method: "POST"});
    if (!payload.ok) throw new Error(payload.message || "候选应用失败，请查看详情后补充、合并或拒绝。");
    renderDiagnostics(payload);
    clearCandidateDetail("已应用入库，候选已移出待审核列表。");
    await Promise.all([loadCandidates(), loadOverview(), loadKnowledge(), loadVersions()]);
  } finally {
    state.candidateActionLoadingIds.delete(candidateId);
    await loadCandidates().catch(() => {});
  }
}

async function rejectCandidate(candidateId) {
  if (!candidateId) return;
  if (state.candidateActionLoadingIds.has(candidateId)) return;
  const reasonInput = prompt("拒绝原因", "不适合写入正式知识库");
  if (reasonInput === null) return;
  const reason = reasonInput.trim() || "rejected in admin";
  state.candidateActionLoadingIds.set(candidateId, "reject");
  if (state.selectedCandidate?.candidate_id === candidateId) renderCandidateDetail(state.selectedCandidate);
  await loadCandidates().catch(() => {});
  try {
    await apiJson(`/api/candidates/${encodeURIComponent(candidateId)}/reject`, {
      method: "POST",
      body: JSON.stringify({reason}),
    });
    clearCandidateDetail("已拒绝该候选，候选已移出待审核列表。");
    await Promise.all([loadCandidates(), loadOverview()]);
  } finally {
    state.candidateActionLoadingIds.delete(candidateId);
    await loadCandidates().catch(() => {});
  }
}

async function loadRecorder() {
  const [summaryPayload, conversationsPayload] = await Promise.all([
    apiGet("/api/recorder/summary"),
    apiGet("/api/recorder/conversations?status=all"),
  ]);
  state.recorderSummary = summaryPayload.item || {};
  state.recorderConversations = conversationsPayload.items || [];
  if (
    state.selectedRecorderConversation?.conversation_id &&
    !state.recorderConversations.some((item) => item.conversation_id === state.selectedRecorderConversation.conversation_id)
  ) {
    state.selectedRecorderConversation = null;
  }
  state.selectedRecorderConversation = state.selectedRecorderConversation || state.recorderConversations[0] || null;
  await loadRecorderMessages(false);
  renderRecorder();
}

async function loadRecorderMessages(shouldRender = true) {
  if (!state.selectedRecorderConversation?.conversation_id) {
    state.recorderMessages = [];
    if (shouldRender) renderRecorderDetail();
    return;
  }
  const payload = await apiGet(`/api/raw-messages/messages?conversation_id=${encodeURIComponent(state.selectedRecorderConversation.conversation_id)}&limit=80`);
  state.recorderMessages = payload.items || [];
  if (shouldRender) renderRecorderDetail();
}

function renderRecorder() {
  const summary = state.recorderSummary || {};
  const raw = summary.raw || {};
  const settings = summary.settings || {};
  document.getElementById("recorder-notify").checked = Boolean(settings.notify_on_collect);
  document.getElementById("recorder-auto-learn").checked = settings.auto_learn !== false;
  document.getElementById("recorder-use-llm").checked = settings.use_llm !== false;
  document.getElementById("recorder-cards").innerHTML = `
    <div class="metric-card"><span>${raw.group_count ?? 0}</span><label>识别群聊</label></div>
    <div class="metric-card"><span>${summary.selected_conversation_count ?? summary.selected_group_count ?? 0}</span><label>正在记录</label></div>
    <div class="metric-card"><span>${raw.message_count ?? 0}</span><label>原始消息</label></div>
    <div class="metric-card"><span>${raw.pending_batch_count ?? 0}</span><label>待整理批次</label></div>
  `;
  renderRecorderGroupList();
  renderRecorderDetail();
}

function renderRecorderGroupList() {
  const list = document.getElementById("recorder-group-list");
  const items = state.recorderConversations || [];
  list.innerHTML = items.length ? items.map((item, index) => {
    const active = state.selectedRecorderConversation?.conversation_id === item.conversation_id ? " is-selected" : "";
    const selected = Boolean(item.selected_by_user);
    return `
      <div class="record-row recorder-row${active}" data-index="${index}">
        <button class="link-button recorder-select" data-index="${index}">
          <strong>${escapeHtml(item.display_name || item.target_name || item.conversation_id)}</strong>
          <span>${escapeHtml(formatRecorderConversationStatus(item))}</span>
          ${badgeListHtml([{key: item.conversation_type || "unknown", label: recorderConversationTypeLabel(item.conversation_type), tone: "info"}, ...(selected ? [{key: "recording", label: "记录中", tone: "ok"}] : [{key: "paused", label: "未选择", tone: "muted"}])])}
        </button>
        <div class="inline-actions">
          <button class="secondary-button recorder-toggle" data-id="${escapeHtml(item.conversation_id)}" data-selected="${selected ? "0" : "1"}">${selected ? "停止" : "记录"}</button>
        </div>
      </div>
    `;
  }).join("") : `<div class="empty-state">尚未识别到群聊。点击“识别群列表”后，再选择需要记录的群。</div>`;
  list.querySelectorAll(".recorder-select").forEach((button) => {
    button.addEventListener("click", async () => {
      state.selectedRecorderConversation = items[Number(button.dataset.index)] || null;
      renderRecorderGroupList();
      await loadRecorderMessages();
    });
  });
  list.querySelectorAll(".recorder-toggle").forEach((button) => {
    button.addEventListener("click", () => updateRecorderConversation(button.dataset.id, {selected_by_user: button.dataset.selected === "1"}).catch((error) => alert(error.message)));
  });
}

function candidateReadableSummary(item, category) {
  const patch = item.proposal?.formal_patch || {};
  const data = patch.item?.data || item.proposal?.suggested_fields || {};
  const categoryName = category?.name || patch.target_category || "知识";
  const titleField = category?.schema?.item_title_field || "title";
  const title = data[titleField] || data.name || data.title || data.customer_message || item.proposal?.summary || item.candidate_id;
  const summary = plainCandidateSummary(data, patch.target_category || category?.id || "", item.proposal?.summary || "");
  return {
    title: String(title || item.candidate_id),
    type: categoryName,
    target: categoryName,
    summary,
  };
}

function plainCandidateSummary(data, categoryId, fallback) {
  if (categoryId === "products") {
    const parts = [
      data.price ? `价格 ${data.price}${data.unit ? `/${data.unit}` : ""}` : "",
      data.inventory !== undefined && data.inventory !== "" ? `库存 ${data.inventory}` : "",
      data.category ? `类目 ${data.category}` : "",
    ].filter(Boolean);
    return parts.length ? parts.join("，") : (fallback || "这是一条商品资料。");
  }
  if (categoryId === "policies") return data.answer || fallback || "这是一条规则或政策。";
  if (categoryId === "chats") return data.service_reply || fallback || "这是一条客服话术。";
  if (categoryId === "product_faq" || categoryId === "product_rules") return data.answer || fallback || "这是一条商品专属知识。";
  if (categoryId === "product_explanations") return data.content || fallback || "这是一条商品专属说明。";
  return fallback || "这是一条可加入知识库的内容。";
}

function candidateMissingHtml(item) {
  const intake = item.intake || {};
  const missing = (intake.missing_labels || intake.missing_fields || []).filter(Boolean);
  const warnings = [...(intake.warnings || []), ...(item.proposal?.warnings || [])].filter(Boolean);
  if (!missing.length && !warnings.length && !intake.question) return "";
  return `
    <div class="status-card ${missing.length ? "warning" : ""}">
      <strong>${missing.length ? "还需要补充一点信息" : "需要留意"}</strong>
      <span>${escapeHtml(missing.length ? `缺少：${missing.join("、")}` : warnings.join("、"))}</span>
      ${intake.question ? `<p>${escapeHtml(intake.question)}</p>` : ""}
    </div>
  `;
}

function candidateEditableCategories(currentCategoryId) {
  const normal = state.categories.filter((category) => category.scope !== "tenant_product");
  const current = categoryById(currentCategoryId);
  if (current?.scope === "tenant_product" && !normal.some((category) => category.id === current.id)) {
    return [current, ...normal];
  }
  return normal;
}

function candidatePreviewHtml(item, category) {
  const patch = item.proposal?.formal_patch || {};
  const data = patch.item?.data || item.proposal?.suggested_fields || {};
  const fields = (category?.schema?.fields || []).filter((field) => hasDisplayValue(data[field.id]));
  if (!fields.length) return "";
  return `
    <div class="preview-panel">
      <div class="section-heading"><div><span>这条知识的主要内容</span><strong>请先看这里，判断有没有错误。</strong></div></div>
      <div class="read-grid">
        ${fields.slice(0, 8).map((field) => `<div class="read-field ${field.type === "long_text" ? "wide-field" : ""}"><span>${escapeHtml(field.label || field.id)}</span><p>${escapeHtml(displayValue(data[field.id]))}</p></div>`).join("")}
      </div>
    </div>
  `;
}

function hasDisplayValue(value) {
  if (value === undefined || value === null || value === "") return false;
  if (Array.isArray(value) && !value.length) return false;
  if (typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length) return false;
  return true;
}

function displayValue(value) {
  if (Array.isArray(value)) {
    return value
      .filter((inner) => hasDisplayValue(inner))
      .map((inner) => {
        if (typeof inner === "object" && inner !== null) {
          return Object.entries(inner)
            .filter(([, nested]) => hasDisplayValue(nested))
            .map(([key, nested]) => `${fieldLabel({id: key, label: key})}：${displayValue(nested)}`)
            .join("，");
        }
        return displayValue(inner);
      })
      .join("；");
  }
  if (typeof value === "object" && value !== null) {
    return Object.entries(value)
      .filter(([, inner]) => hasDisplayValue(inner))
      .map(([key, inner]) => `${fieldLabel({id: key, label: key})}：${displayValue(inner)}`)
      .join("；");
  }
  return String(value ?? "");
}

function renderRecorderDetail() {
  const detail = document.getElementById("recorder-detail");
  const conversation = state.selectedRecorderConversation;
  if (!conversation) {
    detail.innerHTML = `<div class="empty-state">请选择一个群查看最近记录。</div>`;
    return;
  }
  detail.innerHTML = `
    <div class="read-head">
      <div>
        <p class="eyebrow">${escapeHtml(recorderConversationTypeLabel(conversation.conversation_type))}记录</p>
        <h2>${escapeHtml(conversation.display_name || conversation.target_name || conversation.conversation_id)}</h2>
        ${badgeListHtml([{key: conversation.conversation_type || "unknown", label: recorderConversationTypeLabel(conversation.conversation_type), tone: "info"}, ...(conversation.selected_by_user ? [{key: "recording", label: "记录中", tone: "ok"}] : [{key: "paused", label: "未选择", tone: "muted"}])])}
      </div>
      <button class="secondary-button recorder-refresh-messages" type="button">刷新消息</button>
    </div>
    <div class="compact-list compact-list-small">
      ${(state.recorderMessages || []).map((item) => `
        <div class="compact-row">
          <strong>${escapeHtml(item.sender || item.sender_role || "unknown")}</strong>
          <span>${escapeHtml(item.message_time || item.observed_at || "")}</span>
          <p>${escapeHtml(item.content || "")}</p>
        </div>
      `).join("") || `<div class="empty-state">暂无原始消息。</div>`}
    </div>
  `;
  detail.querySelector(".recorder-refresh-messages")?.addEventListener("click", () => loadRecorderMessages().catch((error) => alert(error.message)));
}

function formatRecorderConversationStatus(item) {
  const parts = [item.status || "active"];
  if (item.notify_enabled) parts.push("群内提示");
  if (item.learning_enabled === false) parts.push("仅记录");
  return parts.join(" · ");
}

function recorderConversationTypeLabel(value) {
  const text = String(value || "");
  if (text === "group") return "群聊";
  if (text === "file_transfer") return "文件传输助手";
  if (text === "private") return "私聊";
  if (text === "system") return "系统会话";
  return "未知会话";
}

async function saveRecorderSettings() {
  const payload = await apiJson("/api/recorder/settings", {
    method: "PUT",
    body: JSON.stringify({
      notify_on_collect: document.getElementById("recorder-notify").checked,
      auto_learn: document.getElementById("recorder-auto-learn").checked,
      use_llm: document.getElementById("recorder-use-llm").checked,
    }),
  });
  state.recorderSummary = {...(state.recorderSummary || {}), settings: payload.item || {}};
  renderRecorder();
}

async function discoverRecorderSessions() {
  const result = await apiJson("/api/recorder/discover", {method: "POST", body: "{}"});
  if (!result.ok) alert("未能连接微信主窗口，请确认微信已登录并保持主窗口可见。");
  await loadRecorder();
}

async function captureRecorderNow() {
  const result = await apiJson("/api/recorder/capture", {method: "POST", body: JSON.stringify({send_notifications: true})});
  await loadRecorder();
  alert(`本轮记录完成：新增 ${result.inserted_count || 0} 条消息。`);
}

async function updateRecorderConversation(conversationId, patch) {
  if (!conversationId) return;
  await apiJson(`/api/recorder/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  await loadRecorder();
}

async function downloadKnowledgeExport(sortBy) {
  const response = await fetch(`/api/exports/knowledge/download?sort_by=${encodeURIComponent(sortBy)}`, {headers: apiHeaders()});
  if (!response.ok) throw new Error(await responseErrorMessage(response, "/api/exports/knowledge/download"));
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || `knowledge_${sortBy}.xlsx`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function runDiagnostics(mode) {
  const payload = await apiJson("/api/diagnostics/run", {method: "POST", body: JSON.stringify({mode})});
  renderDiagnostics(payload);
}

function renderDiagnostics(payload) {
  const issues = payload.issues || payload.validation?.issues || [];
  const status = payload.status || (payload.ok ? "ok" : "error");
  const hasRepairable = issues.some((issue) => issue.repairable || issue.auto_repair);
  const repairButton = payload.run_id && hasRepairable
    ? `<button class="secondary-button diagnostic-repair" data-run-id="${escapeHtml(payload.run_id)}">一键修复</button>`
    : "";
  const ignored = payload.ignored_count || payload.summary?.ignored_count || 0;
  const clearButton = ignored
    ? `<button class="secondary-button diagnostic-clear-notices">清除提示记录</button>`
    : "";
  document.getElementById("diagnostics-report").innerHTML = `
    <div class="status-card ${status}"><strong>${escapeHtml(diagnosticStatusTitle(status, issues))}</strong><span>${escapeHtml(diagnosticSummaryText(payload, issues))}${ignored ? ` · 已忽略 ${ignored} 条` : ""}</span></div>
    ${payload.run_id ? `<div class="issue-meta diagnostic-run-meta"><span>检测编号</span><strong>${escapeHtml(payload.run_id)}</strong></div>` : ""}
    ${repairButton}
    ${clearButton}
    ${issues.length ? issues.map(issueHtml).join("") : `<div class="empty-state">未发现故障</div>`}
  `;
  document.querySelectorAll(".diagnostic-repair").forEach((button) => {
    button.addEventListener("click", () => applyDiagnosticRepair(button.dataset.runId).catch((error) => alert(error.message)));
  });
  document.querySelectorAll(".diagnostic-ignore").forEach((button) => {
    button.addEventListener("click", () => ignoreDiagnosticIssue(button.dataset.fingerprint).catch((error) => alert(error.message)));
  });
  document.querySelectorAll(".diagnostic-open").forEach((button) => {
    button.addEventListener("click", () => openDiagnosticTarget(button.dataset.target, button.dataset.targets).catch((error) => alert(error.message)));
  });
  document.querySelectorAll(".diagnostic-toggle").forEach((button) => {
    button.addEventListener("click", () => toggleDiagnosticDetails(button));
  });
  document.querySelectorAll(".diagnostic-clear-notices").forEach((button) => {
    button.addEventListener("click", () => clearDiagnosticNotices().catch((error) => alert(error.message)));
  });
}

function issueHtml(issue) {
  const target = issue.target || "";
  const targetLabel = issue.target_label || target || "未指定位置";
  const detailId = safeDomId(`diagnostic-detail-${issue.fingerprint || Math.random().toString(16).slice(2)}`);
  const hasDetails = hasDiagnosticDetails(issue);
  const highlightTargets = diagnosticTargets(issue).join("|");
  return `
    <div class="issue-row ${escapeHtml(issue.severity || "warning")}">
      <div class="issue-main">
        ${hasDetails
          ? `<button class="link-button diagnostic-title-toggle diagnostic-toggle" data-target="${escapeHtml(detailId)}"><strong>${escapeHtml(issue.title || "问题")}</strong><small>点击查看具体原因</small></button>`
          : `<strong>${escapeHtml(issue.title || "问题")}</strong>`}
        <span>${escapeHtml(targetLabel)}</span>
        <p>${escapeHtml(issue.detail || "")}</p>
        ${hasDetails ? diagnosticDetailHtml(issue, detailId) : ""}
      </div>
      <div class="inline-actions vertical-actions">
        ${hasDetails ? `<button class="secondary-button diagnostic-toggle" data-target="${detailId}">展开详情</button>` : ""}
        ${target ? `<button class="secondary-button diagnostic-open" data-target="${escapeHtml(target)}" data-targets="${escapeHtml(highlightTargets)}">查看位置</button>` : ""}
        ${issue.code === "knowledge_token_budget_large" ? `<button class="secondary-button diagnostic-clear-notices">彻底消去提示</button>` : ""}
        ${issue.fingerprint ? `<button class="secondary-button diagnostic-ignore" data-fingerprint="${escapeHtml(issue.fingerprint)}">标记忽略</button>` : ""}
      </div>
    </div>
  `;
}

function diagnosticStatusTitle(status, issues) {
  if (issues?.length) return "需要关注";
  if (status === "ok") return "检测通过";
  if (status === "warning") return "需要关注";
  if (status === "error") return "检测异常";
  return statusText(status);
}

function diagnosticSummaryText(payload, issues) {
  if (payload.message) return payload.message;
  if (issues?.length) return `发现 ${issues.length} 个需要关注的问题，下面可以展开详情或直接跳到对应知识。`;
  return "检测完成，未发现需要处理的问题。";
}

function diagnosticTargets(issue) {
  const targets = new Set();
  if (issue.target) targets.add(String(issue.target));
  for (const detail of issue.details || []) {
    const value = String(detail.value || "");
    const match = value.match(/([A-Za-z0-9_-]+\/[A-Za-z0-9_.-]+)/);
    if (match) targets.add(match[1]);
  }
  return Array.from(targets);
}

function parseDiagnosticTargets(value) {
  return String(value || "").split("|").map((item) => item.trim()).filter(Boolean);
}

function diagnosticTargetMatches(categoryId, itemId) {
  const target = `${categoryId || ""}/${itemId || ""}`;
  return Boolean(state.diagnosticHighlight?.targets?.includes(target));
}

function safeDomId(value) {
  return String(value || "diagnostic-detail").replace(/[^A-Za-z0-9_-]/g, "-");
}

function hasDiagnosticDetails(issue) {
  return Boolean((issue.details || []).length || (issue.suggestions || []).length || issue.code || issue.fingerprint);
}

function diagnosticDetailHtml(issue, detailId) {
  const details = issue.details || [];
  const suggestions = issue.suggestions || [];
  return `
    <div class="issue-detail-panel is-hidden" id="${detailId}">
      ${issue.code ? `<div class="issue-meta"><span>检测类型</span><strong>${escapeHtml(issue.code)}</strong></div>` : ""}
      ${issue.fingerprint ? `<div class="issue-meta"><span>问题指纹</span><strong>${escapeHtml(issue.fingerprint)}</strong></div>` : ""}
      ${details.length ? `
        <div class="issue-detail-grid">
          ${details.map((item) => `
            <div class="issue-detail-item ${escapeHtml(item.level || "normal")}">
              <span>${escapeHtml(item.label || "详情")}</span>
              <strong>${escapeHtml(item.value ?? "")}</strong>
            </div>
          `).join("")}
        </div>
      ` : ""}
      ${suggestions.length ? `
        <div class="issue-suggestions">
          ${suggestions.map((item) => `
            <div class="issue-suggestion ${escapeHtml(item.level || "normal")}">
              <strong>${escapeHtml(item.title || "建议")}</strong>
              <p>${escapeHtml(item.detail || "")}</p>
            </div>
          `).join("")}
        </div>
      ` : ""}
    </div>
  `;
}

function toggleDiagnosticDetails(button) {
  const id = button.dataset.target;
  const panel = id ? document.getElementById(id) : null;
  if (!panel) return;
  const hidden = panel.classList.toggle("is-hidden");
  button.textContent = hidden ? "展开详情" : "收起详情";
}

async function openDiagnosticTarget(target, highlightTargets = "") {
  if (!target) return;
  const [categoryId, itemId] = String(target).split("/");
  if (!categoryId) return;
  state.diagnosticHighlight = {targets: parseDiagnosticTargets(highlightTargets || target)};
  selectView("knowledge", {keepDiagnosticHighlight: true});
  if (!state.categories.length) {
    await loadKnowledge();
  }
  if (!state.categories.some((category) => category.id === categoryId)) return;
  state.activeCategoryId = categoryId;
  renderCategorySelect();
  await loadCategoryItems();
  if (itemId) {
    const item = state.categoryItems.find((entry) => entry.id === itemId);
    if (item) {
      state.selectedKnowledge = item;
      state.knowledgeMode = "view";
      renderKnowledgeList();
      renderKnowledgeDetail();
    }
  }
}

async function ignoreDiagnosticIssue(fingerprint) {
  if (!fingerprint) return;
  const reason = prompt("忽略原因", "确认该问题可接受") || "ignored";
  await apiJson("/api/diagnostics/ignore", {method: "POST", body: JSON.stringify({fingerprint, reason})});
  await runDiagnostics("quick");
}

async function applyDiagnosticRepair(runId) {
  if (!runId) return;
  const payload = await apiJson(`/api/diagnostics/runs/${encodeURIComponent(runId)}/apply-suggestion`, {method: "POST", body: JSON.stringify({source: "admin_console"})});
  renderDiagnostics(payload);
}

async function clearDiagnosticNotices() {
  const payload = await apiJson("/api/diagnostics/clear-notices", {method: "POST", body: JSON.stringify({code: "knowledge_token_budget_large"})});
  renderDiagnostics(payload);
}

async function loadVersions() {
  const payload = await apiGet("/api/versions");
  const items = (payload.items || []).slice(0, 20);
  document.getElementById("version-list").innerHTML = items
    .map((item) => `
      <div class="record-row version-row">
        <button class="link-button version-select" data-id="${escapeHtml(item.version_id)}">
          <strong>${escapeHtml(item.reason)}</strong>
          <span>${escapeHtml(item.version_id)} · ${escapeHtml(item.created_at)}</span>
        </button>
        <div class="inline-actions">
          <button class="secondary-button version-download" data-id="${escapeHtml(item.version_id)}">下载</button>
          <button class="secondary-button version-rollback" data-id="${escapeHtml(item.version_id)}">还原</button>
        </div>
      </div>
    `)
    .join("") || `<div class="empty-state">暂无备份快照</div>`;
  document.querySelectorAll(".version-rollback").forEach((button) => {
    button.addEventListener("click", () => rollbackVersion(button.dataset.id).catch((error) => alert(error.message)));
  });
  document.querySelectorAll(".version-download").forEach((button) => {
    button.addEventListener("click", () => downloadVersion(button.dataset.id).catch((error) => alert(error.message)));
  });
}

async function createBackup() {
  if (!confirm("确认立即备份当前知识库状态吗？")) return;
  await apiJson("/api/versions", {method: "POST", body: JSON.stringify({reason: "manual backup from admin console"})});
  await loadVersions();
}

async function downloadVersion(versionId) {
  if (!versionId) return;
  const response = await fetch(`/api/versions/${encodeURIComponent(versionId)}/download`, {headers: apiHeaders()});
  if (!response.ok) throw new Error(await responseErrorMessage(response, "/api/versions/download"));
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${versionId}_complete_backup.zip`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function rollbackVersion(versionId) {
  if (!versionId) return;
  if (!confirm(`确认还原到版本 ${versionId}？当前知识会先自动备份。`)) return;
  const payload = await apiJson(`/api/versions/${encodeURIComponent(versionId)}/rollback`, {method: "POST"});
  renderDiagnostics(payload);
  selectView("diagnostics");
  await Promise.all([loadOverview(), loadKnowledge(), loadVersions()]);
}

function statusText(status) {
  if (status === "ok") return "检测通过";
  if (status === "warning") return "需要关注";
  if (status === "error") return "发现故障";
  return status || "完成";
}

function summaryFields(fields) {
  return Object.entries(fields)
    .map(([key, value]) => `${fieldLabel({id: key, label: key})}: ${displayBusinessValue(value)}`)
    .join("；") || "无";
}

function displayBusinessValue(value) {
  if (isEmpty(value)) return "";
  if (Array.isArray(value)) {
    if (value.every((item) => item && typeof item === "object")) {
      return value
        .map((item) => Object.entries(item)
          .filter(([, inner]) => !isEmpty(inner))
          .map(([key, inner]) => `${fieldLabel({id: key, label: key})}: ${displayBusinessValue(inner)}`)
          .join("，"))
        .filter(Boolean)
        .join("；");
    }
    return value.map(displayBusinessValue).filter(Boolean).join("、");
  }
  if (typeof value === "object") {
    return Object.entries(value)
      .filter(([, inner]) => !isEmpty(inner))
      .map(([key, inner]) => `${templateLabels[key] || fieldLabel({id: key, label: key})}: ${displayBusinessValue(inner)}`)
      .join("；");
  }
  return String(value);
}

function optionLabel(fieldId, value) {
  return optionLabels[fieldId]?.[value] || value || "";
}

function fieldLabel(field) {
  return fieldLabelOverrides[field.id] || field.label || field.id;
}

function displayTags(value) {
  return Array.isArray(value) ? value.join("\n") : value || "";
}

function splitTags(value) {
  return value ? value.split(/[,，、\n]+/).map((item) => item.trim()).filter(Boolean) : [];
}

function numberOrNull(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function defaultFieldValue(field) {
  if (field.default !== undefined) return field.default;
  if (field.type === "tags" || field.type === "table") return [];
  if (field.type === "object") return {};
  if (field.type === "boolean") return false;
  return "";
}

function businessSearchText(data) {
  return Object.values(data).map(displayBusinessValue).join(" ");
}

function isEmpty(value) {
  return value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length) || (typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length);
}

function setHidden(id, hidden) {
  const element = document.getElementById(id);
  if (element) element.classList.toggle("is-hidden", hidden);
}

function setChecked(id, checked) {
  const element = document.getElementById(id);
  if (element) element.checked = Boolean(checked);
}

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(value);
  return String(value).replaceAll('"', '\\"');
}

function badgeListHtml(badges) {
  const items = Array.isArray(badges) ? badges : [];
  if (!items.length) return "";
  return `
    <div class="badge-list">
      ${items.map((item) => `<span class="badge ${escapeHtml(item.tone || "muted")}">${escapeHtml(item.label || item.key || "")}</span>`).join("")}
    </div>
  `;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function acknowledgeKnowledgeItem() {
  if (!state.selectedKnowledge?.id || !state.activeCategoryId) return;
  await apiJson(`/api/knowledge/categories/${encodeURIComponent(state.activeCategoryId)}/items/${encodeURIComponent(state.selectedKnowledge.id)}/acknowledge`, {
    method: "POST",
    body: "{}",
  });
  await Promise.all([loadCategoryItems(), loadOverview()]);
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

async function changeLocalPassword(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  if (state.passwordChallenge) {
    await apiJson("/api/auth/change-password/verify", {
      method: "POST",
      body: JSON.stringify({challenge_id: state.passwordChallenge.challenge_id, code: form.get("email_code")}),
    });
    state.passwordChallenge = null;
    formElement.reset();
    document.getElementById("local-password-code-field")?.classList.add("is-hidden");
    formElement.querySelector("button[type='submit']").textContent = "发送验证码并修改";
    alert("密码已修改，请用新密码重新登录。");
    await logoutLocal();
    return;
  }
  if (form.get("new_password") !== form.get("confirm_password")) {
    alert("两次输入的新密码不一致。");
    return;
  }
  const result = await apiJson("/api/auth/change-password/start", {
    method: "POST",
    body: JSON.stringify({
      current_password: form.get("current_password"),
      new_password: form.get("new_password"),
    }),
  });
  state.passwordChallenge = {challenge_id: result.challenge_id};
  document.getElementById("local-password-code-field")?.classList.remove("is-hidden");
  formElement.querySelector("button[type='submit']").textContent = "验证并保存新密码";
  alert(
    result.debug_code
      ? `验证码已生成：${result.debug_code}。生产环境会发送到 ${result.masked_email || "绑定邮箱"}。`
      : `验证码已发送到 ${result.masked_email || "绑定邮箱"}，请输入后保存新密码。`
  );
}

async function bindLocalEmail(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  if (state.emailChallenge) {
    const result = await apiJson("/api/auth/email/verify", {
      method: "POST",
      body: JSON.stringify({challenge_id: state.emailChallenge.challenge_id, code: form.get("email_code")}),
    });
    state.emailChallenge = null;
    formElement.reset();
    document.getElementById("local-email-code-field")?.classList.add("is-hidden");
    formElement.querySelector("button[type='submit']").textContent = "发送绑定验证码";
    state.security = {...(state.security || {}), email: result.email, masked_email: result.masked_email};
    renderLocalSecurity();
    alert("邮箱已绑定。");
    return;
  }
  const result = await apiJson("/api/auth/email/start", {
    method: "POST",
    body: JSON.stringify({email: form.get("email")}),
  });
  state.emailChallenge = {challenge_id: result.challenge_id};
  document.getElementById("local-email-code-field")?.classList.remove("is-hidden");
  formElement.querySelector("button[type='submit']").textContent = "验证并绑定邮箱";
  alert(
    result.debug_code
      ? `验证码已生成：${result.debug_code}。生产环境会发送到 ${result.masked_email || "绑定邮箱"}。`
      : `验证码已发送到 ${result.masked_email || "绑定邮箱"}，请输入后完成绑定。`
  );
}

function emptyPanel(text) {
  return `<div class="empty-state">${escapeHtml(text)}</div>`;
}

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      if (window.location.hash !== `#${item.dataset.view}`) {
        window.location.hash = item.dataset.view;
      }
      selectView(item.dataset.view);
      loadViewData(item.dataset.view).catch(console.error);
    });
  });
  document.querySelectorAll(".nav-shortcut").forEach((item) => {
    item.addEventListener("click", () => {
      const view = item.dataset.view;
      if (!view) return;
      window.location.hash = view;
      selectView(view);
      loadViewData(view).catch(console.error);
    });
  });
  document.querySelectorAll(".workflow-tab").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.group === "intake") {
        if (button.dataset.tab === "rag_experiences") {
          selectView("rag_experiences");
          loadViewData("rag_experiences").catch(console.error);
          return;
        }
        state.activeIntakeTab = button.dataset.tab || "generator";
      }
      if (button.dataset.group === "reference") {
        state.activeReferenceTab = button.dataset.tab || "experiences";
      }
      syncWorkflowTabs();
      loadActiveSubsection().catch(console.error);
    });
  });
}

function activateHashView() {
  const view = window.location.hash.replace("#", "");
  if (!titles[view] && !viewAliases[view]) return;
  selectView(view);
  loadViewData(view).catch(console.error);
}

async function loadViewData(view) {
  const activeView = (viewAliases[view] || {view}).view;
  if (activeView === "customer_service") await loadCustomerService();
  if (activeView === "knowledge_center") await loadOverview();
  if (activeView === "product_catalog") await loadProductCatalog();
  if (activeView === "knowledge") await loadKnowledge();
  if (activeView === "intake") {
    renderGeneratorCategorySelect();
    renderGenerator();
    await Promise.all([loadUploads().catch(console.error), loadCandidates().catch(console.error)]);
  }
  if (activeView === "recorder") await loadRecorder();
  if (activeView === "ai_reference") {
    await Promise.all([loadRagStatus().catch(console.error), loadRagExperiences().catch(console.error)]);
  }
  if (activeView === "settings") {
    await Promise.all([
      loadVersions().catch(console.error),
      refreshAccountContext().catch(console.error),
      loadPlatformSafetyRules().catch(console.error),
      loadPlatformUnderstandingRules().catch(console.error),
    ]);
  }
  if (activeView === "versions") await loadVersions();
}

async function loadActiveSubsection() {
  if (state.activeView === "intake") {
    if (state.activeIntakeTab === "generator") {
      renderGeneratorCategorySelect();
      renderGenerator();
    }
    if (state.activeIntakeTab === "uploads") await loadUploads();
    if (state.activeIntakeTab === "candidates") await loadCandidates();
  }
  if (state.activeView === "ai_reference") {
    if (state.activeReferenceTab === "sources") await loadRagStatus();
    if (state.activeReferenceTab === "experiences") await loadRagExperiences();
  }
  if (state.activeView === "recorder") await loadRecorder();
  if (state.activeView === "product_catalog") await loadProductCatalog();
  if (state.activeView === "customer_service") await loadCustomerService();
}

bindNavigation();
renderCustomerServiceRuntime();
document.getElementById("refresh-overview").addEventListener("click", () => loadOverview().catch(console.error));
document.getElementById("tenant-select")?.addEventListener("change", async (event) => {
  state.activeTenantId = event.target.value || "default";
  localStorage.setItem("localActiveTenantId", state.activeTenantId);
  await Promise.all([
    refreshAccountContext().catch(console.error),
    loadOverview().catch(console.error),
    loadKnowledge().catch(console.error),
    refreshRagExperienceBadge().catch(console.error),
  ]);
  scheduleStartupSync();
  scheduleCustomerServiceRuntimePolling();
  await loadActiveSubsection().catch(console.error);
});
document.getElementById("category-select").addEventListener("change", async (event) => {
  state.activeCategoryId = event.target.value;
  await loadCategoryItems();
});
document.getElementById("knowledge-search").addEventListener("input", renderKnowledgeList);
document.getElementById("create-category").addEventListener("click", () => createCustomCategory().catch((error) => alert(error.message)));
document.getElementById("new-knowledge-item").addEventListener("click", newKnowledgeItem);
document.getElementById("edit-knowledge-item").addEventListener("click", editKnowledgeItem);
document.getElementById("cancel-knowledge-edit").addEventListener("click", cancelKnowledgeEdit);
document.getElementById("save-knowledge-item").addEventListener("click", () => saveKnowledgeItem().catch((error) => alert(error.message)));
document.getElementById("archive-knowledge-item").addEventListener("click", () => archiveKnowledgeItem().catch((error) => alert(error.message)));
document.getElementById("send-generator").addEventListener("click", () => sendGeneratorMessage().catch((error) => alert(error.message)));
document.getElementById("reset-generator").addEventListener("click", resetGenerator);
document.getElementById("confirm-generator").addEventListener("click", () => confirmGenerator().catch((error) => alert(error.message)));
document.getElementById("upload-button").addEventListener("click", () => uploadSelectedFile().catch((error) => alert(error.message)));
document.getElementById("upload-file").addEventListener("change", () => uploadSelectedFile().catch((error) => alert(error.message)));
document.getElementById("refresh-rag").addEventListener("click", () => loadRagStatus().catch((error) => alert(error.message)));
document.getElementById("rebuild-rag").addEventListener("click", () => rebuildRag().catch((error) => alert(error.message)));
document.getElementById("rag-search").addEventListener("click", () => searchRag().catch((error) => alert(error.message)));
document.getElementById("refresh-rag-experiences").addEventListener("click", () => loadRagExperiences().catch((error) => alert(error.message)));
document.getElementById("run-learning").addEventListener("click", () => runLearning().catch((error) => alert(error.message)));
document.getElementById("refresh-candidates")?.addEventListener("click", () => loadCandidates().catch((error) => alert(error.message)));
document.getElementById("refresh-customer-service")?.addEventListener("click", () => loadCustomerService().catch((error) => alert(error.message)));
document.getElementById("customer-save-settings")?.addEventListener("click", () => saveCustomerServiceSettings().catch((error) => alert(error.message)));
document.getElementById("refresh-product-catalog")?.addEventListener("click", () => loadProductCatalog().catch((error) => alert(error.message)));
document.getElementById("new-product-from-catalog")?.addEventListener("click", openNewProductGenerator);
document.getElementById("run-product-command")?.addEventListener("click", () => runProductCommand().catch((error) => alert(error.message)));
document.getElementById("recorder-discover")?.addEventListener("click", () => discoverRecorderSessions().catch((error) => alert(error.message)));
document.getElementById("recorder-capture")?.addEventListener("click", () => captureRecorderNow().catch((error) => alert(error.message)));
document.getElementById("recorder-save-settings")?.addEventListener("click", () => saveRecorderSettings().catch((error) => alert(error.message)));
document.getElementById("export-knowledge-type")?.addEventListener("click", () => downloadKnowledgeExport("type").catch((error) => alert(error.message)));
document.getElementById("export-knowledge-time")?.addEventListener("click", () => downloadKnowledgeExport("time").catch((error) => alert(error.message)));
document.getElementById("quick-diagnostics").addEventListener("click", () => runDiagnostics("quick").catch((error) => alert(error.message)));
document.getElementById("full-diagnostics").addEventListener("click", () => runDiagnostics("full").catch((error) => alert(error.message)));
document.getElementById("create-backup").addEventListener("click", () => createBackup().catch((error) => alert(error.message)));
document.getElementById("refresh-versions").addEventListener("click", () => loadVersions().catch((error) => alert(error.message)));
document.getElementById("refresh-platform-safety")?.addEventListener("click", () => loadPlatformSafetyRules().catch((error) => alert(error.message)));
document.getElementById("save-platform-safety")?.addEventListener("click", () => savePlatformSafetyRules().catch((error) => alert(error.message)));
document.getElementById("refresh-platform-understanding")?.addEventListener("click", () => loadPlatformUnderstandingRules().catch((error) => alert(error.message)));
document.getElementById("save-platform-understanding")?.addEventListener("click", () => savePlatformUnderstandingRules().catch((error) => alert(error.message)));
document.getElementById("local-password-form")?.addEventListener("submit", (event) => changeLocalPassword(event).catch((error) => alert(error.message)));
document.getElementById("local-email-form")?.addEventListener("submit", (event) => bindLocalEmail(event).catch((error) => alert(error.message)));
document.getElementById("local-logout-button")?.addEventListener("click", () => logoutLocal().catch((error) => alert(error.message)));

document.body.classList.toggle("auth-locked", !state.authToken);
initializeLocalLogin();
refreshHealth();
window.addEventListener("hashchange", activateHashView);
