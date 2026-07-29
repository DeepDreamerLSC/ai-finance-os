import { expect, test } from "@playwright/test";


function phoneFor(testInfo, offset = 0) {
  const project = testInfo.project.name === "mobile" ? 5 : 4;
  const testNumber = Number.parseInt(testInfo.titlePath.join("").replace(/\D/g, "").slice(-2) || "10", 10);
  return `139${String(10000000 + project * 100000 + testNumber * 10 + offset).slice(-8)}`;
}

async function login(page, phone) {
  await page.locator("#login-phone").fill(phone);
  await page.locator("#send-code-button").click();
  await expect(page.locator("#send-code-button")).toContainText(/59s|60s/);
  await expect(page.locator("#login-code")).toHaveValue("123456");
  await page.locator("#login-submit").click();
  await expect(page.locator("#app-shell")).toBeVisible();
  await expect(page.locator("#login-screen")).toBeHidden();
}

test("1 手机号登录后刷新和重新打开页面仍保持会话", async ({ page, context }, testInfo) => {
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  await login(page, phoneFor(testInfo));
  await expect(page.locator("#dashboard-view")).toBeVisible();

  await page.reload();
  await expect(page.locator("#app-shell")).toBeVisible();
  await expect(page.locator("#dashboard-view")).toBeVisible();

  await page.close();
  const reopened = await context.newPage();
  await reopened.goto("/");
  await expect(reopened.locator("#app-shell")).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("2 登录后恢复原财务视图", async ({ page }, testInfo) => {
  await page.goto("/#ledger");
  await login(page, phoneFor(testInfo));
  await expect(page.locator("#ledger-view")).toBeVisible();
  await expect(page).toHaveURL(/#ledger$/);
});

test("3 无效长期会话返回登录页", async ({ page, context }, testInfo) => {
  await page.goto("/");
  await login(page, phoneFor(testInfo));
  await context.addCookies([
    {
      name: "finance_refresh",
      value: "expired-session",
      domain: "127.0.0.1",
      path: "/api/auth",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  await expect(page.locator("#app-shell")).toBeHidden();
});

test("4 不同用户的账本内容互不可见", async ({ browser }, testInfo) => {
  const contextA = await browser.newContext();
  const pageA = await contextA.newPage();
  await pageA.goto("/#chat");
  await login(pageA, phoneFor(testInfo, 1));
  const privateNote = `隔离咖啡${Date.now()}`;
  await pageA.locator("#chat-input").fill(`${privateNote}，77元`);
  await pageA.locator("#chat-form").getByRole("button", { name: "发送" }).click();
  await expect(pageA.locator("#parse-preview")).toBeVisible();
  await pageA.locator("#confirm-preview").click();
  await expect(pageA.locator("#toast")).toContainText("记录已写入账本");
  await contextA.close();

  const contextB = await browser.newContext();
  const pageB = await contextB.newPage();
  await pageB.goto("/#ledger");
  await login(pageB, phoneFor(testInfo, 2));
  await expect(pageB.locator("#ledger-view")).toBeVisible();
  await expect(pageB.locator("#ledger-table-body")).not.toContainText(privateNote);
  await contextB.close();
});

test("5 AI 对话中可以选择账本、导入支付宝账单并自动去重", async ({ page }, testInfo) => {
  await page.goto("/#chat");
  await login(page, phoneFor(testInfo));
  await expect(page.locator("#chat-view")).toBeVisible();
  await expect(page.locator('[data-view="import"]')).toHaveCount(0);
  await expect(page.locator("#bill-file")).toHaveAttribute("accept", /\.xlsx,.csv/);

  const csv = [
    "支付宝交易明细",
    "交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注",
    "2026-07-28 19:41:15,餐饮美食,盒马,/,生鲜商品,支出,33.03,信用卡,交易成功,e2e-ali-order-1,e2e-merchant-1,",
    "2026-07-28 18:00:00,账户转存,余额宝,/,转入,不计收支,500.00,余额,交易成功,e2e-neutral-1,e2e-merchant-2,",
  ].join("\r\n");
  await page.locator("#bill-file").setInputFiles({
    name: "账单.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not a bill", "utf8"),
  });
  await expect(page.locator("#toast")).toContainText("仅支持 Excel");

  const previewRequest = page.waitForRequest(
    (request) => request.url().endsWith("/api/imports/preview") && request.method() === "POST",
  );
  await page.locator("#bill-file").setInputFiles({
    name: "支付宝交易明细.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv, "utf8"),
  });
  await previewRequest;
  await expect(page.locator("#import-preview")).toBeVisible();
  await expect(page.locator("#import-count")).toHaveText("1");
  await expect(page.locator("#import-skipped-count")).toHaveText("1");
  await page.locator("#import-create-ledger").click();
  await page.locator("#ledger-name-input").fill("支付宝导入测试");
  await page.locator("#ledger-form").getByRole("button", { name: "创建并切换" }).click();
  await expect(page.locator("#ledger-modal")).toBeHidden();
  await expect(page.locator("#import-ledger-select")).toHaveValue(/.+/);
  await expect(page.locator("#import-ledger-select")).toContainText("支付宝导入测试");
  await page.locator("#commit-import").click();
  await expect(page.locator("#bill-upload-status")).toContainText("已成功导入 1 笔");

  if (testInfo.project.name === "mobile") await page.locator("#mobile-menu").click();
  await page.locator('[data-view="ledger"]').click();
  await expect(page.locator("#ledger-table-body")).toContainText("盒马");
  await expect(page.locator("#ledger-table-body")).toContainText("−¥33.03");

  if (testInfo.project.name === "mobile") await page.locator("#mobile-menu").click();
  await page.locator('[data-view="chat"]').click();
  await page.locator("#bill-file").setInputFiles({
    name: "支付宝交易明细.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv, "utf8"),
  });
  await expect(page.locator("#import-duplicate-count")).toHaveText("1");
  await expect(page.locator("#commit-import")).toBeDisabled();
});

test("6 微信语音剪贴板结果会进入对话输入框", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.navigator, "userAgent", {
      configurable: true,
      value: "Mozilla/5.0 MicroMessenger/8.0.50",
    });
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { readText: async () => "刚刚停车112元" },
    });
  });
  await page.goto("/#chat");
  await login(page, phoneFor(testInfo));
  await page.locator("#voice-button").click();
  await expect(page.locator("#chat-input")).toHaveValue("刚刚停车112元");
});

