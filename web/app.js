import {
  normalizePhoneInput,
  safePostLoginPath,
  validCode,
  validPhone,
  viewFromLocation,
} from "/auth-utils.js?v=20260730-institutional-2";
import { createVoiceInputController } from "/input-utils.js?v=20260730-institutional-2";

const appState = {
  data: null,
  dashboardLedgerId: "",
  filter: "all",
  importPreview: null,
  ledgerFilterIds: null,
  query: "",
  pendingParse: null,
  selectedLedgerId: null,
  user: null,
  turnstileSiteKey: "",
  turnstileToken: "",
};
const palette = ["#2f7654", "#86a18f", "#c6b58f", "#9aa8ad", "#d9d7d0"];
let accessToken = null;
let refreshPromise = null;
let resendTimer = null;
let turnstileWidgetId = null;
let editingTransactionId = null;
const receiptObjectUrls = new Map();

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function currency(value) {
  return `¥${Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function dateLabel(value) {
  if (!value) return "—";
  const [, month, day] = value.split("-");
  return `${Number(month)}月${Number(day)}日`;
}

function monthLabel(value) {
  if (!value) return "本月";
  const [year, month] = value.split("-");
  return `${year} 年 ${Number(month)} 月`;
}

function sourceLabel(source) {
  if (source === "receipt") return "图片凭证";
  if (source === "natural-language") return "AI 对话";
  if (source === "wechat-import") return "微信账单";
  if (source === "alipay-import") return "支付宝账单";
  return "手动记录";
}

function categoryLabel(transaction) {
  return transaction.subcategory && transaction.subcategory !== "其他"
    ? `${transaction.category} · ${transaction.subcategory}`
    : transaction.category;
}

function renderTagChips(tags) {
  return (tags || []).map((tag) => `<span class="transaction-tag">${escapeHtml(tag)}</span>`).join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function requestHeaders(options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  return headers;
}

async function readError(response) {
  const payload = await response.json().catch(() => ({}));
  return new ApiError(payload.detail || payload.error || `请求失败 (${response.status})`, response.status);
}

async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    }).then(async (response) => {
      if (response.status === 204) {
        accessToken = null;
        return null;
      }
      if (!response.ok) throw await readError(response);
      const payload = await response.json();
      accessToken = payload.access_token;
      return accessToken;
    }).finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function api(path, options = {}, retried = false) {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: requestHeaders(options),
  });
  if (response.status === 401 && !retried && !path.startsWith("/api/auth/")) {
    try {
      await refreshAccessToken();
      return api(path, options, true);
    } catch {
      showLogin();
      throw new ApiError("登录状态已失效，请重新验证", 401);
    }
  }
  if (!response.ok) throw await readError(response);
  if (options.responseType === "blob") return response.blob();
  return response.json().catch(() => ({}));
}

function setLoginError(message = "") {
  $("#login-error").textContent = message;
}

function showLogin() {
  accessToken = null;
  appState.user = null;
  $("#auth-loading").classList.add("hidden");
  $("#app-shell").classList.add("hidden");
  $("#login-screen").classList.remove("hidden");
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  sessionStorage.setItem("finance-post-login-path", safePostLoginPath(currentPath));
  window.setTimeout(() => $("#login-phone").focus(), 50);
}

async function showApp(user) {
  appState.user = user;
  appState.dashboardLedgerId = "";
  appState.ledgerFilterIds = null;
  $("#auth-loading").classList.add("hidden");
  $("#login-screen").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  renderUserIdentity();
  await loadState();
  showView(viewFromLocation(window.location), false);
}

function renderUserIdentity() {
  const name = appState.user?.display_name || "理财官";
  $("#current-user-name").textContent = name;
  $("#current-user-phone").textContent = `${appState.user?.masked_phone || "已安全登录"} · 数据已按账户隔离`;
  $("#user-avatar").textContent = name.slice(0, 1).toUpperCase() || "F";
  $("#page-title").textContent = `你好，${name}`;
}

function startResendCountdown(seconds = 60) {
  const button = $("#send-code-button");
  let remaining = seconds;
  window.clearInterval(resendTimer);
  button.disabled = true;
  button.textContent = `${remaining}s 后重发`;
  resendTimer = window.setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      window.clearInterval(resendTimer);
      button.disabled = false;
      button.textContent = "获取验证码";
      return;
    }
    button.textContent = `${remaining}s 后重发`;
  }, 1000);
}

function loadTurnstileScript() {
  if (!appState.turnstileSiteKey || window.turnstile || document.querySelector('script[data-finance-turnstile]')) return;
  const script = document.createElement("script");
  script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
  script.async = true;
  script.defer = true;
  script.dataset.financeTurnstile = "true";
  document.head.appendChild(script);
}

function showTurnstile() {
  const container = $("#turnstile-container");
  if (!appState.turnstileSiteKey) return;
  container.classList.remove("hidden");
  loadTurnstileScript();
  const render = () => {
    if (!window.turnstile || turnstileWidgetId !== null) return;
    turnstileWidgetId = window.turnstile.render(container, {
      sitekey: appState.turnstileSiteKey,
      theme: "light",
      callback: (token) => {
        appState.turnstileToken = token;
        setLoginError();
      },
      "expired-callback": () => {
        appState.turnstileToken = "";
      },
    });
  };
  render();
  const timer = window.setInterval(() => {
    render();
    if (turnstileWidgetId !== null) window.clearInterval(timer);
  }, 150);
  window.setTimeout(() => window.clearInterval(timer), 5000);
}

async function sendLoginCode() {
  const phone = normalizePhoneInput($("#login-phone").value);
  $("#login-phone").value = phone;
  if (!validPhone(phone)) {
    setLoginError("请输入有效的中国大陆手机号");
    return;
  }
  const button = $("#send-code-button");
  button.disabled = true;
  button.textContent = "发送中…";
  setLoginError();
  try {
    const payload = await api("/api/auth/sms/send", {
      method: "POST",
      body: JSON.stringify({
        phone,
        purpose: "login",
        turnstile_token: appState.turnstileToken || null,
      }),
    });
    if (payload.debug_code) $("#login-code").value = payload.debug_code;
    startResendCountdown(60);
    $("#login-code").focus();
  } catch (error) {
    button.disabled = false;
    button.textContent = "获取验证码";
    setLoginError(error.message);
    if (error.status === 403) showTurnstile();
  }
}

async function submitLogin(event) {
  event.preventDefault();
  const phone = normalizePhoneInput($("#login-phone").value);
  const smsCode = $("#login-code").value.replace(/\D/g, "").slice(0, 6);
  if (!validPhone(phone)) {
    setLoginError("请输入有效的中国大陆手机号");
    return;
  }
  if (!validCode(smsCode)) {
    setLoginError("请输入 6 位验证码");
    return;
  }
  const button = $("#login-submit");
  button.disabled = true;
  button.textContent = "正在进入…";
  setLoginError();
  try {
    const result = await api("/api/auth/login/sms", {
      method: "POST",
      body: JSON.stringify({ phone, sms_code: smsCode }),
    });
    accessToken = result.access_token;
    const user = await api("/api/auth/me");
    await showApp(user);
    const target = sessionStorage.getItem("finance-post-login-path");
    sessionStorage.removeItem("finance-post-login-path");
    if (target) window.history.replaceState({}, "", safePostLoginPath(target));
  } catch (error) {
    setLoginError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "继续";
  }
}

async function logoutCurrentDevice() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch {
    // Clearing in-memory state still prevents further authenticated requests.
  }
  showLogin();
  $("#login-code").value = "";
}

async function bootstrapAuth() {
  $("#auth-loading").classList.remove("hidden");
  $("#login-screen").classList.add("hidden");
  $("#app-shell").classList.add("hidden");
  try {
    const config = await fetch("/api/auth/config").then((response) => response.json());
    appState.turnstileSiteKey = config.turnstile_site_key || "";
    const restored = await refreshAccessToken();
    if (!restored) {
      showLogin();
      return;
    }
    const user = await api("/api/auth/me");
    await showApp(user);
  } catch {
    showLogin();
  }
}

function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.classList.remove("show"), 2800);
}

function showView(viewName, updateLocation = true) {
  const targetView = viewName === "import" ? "chat" : viewName;
  $$(".view").forEach((view) => view.classList.toggle("active-view", view.id === `${targetView}-view`));
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === targetView));
  renderUserIdentity();
  $(".sidebar").classList.remove("open");
  if (updateLocation && ["dashboard", "chat", "ledger", "receipts"].includes(targetView)) {
    window.history.replaceState({}, "", `#${targetView}`);
  }
}

