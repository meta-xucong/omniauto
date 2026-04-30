const state = {
  authToken: localStorage.getItem("localAuthToken") || "",
  activeView: "overview",
  overview: null,
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
  activeIntakeTab: "generator",
  activeReferenceTab: "sources",
  ragStatus: null,
  ragHits: [],
  ragExperiences: [],
  ragAnalytics: null,
  auth: null,
  tenants: [],
  activeTenantId: "",
  syncStatus: null,
  sharedPublic: null,
  selectedSharedPublic: null,
  loginChallenge: null,
  initChallenge: null,
  passwordChallenge: null,
  emailChallenge: null,
  security: null,
};
const localDeviceId = getOrCreateDeviceId("localConsoleDeviceId");

const titles = {
  overview: "总览",
  knowledge: "知识库",
  shared_public: "共享公共知识库",
  intake: "知识录入与学习",
  ai_reference: "AI参考资料",
  diagnostics: "一键检测",
  versions: "备份还原",
  security: "账号安全",
};

const viewAliases = {
  generator: {view: "intake", group: "intake", tab: "generator"},
  uploads: {view: "intake", group: "intake", tab: "uploads"},
  candidates: {view: "intake", group: "intake", tab: "candidates"},
  rag: {view: "ai_reference", group: "reference", tab: "sources"},
  rag_experiences: {view: "ai_reference", group: "reference", tab: "experiences"},
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
};

const fieldLabelOverrides = {
  price_tiers: "批量价格",
  reply_templates: "客服回复内容",
  risk_rules: "风险提醒",
  policy_type: "规则类别",
  allow_auto_reply: "允许自动回复",
  requires_handoff: "需要人工确认",
  handoff_reason: "人工确认原因",
  operator_alert: "提醒人工客服",
  fields: "字段内容",
  additional_details: "补充信息",
};

function selectView(view) {
  const target = viewAliases[view] || {view};
  if (target.group === "intake") state.activeIntakeTab = target.tab;
  if (target.group === "reference") state.activeReferenceTab = target.tab;
  const activeView = target.view;
  state.activeView = activeView;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.view === activeView);
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
      tenant_id: state.activeTenantId || "default",
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
  localStorage.setItem("localAuthToken", state.authToken);
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
  await Promise.all([loadOverview().catch(console.error), loadKnowledge().catch(console.error)]);
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
  state.authToken = "";
  state.auth = null;
  state.security = null;
  state.initChallenge = null;
  state.passwordChallenge = null;
  state.emailChallenge = null;
  document.getElementById("local-password-code-field")?.classList.add("is-hidden");
  document.getElementById("local-email-code-field")?.classList.add("is-hidden");
  resetLocalLoginChallenge({silent: true});
  resetLocalInitialization({silent: true});
  localStorage.removeItem("localAuthToken");
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

async function refreshAccountContext() {
  const [auth, tenants, sync, security] = await Promise.all([
    apiGet("/api/auth/me").catch(() => ({ok: false})),
    apiGet("/api/tenants").catch(() => ({ok: false, items: []})),
    apiGet("/api/sync/status").catch(() => ({ok: false, mode: "unknown"})),
    apiGet("/api/auth/security").catch(() => ({ok: false, security: {}})),
  ]);
  state.auth = auth.auth || null;
  state.tenants = tenants.items || [];
  state.activeTenantId = state.activeTenantId || tenants.active_tenant_id || auth.auth?.tenant_id || "default";
  state.syncStatus = sync;
  state.security = security.security || {};
  renderAccountContext();
  renderLocalSecurity();
}

