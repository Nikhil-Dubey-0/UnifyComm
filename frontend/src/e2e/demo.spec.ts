import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

/**
 * ARCHITECTURE §17 demo script on the simulator (Session 4 exit criterion).
 *
 * - With the LLM configured: steps 1–5 (summary and draft use the real OpenAI API).
 * - With the LLM off (API started with OPENAI_API_KEY empty or LLM_ENABLED=false): step 7.
 * - Step 6 (stop and restart the worker) needs process control; see the run-demo skill.
 *
 * Re-runnable: beforeAll resolves the seeded customers' active conversations and restores
 * the §17 preferences through the API, so no database reset is needed between runs.
 * Set DEMO_SCREENSHOTS=<dir> to save a screenshot after each step.
 */

const API = process.env.API_URL ?? "http://localhost:8000";
const PASSWORD = process.env.SEED_AGENT_PASSWORD ?? "demo1234";
const SHOTS = process.env.DEMO_SCREENSHOTS;
const AI_TIMEOUT = 45_000;

const SEEDED = ["Rahul Sharma", "Priya Verma", "Amit Rao"];

/** A unique marker without long digit runs: Date.now() has 13 digits, and one that passes
 * the Luhn check is (correctly) blocked by content.sensitive_data as a card number. */
function marker(): string {
  return `demo-${Date.now().toString(36)}`;
}
const PREFERENCES: Record<string, { channel: string; consent: string; dnd: boolean }[]> = {
  "Rahul Sharma": [
    { channel: "whatsapp", consent: "opted_in", dnd: false },
    { channel: "sms", consent: "opted_in", dnd: false },
    { channel: "email", consent: "opted_in", dnd: false },
  ],
  "Priya Verma": [
    { channel: "whatsapp", consent: "opted_out", dnd: false },
    { channel: "sms", consent: "opted_in", dnd: false },
  ],
  "Amit Rao": [{ channel: "sms", consent: "opted_in", dnd: true }],
};

type Health = { db: string; worker_heartbeat_at: string | null; llm_configured: boolean };
let health: Health;

async function apiToken(request: APIRequestContext): Promise<string> {
  const r = await request.post(`${API}/api/auth/login`, {
    data: { email: "agent@unifycomm.local", password: PASSWORD },
  });
  expect(r.ok(), "agent login").toBeTruthy();
  return (await r.json()).access_token;
}

/** Resolve active conversations of the seeded customers and restore §17 preferences. */
async function resetDemoState(request: APIRequestContext) {
  const headers = { Authorization: `Bearer ${await apiToken(request)}` };
  for (const name of SEEDED) {
    for (const status of ["open", "pending"]) {
      const list = await request.get(`${API}/api/conversations`, {
        headers,
        params: { status, q: name, limit: 100 },
      });
      for (const c of (await list.json()).items) {
        if (c.customer.display_name !== name) continue;
        const r = await request.patch(`${API}/api/conversations/${c.id}`, {
          headers,
          data: { status: "resolved" },
        });
        expect(r.ok(), `resolve conversation ${c.id}`).toBeTruthy();
      }
    }
    const customers = await request.get(`${API}/api/customers`, { headers, params: { q: name } });
    const customer = (await customers.json()).items.find(
      (c: { display_name: string; verified: boolean }) => c.display_name === name && c.verified,
    );
    expect(customer, `seeded customer ${name}`).toBeTruthy();
    for (const pref of PREFERENCES[name]) {
      const r = await request.put(`${API}/api/customers/${customer.id}/preferences`, {
        headers,
        data: pref,
      });
      expect(r.ok(), `restore ${name} ${pref.channel}`).toBeTruthy();
    }
  }
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("agent@unifycomm.local");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/inbox");
}

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

/** Write as a seeded customer in the simulator. */
async function customerSays(sim: Page, persona: string, channel: string, text: string) {
  await sim.getByRole("button", { name: new RegExp(persona) }).click();
  await sim.getByRole("radio", { name: channel }).click();
  await sim.getByLabel("Customer message").fill(text);
  await sim.getByRole("button", { name: "Send as customer" }).click();
  await expect(sim.getByTestId("sim-thread")).toContainText(text);
}