function ledgerStorageKey() {
  return `finance-selected-ledger:${appState.user?.phone || "current"}`;
}

function selectedLedger() {
  return appState.data?.ledgers?.find((ledger) => ledger.id === appState.selectedLedgerId) || null;
}

function selectLedger(ledgerId, announce = false) {
  if (!appState.data?.ledgers?.some((ledger) => ledger.id === ledgerId)) return;
  appState.selectedLedgerId = ledgerId;
  window.localStorage.setItem(ledgerStorageKey(), ledgerId);
  renderLedgerSelector();
  renderLedger();
  if (announce) notify(`已切换到 ${selectedLedger()?.name || "当前账本"}`);
}

function renderLedgerSelector() {
  const importSelector = $("#import-ledger-select");
  const ledgers = appState.data?.ledgers || [];
  renderLedgerFilter();
  if (!ledgers.length) {
    importSelector.innerHTML = "<option value=\"\">请先创建账本</option>";
    importSelector.disabled = true;
    $("#commit-import").disabled = true;
    return;
  }
  const storedLedgerId = window.localStorage.getItem(ledgerStorageKey());
  if (!ledgers.some((ledger) => ledger.id === appState.selectedLedgerId)) {
    appState.selectedLedgerId = ledgers.some((ledger) => ledger.id === storedLedgerId)
      ? storedLedgerId
      : ledgers[0].id;
  }
  window.localStorage.setItem(ledgerStorageKey(), appState.selectedLedgerId);
  importSelector.disabled = false;
  const options = ledgers.map((ledger) => `<option value="${escapeHtml(ledger.id)}">${escapeHtml(ledger.name)}</option>`).join("");
  importSelector.innerHTML = options;
  importSelector.value = appState.selectedLedgerId;
  $("#commit-import").disabled = !appState.importPreview;
}

function renderLedgerFilter() {
  const ledgers = appState.data?.ledgers || [];
  if (Array.isArray(appState.ledgerFilterIds)) {
    appState.ledgerFilterIds = appState.ledgerFilterIds.filter((id) =>
      ledgers.some((ledger) => ledger.id === id),
    );
    if (ledgers.length && appState.ledgerFilterIds.length === ledgers.length) {
      appState.ledgerFilterIds = null;
    }
  }
  const allSelected = appState.ledgerFilterIds === null;
  const selectedIds = allSelected ? ledgers.map((ledger) => ledger.id) : appState.ledgerFilterIds;
  const selectedNames = ledgers
    .filter((ledger) => selectedIds.includes(ledger.id))
    .map((ledger) => ledger.name);
  $("#ledger-filter-label").textContent = allSelected
    ? "全部账本"
    : selectedNames.length === 1
      ? selectedNames[0]
      : selectedNames.length
        ? `已选 ${selectedNames.length} 个账本`
        : "未选择账本";
  $("#ledger-filter-menu").innerHTML = `
    <label class="ledger-filter-option ledger-filter-all">
      <input type="checkbox" data-ledger-filter-all ${allSelected ? "checked" : ""} />
      <span>全部账本</span>
    </label>
    ${ledgers.map((ledger) => `
      <label class="ledger-filter-option">
        <input type="checkbox" data-ledger-filter-id="${escapeHtml(ledger.id)}" ${selectedIds.includes(ledger.id) ? "checked" : ""} />
        <span>${escapeHtml(ledger.name)}</span>
      </label>
    `).join("")}
  `;
}

function updateLedgerFilter(event) {
  const ledgers = appState.data?.ledgers || [];
  const allIds = ledgers.map((ledger) => ledger.id);
  if (event.target.matches("[data-ledger-filter-all]")) {
    appState.ledgerFilterIds = event.target.checked ? null : [];
  } else if (event.target.matches("[data-ledger-filter-id]")) {
    const ledgerId = event.target.dataset.ledgerFilterId;
    const selected = appState.ledgerFilterIds === null ? [...allIds] : [...appState.ledgerFilterIds];
    appState.ledgerFilterIds = event.target.checked
      ? [...new Set([...selected, ledgerId])]
      : selected.filter((id) => id !== ledgerId);
    if (appState.ledgerFilterIds.length === allIds.length) appState.ledgerFilterIds = null;
  } else {
    return;
  }
  renderLedgerFilter();
  renderLedger();
}

function renderChatDashboard() {
  const dashboard = appState.data?.dashboard;
  if (!dashboard) return;
  $("#chat-dashboard-summary").innerHTML = `<h3>财务摘要</h3><div class="mini-metrics"><div><span>消费</span><strong>${currency(dashboard.spend)}</strong></div><div><span>收入</span><strong>${currency(dashboard.income)}</strong></div><div><span>净现金流</span><strong>${currency(dashboard.net)}</strong></div></div><p class="mini-insight">${escapeHtml(dashboard.insight)}</p><button class="text-button" data-view-target="dashboard">查看财务总览 →</button>`;
  $("#chat-dashboard-summary [data-view-target]").addEventListener("click", () => showView("dashboard"));
}

