const appState = { data: null, filter: "all", query: "", pendingParse: null, selectedLedgerId: null };
const palette = ["#6d5ef7", "#26c6dd", "#2bc985", "#f2ae3f", "#ff6877"];

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
  return source === "receipt" ? "图片凭证" : source === "natural-language" ? "AI 对话" : "手动记录";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => toast.classList.remove("show"), 2800);
}

function showView(viewName) {
  $$(".view").forEach((view) => view.classList.toggle("active-view", view.id === `${viewName}-view`));
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === viewName));
  const titles = { dashboard: "下午好，理财官", chat: "AI 财务助手", ledger: "智能账本", receipts: "图片凭证" };
  $("#page-title").textContent = titles[viewName] || titles.dashboard;
  $(".sidebar").classList.remove("open");
}

function renderLedgerSelector() {
  const selector = $("#ledger-name-button");
  const ledgers = appState.data?.ledgers || [];
  if (!ledgers.length) {
    selector.innerHTML = "<option value=\"\">暂无账本</option>";
    selector.disabled = true;
    return;
  }
  if (!ledgers.some((ledger) => ledger.id === appState.selectedLedgerId)) appState.selectedLedgerId = ledgers[0].id;
  selector.disabled = false;
  selector.innerHTML = ledgers.map((ledger) => `<option value="${escapeHtml(ledger.id)}">${escapeHtml(ledger.name)}</option>`).join("");
  selector.value = appState.selectedLedgerId;
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

function viewTransactionReceipt(receiptId) {
  const receipt = appState.data.receipts.find((item) => item.id === receiptId);
  if (!receipt?.url) { notify("这笔交易暂未保存原始图片"); return; }
  window.open(receipt.url, "_blank", "noopener");
}

function openTransactionDetails(transactionId) {
  const tx = appState.data.transactions.find((item) => item.id === transactionId);
  if (!tx) return;
  const receipt = tx.receiptId && appState.data.receipts.find((item) => item.id === tx.receiptId);
  const ledger = appState.data.ledgers.find((item) => item.id === tx.ledgerId);
  $("#transaction-detail-content").innerHTML = `<p class="eyebrow">交易详情</p><h3 id="transaction-detail-title">${escapeHtml(tx.note)}</h3><div class="detail-grid"><span>金额</span><strong class="${tx.type === "income" ? "amount-income" : "amount-expense"}">${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong><span>类型</span><strong>${tx.type === "income" ? "收入" : "支出"}</strong><span>分类</span><strong>${escapeHtml(tx.category)}</strong><span>日期</span><strong>${escapeHtml(tx.date)}</strong><span>账本</span><strong>${escapeHtml(ledger?.name || "个人账本")}</strong><span>来源</span><strong>${sourceLabel(tx.source)}</strong></div>${receipt?.url ? `<div class="detail-receipt"><img src="${escapeHtml(receipt.url)}" alt="${escapeHtml(receipt.filename)}" /><button class="text-button" data-modal-receipt-id="${escapeHtml(receipt.id)}">查看原始凭证 →</button></div>` : `<p class="muted-label detail-empty">暂无关联原始凭证</p>`}`;
  $("#transaction-modal").classList.remove("hidden");
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
  $("#receipt-list").innerHTML = receipts.length ? receipts.map((receipt) => `<div class="receipt-row"><div class="receipt-thumb">${receipt.url ? `<img src="${escapeHtml(receipt.url)}" alt="${escapeHtml(receipt.filename)}" />` : "▤"}</div><div><strong>${escapeHtml(receipt.merchant)}</strong><small>${currency(receipt.amount)} · ${escapeHtml(receipt.category)} · ${dateLabel(receipt.date)}</small></div><div class="receipt-actions">${receipt.url ? `<button class="view-receipt" data-receipt-url="${escapeHtml(receipt.url)}">查看照片</button>` : ""}<button class="edit-receipt" data-edit-receipt-id="${escapeHtml(receipt.id)}">编辑识别</button><button class="apply-receipt" data-receipt-id="${escapeHtml(receipt.id)}">记入账本</button></div></div>`).join("") : `<div class="empty-state">上传第一张凭证，开始建立你的财务档案。</div>`;
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
  preview.innerHTML = `<p class="eyebrow">结构化预览</p><h3>${escapeHtml(parsed.ledger?.name || "当前账本")}</h3>${parsed.transactions.map((tx) => `<div class="preview-line"><span>${escapeHtml(tx.note)}</span><strong>${tx.type === "income" ? "+" : "−"}${currency(tx.amount)}</strong></div><div class="preview-line"><span>分类</span><strong>${escapeHtml(tx.category)}</strong></div>`).join("")}<div class="preview-actions"><button class="cancel-button" id="cancel-preview">取消</button><button class="confirm-button" id="confirm-preview">确认写入</button></div>`;
  $("#confirm-preview").addEventListener("click", confirmParsedTransactions);
  $("#cancel-preview").addEventListener("click", () => preview.classList.add("hidden"));
}

async function confirmParsedTransactions() {
  if (!appState.pendingParse?.transactions?.length) return;
  try {
    const result = await api("/api/transactions/batch", { method: "POST", body: JSON.stringify({ ledgerName: appState.pendingParse.ledger?.name, transactions: appState.pendingParse.transactions }) });
    const ledgerName = appState.pendingParse.ledger?.name;
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
  try { await api("/api/receipts/apply", { method: "POST", body: JSON.stringify({ receiptId }) }); await loadState(); notify("凭证已关联到交易"); }
  catch (error) { notify(`关联失败：${error.message}`); }
}

async function loadState() {
  appState.data = await api("/api/state");
  renderLedgerSelector(); renderDashboard(); renderChatDashboard(); renderLedger(); renderReceipts();
}

function wireEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $$('[data-view-target]').forEach((button) => button.addEventListener("click", () => showView(button.dataset.viewTarget)));
  $("#mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  $("#refresh-button").addEventListener("click", () => loadState().then(() => notify("数据已刷新")));
  $("#ledger-name-button").addEventListener("change", (event) => { appState.selectedLedgerId = event.target.value; renderLedger(); notify(`已切换到 ${event.target.options[event.target.selectedIndex].text}`); });
  $("#chat-form").addEventListener("submit", handleChat);
  $$(".quick-prompts button").forEach((button) => button.addEventListener("click", () => { $("#chat-input").value = button.dataset.prompt; $("#chat-input").focus(); }));
  $("#ledger-search").addEventListener("input", (event) => { appState.query = event.target.value; renderLedger(); });
  $$(".filter-tab").forEach((button) => button.addEventListener("click", () => { appState.filter = button.dataset.filter; $$(".filter-tab").forEach((tab) => tab.classList.toggle("active", tab === button)); renderLedger(); }));
  $("#new-ledger-entry").addEventListener("click", () => { showView("chat"); $("#chat-input").focus(); });
  $("#voice-button").addEventListener("click", () => notify("语音入口已预留，接入真实 Provider 后即可直接说话。"));
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
  $("#receipt-list").addEventListener("click", (event) => { const apply = event.target.closest("[data-receipt-id]"); const edit = event.target.closest("[data-edit-receipt-id]"); const view = event.target.closest("[data-receipt-url]"); if (apply) applyReceipt(apply.dataset.receiptId); if (edit) editReceipt(edit.dataset.editReceiptId); if (view) window.open(view.dataset.receiptUrl, "_blank", "noopener"); });
  $("#close-transaction-modal").addEventListener("click", closeTransactionDetails);
  $("#transaction-modal").addEventListener("click", (event) => { if (event.target.matches("[data-close-modal]")) closeTransactionDetails(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeTransactionDetails(); });
}

async function init() {
  wireEvents();
  addMessage("你好，我是你的 AI 财务助手。说一句消费或收入，我会先生成可确认的账单。", "ai");
  try { await loadState(); } catch (error) { addMessage(`数据加载失败：${error.message}`); notify("无法连接到本地服务"); }
}

window.addEventListener("DOMContentLoaded", init);
