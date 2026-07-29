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

test("5 可以创建账本并导入支付宝账单且自动去重", async ({ page }, testInfo) => {
  await page.goto("/#import");
  await login(page, phoneFor(testInfo));
  await expect(page.locator("#import-view")).toBeVisible();

  await page.locator("#import-create-ledger").click();
  await page.locator("#ledger-name-input").fill("支付宝导入测试");
  await page.locator("#ledger-form").getByRole("button", { name: "创建并切换" }).click();
  await expect(page.locator("#ledger-modal")).toBeHidden();
  await expect(page.locator("#import-ledger-select")).toHaveValue(/.+/);
  await expect(page.locator("#import-ledger-select")).toContainText("支付宝导入测试");

  const csv = [
    "支付宝交易明细",
    "交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注",
    "2026-07-28 19:41:15,餐饮美食,盒马,/,生鲜商品,支出,33.03,信用卡,交易成功,e2e-ali-order-1,e2e-merchant-1,",
    "2026-07-28 18:00:00,账户转存,余额宝,/,转入,不计收支,500.00,余额,交易成功,e2e-neutral-1,e2e-merchant-2,",
  ].join("\r\n");
  await page.locator("#bill-file").setInputFiles({
    name: "支付宝交易明细.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv, "utf8"),
  });
  await expect(page.locator("#import-preview")).toBeVisible();
  await expect(page.locator("#import-count")).toHaveText("1");
  await expect(page.locator("#import-skipped-count")).toHaveText("1");
  await page.locator("#commit-import").click();
  await expect(page.locator("#bill-upload-status")).toContainText("已成功导入 1 笔");

  if (testInfo.project.name === "mobile") await page.locator("#mobile-menu").click();
  await page.locator('[data-view="ledger"]').click();
  await expect(page.locator("#ledger-table-body")).toContainText("盒马");

  if (testInfo.project.name === "mobile") await page.locator("#mobile-menu").click();
  await page.locator('[data-view="import"]').click();
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