function renderDashboard() {
  const ledgers = appState.data.ledgers || [];
  if (appState.dashboardLedgerId && !ledgers.some((ledger) => ledger.id === appState.dashboardLedgerId)) {
    appState.dashboardLedgerId = "";
  }
  const dashboardSelector = $("#dashboard-ledger-filter");
  dashboardSelector.innerHTML = `<option value="">全部账本</option>${ledgers.map(
    (ledger) => `<option value="${escapeHtml(ledger.id)}">${escapeHtml(ledger.name)}</option>`,
  ).join("")}`;
  dashboardSelector.value = appState.dashboardLedgerId;
  const dashboard = appState.dashboardLedgerId
    ? appState.data.dashboardsByLedger?.[appState.dashboardLedgerId] || appState.data.dashboard
    : appState.data.dashboard;
  $("#focus-month").textContent = monthLabel(dashboard.month);
  $("#metric-spend").textContent = currency(dashboard.spend);
  $("#metric-income").textContent = currency(dashboard.income);
  $("#metric-net").textContent = currency(dashboard.net);
  $("#metric-spend-delta").textContent = `${dashboard.recent.length} 笔记录`;
  $("#dashboard-insight").textContent = dashboard.insight;

  const trend = dashboard.trend || [];
  const maxTrend = Math.max(1, ...trend.map((item) => item.value));
  $("#trend-chart").innerHTML = trend.map((item) => `<div class="trend-column"><em>${item.value ? currency(item.value) : "—"}</em><div class="trend-bar" style="height:${Math.max(4, item.value / maxTrend * 100)}%"></div><small>${item.month.slice(5)}月</small></div>`).join("");

  const categories = Object.entries(dashboard.categories || {}).sort((a, b) => b[1] - a[1]);
  const categoryTotal = categories.reduce((sum, [, value]) => sum + value, 0) || 1;
  const firstPercent = Math.round((categories[0]?.[1] || 0) / categoryTotal * 100);
  $("#donut-percent").textContent = `${firstPercent}%`;
  const stops = [];
  let cursor = 0;
  categories.forEach(([, value], index) => { const end = cursor + value / categoryTotal * 100; stops.push(`${palette[index % palette.length]} ${cursor}% ${end}%`); cursor = end; });
  $("#donut-chart").style.background = stops.length ? `conic-gradient(${stops.join(",")})` : "#e7ebf0";
  $("#category-legend").innerHTML = categories.length ? categories.map(([label, value], index) => `<div class="legend-row"><span class="legend-label"><i class="legend-dot" style="background:${palette[index % palette.length]}"></i>${escapeHtml(label)}</span><strong>${Math.round(value / categoryTotal * 100)}%</strong></div>`).join("") : `<span class="muted-label">暂无分类</span>`;

  $("#recent-list").innerHTML = (dashboard.recent || []).slice(0, 5).map((tx) => `<div class="recent-row"><span class="transaction-icon ${tx.type}">${tx.type === "income" ? "↗" : "↘"}</span><div class="recent-main"><strong>${escapeHtml(tx.note)}</strong><small>${escapeHtml(categoryLabel(tx))} · ${dateLabel(tx.date)}</small></div><div class="recent-amount"><strong class="${tx.type}">${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong><small>${sourceLabel(tx.source)}</small></div></div>`).join("") || `<div class="empty-state">还没有交易。</div>`;
}

function renderLedger() {
  const ledgersById = new Map((appState.data.ledgers || []).map((ledger) => [ledger.id, ledger]));
  const rows = (appState.data.transactions || []).filter((tx) => {
    const matchesLedger = appState.ledgerFilterIds === null
      || appState.ledgerFilterIds.includes(tx.ledgerId);
    const matchesFilter = appState.filter === "all" || tx.type === appState.filter;
    const ledgerName = ledgersById.get(tx.ledgerId)?.name || "个人账本";
    const haystack = `${tx.note} ${tx.category} ${tx.subcategory || ""} ${(tx.tags || []).join(" ")} ${ledgerName} ${tx.date}`.toLowerCase();
    return matchesLedger && matchesFilter && haystack.includes(appState.query.toLowerCase());
  }).sort((a, b) => b.date.localeCompare(a.date));
  $("#ledger-empty").classList.toggle("hidden", rows.length > 0);
  $("#ledger-table-body").innerHTML = rows.map((tx) => { const receipt = tx.receiptId && appState.data.receipts.find((item) => item.id === tx.receiptId); const receiptAction = receipt ? `<button class="row-action" data-view-receipt-id="${escapeHtml(tx.receiptId)}">凭证</button>` : ""; const ledgerName = ledgersById.get(tx.ledgerId)?.name || "个人账本"; return `<tr><td><div class="table-transaction"><span class="transaction-icon ${tx.type}">${tx.type === "income" ? "↗" : "↘"}</span><div><strong>${escapeHtml(tx.note)}</strong><small>${tx.type === "income" ? "收入" : "支出"}</small></div></div></td><td><span class="ledger-badge">${escapeHtml(ledgerName)}</span></td><td><span class="category-tag">${escapeHtml(categoryLabel(tx))}</span><div class="transaction-tags">${renderTagChips(tx.tags)}</div></td><td>${dateLabel(tx.date)}</td><td>${sourceLabel(tx.source)}</td><td class="align-right ${tx.type === "income" ? "amount-income" : "amount-expense"}">${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</td><td class="align-right"><div class="row-actions"><button class="row-action" data-detail-id="${escapeHtml(tx.id)}">详情</button>${receiptAction}<button class="row-action" data-edit-id="${escapeHtml(tx.id)}">编辑</button><button class="row-action danger" data-delete-id="${escapeHtml(tx.id)}">删除</button></div></td></tr>`; }).join("");
}

async function viewTransactionReceipt(receiptId) {
  const receipt = appState.data.receipts.find((item) => item.id === receiptId);
  if (!receipt?.fileUrl) { notify("这笔交易暂未保存原始图片"); return; }
  const previewWindow = window.open("", "_blank", "noopener");
  try {
    const blob = await api(receipt.fileUrl, { responseType: "blob" });
    const objectUrl = URL.createObjectURL(blob);
    if (previewWindow) previewWindow.location = objectUrl;
    else window.location.assign(objectUrl);
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  } catch (error) {
    if (previewWindow) previewWindow.close();
    notify(`凭证读取失败：${error.message}`);
  }
}

