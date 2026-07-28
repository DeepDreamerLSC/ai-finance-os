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