async function openConversation(agent: Page, customerName: string) {
  await agent.goto("/inbox");
  const row = agent
    .getByTestId("conversation-list")
    .getByRole("link", { name: new RegExp(customerName) })
    .first();
  await expect(row).toBeVisible();
  await row.click();
  await agent.waitForURL(/\/inbox\/\d+$/);
}

async function chooseComposerChannel(agent: Page, label: string) {
  await agent.getByRole("combobox", { name: "Channel" }).click();
  await agent.getByRole("option", { name: label }).click();
}

test.beforeAll(async ({ request }) => {
  health = await (await request.get(`${API}/api/health`)).json();
  expect(health.db, "database reachable").toBe("ok");
  const age = Date.now() - new Date(health.worker_heartbeat_at ?? 0).getTime();
  expect(age, "worker heartbeat is fresh: start `uv run python -m app.worker`").toBeLessThan(30_000);
  await resetDemoState(request);
});

test("demo steps 1–5: one conversation across channels, AI assistance, compliance", async ({
  browser,
}) => {
  test.skip(!health.llm_configured, "needs OPENAI_API_KEY (step 7 covers the LLM-off case)");
  test.setTimeout(240_000);
  const context = await browser.newContext();
  const agent = await context.newPage();
  const sim = await context.newPage();
  await login(agent);
  await login(sim);
  await sim.goto("/simulator");
  await expect(agent.getByTestId("live-status")).toHaveAttribute("data-state", "open");

  const rahulFirst = "My payment failed but the money was deducted.";

  await test.step("1. Rahul on WhatsApp: new conversation, Payments & Billing, high, acknowledged", async () => {
    await customerSays(sim, "Rahul Sharma", "WhatsApp", rahulFirst);
    await openConversation(agent, "Rahul Sharma");
    const thread = agent.getByTestId("thread");
    await expect(thread).toContainText(rahulFirst);
    const first = thread.getByTestId("message").filter({ hasText: rahulFirst });
    await expect(first.getByTestId("ai-chips")).toContainText("Payments & Billing");
    await expect(first.getByTestId("ai-chips")).toContainText("Negative");
    const header = agent.locator("header").filter({ hasText: "Conversation #" });
    await expect(header).toContainText("Payments & Billing");
    await expect(header).toContainText("High");
    const ack = thread.getByTestId("message").filter({ hasText: "Automatic acknowledgement" });
    await expect(ack.getByTestId("delivery-status")).toHaveAttribute("data-status", "delivered");
    await expect(sim.getByTestId("sim-thread")).toContainText("thank you for contacting us");
    await shot(agent, "step1-agent");
  });

  const conversationUrl = agent.url();

  await test.step("2. Rahul by email: same conversation, queue and intent unchanged", async () => {
    await customerSays(sim, "Rahul Sharma", "Email", "Any update?");
    const thread = agent.getByTestId("thread");
    await expect(thread).toContainText("Any update?");
    expect(agent.url()).toBe(conversationUrl);
    const followUp = thread.getByTestId("message").filter({ hasText: "Any update?" });
    await expect(followUp.getByTestId("ai-chips")).toBeVisible();
    const header = agent.locator("header").filter({ hasText: "Conversation #" });
    await expect(header).toContainText("Payments & Billing");
    await expect(header).toContainText("High");
    await shot(agent, "step2-agent");
  });

  await test.step("3. Summarize, draft, edit and send on WhatsApp: allowed and delivered", async () => {
    const summary = agent.getByTestId("summary");
    await summary.getByRole("button", { name: "Summarize" }).click();
    await expect(agent.getByTestId("summary-body")).toBeVisible({ timeout: AI_TIMEOUT });

    await chooseComposerChannel(agent, "WhatsApp");
    await agent.getByRole("button", { name: "Draft reply" }).click();
    await expect(agent.getByTestId("draft-panel")).toBeVisible({ timeout: AI_TIMEOUT });
    const reply = agent.getByLabel("Reply");
    const drafted = await reply.inputValue();
    expect(drafted.length).toBeGreaterThan(20);
    const final = `${drafted.trim()} Reference: ${marker()}.`;
    await reply.fill(final);
    await expect(agent.getByTestId("draft-panel")).toContainText("edited by you");
    await shot(agent, "step3-draft");
    await agent.getByRole("button", { name: "Send", exact: true }).click();

    const sent = agent.getByTestId("thread").getByTestId("message").filter({ hasText: final });
    await expect(sent.getByTestId("delivery-status")).toHaveAttribute("data-status", "delivered");
    await sim.getByRole("radio", { name: "WhatsApp" }).click();
    await expect(sim.getByTestId("sim-thread")).toContainText(final);
    await shot(agent, "step3-sent");
  });

  await test.step("4. Priya on WhatsApp: Cards queue; reply blocked by consent.opt_out; logged", async () => {
    await customerSays(sim, "Priya Verma", "WhatsApp", "When will my new card arrive?");
    await openConversation(agent, "Priya Verma");
    const thread = agent.getByTestId("thread");
    const inbound = thread.getByTestId("message").filter({ hasText: "When will my new card arrive?" });
    await expect(inbound.getByTestId("ai-chips")).toContainText("Cards");

    const text = `Your new card is on its way (${marker()}).`;
    await chooseComposerChannel(agent, "WhatsApp");
    await agent.getByLabel("Reply").fill(text);
    await agent.getByRole("button", { name: "Send", exact: true }).click();
    const blocked = thread.getByTestId("message").filter({ hasText: text });
    await expect(blocked.getByTestId("delivery-status")).toHaveAttribute("data-status", "blocked");
    await expect(blocked.getByTestId("compliance-reasons")).toContainText(
      "Customer has opted out of WhatsApp messages.",
    );
    await shot(agent, "step4-blocked");

    await agent.goto("/admin/compliance");
    const row = agent
      .getByTestId("compliance-row")
      .filter({ hasText: "Priya Verma" })
      .and(agent.locator('[data-rule="consent.opt_out"]'))
      .first();
    await expect(row).toBeVisible();
    await shot(agent, "step4-log");
  });

  await test.step("5. Proactive SMS to Amit: blocked by dnd.proactive", async () => {
    await agent.goto("/customers");
    await agent.getByRole("link", { name: /Amit Rao/ }).first().click();
    await agent.getByRole("button", { name: "Send proactive message" }).click();
    const dialog = agent.getByRole("dialog");
    await dialog.getByRole("combobox").click();
    await agent.getByRole("option", { name: "SMS" }).click();
    await dialog.getByLabel("Message", { exact: true }).fill("Special offer: new fixed deposit rates at 7.5% p.a.");
    await dialog.getByRole("button", { name: "Send", exact: true }).click();
    const result = dialog.getByTestId("outreach-result");
    await expect(result).toHaveAttribute("data-allowed", "false");
    await expect(result.locator('[data-rule="dnd.proactive"]')).toContainText(
      "Customer is on DND. Only service replies are allowed.",
    );
    await shot(agent, "step5-blocked");
  });

  await context.close();
});