function openTransactionDetails(transactionId) {
  const tx = appState.data.transactions.find((item) => item.id === transactionId);
  if (!tx) return;
  const receipt = tx.receiptId && appState.data.receipts.find((item) => item.id === tx.receiptId);
  const ledger = appState.data.ledgers.find((item) => item.id === tx.ledgerId);
  $("#transaction-detail-content").innerHTML = `<p class="eyebrow">交易详情</p><h3 id="transaction-detail-title">${escapeHtml(tx.note)}</h3><div class="detail-grid"><span>金额</span><strong class="${tx.type === "income" ? "amount-income" : "amount-expense"}">${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong><span>类型</span><strong>${tx.type === "income" ? "收入" : "支出"}</strong><span>一级分类</span><strong>${escapeHtml(tx.category)}</strong><span>二级分类</span><strong>${escapeHtml(tx.subcategory || "其他")}</strong><span>标签</span><strong class="detail-tags">${renderTagChips(tx.tags) || "—"}</strong><span>日期</span><strong>${escapeHtml(tx.date)}</strong><span>账本</span><strong>${escapeHtml(ledger?.name || "个人账本")}</strong><span>来源</span><strong>${sourceLabel(tx.source)}</strong></div>${receipt?.fileUrl ? `<div class="detail-receipt"><img data-protected-receipt="${escapeHtml(receipt.id)}" alt="${escapeHtml(receipt.filename)}" /><button class="text-button" data-modal-receipt-id="${escapeHtml(receipt.id)}">查看原始凭证 →</button></div>` : `<p class="muted-label detail-empty">暂无关联原始凭证</p>`}<div class="detail-actions"><button class="primary-button" type="button" data-edit-detail-id="${escapeHtml(tx.id)}">编辑完整明细</button></div>`;
  $("#transaction-modal").classList.remove("hidden");
  hydrateProtectedReceiptImages($("#transaction-detail-content"));
  const receiptButton = $("#transaction-detail-content [data-modal-receipt-id]");
  if (receiptButton) receiptButton.addEventListener("click", () => viewTransactionReceipt(receiptButton.dataset.modalReceiptId));
  $("#transaction-detail-content [data-edit-detail-id]").addEventListener("click", () => {
    closeTransactionDetails();
    editTransaction(tx.id);
  });
}

function closeTransactionDetails() {
  $("#transaction-modal").classList.add("hidden");
}

function editTransaction(transactionId) {
  const tx = appState.data.transactions.find((item) => item.id === transactionId);
  if (!tx) return;
  editingTransactionId = transactionId;
  $("#transaction-edit-error").textContent = "";
  $("#transaction-edit-note").value = tx.note;
  $("#transaction-edit-amount").value = Number(tx.amount).toFixed(2);
  $("#transaction-edit-type").value = tx.type;
  updateTransactionCategoryInputs(tx.category, tx.subcategory);
  $("#transaction-edit-tags").value = (tx.tags || []).join("，");
  $("#transaction-edit-date").value = tx.date;
  $("#transaction-edit-ledger").innerHTML = appState.data.ledgers.map(
    (ledger) => `<option value="${escapeHtml(ledger.id)}">${escapeHtml(ledger.name)}</option>`,
  ).join("");
  $("#transaction-edit-ledger").value = tx.ledgerId;
  $("#transaction-edit-source").textContent = `记录来源：${sourceLabel(tx.source)}（来源与原始凭证保持只读）`;
  $("#transaction-edit-modal").classList.remove("hidden");
  window.setTimeout(() => $("#transaction-edit-note").focus(), 40);
}

