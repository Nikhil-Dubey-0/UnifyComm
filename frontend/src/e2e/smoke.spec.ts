import { expect, type Page, test } from "@playwright/test";

/**
 * Session 2 smoke (ARCHITECTURE §16): login → simulator message → appears in the inbox
 * without a reload → agent reply → appears in the simulator.
 * Needs the api, the worker (fake or real AI) and the web app, with seed data loaded.
 */

const API = process.env.API_URL ?? "http://localhost:8000";
const PASSWORD = process.env.SEED_AGENT_PASSWORD ?? "demo1234";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("agent@unifycomm.local");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/inbox");
}

function uniqueIndianMobile(): string {
  const digits = String(Date.now()).slice(-8) + String(Math.floor(Math.random() * 10));
  return `+91 9${digits}`;
}

test.beforeAll(async ({ request }) => {
  const health = await (await request.get(`${API}/api/health`)).json();
  expect(health.db, "database reachable").toBe("ok");
  const age = Date.now() - new Date(health.worker_heartbeat_at ?? 0).getTime();
  expect(age, "worker heartbeat is fresh: start `uv run python -m app.worker`").toBeLessThan(30_000);
});

test("simulator message reaches the live inbox and the reply reaches the customer", async ({
  browser,
}) => {
  const context = await browser.newContext();
  const agent = await context.newPage();
  const customer = await context.newPage();

  const name = `Smoke ${Date.now()}`;
  const phone = uniqueIndianMobile();
  const question = `Hi, I was charged twice for my order (${name})`;
  const reply = `Sorry about that, we are checking the double charge (${name}).`;

  await login(agent);
  await expect(agent.getByTestId("live-status")).toHaveAttribute("data-state", "open");
  await expect(agent.getByRole("heading", { name: "Inbox" })).toBeVisible();
  // Filter to this sender: the list still updates live, and the test does not depend on
  // how many other conversations wait ahead of a brand-new one.
  await agent.getByLabel("Search conversations").fill(name);

  // The customer writes from the simulator as a new sender.
  await login(customer);
  await customer.goto("/simulator");
  await customer.getByRole("button", { name: /New sender/ }).click();
  await customer.getByLabel("Phone number").fill(phone);
  await customer.getByLabel("Display name (optional)").fill(name);
  await customer.getByLabel("Customer message").fill(question);
  await customer.getByRole("button", { name: "Send as customer" }).click();
  await expect(customer.getByTestId("sim-thread")).toContainText(question);

  // The agent's inbox updates over the WebSocket, without a reload.
  const row = agent.getByTestId("conversation-list").getByRole("link", { name: new RegExp(name) });
  await expect(row).toBeVisible();
  await row.click();
  const thread = agent.getByTestId("thread");
  await expect(thread).toContainText(question);
  // The worker analysed it: the AI chips replace "Analysis pending".
  await expect(thread.getByTestId("ai-chips")).toContainText("Payments & Billing");

  await agent.getByLabel("Reply").fill(reply);
  await agent.getByRole("button", { name: "Send", exact: true }).click();
  const sent = thread.getByTestId("message").filter({ hasText: reply });
  await expect(sent.getByTestId("delivery-status")).toHaveAttribute("data-status", "delivered");

  // The reply appears on the customer's side, again without a reload.
  await expect(customer.getByTestId("sim-thread")).toContainText(reply);

  await context.close();
});
