import {
  normalizePhoneInput,
  safePostLoginPath,
  validCode,
  validPhone,
  viewFromLocation,
} from "/auth-utils.js?v=20260729-upload-1";
import { createVoiceInputController } from "/input-utils.js?v=20260729-upload-1";

const appState = {
  data: null,
  filter: "all",
  importPreview: null,
  query: "",
  pendingParse: null,
  selectedLedgerId: null,
  user: null,
  turnstileSiteKey: "",
  turnstileToken: "",
};
const palette = ["#6d5ef7", "#26c6dd", "#2bc985", "#f2ae3f", "#ff6877"];
let accessToken = null;
let refreshPromise = null;
let resendTimer = null;
let turnstileWidgetId = null;
const receiptObjectUrls = new Map();

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function currency(value) {
  return `¥${Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
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

function exactCurrency(value) {
  return `¥${Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
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
  $("#auth-loading").classList.add("hidden");
  $("#login-screen").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  $("#current-user-phone").textContent = user.masked_phone || "已安全登录";
  $("#user-avatar").textContent = (user.phone || "F").slice(-1);
  await loadState();
  showView(viewFromLocation(window.location), false);
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
  const titles = { dashboard: "下午好，理财官", chat: "AI 财务助手", ledger: "智能账本", receipts: "图片凭证" };
  $("#page-title").textContent = titles[targetView] || titles.dashboard;
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
  const selector = $("#ledger-name-button");
  const importSelector = $("#import-ledger-select");
  const ledgers = appState.data?.ledgers || [];
  if (!ledgers.length) {
    selector.innerHTML = "<option value=\"\">暂无账本</option>";
    selector.disabled = true;
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
  selector.disabled = false;
  importSelector.disabled = false;
  const options = ledgers.map((ledger) => `<option value="${escapeHtml(ledger.id)}">${escapeHtml(ledger.name)}</option>`).join("");
  selector.innerHTML = options;
  importSelector.innerHTML = options;
  selector.value = appState.selectedLedgerId;
  importSelector.value = appState.selectedLedgerId;
  $("#commit-import").disabled = !appState.importPreview;
}

function renderChatDashboard() {
  const dashboard = appState.data?.dashboard;
  if (!dashboard) return;
  $("#chat-dashboard-summary").innerHTML = `<p class="eyebrow">实时财务摘要</p><div class="mini-metrics"><div><span>消费</span><strong>${currency(dashboard.spend)}</strong></div><div><span>收入</span><strong>${currency(dashboard.income)}</strong></div><div><span>净现金流</span><strong>${currency(dashboard.net)}</strong></div></div><p class="mini-insight">${escapeHtml(dashboard.insight)}</p><button class="text-button" data-view-target="dashboard">打开完整 Dashboard →</button>`;
  $("#chat-dashboard-summary [data-view-target]").addEventListener("click", () => showView("dashboard"));
}

function renderDashboard() {
  const dashboard = appState.data.dashboard;
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

  $("#recent-list").innerHTML = (dashboard.recent || []).slice(0, 5).map((tx) => `<div class="recent-row"><span class="transaction-icon ${tx.type}">${tx.type === "income" ? "↗" : "↘"}</span><div class="recent-main"><strong>${escapeHtml(tx.note)}</strong><small>${escapeHtml(tx.category)} · ${dateLabel(tx.date)}</small></div><div class="recent-amount"><strong class="${tx.type}">${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong><small>${sourceLabel(tx.source)}</small></div></div>`).join("") || `<div class="empty-state">还没有交易。</div>`;
}

function renderLedger() {
  const rows = (appState.data.transactions || []).filter((tx) => {
    const matchesLedger = !appState.selectedLedgerId || tx.ledgerId === appState.selectedLedgerId;
    const matchesFilter = appState.filter === "all" || tx.type === appState.filter;
    const haystack = `${tx.note} ${tx.category} ${tx.date}`.toLowerCase();
    return matchesLedger && matchesFilter && haystack.includes(appState.query.toLowerCase());
  }).sort((a, b) => b.date.localeCompare(a.date));
  $("#ledger-empty").classList.toggle("hidden", rows.length > 0);
  $("#ledger-table-body").innerHTML = rows.map((tx) => { const receipt = tx.receiptId && appState.data.receipts.find((item) => item.id === tx.receiptId); const receiptAction = receipt ? `<button class="row-action" data-view-receipt-id="${escapeHtml(tx.receiptId)}">凭证</button>` : ""; return `<tr><td><div class="table-transaction"><span class="transaction-icon ${tx.type}">${tx.type === "income" ? "↗" : "↘"}</span><div><strong>${escapeHtml(tx.note)}</strong><small>${escapeHtml((appState.data.ledgers.find((ledger) => ledger.id === tx.ledgerId) || {}).name || "个人账本")}</small></div></div></td><td><span class="category-tag">${escapeHtml(tx.category)}</span></td><td>${dateLabel(tx.date)}</td><td>${sourceLabel(tx.source)}</td><td class="align-right ${tx.type === "income" ? "amount-income" : "amount-expense"}">${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</td><td class="align-right"><div class="row-actions"><button class="row-action" data-detail-id="${escapeHtml(tx.id)}">详情</button>${receiptAction}<button class="row-action" data-edit-id="${escapeHtml(tx.id)}">编辑</button><button class="row-action danger" data-delete-id="${escapeHtml(tx.id)}">删除</button></div></td></tr>`; }).join("");
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
  $("#transaction-detail-content").innerHTML = `<p class="eyebrow">交易详情</p><h3 id="transaction-detail-title">${escapeHtml(tx.note)}</h3><div class="detail-grid"><span>金额</span><strong class="${tx.type === "income" ? "amount-income" : "amount-expense"}">${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong><span>类型</span><strong>${tx.type === "income" ? "收入" : "支出"}</strong><span>分类</span><strong>${escapeHtml(tx.category)}</strong><span>日期</span><strong>${escapeHtml(tx.date)}</strong><span>账本</span><strong>${escapeHtml(ledger?.name || "个人账本")}</strong><span>来源</span><strong>${sourceLabel(tx.source)}</strong></div>${receipt?.fileUrl ? `<div class="detail-receipt"><img data-protected-receipt="${escapeHtml(receipt.id)}" alt="${escapeHtml(receipt.filename)}" /><button class="text-button" data-modal-receipt-id="${escapeHtml(receipt.id)}">查看原始凭证 →</button></div>` : `<p class="muted-label detail-empty">暂无关联原始凭证</p>`}`;
  $("#transaction-modal").classList.remove("hidden");
  hydrateProtectedReceiptImages($("#transaction-detail-content"));
  const receiptButton = $("#transaction-detail-content [data-modal-receipt-id]");
  if (receiptButton) receiptButton.addEventListener("click", () => viewTransactionReceipt(receiptButton.dataset.modalReceiptId));
}

function closeTransactionDetails() {
  $("#transaction-modal").classList.add("hidden");
}

async function editTransaction(transactionId) {
  const tx = appState.data.transactions.find((item) => item.id === transactionId);
  if (!tx) return;
  const note = window.prompt("交易备注", tx.note);
  if (note === null) return;
  const amount = window.prompt("金额（元）", String(tx.amount));
  if (amount === null) return;
  const parsedAmount = Number(amount);
  if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) { notify("请输入有效金额"); return; }
  try {
    await api(`/api/transactions/${encodeURIComponent(transactionId)}`, { method: "PATCH", body: JSON.stringify({ note, amount: parsedAmount }) });
    await loadState();
    notify("交易已更新");
  } catch (error) { notify(`更新失败：${error.message}`); }
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
  preview.innerHTML = `<p class="eyebrow">结构化预览</p><h3>${escapeHtml(parsed.ledger?.name || selectedLedger()?.name || "当前账本")}</h3>${parsed.transactions.map((tx) => `<div class="preview-line"><span>${escapeHtml(tx.note)}</span><strong>${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong></div><div class="preview-line"><span>分类</span><strong>${escapeHtml(tx.category)}</strong></div>`).join("")}<div class="preview-actions"><button class="cancel-button" id="cancel-preview">取消</button><button class="confirm-button" id="confirm-preview">确认写入</button></div>`;
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

function renderImportSelectionSummary() {
  const selected = $$("#import-table-body input[data-import-index]:checked").length;
  $("#import-selection-summary").textContent = `已选择 ${selected} 笔交易`;
  $("#commit-import").disabled = selected === 0 || !appState.selectedLedgerId;
}

function renderImportPreview(preview) {
  appState.importPreview = preview;
  $("#import-preview").classList.remove("hidden");
  $("#import-preview-title").textContent = preview.fileName;
  $("#import-provider-badge").textContent = preview.providerLabel;
  $("#import-count").textContent = preview.importableCount;
  $("#import-duplicate-count").textContent = preview.duplicateCount;
  $("#import-skipped-count").textContent = preview.skippedCount;
  $("#import-table-body").innerHTML = preview.transactions.map((tx, index) => `
    <label class="import-confirm-row ${tx.duplicate ? "is-duplicate" : ""}">
      <input type="checkbox" data-import-index="${index}" ${tx.duplicate ? "disabled" : "checked"} aria-label="选择 ${escapeHtml(tx.note)}" />
      <span class="import-confirm-main">
        <strong>${escapeHtml(tx.note)}</strong>
        <small>${escapeHtml(tx.category)} · ${escapeHtml(tx.date)}${tx.duplicate ? " · 已存在" : ""}</small>
      </span>
      <strong class="${tx.type === "income" ? "amount-income" : "amount-expense"}">${tx.type === "income" ? "+" : "−"}${exactCurrency(tx.amount)}</strong>
    </label>
  `).join("");
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
    status.textContent = `已识别 ${preview.totalRows} 笔原始记录，请在右侧选择账本并确认。`;
    addMessage(`已识别 ${preview.importableCount} 笔可导入记录，请在右侧选择账本并确认。`);
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
  if (!selectedTransactions.length) {
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
        transactions: selectedTransactions,
      }),
    });
    appState.data = result.state;
    appState.importPreview = null;
    $("#import-preview").classList.add("hidden");
    $("#bill-file").value = "";
    $("#bill-upload-status").textContent = `已成功导入 ${result.importedCount} 笔，重复跳过 ${result.skippedCount} 笔。`;
    renderLedgerSelector();
    renderDashboard();
    renderChatDashboard();
    renderLedger();
    renderReceipts();
    addMessage(`已导入 ${result.importedCount} 笔到 ${selectedLedger()?.name || "当前账本"}。`);
    notify(`已导入 ${result.importedCount} 笔到 ${selectedLedger()?.name || "当前账本"}`);
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
  $("#ledger-name-button").addEventListener("change", (event) => selectLedger(event.target.value, true));
  $("#import-ledger-select").addEventListener("change", (event) => selectLedger(event.target.value, true));
  $("#create-ledger-button").addEventListener("click", openLedgerModal);
  $("#new-ledger-button").addEventListener("click", openLedgerModal);
  $("#import-create-ledger").addEventListener("click", openLedgerModal);
  $("#ledger-form").addEventListener("submit", createLedgerFromModal);
  $("#close-ledger-modal").addEventListener("click", closeLedgerModal);
  $("#ledger-modal").addEventListener("click", (event) => { if (event.target.matches("[data-close-ledger-modal]")) closeLedgerModal(); });
  $("#chat-form").addEventListener("submit", handleChat);
  $$(".quick-prompts button").forEach((button) => button.addEventListener("click", () => { $("#chat-input").value = button.dataset.prompt; $("#chat-input").focus(); }));
  $("#ledger-search").addEventListener("input", (event) => { appState.query = event.target.value; renderLedger(); });
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
    if (!event.target.matches("input[data-import-index]")) return;
    const selectable = $$("#import-table-body input[data-import-index]:not(:disabled)");
    $("#import-select-all").checked = selectable.length > 0 && selectable.every((input) => input.checked);
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
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeTransactionDetails(); closeLedgerModal(); } });
}

async function init() {
  wireEvents();
  addMessage("你好，我是你的 AI 财务助手。说一句消费或收入，我会先生成可确认的账单。", "ai");
  await bootstrapAuth();
}

window.addEventListener("DOMContentLoaded", init);