test("7 用户名可修改，账本可重命名和删除", async ({ page }, testInfo) => {
  await page.goto("/#ledger");
  await login(page, phoneFor(testInfo));

  await page.locator("#user-avatar").click();
  await expect(page.locator("#profile-modal")).toBeVisible();
  await page.locator("#profile-name-input").fill("林同学");
  await page.locator("#profile-form").getByRole("button", { name: "保存用户名" }).click();
  await expect(page.locator("#profile-modal")).toBeHidden();
  await expect(page.locator("#page-title")).toHaveText("你好，林同学");

  await page.locator("#new-ledger-button").click();
  await page.locator("#ledger-name-input").fill("待整理账本");
  await page.locator("#ledger-form").getByRole("button", { name: "创建并切换" }).click();
  await page.locator("#manage-ledgers-button").click();
  const row = page.locator('#ledger-manager-list input[value="待整理账本"]').locator("..");
  await row.locator("input").fill("旅行账本");
  await row.getByRole("button", { name: "保存" }).click();
  await expect(page.locator("#ledger-name-button")).toContainText("旅行账本");

  page.once("dialog", (dialog) => dialog.accept());
  await page.locator('#ledger-manager-list input[value="旅行账本"]').locator("..").getByRole("button", { name: "删除" }).click();
  await expect(page.locator('#ledger-manager-list input[value="旅行账本"]')).toHaveCount(0);
});

test("8 账目完整明细和金额都可以编辑", async ({ page }, testInfo) => {
  await page.goto("/#ledger");
  await login(page, phoneFor(testInfo));

  await page.locator("#new-ledger-button").click();
  await page.locator("#ledger-name-input").fill("报销账本");
  await page.locator("#ledger-form").getByRole("button", { name: "创建并切换" }).click();
  await page.locator("#new-ledger-entry").click();
  await page.locator("#chat-input").fill("临时停车112元");
  await page.locator("#chat-form").getByRole("button", { name: "发送" }).click();
  await expect(page.locator("#parse-preview")).toBeVisible();
  await page.locator("#confirm-preview").click();
  await expect(page.locator("#toast")).toContainText("记录已写入账本");
  if (testInfo.project.name === "mobile") await page.locator("#mobile-menu").click();
  await page.locator('[data-view="ledger"]').click();

  const parkingRow = page.locator("#ledger-table-body tr").filter({ hasText: "临时停车" });
  await expect(parkingRow).toHaveCount(1);
  await parkingRow.getByRole("button", { name: "编辑" }).click();
  await expect(page.locator("#transaction-edit-modal")).toBeVisible();
  await page.locator("#transaction-edit-note").fill("停车报销");
  await page.locator("#transaction-edit-amount").fill("112.36");
  await page.locator("#transaction-edit-type").selectOption("income");
  await page.locator("#transaction-edit-category").fill("差旅报销");
  await page.locator("#transaction-edit-date").fill("2026-07-09");
  await page.locator("#transaction-edit-ledger").selectOption({ label: "报销账本" });
  await page.locator("#transaction-edit-form").getByRole("button", { name: "保存全部修改" }).click();
  await expect(page.locator("#transaction-edit-modal")).toBeHidden();

  await page.locator("#ledger-name-button").selectOption({ label: "报销账本" });
  await expect(page.locator("#ledger-table-body")).toContainText("停车报销");
  await expect(page.locator("#ledger-table-body")).toContainText("差旅报销");
  await expect(page.locator("#ledger-table-body")).toContainText("+¥112.36");
  await expect(page.locator("#ledger-table-body")).toContainText("7月9日");
});