test("demo step 7: with the LLM off the UI shows AI unavailable and manual send works", async ({
  browser,
}) => {
  test.skip(health.llm_configured, "start the API with OPENAI_API_KEY empty to run this step");
  const context = await browser.newContext();
  const agent = await context.newPage();
  const sim = await context.newPage();
  await login(agent);
  await login(sim);
  await sim.goto("/simulator");

  await customerSays(sim, "Rahul Sharma", "WhatsApp", "Is anyone there? My payment failed.");
  await openConversation(agent, "Rahul Sharma");
  await agent.getByRole("button", { name: "Draft reply" }).click();
  await expect(agent.getByTestId("ai-unavailable")).toContainText("AI unavailable");
  await agent.getByTestId("summary").getByRole("button", { name: "Summarize" }).click();
  await expect(agent.getByTestId("summary-unavailable")).toBeVisible();
  await shot(agent, "step7-unavailable");

  const manual = `Typed by hand while AI is off (${marker()}).`;
  await agent.getByLabel("Reply").fill(manual);
  await agent.getByRole("button", { name: "Send", exact: true }).click();
  const sent = agent.getByTestId("thread").getByTestId("message").filter({ hasText: manual });
  await expect(sent.getByTestId("delivery-status")).toHaveAttribute("data-status", "delivered");
  await expect(sim.getByTestId("sim-thread")).toContainText(manual);
  await shot(agent, "step7-sent");
  await context.close();
});
