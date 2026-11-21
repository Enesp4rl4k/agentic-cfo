import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { API, API_WITH_MODEL, PASSWORD, acceptInvite, noteSignIns, bearer, invite, login, loginInBrowser, probe, register, type OutboxRow } from "./support/api";
import { OPENING_BALANCE_TL, bankStatement, bankStatementWithoutCurrency, invoiceList, iso, tr } from "./support/fixtures";

/**
 * The pilot's core flow as one story, told in order, in a real browser against the real stack.
 *
 * Every step asserts what a person can read: the screen's own sentences, and the dates and
 * amounts of the documents uploaded. Where the product does not do what the brief asks, the step
 * is a `test.fixme` with the reason, written as the test that should pass once it does.
 */

const stamp = Date.now();
const OWNER = `sahip.${stamp}@example.com`;
const ACCOUNTANT = `musavir.${stamp}@example.com`;
const ANALYST = `analist.${stamp}@example.com`;
const VIEWER = `izleyici.${stamp}@example.com`;
const COMPANY = "Deniz Tekstil A.Ş.";

const bank = bankStatement();
const invoices = invoiceList();
const asOf = tr(bank.asOf); // "19.11.2026": how the setup page writes the statement date
const asOfLong = bank.asOf.toLocaleDateString("tr-TR", { day: "numeric", month: "long" }); // "19 Kasım"
const todayLong = new Date().toLocaleDateString("tr-TR", { day: "numeric", month: "long" });

const S: {
  bankJob?: string;
  jobs?: string[];
  ownerToken?: string;
  ownerId?: string;
  ownerOrg?: string | null;
  accountantId?: string;
  briefingId?: string;
} = {};

async function inNewContext<T>(browser: Browser, email: string, body: (page: Page) => Promise<T>): Promise<T> {
  const ctx = await browser.newContext({ locale: "tr-TR", timezoneId: "Europe/Istanbul" });
  const page = await ctx.newPage();
  try {
    await loginInBrowser(page, email);
    return await body(page);
  } finally {
    await ctx.close();
  }
}

/**
 * A colleague joins the way the product lets a company add one: the owner invites them on the
 * workspace screen, they register, and they accept with the token from the invitation e-mail
 * (read from the database: the API only e-mails it, and there is no mail server here).
 */
async function addColleague(browser: Browser, request: APIRequestContext, email: string, role: "analyst" | "viewer", fullName: string) {
  await inNewContext(browser, OWNER, async (page) => {
    await page.goto("/settings/workspace");
    const form = page.locator("form").filter({ has: page.locator('input[type="email"]') });
    await form.locator('input[type="email"]').fill(email);
    await form.locator("select").selectOption(role);
    await form.getByRole("button").click();
    await expect(page.getByText(email)).toBeVisible({ timeout: 30_000 });
  });
  await register(request, email, fullName);
  const { token } = probe<{ token: string | null }>("invite-token", email);
  expect(token, "the invitation exists").toBeTruthy();
  expect((await acceptInvite(request, token as string, fullName)).status()).toBe(201);
}

/** The page's own content (the layout nests two <main> elements; the inner one is the page). */
const screen = (page: Page) => page.locator("main").last();

test.describe.configure({ mode: "serial" });