function updateTransactionCategoryInputs(selectedCategory = "", selectedSubcategory = "") {
  const transactionType = $("#transaction-edit-type").value;
  const taxonomy = appState.data?.categoryOptions?.taxonomy?.[transactionType] || {};
  const categories = Object.keys(taxonomy);
  const category = categories.includes(selectedCategory) ? selectedCategory : categories[0] || "";
  $("#transaction-edit-category").innerHTML = categories.map(
    (item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`,
  ).join("");
  $("#transaction-edit-category").value = category;
  const subcategories = taxonomy[category] || ["其他"];
  const subcategory = subcategories.includes(selectedSubcategory) ? selectedSubcategory : subcategories[0];
  $("#transaction-edit-subcategory").innerHTML = subcategories.map(
    (item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`,
  ).join("");
  $("#transaction-edit-subcategory").value = subcategory;
}

function closeTransactionEditor() {
  editingTransactionId = null;
  $("#transaction-edit-modal").classList.add("hidden");
}

async function saveTransactionEdits(event) {
  event.preventDefault();
  if (!editingTransactionId) return;
  const payload = {
    ledgerId: $("#transaction-edit-ledger").value,
    amount: $("#transaction-edit-amount").value,
    type: $("#transaction-edit-type").value,
    category: $("#transaction-edit-category").value,
    subcategory: $("#transaction-edit-subcategory").value,
    tags: $("#transaction-edit-tags").value,
    note: $("#transaction-edit-note").value.trim(),
    date: $("#transaction-edit-date").value,
  };
  if (!payload.note || !payload.category || !payload.subcategory || !payload.amount || !payload.date || !payload.ledgerId) {
    $("#transaction-edit-error").textContent = "请完整填写账目字段";
    return;
  }
  try {
    await api(`/api/transactions/${encodeURIComponent(editingTransactionId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    closeTransactionEditor();
    await loadState();
    notify("账目明细已全部更新");
  } catch (error) {
    $("#transaction-edit-error").textContent = error.message;
  }
}

async function deleteTransaction(transactionId) {
  const tx = appState.data.transactions.find((item) => item.id === transactionId);
  if (!tx || !window.confirm(`删除“${tx.note}”这笔交易？`)) return;
  try {
    await api(`/api/transactions/${encodeURIComponent(transactionId)}`, { method: "DELETE" });
    await loadState();
    notify("交易已删除");
  } catch (error) { notify(`删除失败：${error.message}`); }
}

function renderReceipts() {
  const receipts = appState.data.receipts || [];
  $("#receipt-list").innerHTML = receipts.length ? receipts.map((receipt) => `<div class="receipt-row"><div class="receipt-thumb">${receipt.fileUrl ? `<img data-protected-receipt="${escapeHtml(receipt.id)}" alt="${escapeHtml(receipt.filename)}" />` : "▤"}</div><div><strong>${escapeHtml(receipt.merchant)}</strong><small>${currency(receipt.amount)} · ${escapeHtml(receipt.category)} · ${dateLabel(receipt.date)}</small></div><div class="receipt-actions">${receipt.fileUrl ? `<button class="view-receipt" data-view-receipt-id="${escapeHtml(receipt.id)}">查看照片</button>` : ""}<button class="edit-receipt" data-edit-receipt-id="${escapeHtml(receipt.id)}">编辑识别</button>${receipt.transactionId ? `<button disabled>已记账</button>` : `<button class="apply-receipt" data-receipt-id="${escapeHtml(receipt.id)}">记入账本</button>`}</div></div>`).join("") : `<div class="empty-state">上传第一张凭证，开始建立你的财务档案。</div>`;
  hydrateProtectedReceiptImages($("#receipt-list"));
}

async function hydrateProtectedReceiptImages(root = document) {
  const images = [...root.querySelectorAll("[data-protected-receipt]")];
  await Promise.all(images.map(async (image) => {
    const receiptId = image.dataset.protectedReceipt;
    const receipt = appState.data.receipts.find((item) => item.id === receiptId);
    if (!receipt?.fileUrl) return;
    try {
      let objectUrl = receiptObjectUrls.get(receiptId);
      if (!objectUrl) {
        const blob = await api(receipt.fileUrl, { responseType: "blob" });
        objectUrl = URL.createObjectURL(blob);
        receiptObjectUrls.set(receiptId, objectUrl);
      }
      image.src = objectUrl;
    } catch {
      image.replaceWith(document.createTextNode("▤"));
    }
  }));
}

async function editReceipt(receiptId) {
  const receipt = appState.data.receipts.find((item) => item.id === receiptId);
  if (!receipt) return;
  const merchant = window.prompt("商户", receipt.merchant);
  if (merchant === null) return;
  const amount = window.prompt("金额（元）", String(receipt.amount));
  if (amount === null) return;
  const category = window.prompt("分类", receipt.category);
  if (category === null) return;
  const date = window.prompt("日期（YYYY-MM-DD）", receipt.date);
  if (date === null) return;
  const parsedAmount = Number(amount);
  if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) { notify("请输入有效金额"); return; }
  try {
    await api(`/api/receipts/${encodeURIComponent(receiptId)}`, { method: "PATCH", body: JSON.stringify({ merchant, amount: parsedAmount, category, date }) });
    await loadState();
    notify("识别结果已更新");
  } catch (error) { notify(`更新失败：${error.message}`); }
}

function addMessage(text, role = "ai") {
  const messages = $("#chat-messages");
  const message = document.createElement("div");
  message.className = `message ${role}`;
  message.textContent = text;
  messages.appendChild(message);
  messages.scrollTop = messages.scrollHeight;
}

function renderParsePreview(parsed) {
  const preview = $("#parse-preview");
  appState.pendingParse = parsed;
  if (!parsed.transactions?.length) {
    preview.classList.remove("hidden");
    preview.innerHTML = `<p class="eyebrow">需要更多信息</p><h3>没有识别到金额</h3><p class="subcopy">试试“停车112元”或“记录工资5000元”。</p>`;
    return;
  }
  preview.classList.remove("hidden");
  const targetLedger = parsed.ledger?.name;
  const ledgerControl = targetLedger
    ? `<div class="preview-ledger-target"><span>写入账本</span><strong>${escapeHtml(targetLedger)}（新建）</strong></div>`
    : appState.data.ledgers.length
      ? `<label class="preview-ledger-field" for="parse-ledger-select"><span>写入账本</span><select id="parse-ledger-select">${appState.data.ledgers.map((ledger) => `<option value="${escapeHtml(ledger.id)}">${escapeHtml(ledger.name)}</option>`).join("")}</select></label>`
      : `<div class="preview-ledger-target"><span>写入账本</span><strong>提交后创建默认账本</strong></div>`;
  preview.innerHTML = `<p class="eyebrow">结构化预览</p><h3>确认账务信息</h3>${ledgerControl}${parsed.transactions.map((tx) => `<div class="preview-line"><span>${escapeHtml(tx.note)}</span><strong>${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong></div><div class="preview-line"><span>类型</span><strong>${tx.type === "income" ? "收入" : "支出"}</strong></div><div class="preview-line"><span>分类</span><strong>${escapeHtml(categoryLabel(tx))}</strong></div>`).join("")}<div class="preview-actions"><button class="cancel-button" id="cancel-preview">取消</button><button class="confirm-button" id="confirm-preview">确认写入</button></div>`;
  const parseLedgerSelector = $("#parse-ledger-select");
  if (parseLedgerSelector) {
    parseLedgerSelector.value = appState.selectedLedgerId || appState.data.ledgers[0].id;
    parseLedgerSelector.addEventListener("change", (event) => {
      appState.selectedLedgerId = event.target.value;
      window.localStorage.setItem(ledgerStorageKey(), appState.selectedLedgerId);
    });
  }
  $("#confirm-preview").addEventListener("click", confirmParsedTransactions);
  $("#cancel-preview").addEventListener("click", () => preview.classList.add("hidden"));
}

async function confirmParsedTransactions() {
  if (!appState.pendingParse?.transactions?.length) return;
  try {
    const ledgerName = appState.pendingParse.ledger?.name || selectedLedger()?.name;
    const result = await api("/api/transactions/batch", { method: "POST", body: JSON.stringify({ ledgerName, transactions: appState.pendingParse.transactions }) });
    const createdLedger = result.state?.ledgers?.find((ledger) => ledger.name === ledgerName);
    if (createdLedger) appState.selectedLedgerId = createdLedger.id;
    addMessage(`已写入 ${result.transactions.length} 笔记录，所有字段都可以在智能账本中继续编辑。`);
    $("#parse-preview").classList.add("hidden");
    appState.pendingParse = null;
    await loadState();
    notify("记录已写入账本");
  } catch (error) { addMessage(`写入失败：${error.message}`); }
}

async function handleChat(event) {
  event.preventDefault();
  const input = $("#chat-input");
  const value = input.value.trim();
  if (!value) return;
  input.value = "";
  appState.importPreview = null;
  $("#import-preview").classList.add("hidden");
  $("#bill-file").value = "";
  $("#bill-upload-status").textContent = "支持 Excel（.xlsx）与 CSV，AI 解析后会在右侧等待确认。";
  addMessage(value, "user");
  try {
    if (/为什么|花这么多|支出/.test(value)) {
      const result = await api(`/api/insights?question=${encodeURIComponent(value)}`);
      addMessage(result.answer);
      result.reasons?.forEach((reason) => addMessage(`${reason.category}  +${currency(reason.amount)}`, "ai"));
      if (result.suggestion) addMessage(`建议：${result.suggestion}`);
      return;
    }
    const parsed = await api("/api/parse", { method: "POST", body: JSON.stringify({ text: value }) });
    if (parsed.transactions?.length) addMessage(`我识别到了 ${parsed.transactions.length} 笔结构化记录，请在右侧预览后确认。`);
    else addMessage("我还没有识别到金额，可以试试“刚刚停车112元，帮我记一下”。");
    renderParsePreview(parsed);
  } catch (error) { addMessage(`暂时无法完成：${error.message}`); }
}

function dataUrlToPayload(dataUrl) {
  const [, base64] = dataUrl.split(",");
  return base64 || "";
}

function processReceiptFile(file) {
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) { notify("图片不能超过 8MB"); return; }
  const progress = $("#upload-progress");
  const progressBar = $("#upload-progress-bar");
  progress.classList.remove("hidden", "error");
  progressBar.style.width = "18%";
  $("#upload-status").textContent = "正在上传并提取商户、金额和分类…";
  const reader = new FileReader();
  reader.onprogress = (progressEvent) => { if (progressEvent.lengthComputable) progressBar.style.width = `${Math.max(18, Math.round(progressEvent.loaded / progressEvent.total * 70))}%`; };
  reader.onload = async () => {
    try {
      progressBar.style.width = "72%";
      await api("/api/receipts", { method: "POST", body: JSON.stringify({ filename: file.name, contentType: file.type, data: dataUrlToPayload(reader.result), hint: file.name }) });
      await loadState();
      progressBar.style.width = "100%";
      $("#upload-status").textContent = "识别完成，可确认后记入账本。";
      notify("凭证已保存");
    } catch (error) { progress.classList.add("error"); progressBar.style.width = "100%"; $("#upload-status").textContent = `上传失败：${error.message}`; }
  };
  reader.onerror = () => { progress.classList.add("error"); progressBar.style.width = "100%"; $("#upload-status").textContent = "上传失败：无法读取图片"; };
  reader.readAsDataURL(file);
}

function handleReceipt(event) {
  processReceiptFile(event.target.files?.[0]);
}

async function applyReceipt(receiptId) {
  try { await api("/api/receipts/apply", { method: "POST", body: JSON.stringify({ receiptId, ledgerName: selectedLedger()?.name }) }); await loadState(); notify("凭证已关联到交易"); }
  catch (error) { notify(`关联失败：${error.message}`); }
}

function openLedgerModal() {
  $("#ledger-form-error").textContent = "";
  $("#ledger-name-input").value = "";
  $("#ledger-modal").classList.remove("hidden");
  window.setTimeout(() => $("#ledger-name-input").focus(), 40);
}

function closeLedgerModal() {
  $("#ledger-modal").classList.add("hidden");
}

async function createLedgerFromModal(event) {
  event.preventDefault();
  const name = $("#ledger-name-input").value.trim();
  if (!name) {
    $("#ledger-form-error").textContent = "请输入账本名称";
    return;
  }
  try {
    const result = await api("/api/ledgers", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    appState.data = result.state;
    appState.selectedLedgerId = result.ledger.id;
    closeLedgerModal();
    renderLedgerSelector();
    renderDashboard();
    renderChatDashboard();
    renderLedger();
    renderReceipts();
    notify(`已创建并切换到 ${result.ledger.name}`);
  } catch (error) {
    $("#ledger-form-error").textContent = error.message;
  }
}

function openProfileModal() {
  $("#profile-form-error").textContent = "";
  $("#profile-name-input").value = appState.user?.display_name || "";
  $("#profile-phone").textContent = `登录手机号：${appState.user?.masked_phone || "—"}`;
  $("#profile-modal").classList.remove("hidden");
  window.setTimeout(() => $("#profile-name-input").focus(), 40);
}

function closeProfileModal() {
  $("#profile-modal").classList.add("hidden");
}

async function saveProfile(event) {
  event.preventDefault();
  const displayName = $("#profile-name-input").value.trim();
  if (!displayName) {
    $("#profile-form-error").textContent = "请输入用户名";
    return;
  }
  try {
    appState.user = await api("/api/auth/me", {
      method: "PATCH",
      body: JSON.stringify({ display_name: displayName }),
    });
    renderUserIdentity();
    closeProfileModal();
    notify("用户名已更新");
  } catch (error) {
    $("#profile-form-error").textContent = error.message;
  }
}

function renderLedgerManager() {
  const ledgers = appState.data?.ledgers || [];
  $("#ledger-manager-list").innerHTML = ledgers.length
    ? ledgers.map((ledger) => `
      <div class="ledger-manager-row" data-ledger-row="${escapeHtml(ledger.id)}">
        <input value="${escapeHtml(ledger.name)}" maxlength="80" aria-label="账本名称：${escapeHtml(ledger.name)}" />
        <button class="ledger-manager-save" type="button" data-rename-ledger="${escapeHtml(ledger.id)}">保存</button>
        <button class="ledger-manager-delete" type="button" data-delete-ledger="${escapeHtml(ledger.id)}">删除</button>
      </div>
    `).join("")
    : `<div class="ledger-manager-empty">还没有账本，可以关闭后新建一个。</div>`;
}

function openLedgerManager() {
  renderLedgerManager();
  $("#ledger-manager-modal").classList.remove("hidden");
}

function closeLedgerManager() {
  $("#ledger-manager-modal").classList.add("hidden");
}

async function renameLedger(ledgerId) {
  const row = $(`[data-ledger-row="${CSS.escape(ledgerId)}"]`);
  const name = row?.querySelector("input")?.value.trim();
  if (!name) {
    notify("请输入账本名称");
    return;
  }
  try {
    const result = await api(`/api/ledgers/${encodeURIComponent(ledgerId)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    appState.data = result.state;
    renderLedgerSelector();
    renderLedger();
    renderLedgerManager();
    notify(`账本已重命名为 ${result.ledger.name}`);
  } catch (error) {
    notify(`重命名失败：${error.message}`);
  }
}

async function removeLedger(ledgerId) {
  const ledger = appState.data.ledgers.find((item) => item.id === ledgerId);
  if (!ledger) return;
  const transactionCount = appState.data.transactions.filter((item) => item.ledgerId === ledgerId).length;
  if (!window.confirm(`删除账本“${ledger.name}”及其中 ${transactionCount} 笔交易？此操作无法撤销。`)) return;
  try {
    const result = await api(`/api/ledgers/${encodeURIComponent(ledgerId)}`, { method: "DELETE" });
    appState.data = result.state;
    if (appState.selectedLedgerId === ledgerId) appState.selectedLedgerId = result.state.ledgers[0]?.id || null;
    renderLedgerSelector();
    renderDashboard();
    renderChatDashboard();
    renderLedger();
    renderReceipts();
    renderLedgerManager();
    notify(`账本“${ledger.name}”已删除`);
  } catch (error) {
    notify(`删除失败：${error.message}`);
  }
}

function renderImportSelectionSummary() {
  const selected = $$("#import-table-body input[data-import-index]:checked").length;
  const conflictSelects = $$("#import-table-body select[data-conflict-index]");
  const unresolved = conflictSelects.filter((select) => !select.value).length;
  const resolved = conflictSelects.length - unresolved;
  $("#import-selection-summary").textContent = conflictSelects.length
    ? `已选择 ${selected} 笔新增 · 已确认 ${resolved}/${conflictSelects.length} 笔冲突`
    : `已选择 ${selected} 笔交易`;
  $("#commit-import").disabled = !appState.selectedLedgerId
    || unresolved > 0
    || (selected === 0 && conflictSelects.length === 0);
}

function importVersionCard(label, transaction, ledgerName = "") {
  return `
    <div class="import-version-card">
      <span>${label}</span>
      <strong>${escapeHtml(transaction.note)}</strong>
      <small>${escapeHtml(categoryLabel(transaction))} · ${escapeHtml(transaction.date)}${ledgerName ? ` · ${escapeHtml(ledgerName)}` : ""}</small>
      <b class="${transaction.type === "income" ? "amount-income" : "amount-expense"}">${transaction.type === "income" ? "+" : "−"}${currency(transaction.amount)}</b>
    </div>
  `;
}

function renderImportPreview(preview) {
  appState.importPreview = preview;
  $("#import-preview").classList.remove("hidden");
  $("#import-preview-title").textContent = preview.fileName;
  $("#import-provider-badge").textContent = preview.providerLabel;
  $("#import-count").textContent = preview.importableCount;
  $("#import-duplicate-count").textContent = preview.duplicateCount;
  $("#import-conflict-count").textContent = preview.conflictCount;
  $("#import-skipped-count").textContent = preview.skippedCount;
  $("#import-table-body").innerHTML = preview.transactions.map((tx, index) => {
    if (tx.conflict) {
      return `
        <section class="import-conflict-row">
          <div class="import-conflict-heading">
            <span class="import-conflict-badge">需二次确认</span>
            <strong>检测到系统记录已被修改</strong>
          </div>
          <div class="import-conflict-versions">
            ${importVersionCard("系统版本", tx.existingTransaction, tx.existingTransaction.ledgerName)}
            ${importVersionCard("文件版本", tx, selectedLedger()?.name || "目标账本")}
          </div>
          <label class="import-conflict-choice">
            <span>这笔交易保留哪一条？</span>
            <select data-conflict-index="${index}" aria-label="选择 ${escapeHtml(tx.note)} 保留版本">
              <option value="">请选择保留版本</option>
              <option value="keep-existing">保留系统版本</option>
              <option value="replace-existing">使用文件版本</option>
            </select>
          </label>
        </section>
      `;
    }
    return `
      <label class="import-confirm-row ${tx.duplicate ? "is-duplicate" : ""}">
        <input type="checkbox" data-import-index="${index}" ${tx.duplicate ? "disabled" : "checked"} aria-label="选择 ${escapeHtml(tx.note)}" />
        <span class="import-confirm-main">
          <strong>${escapeHtml(tx.note)}</strong>
          <small>${escapeHtml(categoryLabel(tx))} · ${escapeHtml(tx.date)}${tx.duplicate ? ` · ${escapeHtml(tx.duplicateReason)}` : ""}</small>
        </span>
        <strong class="${tx.type === "income" ? "amount-income" : "amount-expense"}">${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong>
      </label>
    `;
  }).join("");
  $("#import-select-all").checked = preview.importableCount > 0;
  renderImportSelectionSummary();
}

async function processBillFile(file) {
  if (!file) return;
  if (!/\.(xlsx|csv)$/i.test(file.name)) {
    $("#bill-file").value = "";
    notify("仅支持 Excel（.xlsx）或 CSV 文件");
    return;
  }
  if (file.size > 12 * 1024 * 1024) {
    $("#bill-file").value = "";
    notify("账单文件不能超过 12MB");
    return;
  }
  const status = $("#bill-upload-status");
  appState.pendingParse = null;
  $("#parse-preview").classList.add("hidden");
  $("#import-preview").classList.add("hidden");
  addMessage(`上传账单：${file.name}`, "user");
  status.textContent = "正在识别账单格式、退款与重复记录…";
  const formData = new FormData();
  formData.append("file", file);
  try {
    const preview = await api("/api/imports/preview", { method: "POST", body: formData });
    renderImportPreview(preview);
    status.textContent = `已识别 ${preview.totalRows} 笔原始记录，其中 ${preview.conflictCount} 笔需要二次确认。`;
    addMessage(`已识别 ${preview.importableCount} 笔可新增记录、${preview.conflictCount} 笔冲突记录，请在右侧确认。`);
    $("#import-preview").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    $("#bill-file").value = "";
    status.textContent = `解析失败：${error.message}`;
    addMessage(`账单解析失败：${error.message}`);
    notify(`账单解析失败：${error.message}`);
  }
}

async function commitBillImport() {
  if (!appState.importPreview || !appState.selectedLedgerId) {
    notify("请先选择或创建目标账本");
    return;
  }
  const selectedTransactions = $$("#import-table-body input[data-import-index]:checked")
    .map((input) => appState.importPreview.transactions[Number(input.dataset.importIndex)]);
  const conflictSelects = $$("#import-table-body select[data-conflict-index]");
  if (conflictSelects.some((select) => !select.value)) {
    notify("请先确认每一笔冲突记录保留哪个版本");
    return;
  }
  const resolvedTransactions = conflictSelects.map((select) => ({
    ...appState.importPreview.transactions[Number(select.dataset.conflictIndex)],
    resolution: select.value,
  }));
  const transactions = [...selectedTransactions, ...resolvedTransactions];
  if (!transactions.length) {
    notify("请至少选择一笔交易");
    return;
  }
  const button = $("#commit-import");
  button.disabled = true;
  button.textContent = "正在导入…";
  try {
    const result = await api("/api/imports/commit", {
      method: "POST",
      body: JSON.stringify({
        ledgerId: appState.selectedLedgerId,
        transactions,
      }),
    });
    appState.data = result.state;
    appState.importPreview = null;
    $("#import-preview").classList.add("hidden");
    $("#bill-file").value = "";
    $("#bill-upload-status").textContent = `新增 ${result.importedCount} 笔，更新 ${result.updatedCount} 笔，跳过 ${result.skippedCount} 笔。`;
    renderLedgerSelector();
    renderDashboard();
    renderChatDashboard();
    renderLedger();
    renderReceipts();
    addMessage(`账单已处理：新增 ${result.importedCount} 笔，按选择更新 ${result.updatedCount} 笔。`);
    notify(`账单已处理：新增 ${result.importedCount} 笔，更新 ${result.updatedCount} 笔`);
  } catch (error) {
    notify(`导入失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "确认导入";
  }
}

async function loadState() {
  appState.data = await api("/api/state");
  renderLedgerSelector(); renderDashboard(); renderChatDashboard(); renderLedger(); renderReceipts();
}

function wireEvents() {
  $("#login-phone").addEventListener("input", (event) => {
    event.target.value = normalizePhoneInput(event.target.value);
  });
  $("#login-code").addEventListener("input", (event) => {
    event.target.value = event.target.value.replace(/\D/g, "").slice(0, 6);
  });
  $("#send-code-button").addEventListener("click", sendLoginCode);
  $("#login-form").addEventListener("submit", submitLogin);
  $("#logout-button").addEventListener("click", logoutCurrentDevice);
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $$('[data-view-target]').forEach((button) => button.addEventListener("click", () => showView(button.dataset.viewTarget)));
  $("#mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  $("#refresh-button").addEventListener("click", () => loadState().then(() => notify("数据已刷新")));
  $("#import-ledger-select").addEventListener("change", (event) => selectLedger(event.target.value, true));
  $("#dashboard-ledger-filter").addEventListener("change", (event) => {
    appState.dashboardLedgerId = event.target.value;
    renderDashboard();
  });
  $("#new-ledger-button").addEventListener("click", openLedgerModal);
  $("#manage-ledgers-button").addEventListener("click", openLedgerManager);
  $("#import-create-ledger").addEventListener("click", openLedgerModal);
  $("#ledger-form").addEventListener("submit", createLedgerFromModal);
  $("#close-ledger-modal").addEventListener("click", closeLedgerModal);
  $("#ledger-modal").addEventListener("click", (event) => { if (event.target.matches("[data-close-ledger-modal]")) closeLedgerModal(); });
  $("#user-avatar").addEventListener("click", openProfileModal);
  $("#profile-form").addEventListener("submit", saveProfile);
  $("#close-profile-modal").addEventListener("click", closeProfileModal);
  $("#profile-modal").addEventListener("click", (event) => { if (event.target.matches("[data-close-profile-modal]")) closeProfileModal(); });
  $("#close-ledger-manager").addEventListener("click", closeLedgerManager);
  $("#ledger-manager-modal").addEventListener("click", (event) => { if (event.target.matches("[data-close-ledger-manager]")) closeLedgerManager(); });
  $("#ledger-manager-list").addEventListener("click", (event) => {
    const rename = event.target.closest("[data-rename-ledger]");
    const remove = event.target.closest("[data-delete-ledger]");
    if (rename) renameLedger(rename.dataset.renameLedger);
    if (remove) removeLedger(remove.dataset.deleteLedger);
  });
  $("#chat-form").addEventListener("submit", handleChat);
  $$(".quick-prompts button").forEach((button) => button.addEventListener("click", () => { $("#chat-input").value = button.dataset.prompt; $("#chat-input").focus(); }));
  $("#ledger-search").addEventListener("input", (event) => { appState.query = event.target.value; renderLedger(); });
  $("#ledger-filter-button").addEventListener("click", () => {
    const menu = $("#ledger-filter-menu");
    menu.classList.toggle("hidden");
    $("#ledger-filter-button").setAttribute("aria-expanded", String(!menu.classList.contains("hidden")));
  });
  $("#ledger-filter-menu").addEventListener("change", updateLedgerFilter);
  document.addEventListener("click", (event) => {
    if (event.target.closest("#ledger-filter")) return;
    $("#ledger-filter-menu").classList.add("hidden");
    $("#ledger-filter-button").setAttribute("aria-expanded", "false");
  });
  $$(".filter-tab").forEach((button) => button.addEventListener("click", () => { appState.filter = button.dataset.filter; $$(".filter-tab").forEach((tab) => tab.classList.toggle("active", tab === button)); renderLedger(); }));
  $("#new-ledger-entry").addEventListener("click", () => { showView("chat"); $("#chat-input").focus(); });
  createVoiceInputController({
    input: $("#chat-input"),
    button: $("#voice-button"),
    notify,
  });
  $("#bill-file").addEventListener("change", (event) => processBillFile(event.target.files?.[0]));
  $("#import-select-all").addEventListener("change", (event) => {
    $$("#import-table-body input[data-import-index]:not(:disabled)").forEach((input) => { input.checked = event.target.checked; });
    renderImportSelectionSummary();
  });
  $("#import-table-body").addEventListener("change", (event) => {
    if (event.target.matches("input[data-import-index]")) {
      const selectable = $$("#import-table-body input[data-import-index]:not(:disabled)");
      $("#import-select-all").checked = selectable.length > 0 && selectable.every((input) => input.checked);
    }
    if (!event.target.matches("input[data-import-index], select[data-conflict-index]")) return;
    renderImportSelectionSummary();
  });
  $("#commit-import").addEventListener("click", commitBillImport);
  $("#ledger-table-body").addEventListener("click", (event) => {
    const edit = event.target.closest("[data-edit-id]");
    const remove = event.target.closest("[data-delete-id]");
    const receipt = event.target.closest("[data-view-receipt-id]");
    const detail = event.target.closest("[data-detail-id]");
    if (edit) editTransaction(edit.dataset.editId);
    if (remove) deleteTransaction(remove.dataset.deleteId);
    if (receipt) viewTransactionReceipt(receipt.dataset.viewReceiptId);
    if (detail) openTransactionDetails(detail.dataset.detailId);
  });
  $("#receipt-file").addEventListener("change", handleReceipt);
  const dropzone = $("#receipt-dropzone");
  ["dragenter", "dragover"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => { event.preventDefault(); dropzone.classList.add("drop-active"); }));
  ["dragleave", "drop"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => { event.preventDefault(); dropzone.classList.remove("drop-active"); }));
  dropzone.addEventListener("drop", (event) => processReceiptFile(event.dataTransfer.files?.[0]));
  $("#receipt-list").addEventListener("click", (event) => { const apply = event.target.closest("[data-receipt-id]"); const edit = event.target.closest("[data-edit-receipt-id]"); const view = event.target.closest("[data-view-receipt-id]"); if (apply) applyReceipt(apply.dataset.receiptId); if (edit) editReceipt(edit.dataset.editReceiptId); if (view) viewTransactionReceipt(view.dataset.viewReceiptId); });
  $("#close-transaction-modal").addEventListener("click", closeTransactionDetails);
  $("#transaction-modal").addEventListener("click", (event) => { if (event.target.matches("[data-close-modal]")) closeTransactionDetails(); });
  $("#transaction-edit-form").addEventListener("submit", saveTransactionEdits);
  $("#transaction-edit-type").addEventListener("change", () => updateTransactionCategoryInputs());
  $("#transaction-edit-category").addEventListener("change", (event) => updateTransactionCategoryInputs(event.target.value));
  $("#close-transaction-edit-modal").addEventListener("click", closeTransactionEditor);
  $("#transaction-edit-modal").addEventListener("click", (event) => { if (event.target.matches("[data-close-transaction-edit]")) closeTransactionEditor(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeTransactionDetails(); closeTransactionEditor(); closeLedgerModal(); closeProfileModal(); closeLedgerManager(); } });
}

async function init() {
  wireEvents();
  addMessage("你好，我是你的 AI 财务助手。说一句消费或收入，我会先生成可确认的账单。", "ai");
  await bootstrapAuth();
}

window.addEventListener("DOMContentLoaded", init);