function renderAccountContext() {
  const select = document.getElementById("tenant-select");
  if (select) {
    const items = state.tenants.length ? state.tenants : [{tenant_id: state.activeTenantId || "default", display_name: state.activeTenantId || "default"}];
    select.innerHTML = items.map((item) => `<option value="${escapeHtml(item.tenant_id)}">${escapeHtml(item.display_name || item.tenant_id)}</option>`).join("");
    select.value = state.activeTenantId || "default";
  }
  const user = state.auth?.session?.user || {};
  const role = user.role || state.auth?.role || "local";
  const roleNames = {admin: "管理员", customer: "客户", guest: "访客", local: "本地"};
  const accountName = user.username || user.display_name || user.user_id || "未登录";
  document.getElementById("auth-pill").textContent = `${roleNames[role] || role}：${accountName}`;
  const nodeText = state.syncStatus?.node?.node_id ? "VPS 已连接" : "VPS 已配置";
  document.getElementById("sync-pill").textContent = state.syncStatus?.vps_configured ? nodeText : "本地模式";
  document.querySelectorAll(".admin-only-nav").forEach((item) => item.classList.toggle("is-hidden", role !== "admin"));
  if (role !== "admin" && state.activeView === "shared_public") {
    window.location.hash = "overview";
    selectView("overview");
  }
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

async function loadOverview() {
  const [knowledge, system] = await Promise.all([
    apiGet("/api/knowledge/overview"),
    apiGet("/api/system/status").catch(() => ({ok: false})),
  ]);
  state.overview = knowledge;
  const counts = knowledge.counts || {};
  document.getElementById("metric-products").textContent = counts.products ?? "-";
  document.getElementById("metric-candidates").textContent = counts.pending_candidates ?? "-";
  document.getElementById("metric-diagnostics").textContent = system.ok ? "正常" : "待查";
  document.getElementById("overview-cards").innerHTML = `
    <div class="metric-card"><span>${counts.categories ?? 0}</span><label>知识门类</label></div>
    <div class="metric-card"><span>${counts.products ?? 0}</span><label>商品知识</label></div>
    <div class="metric-card"><span>${counts.faqs ?? 0}</span><label>规则问答</label></div>
    <div class="metric-card"><span>${counts.style_examples ?? 0}</span><label>话术样例</label></div>
    <div class="metric-card"><span>${counts.pending_candidates ?? 0}</span><label>待审核候选</label></div>
    <div class="metric-card"><span>${system.ok ? "正常" : "异常"}</span><label>系统状态</label></div>
  `;
}

async function loadKnowledge() {
  const payload = await apiGet("/api/knowledge/categories");
  state.categories = payload.items || [];
  if (!state.activeCategoryId && state.categories.length) {
    state.activeCategoryId = state.categories[0].id;
  }
  renderCategorySelect();
  renderGeneratorCategorySelect();
  await loadCategoryItems();
}

function renderCategorySelect() {
  const select = document.getElementById("category-select");
  select.innerHTML = state.categories
    .map((category) => `<option value="${escapeHtml(category.id)}">${escapeHtml(category.name || category.id)} (${category.item_count || 0})</option>`)
    .join("");
  select.value = state.activeCategoryId;
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
  state.categoryItems = payload.items || [];
  state.selectedKnowledge = state.categoryItems[0] || null;
  state.knowledgeMode = "view";
  renderKnowledgeList();
  renderKnowledgeDetail();
}

function activeCategory() {
  return state.categories.find((item) => item.id === state.activeCategoryId) || null;
}

function categoryById(categoryId) {
  return state.categories.find((item) => item.id === categoryId) || null;
}

function renderKnowledgeList() {
  const query = (document.getElementById("knowledge-search").value || "").trim().toLowerCase();
  const category = activeCategory();
  const titleField = category?.schema?.item_title_field || "title";
  const subtitleField = category?.schema?.item_subtitle_field || "";
  const list = document.getElementById("knowledge-list");
  const filtered = state.categoryItems.filter((item) => {
    const text = `${item.id} ${businessSearchText(item.data || {})}`.toLowerCase();
    return !query || text.includes(query);
  });
  list.innerHTML = filtered
    .map((item, index) => {
      const title = item.data?.[titleField] || item.id;
      const subtitle = subtitleField ? item.data?.[subtitleField] : item.status;
      const active = state.selectedKnowledge?.id === item.id ? " is-selected" : "";
      return `
        <button class="record-row${active}" data-index="${index}">
          <strong>${escapeHtml(title)}</strong>
          <span>${escapeHtml(item.id)} · ${escapeHtml(subtitle || item.status || "")}</span>
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
  return `
    <div class="read-head">
      <div>
        <p class="eyebrow">${escapeHtml(category.name || category.id)}</p>
        <h2>${escapeHtml(primaryTitle(category, item))}</h2>
      </div>
      <span class="status-chip ${item.status === "archived" ? "warning" : "ok"}">${item.status === "archived" ? "已归档" : "启用中"}</span>
    </div>
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
  return `
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
      ${fields.map((field) => fieldHtml(field, item.data?.[field.id])).join("")}
    </div>
  `;
}

function fieldHtml(field, value) {
  const id = `data-${field.id}`;
  const label = `${fieldLabel(field)}${field.required ? " *" : ""}`;
  if (field.type === "boolean") {
    return `<label class="checkbox-line" data-field="${escapeHtml(field.id)}"><input id="${escapeHtml(id)}" type="checkbox" ${value ? "checked" : ""} /> ${escapeHtml(label)}</label>`;
  }
  if (field.type === "single_select") {
    const options = field.options || [];
    return `
      <label class="form-field" data-field="${escapeHtml(field.id)}" data-kind="single_select">
        <span>${escapeHtml(label)}</span>
        <select id="${escapeHtml(id)}">${options.map((option) => `<option value="${escapeHtml(option)}" ${option === value ? "selected" : ""}>${escapeHtml(optionLabel(field.id, option))}</option>`).join("")}</select>
      </label>
    `;
  }
  if (field.type === "tags") {
    return `
      <label class="form-field wide-field" data-field="${escapeHtml(field.id)}" data-kind="tags">
        <span>${escapeHtml(label)}</span>
        <textarea id="${escapeHtml(id)}" placeholder="可用逗号、顿号或换行分隔">${escapeHtml(displayTags(value))}</textarea>
      </label>
    `;
  }
  if (field.type === "table") {
    return tableFieldHtml(field, Array.isArray(value) ? value : []);
  }
  if (field.type === "object") {
    return objectFieldHtml(field, value && typeof value === "object" && !Array.isArray(value) ? value : {});
  }
  if (field.type === "long_text") {
    return `
      <label class="form-field wide-field" data-field="${escapeHtml(field.id)}" data-kind="long_text">
        <span>${escapeHtml(label)}</span>
        <textarea id="${escapeHtml(id)}">${escapeHtml(value || "")}</textarea>
      </label>
    `;
  }
  return `
    <label class="form-field" data-field="${escapeHtml(field.id)}" data-kind="${escapeHtml(field.type || "short_text")}">
      <span>${escapeHtml(label)}</span>
      <input id="${escapeHtml(id)}" value="${escapeHtml(value ?? "")}" />
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

function objectFieldHtml(field, value) {
  if (field.id === "reply_templates") {
    const keys = Array.from(new Set([...Object.keys(templateLabels), ...Object.keys(value)]));
    return `
      <div class="form-field wide-field reply-template-editor" data-field="${escapeHtml(field.id)}" data-kind="object">
        <span>${escapeHtml(fieldLabel(field))}</span>
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
  await Promise.all([loadKnowledge(), loadOverview()]);
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
  await apiJson(`/api/knowledge/categories/${encodeURIComponent(state.activeCategoryId)}/items/${encodeURIComponent(state.selectedKnowledge.id)}`, {method: "DELETE"});
  await Promise.all([loadKnowledge(), loadOverview()]);
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

async function loadRagExperiences() {
  const payload = await apiGet("/api/rag/experiences?status=active&limit=100");
  state.ragExperiences = payload.items || [];
  renderRagExperiences(payload);
}

function renderRagExperiences(payload = {}) {
  const items = payload.items || state.ragExperiences || [];
  const counts = payload.counts || {};
  const cards = document.getElementById("rag-experience-cards");
  if (cards) {
    cards.innerHTML = [
      ["默认采纳", counts.active ?? items.length],
      ["已废弃", counts.discarded ?? 0],
      ["总经验", counts.total ?? items.length],
    ]
      .map(([label, value]) => `<div class="metric-card"><span>${escapeHtml(value)}</span><label>${escapeHtml(label)}</label></div>`)
      .join("");
  }
  const list = document.getElementById("rag-experience-list");
  if (!list) return;
  list.innerHTML = items.length
    ? items.map((item) => {
        const hit = item.rag_hit || {};
        const usage = item.usage || {};
        const source = [hit.category || hit.source_type || "RAG片段", hit.product_id || "未指定商品"].filter(Boolean).join(" · ");
        return `
          <div class="record-row rag-experience-row">
            <div>
              <strong>${escapeHtml(item.summary || "未生成概括")}</strong>
              <span>${escapeHtml(source)} · 使用 ${escapeHtml(usage.reply_count ?? 1)} 次 · ${escapeHtml(item.updated_at || item.created_at || "")}</span>
              <p><b>客户问法：</b>${escapeHtml(item.question || "")}</p>
              <p><b>回复要点：</b>${escapeHtml(item.reply_text || "")}</p>
              ${hit.text ? `<p><b>命中资料：</b>${escapeHtml(hit.text)}</p>` : ""}
            </div>
            <div class="inline-actions">
              <span class="status-chip ok">默认采纳</span>
              <button class="secondary-button rag-experience-discard" data-id="${escapeHtml(item.experience_id || "")}">废弃</button>
            </div>
          </div>
        `;
      }).join("")
    : `<div class="empty-state">暂无对话经验。系统只有在客服使用参考资料成功回复后，才会在这里生成概括。</div>`;
  list.querySelectorAll(".rag-experience-discard").forEach((button) => {
    button.addEventListener("click", () => discardRagExperience(button.dataset.id).catch((error) => alert(error.message)));
  });
}

async function discardRagExperience(experienceId) {
  if (!experienceId) return;
  if (!confirm("确认废弃这条对话经验？废弃后不会再作为默认经验展示。")) return;
  await apiJson(`/api/rag/experiences/${encodeURIComponent(experienceId)}/discard`, {
    method: "POST",
    body: JSON.stringify({reason: "discarded in admin"}),
  });
  await Promise.all([loadRagExperiences(), loadRagStatus().catch(() => {})]);
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
  const payload = await apiGet("/api/rag/experiences?status=all&limit=200");
  state.ragExperiences = payload.items || [];
  renderRagExperiences(payload);
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
      ["默认采纳", counts.active ?? 0],
      ["可参与检索", retrievalCounts.retrievable ?? 0],
      ["需观察", qualityCounts.low ?? 0],
      ["已阻断", qualityCounts.blocked ?? 0],
      ["建议升级", relationCounts.promotion_candidate ?? 0],
      ["正式覆盖", relationCounts.covered_by_formal ?? 0],
      ["已升级", counts.promoted ?? 0],
      ["已废弃", counts.discarded ?? 0],
      ["总经验", counts.total ?? items.length],
    ]
      .map(([label, value]) => `<div class="metric-card"><span>${escapeHtml(value)}</span><label>${escapeHtml(label)}</label></div>`)
      .join("");
  }
  const list = document.getElementById("rag-experience-list");
  if (!list) return;
  list.innerHTML = items.length
    ? items.map((item) => {
        const hit = item.rag_hit || {};
        const usage = item.usage || {};
        const source = [hit.category || hit.source_type || "RAG片段", hit.product_id || "未指定商品"].filter(Boolean).join(" · ");
        const relation = item.formal_relation || item.status || "novel";
        const match = item.formal_match || {};
        const quality = item.quality || {};
        const qualityBand = quality.band || "unknown";
        const qualityReasons = Array.isArray(quality.reasons) ? quality.reasons : [];
        const canAct = (item.status || "active") === "active";
        const canPromote = canAct && relation !== "covered_by_formal" && relation !== "conflicts_formal";
        return `
          <div class="record-row rag-experience-row">
            <div>
              <div class="row-title-line">
                <strong>${escapeHtml(item.summary || "未生成概括")}</strong>
                <span class="relation-chip relation-${escapeHtml(relation)}">${escapeHtml(relationText(relation))}</span>
              </div>
              <div class="quality-line" title="${escapeHtml(qualityReasons.join("；"))}">
                <span class="quality-chip quality-${escapeHtml(qualityBand)}">${escapeHtml(qualityText(qualityBand))} · ${escapeHtml(quality.score ?? "")}</span>
                <span class="status-chip ${quality.retrieval_allowed ? "ok" : "warning"}">${escapeHtml(quality.retrieval_allowed ? "参与检索" : "不参与检索")}</span>
              </div>
              ${qualityReasons.length ? `<p><b>质量说明：</b>${escapeHtml(qualityReasons.join("；"))}</p>` : ""}
              <span>${escapeHtml(source)} · 使用 ${escapeHtml(usage.reply_count ?? 1)} 次 · ${escapeHtml(item.updated_at || item.created_at || "")}</span>
              <p><b>客户问法：</b>${escapeHtml(item.question || "")}</p>
              <p><b>回复要点：</b>${escapeHtml(item.reply_text || "")}</p>
              ${hit.text ? `<p><b>命中资料：</b>${escapeHtml(hit.text)}</p>` : ""}
              ${match.item_id ? `<p><b>正式知识关系：</b>${escapeHtml(match.category_id || "")}/${escapeHtml(match.item_id || "")} · 相似度 ${escapeHtml(match.similarity ?? "")} · ${escapeHtml(match.title || "")}</p>` : ""}
              <p><b>建议：</b>${escapeHtml(actionText(item.recommended_action || ""))}</p>
            </div>
            <div class="inline-actions">
              ${canPromote ? `<button class="primary-button rag-experience-promote" data-id="${escapeHtml(item.experience_id || "")}">升级为待确认知识</button>` : ""}
              ${canAct ? `<button class="secondary-button rag-experience-discard" data-id="${escapeHtml(item.experience_id || "")}">废弃</button>` : `<span class="status-chip">${escapeHtml(statusText(item.status || relation))}</span>`}
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
}

async function promoteRagExperience(experienceId) {
  if (!experienceId) return;
  if (!confirm("确认把这条经验转为“待确认知识”？它仍需要人工审核后才会进入正式知识库。")) return;
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
}

async function discardRagExperience(experienceId) {
  if (!experienceId) return;
  if (!confirm("确认废弃这条对话经验？废弃后不会再参与参考检索。")) return;
  await apiJson(`/api/rag/experiences/${encodeURIComponent(experienceId)}/discard`, {
    method: "POST",
    body: JSON.stringify({reason: "discarded in admin"}),
  });
  await Promise.all([loadRagExperiences(), loadRagStatus().catch(() => {})]);
}

function sourceLabel(source) {
  return [source.source_type || "资料源", source.source_id || ""].filter(Boolean).join(" · ");
}

function shortPath(value) {
  const text = String(value || "");
  if (!text) return "";
  const parts = text.split(/[\\/]+/);
  return parts.slice(-3).join("/");
}

function qualityText(value) {
  return {
    high: "高质量",
    medium: "可参考",
    low: "需观察",
    blocked: "已阻断",
    unknown: "未评估",
  }[value] || value || "未评估";
}

function relationText(value) {
  return {
    novel: "新经验",
    covered_by_formal: "正式知识已覆盖",
    supports_formal: "支持正式知识",
    conflicts_formal: "疑似冲突",
    promotion_candidate: "建议升级",
    promoted: "已升级",
    discarded: "已废弃",
  }[value] || value || "未判断";
}

function actionText(value) {
  return {
    keep_as_rag_experience: "保留在经验层，作为辅助表达参考。",
    keep_low_priority_or_discard: "正式知识已经覆盖，可降低优先级或废弃。",
    keep_as_supporting_expression: "可保留为正式知识的表达补充。",
    manual_review_conflict: "疑似和正式知识冲突，建议人工检查后处理。",
    promote_to_review_candidate: "建议升级为待确认知识，由人工审核后再入库。",
    already_promoted: "已升级为待确认知识。",
    already_discarded: "已废弃。",
  }[value] || value || "保持观察。";
}

function statusText(value) {
  return {promoted: "已升级", discarded: "已废弃", active: "默认采纳"}[value] || value || "默认采纳";
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
    document.getElementById("candidate-detail").innerHTML = `<div class="empty-state">没有待学习的上传资料。</div>`;
    state.activeIntakeTab = "candidates";
    selectView("intake");
    await loadCandidates();
    return;
  }
  state.activeIntakeTab = "candidates";
  selectView("intake");
  setLearningBusy(true, uploadIds.length);
  try {
    const payload = await apiJson("/api/learning/jobs", {method: "POST", body: JSON.stringify({upload_ids: uploadIds, use_llm: true})});
    const skipped = Number(payload.job?.skipped_duplicate_count || 0);
    const skippedText = skipped ? `；已自动跳过 ${skipped} 条重复内容` : "";
    renderCandidatePlaceholder("ok", "分析完成", `已生成 ${payload.job.candidate_count} 条候选${skippedText}，请在左侧逐条审核。`);
    await loadCandidates();
  } catch (error) {
    renderCandidatePlaceholder("error", "分析失败", error.message || "请查看后台服务状态后重试。");
    throw error;
  } finally {
    setLearningBusy(false);
  }
}

async function loadCandidates() {
  const payload = await apiGet("/api/candidates?status=pending");
  const list = document.getElementById("candidate-list");
  const items = payload.items || [];
  list.innerHTML = (payload.items || [])
    .map((item, index) => `
      <div class="record-row candidate-row" data-index="${index}">
        <button class="link-button candidate-select" data-index="${index}">
          <strong>${escapeHtml(candidateTitle(item))}</strong>
          <span>${escapeHtml(item.proposal?.summary || "")}${candidateIsIncomplete(item) ? " · 待补充" : ""}</span>
        </button>
        <div class="inline-actions">
          <button class="secondary-button candidate-reject" data-id="${escapeHtml(item.candidate_id)}">拒绝</button>
          <button class="primary-button candidate-apply" data-id="${escapeHtml(item.candidate_id)}" ${candidateIsIncomplete(item) ? "disabled" : ""}>应用</button>
        </div>
      </div>
    `)
    .join("") || `<div class="empty-state">暂无待审核候选</div>`;
  list.querySelectorAll(".candidate-select").forEach((button) => {
    button.addEventListener("click", () => {
      const item = payload.items[Number(button.dataset.index)];
      state.selectedCandidate = item;
      renderCandidateDetail(item);
    });
  });
  list.querySelectorAll(".candidate-apply").forEach((button) => {
    button.addEventListener("click", () => applyCandidate(button.dataset.id).catch((error) => alert(error.message)));
  });
  list.querySelectorAll(".candidate-reject").forEach((button) => {
    button.addEventListener("click", () => rejectCandidate(button.dataset.id).catch((error) => alert(error.message)));
  });
  if (state.selectedCandidate?.candidate_id) {
    const selectedStillPending = items.some((item) => item.candidate_id === state.selectedCandidate.candidate_id);
    if (!selectedStillPending) clearCandidateDetail();
  }
}

function setLearningBusy(isBusy, uploadCount = 0) {
  state.learningInProgress = isBusy;
  const buttons = [document.getElementById("run-learning"), document.getElementById("run-learning-from-candidates")].filter(Boolean);
  for (const button of buttons) {
    button.disabled = isBusy;
    button.textContent = isBusy ? "分析中..." : "AI整理资料";
  }
  if (isBusy) {
    renderCandidatePlaceholder(
      "loading",
      "正在分析上传资料",
      `正在调用 AI 和本地规则分析 ${uploadCount} 个文件，文件较多时会多等一会儿。`
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
  const target = patch.target_category || patch.target_file || item.proposal?.change_type || item.candidate_id;
  return `建议入库：${target}`;
}

function candidateIsIncomplete(item) {
  return item?.intake?.status === "needs_more_info" || item?.review?.completeness_status === "needs_more_info";
}

function renderCandidateDetail(item) {
  const patch = item.proposal?.formal_patch || {};
  const intake = item.intake || {};
  const detail = document.getElementById("candidate-detail");
  detail.innerHTML = `
    <div class="status-card ${candidateIsIncomplete(item) ? "warning" : ""}"><strong>${escapeHtml(candidateTitle(item))}</strong><span>${escapeHtml(item.proposal?.summary || "")}</span></div>
    <div class="read-grid">
      <div class="read-field"><span>来源证据</span><p>${escapeHtml(item.source?.evidence_excerpt || "无")}</p></div>
      <div class="read-field"><span>建议字段</span><p>${escapeHtml(summaryFields(item.proposal?.suggested_fields || {}))}</p></div>
      <div class="read-field"><span>入库动作</span><p>${escapeHtml(patch.operation || "待判断")}</p></div>
      <div class="read-field"><span>完整性</span><p>${escapeHtml(candidateIsIncomplete(item) ? "待补充" : "可审核入库")}</p></div>
      <div class="read-field wide-field"><span>缺失内容</span><p>${escapeHtml((intake.missing_labels || intake.missing_fields || []).join("、") || "无")}</p></div>
      <div class="read-field wide-field"><span>补充提示</span><p>${escapeHtml(intake.question || "无")}</p></div>
      <div class="read-field wide-field"><span>风险提示</span><p>${escapeHtml((intake.warnings || item.proposal?.warnings || []).join("、") || "未发现")}</p></div>
    </div>
    ${candidateRagEvidenceHtml(item)}
    ${candidateSupplementHtml(item, patch)}
  `;
  bindDynamicEditors(detail);
  detail.querySelector(".candidate-category-change")?.addEventListener("click", () => {
    changeCandidateCategory(item.candidate_id).catch((error) => alert(error.message));
  });
  detail.querySelector(".candidate-supplement-save")?.addEventListener("click", () => {
    saveCandidateSupplement(item.candidate_id, patch.target_category).catch((error) => alert(error.message));
  });
}

function candidateRagEvidenceHtml(item) {
  const evidence = item.review?.rag_evidence || {};
  const hits = evidence.hits || [];
  if (!evidence.enabled) return "";
  return `
    <div class="candidate-rag">
      <div class="editor-head">
        <div>
          <strong>参考资料来源片段</strong>
          <span>这些片段只用于辅助审核，不会绕过正式知识库规则。</span>
        </div>
      </div>
      ${hits.length ? hits.map((hit) => `
        <div class="read-field wide-field rag-hit">
          <span>${escapeHtml(hit.category || "资料片段")} · ${escapeHtml(hit.score || "")}</span>
          <p>${escapeHtml(hit.text || "")}</p>
        </div>
      `).join("") : `<div class="empty-state">没有可展示的参考资料片段。</div>`}
    </div>
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
  const categoryOptions = state.categories
    .map((candidateCategory) => `<option value="${escapeHtml(candidateCategory.id)}" ${candidateCategory.id === categoryId ? "selected" : ""}>${escapeHtml(candidateCategory.name || candidateCategory.id)}</option>`)
    .join("");
  return `
    <div class="candidate-supplement-panel">
      <div class="section-heading">
        <div>
          <span>补充后重新诊断</span>
          <strong>把缺失内容直接填进表单，保存后系统会重新判断是否可入库。</strong>
        </div>
        <button class="primary-button candidate-supplement-save" type="button">保存补充并重新诊断</button>
      </div>
      <div class="candidate-category-tools">
        <label class="form-field">
          <span>当前判断的数据类型</span>
          <select id="candidate-category-target">${categoryOptions}</select>
        </label>
        <button class="secondary-button candidate-category-change" type="button">切换类型并重新诊断</button>
      </div>
      <div id="candidate-supplement-form" class="form-grid" data-candidate-id="${escapeHtml(item.candidate_id)}" data-category="${escapeHtml(categoryId)}">
        ${fields.map((field) => fieldHtml(field, data?.[field.id])).join("")}
      </div>
    </div>
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
  if (!confirm(`确认应用候选 ${candidateId}？应用前会自动创建备份。`)) return;
  const payload = await apiJson(`/api/candidates/${encodeURIComponent(candidateId)}/apply`, {method: "POST"});
  if (!payload.ok) throw new Error(payload.message || "候选应用失败，请查看详情后补充、合并或拒绝。");
  renderDiagnostics(payload);
  clearCandidateDetail("已应用入库，候选已移出待审核列表。");
  await Promise.all([loadCandidates(), loadOverview(), loadKnowledge(), loadVersions()]);
}

async function rejectCandidate(candidateId) {
  if (!candidateId) return;
  const reasonInput = prompt("拒绝原因", "不适合写入正式知识库");
  if (reasonInput === null) return;
  const reason = reasonInput.trim() || "rejected in admin";
  await apiJson(`/api/candidates/${encodeURIComponent(candidateId)}/reject`, {
    method: "POST",
    body: JSON.stringify({reason}),
  });
  clearCandidateDetail("已拒绝该候选，候选已移出待审核列表。");
  await Promise.all([loadCandidates(), loadOverview()]);
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
    <div class="status-card ${status}"><strong>${statusText(status)}</strong><span>${escapeHtml(payload.message || payload.run_id || "")}${ignored ? ` · 已忽略 ${ignored} 条` : ""}</span></div>
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
    button.addEventListener("click", () => openDiagnosticTarget(button.dataset.target).catch((error) => alert(error.message)));
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
        ${target ? `<button class="secondary-button diagnostic-open" data-target="${escapeHtml(target)}">查看位置</button>` : ""}
        ${issue.code === "knowledge_token_budget_large" ? `<button class="secondary-button diagnostic-clear-notices">彻底消去提示</button>` : ""}
        ${issue.fingerprint ? `<button class="secondary-button diagnostic-ignore" data-fingerprint="${escapeHtml(issue.fingerprint)}">标记忽略</button>` : ""}
      </div>
    </div>
  `;
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

async function openDiagnosticTarget(target) {
  if (!target) return;
  const [categoryId, itemId] = String(target).split("/");
  if (!categoryId) return;
  selectView("knowledge");
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
          <button class="secondary-button version-rollback" data-id="${escapeHtml(item.version_id)}">还原</button>
        </div>
      </div>
    `)
    .join("") || `<div class="empty-state">暂无备份快照</div>`;
  document.querySelectorAll(".version-rollback").forEach((button) => {
    button.addEventListener("click", () => rollbackVersion(button.dataset.id).catch((error) => alert(error.message)));
  });
}

async function createBackup() {
  if (!confirm("确认立即备份当前知识库状态吗？")) return;
  await apiJson("/api/versions", {method: "POST", body: JSON.stringify({reason: "manual backup from admin console"})});
  await loadVersions();
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
      return value.map((item) => Object.entries(item).map(([key, inner]) => `${key}: ${inner}`).join("，")).join("；");
    }
    return value.join("、");
  }
  if (typeof value === "object") return Object.entries(value).map(([key, inner]) => `${templateLabels[key] || key}: ${inner}`).join("；");
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

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(value);
  return String(value).replaceAll('"', '\\"');
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

async function loadSharedPublic() {
  if ((state.auth?.session?.user?.role || "") !== "admin") {
    state.sharedPublic = null;
    renderSharedPublic();
    return;
  }
  state.sharedPublic = await apiGet("/api/shared-knowledge/items");
  renderSharedPublic();
}

function renderSharedPublic() {
  const list = document.getElementById("shared-public-list");
  const detail = document.getElementById("shared-public-detail");
  if (!list || !detail) return;
  const items = state.sharedPublic?.items || [];
  if (!state.sharedPublic) {
    list.innerHTML = emptyPanel("仅 admin 可查看共享公共知识库。");
    detail.textContent = "客户账号不会显示这个入口。";
    return;
  }
  list.innerHTML = items.map((item) => `
    <button class="list-item ${state.selectedSharedPublic?.item_id === item.item_id ? "is-active" : ""}" data-shared-action="select" data-item-id="${escapeAttr(item.item_id)}">
      <strong>${escapeHtml(item.title || item.item_id)}</strong>
      <span>${escapeHtml(item.category_id || "-")} · ${escapeHtml(item.status || "-")}</span>
    </button>
  `).join("") || emptyPanel("暂无共享公共知识");
  const selected = state.selectedSharedPublic || items[0] || null;
  if (selected && !state.selectedSharedPublic) state.selectedSharedPublic = selected;
  renderSharedPublicDetail(selected);
}

function renderSharedPublicDetail(item) {
  const detail = document.getElementById("shared-public-detail");
  if (!detail) return;
  if (!item) {
    detail.textContent = "请选择一条共享公共知识。";
    return;
  }
  const payload = item.payload || item;
  const data = payload.data || {};
  detail.innerHTML = `
    <div class="detail-title">
      <div>
        <h3>${escapeHtml(item.title || data.title || item.item_id)}</h3>
        <p>${escapeHtml(item.category_id || payload.category_id || "-")} · ${escapeHtml(item.item_id || payload.id || "-")}</p>
      </div>
      <span class="status-badge ok">${escapeHtml(item.status || payload.status || "active")}</span>
    </div>
    <div class="detail-section">
      <h4>正文</h4>
      <p>${escapeHtml(data.guideline_text || data.content || "")}</p>
    </div>
    <div class="button-row">
      <button class="secondary-button" data-shared-action="edit" data-item-id="${escapeAttr(item.item_id)}">编辑</button>
      <button class="secondary-button danger-button" data-shared-action="delete" data-item-id="${escapeAttr(item.item_id)}">删除</button>
    </div>
  `;
}

async function createSharedPublicItem(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await apiJson("/api/shared-knowledge/items", {
    method: "POST",
    body: JSON.stringify({
      item_id: form.get("item_id"),
      category_id: form.get("category_id"),
      title: form.get("title"),
      content: form.get("content"),
      source: "local_admin_console",
    }),
  });
  event.currentTarget.reset();
  state.selectedSharedPublic = null;
  await loadSharedPublic();
}

async function handleSharedPublicAction(event) {
  const button = event.target.closest("[data-shared-action]");
  if (!button) return;
  const action = button.dataset.sharedAction;
  const itemId = button.dataset.itemId;
  if (action === "select") {
    const selected = (state.sharedPublic?.items || []).find((item) => item.item_id === itemId);
    state.selectedSharedPublic = selected || null;
    renderSharedPublic();
    return;
  }
  if (action === "edit") {
    const payload = await apiGet(`/api/shared-knowledge/items/${encodeURIComponent(itemId)}`);
    const item = payload.item || {};
    const data = item.data || {};
    const title = prompt("标题", data.title || item.id || "");
    if (title === null) return;
    const content = prompt("正文", data.guideline_text || data.content || "");
    if (content === null) return;
    await apiJson(`/api/shared-knowledge/items/${encodeURIComponent(itemId)}`, {
      method: "PUT",
      body: JSON.stringify({title, content, category_id: item.category_id || "global_guidelines", status: item.status || "active"}),
    });
    state.selectedSharedPublic = null;
    await loadSharedPublic();
    return;
  }
  if (action === "delete") {
    if (!confirm("确认删除这条本地共享公共知识吗？")) return;
    await apiJson(`/api/shared-knowledge/items/${encodeURIComponent(itemId)}`, {method: "DELETE"});
    state.selectedSharedPublic = null;
    await loadSharedPublic();
  }
}

async function uploadSharedCandidates() {
  const result = await apiJson("/api/sync/shared/upload-candidates", {method: "POST", body: "{}"});
  const uploaded = result.uploaded?.length || 0;
  const skipped = result.skipped?.length || 0;
  alert(result.ok === false ? result.error || "上传失败" : `上传完成：新增 ${uploaded} 条，跳过 ${skipped} 条。`);
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
  document.querySelectorAll(".workflow-tab").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.group === "intake") {
        state.activeIntakeTab = button.dataset.tab || "generator";
      }
      if (button.dataset.group === "reference") {
        state.activeReferenceTab = button.dataset.tab || "sources";
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
  if (activeView === "knowledge") await loadKnowledge();
  if (activeView === "shared_public") await loadSharedPublic();
  if (activeView === "intake") {
    renderGeneratorCategorySelect();
    renderGenerator();
    await Promise.all([loadUploads().catch(console.error), loadCandidates().catch(console.error)]);
  }
  if (activeView === "ai_reference") {
    await Promise.all([loadRagStatus().catch(console.error), loadRagExperiences().catch(console.error)]);
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
}

bindNavigation();
document.getElementById("refresh-overview").addEventListener("click", () => loadOverview().catch(console.error));
document.getElementById("tenant-select").addEventListener("change", async (event) => {
  state.activeTenantId = event.target.value || "default";
  await Promise.all([refreshAccountContext().catch(console.error), loadOverview().catch(console.error), loadKnowledge().catch(console.error)]);
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
document.getElementById("run-learning-from-candidates").addEventListener("click", () => runLearning().catch((error) => alert(error.message)));
document.getElementById("quick-diagnostics").addEventListener("click", () => runDiagnostics("quick").catch((error) => alert(error.message)));
document.getElementById("full-diagnostics").addEventListener("click", () => runDiagnostics("full").catch((error) => alert(error.message)));
document.getElementById("create-backup").addEventListener("click", () => createBackup().catch((error) => alert(error.message)));
document.getElementById("refresh-versions").addEventListener("click", () => loadVersions().catch((error) => alert(error.message)));
document.getElementById("refresh-shared-public")?.addEventListener("click", () => loadSharedPublic().catch((error) => alert(error.message)));
document.getElementById("upload-shared-candidates")?.addEventListener("click", () => uploadSharedCandidates().catch((error) => alert(error.message)));
document.getElementById("shared-public-form")?.addEventListener("submit", (event) => createSharedPublicItem(event).catch((error) => alert(error.message)));
document.getElementById("shared-public-list")?.addEventListener("click", (event) => handleSharedPublicAction(event).catch((error) => alert(error.message)));
document.getElementById("shared-public-detail")?.addEventListener("click", (event) => handleSharedPublicAction(event).catch((error) => alert(error.message)));
document.getElementById("local-password-form")?.addEventListener("submit", (event) => changeLocalPassword(event).catch((error) => alert(error.message)));
document.getElementById("local-email-form")?.addEventListener("submit", (event) => bindLocalEmail(event).catch((error) => alert(error.message)));
document.getElementById("local-logout-button")?.addEventListener("click", () => logoutLocal().catch((error) => alert(error.message)));

document.body.classList.toggle("auth-locked", !state.authToken);
initializeLocalLogin();
refreshHealth();
window.addEventListener("hashchange", activateHashView);
