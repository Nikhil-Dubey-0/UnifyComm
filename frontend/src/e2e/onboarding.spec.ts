import { expect, type Page, test } from "@playwright/test";

/**
 * User-reported bugs (Session 5): a customer registered with a phone and an email gets ONE
 * conversation across WhatsApp, email and SMS, the newest conversation is on top of the
 * inbox, and a new sender stays listed in the simulator.
 */

const PASSWORD = process.env.SEED_AGENT_PASSWORD ?? "demo1234";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("agent@unifycomm.local");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/inbox");
}

function unique() {
  const digits = String(Date.now()).slice(-8);
  return { phone: `+91 7${digits}1`, tag: Date.now().toString(36) };
}

test("a registered customer's WhatsApp, email and SMS land in one conversation", async ({ browser }) => {
  const context = await browser.newContext();
  const agent = await context.newPage();
  const sim = await context.newPage();
  const { phone, tag } = unique();
  const name = `Ryan ${tag}`;
  const email = `ryan.${tag}@example.com`;

  await login(agent);
  await agent.goto("/customers");
  await agent.getByRole("button", { name: "New customer" }).click();
  const dialog = agent.getByRole("dialog");
  await dialog.getByLabel("Full name").fill(name);
  await dialog.getByLabel("Mobile number").fill(phone);
  await dialog.getByLabel("Email", { exact: true }).fill(email);
  await dialog.getByRole("button", { name: "Register" }).click();
  await agent.waitForURL(/\/customers\/\d+$/);
  await expect(agent.getByRole("heading", { name })).toBeVisible();

  await login(sim);
  await sim.goto("/simulator");
  const persona = sim.getByRole("button", { name: new RegExp(name) });
  for (const [channel, text] of [
    ["WhatsApp", `Card blocked (${tag})`],
    ["Email", `Any update? (${tag})`],
    ["SMS", `Please call me (${tag})`],
  ] as const) {
    await persona.click();
    await sim.getByRole("radio", { name: channel }).click();
    await sim.getByLabel("Customer message").fill(text);
    await sim.getByRole("button", { name: "Send as customer" }).click();
    await expect(sim.getByTestId("sim-thread")).toContainText(text);
  }

  // Newest first: the conversation is the top row without searching.
  await agent.goto("/inbox");
  await agent.getByRole("radio", { name: "Newest" }).click();
  const top = agent.getByTestId("conversation-list").getByRole("link").first();
  await expect(top).toContainText(name);
  await top.click();
  const thread = agent.getByTestId("thread");
  for (const text of [`Card blocked (${tag})`, `Any update? (${tag})`, `Please call me (${tag})`]) {
    await expect(thread).toContainText(text);
  }
  await expect(thread.getByTestId("provider").first()).toHaveText("simulated");
  await context.close();
});

test("a new sender stays listed in the simulator", async ({ page }) => {
  const { phone, tag } = unique();
  await login(page);
  await page.goto("/simulator");
  await page.getByRole("button", { name: /New sender/ }).click();
  await page.getByLabel("Phone number").fill(phone);
  await page.getByLabel("Display name (optional)").fill(`Walk-in ${tag}`);
  await page.getByLabel("Customer message").fill(`Hello (${tag})`);
  await page.getByRole("button", { name: "Send as customer" }).click();
  await expect(page.getByTestId("sim-thread")).toContainText(`Hello (${tag})`);
  await expect(page.getByTestId("recent-senders")).toContainText(`Walk-in ${tag}`);
});