test.describe("Pilot flow", () => {
  test("1. a new owner registers and creates a company", async ({ page }) => {
    await page.goto("/auth/register");
    await page.locator("#fullName").fill("Ayşe Sahibi");
    await page.locator("#email").fill(OWNER);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /devam/i }).first().click();
    await page.locator("#orgName").fill(COMPANY);
    await page.getByRole("button", { name: /workspace oluştur/i }).click();
    await page.waitForURL(/\/baslangic/, { timeout: 60_000 });
    noteSignIns(3); // the screen signs in, asks for a token, and signs in again
    await expect(screen(page).getByRole("heading", { name: "Başlangıç" })).toBeVisible();
  });

  test("2. the setup page lists the steps and says there is no proven opening balance yet", async ({ page }) => {
    await loginInBrowser(page, OWNER);
    await page.goto("/baslangic");
    const main = screen(page);
    await expect(main.getByText("4 adımdan 1'i tamam")).toBeVisible({ timeout: 60_000 });
    await expect(main.getByText("Firmanızı tanımlayın")).toBeVisible();
    await expect(main.getByText(COMPANY)).toBeVisible();
    await expect(main.getByText("Verilerinizi bağlayın")).toBeVisible();
    await expect(main.getByText("İlk analiziniz", { exact: true })).toBeVisible();
    await expect(main.getByText("Nakit radarının başlangıç bakiyesi")).toBeVisible();
    // No statement yet: the radar step promises nothing and shows no amount.
    await expect(main.getByText("Radar, banka ekstrenizin kapanış bakiyesinden başlar; tahminle başlamaz.")).toBeVisible();
    await expect(main.getByText("İlk analiziniz bitince burada görünür.")).toBeVisible();
    await expect(main.getByText(/tarihinde ₺/)).toHaveCount(0);
  });

  test("3. the owner uploads the bank statement and the invoice list", async ({ page }) => {
    await loginInBrowser(page, OWNER);
    const jobs: string[] = [];
    for (const file of [bank, invoices]) {
      await page.goto("/upload");
      await page.locator('input[type="file"]').first().setInputFiles({ name: file.name, mimeType: file.mimeType, buffer: file.buffer });
      // The upload screen sends the person to the result once the job is accepted.
      await page.waitForURL(/\/pnl\?job=/, { timeout: 90_000 });
      jobs.push(new URL(page.url()).searchParams.get("job") as string);
    }
    S.bankJob = jobs[0];
    S.jobs = jobs;
  });

  test("3b. while the statement waits for the owner's approval, the setup page says that, not that the statement has no balance", async ({ page }) => {
    // The statement (6 rows, balances that chain) is held; the invoice list completes. The radar step
    // used to say "Ekstrede bakiye sütunu yok ya da satır bakiyeleri birbirini tutmuyor" because one
    // analysis was complete and no balance was proven yet: wrong, the statement is fine and waits.
    await loginInBrowser(page, OWNER);
    await page.goto("/baslangic");
    const main = screen(page);
    // The page refreshes by itself while an analysis runs, then shows what became of each.
    await expect(main.getByText("Ekstreniz onayınızı bekliyor")).toBeVisible({ timeout: 150_000 });
    await expect(main.getByText(/satır bakiyeleri birbirini tutuyor, dosyada eksik yok/)).toBeVisible();
    await expect(main.getByText("1 analiz onayınızı bekliyor")).toBeVisible();
    await expect(main.getByText(/En zayıf halka: forecast/)).toBeVisible(); // why it was held, in the run's own words
    await expect(main.getByText(/bakiye sütunu yok/)).toHaveCount(0);
    await expect(main.getByText("Kanıtlanmış banka bakiyesi yok")).toHaveCount(0);
    await expect(main.getByText("Kurulum tamam")).toHaveCount(0);
  });

  test("3c. the analyses finish; the invoice list completes and the statement waits for the owner", async ({ request }) => {
    // The forecast flags the statement's company as running out of cash within three months (its
    // net flow is negative; the forecast does not weigh the 116.500 on the account), and a flagged
    // step holds the whole run. The owner decides on the approvals screen (3d).
    const owner = await login(request, OWNER);
    S.ownerToken = owner.token;
    S.ownerId = owner.userId;
    S.ownerOrg = owner.orgId;
    const status = async (job: string) =>
      (await (await request.get(`${API}/analysis/${job}`, { headers: bearer(owner.token) })).json()).data.status as string;
    const jobs = S.jobs as string[];
    await expect.poll(async () => (await Promise.all(jobs.map(status))).every((s) => s === "completed" || s === "awaiting_review"), { timeout: 180_000, intervals: [3_000] }).toBe(true);
    const held = (await Promise.all(jobs.map(async (job) => ((await status(job)) === "awaiting_review" ? job : null)))).filter(Boolean) as string[];
    expect(held, "exactly the statement is held").toEqual([S.bankJob]);
  });

  test("3d. a held analysis is approved on the approvals screen, one click from the setup page", async ({ page, request }) => {
    // The notice used to say the held analysis waited "in the Command Center", whose queue lists only
    // agent jobs; the setup page's button showed only when nothing was completed. Now the setup page,
    // the result page and the menu lead to the approvals screen, which lists every kind of decision.
    await loginInBrowser(page, OWNER);
    await page.goto("/baslangic");
    await expect(screen(page).getByText("1 analiz onayınızı bekliyor")).toBeVisible({ timeout: 60_000 });
    await screen(page).getByRole("link", { name: "Onay bekleyenleri aç" }).first().click();
    await page.waitForURL(/\/onay/);

    const main = screen(page);
    await expect(main.getByText("1 karar sizi bekliyor")).toBeVisible({ timeout: 60_000 });
    await expect(main.getByRole("heading", { name: "Onayınızı bekleyen 1 analiz" })).toBeVisible();
    await expect(main.getByText("banka-ekstresi.csv")).toBeVisible();
    await expect(main.getByText(/En zayıf halka: forecast/)).toBeVisible();
    await expect(main.getByText(/kapanış bakiyesinden başlar/)).toBeVisible();
    await main.getByRole("button", { name: "Onayla ve tamamla" }).click();
    await page.getByRole("button", { name: "Evet, onayla" }).click();
    await expect(main.getByText("Analiz onaylandı.")).toBeVisible({ timeout: 30_000 });
    await expect(main.getByText("1 karar sizi bekliyor")).toHaveCount(0, { timeout: 30_000 });

    const owner = { token: S.ownerToken as string };
    const jobs = S.jobs as string[];
    const status = async (job: string) =>
      (await (await request.get(`${API}/analysis/${job}`, { headers: bearer(owner.token) })).json()).data.status as string;
    await expect.poll(async () => (await Promise.all(jobs.map(status))).join(","), { timeout: 180_000, intervals: [3_000] }).toBe("completed,completed");

    // The approval is on record: who, when, and why the run had been held.
    const records = await request.get(`${API}/decision-records?kind=held_run_release&limit=10`, { headers: bearer(owner.token) });
    const { data } = await records.json();
    expect(data).toHaveLength(1);
    expect(data[0]).toMatchObject({ decided_by: S.ownerId, decided_via: "human", outcome: "approved", target_id: S.bankJob });
  });

  test("3e. after the owner confirms the currency and approves the held run, the radar starts from the statement's balance", async ({ page, request }) => {
    // A statement without a currency column is held whole (every row waits). The balances chain, but
    // the proof was read only from rows already booked (none), so after the owner confirmed TRY and
    // approved, the setup page said "Kanıtlanmış banka bakiyesi yok" and the radar had no starting cash.
    const email = `para.${stamp}@example.com`;
    await register(request, email, "Para Sahibi");
    const first = await login(request, email);
    await request.post(`${API}/org/create`, { headers: bearer(first.token), data: { name: "Para Birimsiz A.Ş." } });
    const owner = await login(request, email);
    const file = bankStatementWithoutCurrency();
    const up = await request.post(`${API}/upload`, {
      headers: bearer(owner.token),
      multipart: { file: { name: file.name, mimeType: file.mimeType, buffer: file.buffer } },
    });
    const jobId = (await up.json()).data.job_id;
    await expect.poll(async () => (await (await request.get(`${API}/analysis/${jobId}`, { headers: bearer(owner.token) })).json()).data.status, { timeout: 120_000 }).toBe("awaiting_review");

    await loginInBrowser(page, email);
    // Before any decision the radar has no start, and the setup page says why in the right words.
    await page.goto("/baslangic");
    await expect(screen(page).getByText("Ekstreniz onayınızı bekliyor")).toBeVisible({ timeout: 60_000 });
    await expect(screen(page).getByText(/bakiye sütunu yok/)).toHaveCount(0);

    // The company currency, on the held-rows screen (which releases the rows that waited only for it).
    await page.goto("/bekleyen-kayitlar");
    await page.getByLabel("Para birimi").first().fill("TRY");
    await page.getByRole("button", { name: "Onayla", exact: true }).first().click();
    await expect(page.getByText("Şirketinizin para birimi nedir?")).toHaveCount(0, { timeout: 30_000 });

    // The run itself still waits for the owner, on the approvals screen.
    await page.goto("/onay");
    await expect(screen(page).getByRole("heading", { name: "Onayınızı bekleyen 1 analiz" })).toBeVisible({ timeout: 60_000 });
    await screen(page).getByRole("button", { name: "Onayla ve tamamla" }).click();
    await page.getByRole("button", { name: "Evet, onayla" }).click();
    await expect(screen(page).getByText("Analiz onaylandı.")).toBeVisible({ timeout: 30_000 });

    await page.goto("/nakit-radari");
    await expect(screen(page).getByText("Başlangıç nakdi")).toBeVisible({ timeout: 60_000 });
    await expect(screen(page).getByText(`₺${OPENING_BALANCE_TL.split(",")[0]}`).first()).toBeVisible();
    await expect(screen(page).getByText(asOfLong).first()).toBeVisible();
    const radar = await (await request.get(`${API}/ledger/cash-radar`, { headers: bearer(owner.token) })).json();
    expect(radar.data.starting_cash_cents).toBe(11_650_000);
    expect(radar.data.starting_cash_as_of).toBe(iso(bank.asOf));
  });

  test("4. the setup page now shows the proven opening balance with its date", async ({ page }) => {
    await loginInBrowser(page, OWNER);
    await page.goto("/baslangic");
    const main = screen(page);
    await expect(main.getByText("Kurulum tamam")).toBeVisible({ timeout: 60_000 });
    await expect(main.getByText("2 analiz tamamlandı")).toBeVisible();
    await expect(main.getByText(`${asOf} tarihinde ₺116.500`)).toBeVisible();
  });

  test("5. the cash radar starts from the statement balance, names its date, lists known items and marks estimates", async ({ page }) => {
    await loginInBrowser(page, OWNER);
    await page.goto("/nakit-radari");
    const main = screen(page);
    await expect(main.getByText("Başlangıç nakdi")).toBeVisible({ timeout: 60_000 });
    await expect(main.getByText(`₺${OPENING_BALANCE_TL.split(",")[0]}`).first()).toBeVisible();
    await expect(main.getByText(asOfLong).first()).toBeVisible();
    // A known item: the open receivable from the invoice list, in the week it falls due.
    await expect(main.getByText(/Mavi Tekstil Ltd/).first()).toBeVisible();
    // Estimated rows (rent seen in three months, projected forward) carry the "tahmini" tag.
    await expect(main.getByRole("button", { name: /tahmini/i }).first()).toBeVisible();
  });

  test("6. the Monday briefing answers the week and names the date of the data", async ({ page }) => {
    await loginInBrowser(page, OWNER);
    await page.goto("/bulten");
    const main = screen(page);
    await expect(main.getByText(/bu haftanın cevabı/i)).toBeVisible({ timeout: 60_000 });
    await expect(main.getByText(new RegExp(`${asOfLong} ekstresine göre`)).first()).toBeVisible();
    await expect(main.getByText(`${asOfLong} ekstresine göre kasa`)).toBeVisible();
    await expect(main.getByText("₺116.500")).toBeVisible();
    await expect(main.getByText(/Tahsilat takibi: Mavi Tekstil Ltd/)).toBeVisible();
  });

  test("7. the owner corrects a transaction's category and the ledger summary follows", async ({ page }) => {
    await loginInBrowser(page, OWNER);
    const expenseOnCard = async () => {
      await page.goto("/command-center");
      const label = page.getByText("Gider", { exact: true }).first();
      await expect(label).toBeVisible({ timeout: 60_000 });
      const text = await label.locator("xpath=following-sibling::dd[1]").innerText();
      return Number(text.replace(/[^\d,]/g, "").replace(",", ".")) || 0;
    };
    const before = await expenseOnCard();
    expect(before).toBeGreaterThan(30_000);

    await page.goto(`/transactions?job=${S.bankJob}`);
    const row = page.locator("tr", { hasText: "Personel maaş ödemesi" });
    await expect(row).toBeVisible({ timeout: 60_000 });
    await row.getByRole("button", { name: /salary/ }).click();
    await page.getByRole("listbox", { name: "Select category" }).getByRole("option", { name: "transfer" }).click();
    await expect(page.getByText("Category updated", { exact: true })).toBeVisible();
    await expect(row.getByRole("button", { name: /transfer/ })).toBeVisible();

    // The salary payment (30.000) is now a transfer between the company's own accounts: not an expense.
    await expect.poll(expenseOnCard, { timeout: 60_000 }).toBe(before - 30_000);
  });

  test("8. an accountant (SMMM) is added to the company through an invitation", async ({ request }) => {
    const owner = { token: S.ownerToken as string, orgId: S.ownerOrg };
    await register(request, ACCOUNTANT, "Murat Müşavir"); // an accountant with no company of their own yet
    await invite(request, owner.token, ACCOUNTANT, "smmm");

    // The API only e-mails the token (there is no SMTP here), so the test reads it from the database.
    const { token } = probe<{ token: string | null }>("invite-token", ACCOUNTANT);
    expect(token, "the invitation exists").toBeTruthy();
    const accepted = await acceptInvite(request, token as string, "Murat Müşavir");
    expect(accepted.status(), await accepted.text()).toBe(201);
    const smmm = await login(request, ACCOUNTANT);
    expect(smmm.role).toBe("smmm");
    expect(smmm.orgId).toBe(owner.orgId);
    S.accountantId = smmm.userId;
  });

  test("9. the Monday job runs: the owner's e-mail is held for the accountant, and the owner can see that", async ({ page }) => {
    probe("monday-tick");
    const rows = probe<OutboxRow[]>("outbox", OWNER);
    expect(rows).toHaveLength(1);
    expect(rows[0].source).toBe("monday_briefing");
    expect(rows[0].status).toBe("held");
    S.briefingId = rows[0].source_ref;

    await loginInBrowser(page, OWNER);
    await page.goto("/bulten");
    await expect(screen(page).getByText("Bülten e-postası")).toBeVisible({ timeout: 60_000 });
    await expect(screen(page).getByText(/E-posta mali müşavirinin onayını bekliyor/)).toBeVisible();
    // The owner cannot release it: there is no button.
    await expect(screen(page).getByRole("button", { name: "E-postayı serbest bırak" })).toHaveCount(0);
  });

  test("10. a colleague (analyst) proposes moving a payment date; it waits for the owner", async ({ browser, request }) => {
    await addColleague(browser, request, ANALYST, "analyst", "Aslı Analist");
    await inNewContext(browser, ANALYST, async (page) => {
      await page.goto("/takvim");
      await expect(page.getByText("Yeşil Ambalaj AŞ").first()).toBeVisible({ timeout: 60_000 });
      await page.getByRole("button", { name: "Yeşil Ambalaj AŞ: 1 hafta ötele" }).click();
      await expect(page.getByText("1 ödeme taşındı")).toBeVisible();
      await page.getByRole("button", { name: "Yeşil Ambalaj AŞ: Onaya gönder" }).click();
      await expect(page.getByText("Öneri onaya gönderildi. Onaylanana kadar rota eski tarihle hesaplanır.")).toBeVisible();
    });
  });

  test("11. the accountant sees the held briefing and releases it; the outbox holds it with the data date", async ({ browser }) => {
    await inNewContext(browser, ACCOUNTANT, async (page) => {
      await page.goto("/bulten");
      await expect(screen(page).getByText(/Bu haftanın e-postası senin onayını bekliyor/)).toBeVisible({ timeout: 60_000 });
      await screen(page).getByRole("button", { name: "E-postayı serbest bırak" }).click();
      await page.getByRole("button", { name: "Evet, gönder" }).click();
      await expect(screen(page).getByText("Onaylandı, e-posta gönderiliyor.")).toBeVisible({ timeout: 30_000 });
    });
    const [mail] = probe<OutboxRow[]>("outbox", OWNER);
    expect(mail.status).toBe("pending"); // released, waiting for the mail worker: nothing was delivered anywhere
    expect(mail.subject).toMatch(/^Pazartesi bülteni/);
    expect(mail.body).toContain(`${todayLong} tarihli verilere göre`);
    expect(mail.body).toContain("₺");
  });

  test("12. a viewer is invited from the workspace page; the viewer cannot correct a category or release the briefing", async ({ browser, request }) => {
    await addColleague(browser, request, VIEWER, "viewer", "İlker İzleyici");
    const viewer = await login(request, VIEWER);
    expect(viewer.role).toBe("viewer");

    await inNewContext(browser, VIEWER, async (page) => {
      // Correction: the screen offers the editor; the refusal is shown and nothing changes.
      await page.goto(`/transactions?job=${S.bankJob}`);
      const row = page.locator("tr", { hasText: "Danışmanlık geliri - Kara Holding" });
      await expect(row).toBeVisible({ timeout: 60_000 });
      await row.getByRole("button", { name: /revenue/ }).click();
      await page.getByRole("listbox", { name: "Select category" }).getByRole("option", { name: "other income" }).click();
      await expect(page.getByText("Failed to update category", { exact: true })).toBeVisible();
      await expect(row.getByRole("button", { name: /revenue/ })).toBeVisible();

      // Briefing: the viewer has no release button, and the server refuses a direct attempt.
      await page.goto("/bulten");
      await expect(page.getByText(/bu haftanın cevabı/i)).toBeVisible({ timeout: 60_000 });
      await expect(page.getByRole("button", { name: "E-postayı serbest bırak" })).toHaveCount(0);
    });
    const forbidden = await request.post(`${API}/briefing/monday/release`, {
      headers: bearer(viewer.token),
      data: { briefing_id: S.briefingId },
    });
    expect(forbidden.status()).toBe(403);
  });

  test("13. the owner approves the accountant's plan change in the approvals screen", async ({ browser }) => {
    await inNewContext(browser, OWNER, async (page) => {
      await page.goto("/onay");
      await expect(page.getByText("Ödeme planı değişikliği önerileri")).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText(/Yeşil Ambalaj AŞ/).first()).toBeVisible();
      // The screen now lists every kind of decision (role results waiting for the owner too), each in
      // its own section: the plan change's button is the one in the plan change section.
      await page.getByRole("region", { name: "Ödeme planı değişikliği önerileri" }).getByRole("button", { name: "Onayla" }).click();
      await expect(page.getByText("Ödeme planı değişikliği önerileri")).toHaveCount(0, { timeout: 30_000 });
    });
  });

  test("14. the decision records list the accountant's briefing release, with who and when", async ({ request }) => {
    const res = await request.get(`${API}/decision-records?limit=100`, { headers: bearer(S.ownerToken as string) });
    expect(res.status()).toBe(200);
    const { data } = await res.json();
    const releases = data.filter((d: { kind: string; decided_via: string }) => d.kind === "briefing_release" && d.decided_via === "human");
    expect(releases, "the accountant's release is recorded").toHaveLength(1);
    expect(releases[0].decided_by).toBe(S.accountantId);
    expect(releases[0].outcome).toBe("released");
    expect(Date.parse(releases[0].decided_at)).not.toBeNaN();
    // The system's own hold is recorded too, and is not mistaken for a person.
    expect(data.some((d: { kind: string; decided_via: string }) => d.kind === "briefing_release" && d.decided_via === "system")).toBe(true);
  });

  test.fixme("14b. the decision records list the owner's category correction, with who and when", async ({ request }) => {
    // PATCH /transactions/{id}/category writes an audit-log line (ledger.category_correction) but no
    // decision record, although DecisionKind.CATEGORY_CORRECTION exists.
    const res = await request.get(`${API}/decision-records?kind=category_correction`, { headers: bearer(S.ownerToken as string) });
    const { data } = await res.json();
    expect(data).toHaveLength(1);
    expect(data[0].decided_by).toBe(S.ownerId);
  });

  test.fixme("14c. the decision records list the owner's approval of the plan change, with who and when", async ({ request }) => {
    // Approving a plan change updates the payment_plan_changes row (decided_by, decided_at) but
    // writes no decision record, although DecisionKind.PLAN_CHANGE exists.
    const res = await request.get(`${API}/decision-records?kind=plan_change`, { headers: bearer(S.ownerToken as string) });
    const { data } = await res.json();
    expect(data).toHaveLength(1);
    expect(data[0].decided_by).toBe(S.ownerId);
    expect(data[0].outcome).toMatch(/approved/);
  });

  test("15. an approved action says plainly that it is not connected and that nothing was done", async ({ page, request }) => {
    // The one call that needs a model: a boardroom debate puts an action in front of the owner.
    // The model is a stub at the HTTP boundary (see support/llm_stub.py), behind a second API process
    // on port 8001 that shares the first one's database; every other step runs without any model.
    const debate = await request.post(`${API_WITH_MODEL}/negotiation/boardroom/debate`, {
      headers: bearer(S.ownerToken as string),
      data: { topic: "Tahsilat önceliği", context: "Mavi Tekstil alacağı bu hafta vadeli." },
      timeout: 120_000, // three rounds of model calls, on a process that has just started
    });
    expect(debate.status(), await debate.text()).toBe(200);

    await loginInBrowser(page, OWNER);
    // The screen talks to the first API; the action lives in the one that has the model's memory.
    await page.route(`${API}/actions/**`, (route) =>
      route.continue({ url: route.request().url().replace("localhost:8000", "localhost:8001") }),
    );
    await page.goto("/ceo");
    await expect(page.getByText("Onay Bekleyen Otonom Aksiyonlar")).toBeVisible({ timeout: 60_000 });
    await page.getByRole("button", { name: "Onayla" }).first().click();
    await expect(page.getByRole("status").filter({ hasText: "Bu işlem henüz bağlı değil — hiçbir şey yapılmadı." })).toBeVisible();
    // It stays on the list: nothing ran.
    await expect(page.getByText("1 Bekleyen")).toBeVisible();
  });

  test.fixme("15b. the accountant (smmm) can propose a payment date change, like any other writer", async ({ browser }) => {
    // The screen offers the accountant the button; the API answers 403 "Ödeme tarihi önermek için
    // yazma yetkisi gerekir" because PROPOSER_ROLES (owner, admin, cfo, analyst) leaves out smmm,
    // which every other writer check includes.
    await inNewContext(browser, ACCOUNTANT, async (page) => {
      await page.goto("/takvim");
      await page.getByRole("button", { name: /1 hafta (ötele|öne al)/ }).first().click();
      await page.getByRole("button", { name: /Onaya gönder/ }).first().click();
      await expect(page.getByText(/Öneri onaya gönderildi|Ödeme planı değişti/)).toBeVisible();
    });
  });

  test.fixme("16. the invitation link in the e-mail opens a page where the invitee accepts", async ({ page }) => {
    // The e-mail says {frontend}/auth/accept-invite?token=…; the app has no such page (404), and
    // the workspace screen copies /auth/register?invite=… (which the register page ignores).
    const res = await page.goto("/auth/accept-invite?token=anything");
    expect(res?.status()).toBe(200);
  });

  test.fixme("17. the workspace screen can invite an accountant (smmm)", async ({ page }) => {
    // The API accepts role smmm and the briefing flow depends on it, but the invite form offers
    // only analyst, viewer and admin.
    await loginInBrowser(page, OWNER);
    await page.goto("/settings/workspace");
    await expect(page.locator("form select option[value='smmm']")).toHaveCount(1);
  });

  test.fixme("18. an accountant who already has a company of their own can be added to a client and switch into it", async ({ browser, request }) => {
    // Registering through the screen always creates a company, so an accountant normally has one;
    // accepting an invitation then answers 400 "Zaten başka bir organizasyona üyesiniz", and the
    // company switcher (shown only with two memberships) can never appear.
    const email = `musavir2.${stamp}@example.com`;
    await register(request, email, "İkinci Müşavir");
    const own = await login(request, email);
    await request.post(`${API}/org/create`, { headers: bearer(own.token), data: { name: "Müşavirlik Bürosu" } });
    await invite(request, S.ownerToken as string, email, "smmm");
    const { token } = probe<{ token: string | null }>("invite-token", email);
    expect((await acceptInvite(request, token as string, "İkinci Müşavir")).status()).toBe(201);
    await inNewContext(browser, email, async (page) => {
      await page.goto("/command-center");
      await expect(page.getByRole("button", { name: new RegExp(COMPANY) })).toBeVisible();
    });
  });
});
