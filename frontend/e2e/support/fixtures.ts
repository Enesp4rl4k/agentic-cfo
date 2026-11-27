/**
 * The documents the journey uploads, written so the facts a reader can check stay fixed:
 * amounts, counterparties and invoice numbers never change; the dates are relative to the
 * journey's SIMULATED day, so the bank balance is "recent" and the invoices fall due in the
 * coming weeks — and every run sees the same dates.
 *
 * The journey runs on one simulated instant: the APIs (`start_backend.py` → APP_CLOCK_START), the
 * probe (`probe.py`) and the browser (`page.clock`, pilot-flow.spec.ts) all start at E2E_NOW, which
 * `playwright.config.ts` sets once (E2E_CLOCK_INSTANT). Not simulated: the Next.js server and the
 * backend's token stamps (app/core/clock.py `wall_now`), which only compare times, never dates.
 */

export const OPENING_BALANCE_TL = "116.500,00"; // the statement's closing balance, as the screen writes it

/** The journey's "now". 10:00 UTC is 13:00 in Istanbul: the same calendar day for every reader. */
export const E2E_NOW = new Date(process.env.E2E_CLOCK_INSTANT ?? "2026-11-25T10:00:00Z");

const pad = (n: number) => String(n).padStart(2, "0");

export function daysFromToday(offset: number): Date {
  const d = new Date(E2E_NOW.getTime());
  d.setDate(d.getDate() + offset);
  return d;
}

/** dd.mm.yyyy: how a Turkish export writes a date. */
export const tr = (d: Date) => `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
/** yyyy-mm-dd, the form the product's screens and e-mails use for data dates. */
export const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** A day of a calendar month, `monthsBack` months before this one (day 1 is the first, never past today). */
export function dayOfMonth(monthsBack: number, day: number): Date {
  return new Date(E2E_NOW.getFullYear(), E2E_NOW.getMonth() - monthsBack, day);
}

/**
 * The last statement row: two days ago, but never before the first of this month, so the three
 * calendar months before it are whole months and this one is the partial month the burn leaves out.
 */
function lastRowDate(): Date {
  const twoDaysAgo = daysFromToday(-2);
  const firstOfMonth = dayOfMonth(0, 1);
  return twoDaysAgo < firstOfMonth ? firstOfMonth : twoDaysAgo;
}

/**
 * Bank statement whose running balance chains: 120.000 opening, then the rows below, closing at
 * 116.500,00. It covers three whole calendar months (from the 2nd of the first, with this month's
 * rows after them), as a quarter's export does. Rent leaves in all three, which is what lets the
 * radar project the next one as an estimate ("tahmini") rather than a document. The months' nets
 * are +38.000, -42.000 and -12.000: an average burn of 5.333,33 against 116.500 in the bank.
 */
export function bankStatement() {
  const last = lastRowDate();
  const row = (date: Date, text: string, amount: string, balance: string) =>
    `${tr(date)};${text};"${amount}";"${balance}";TRY`;
  const csv = [
    "Tarih;Açıklama;Tutar;Bakiye;Para Birimi",
    row(dayOfMonth(3, 2), "Ofis kirası", "-12.000,00", "108.000,00"),
    row(dayOfMonth(3, 12), "Satış tahsilatı - Mavi Tekstil", "50.000,00", "158.000,00"),
    row(dayOfMonth(2, 2), "Ofis kirası", "-12.000,00", "146.000,00"),
    row(dayOfMonth(2, 20), "Personel maaş ödemesi", "-30.000,00", "116.000,00"),
    row(dayOfMonth(1, 2), "Ofis kirası", "-12.000,00", "104.000,00"),
    row(last, "Danışmanlık geliri - Kara Holding", "12.500,00", "116.500,00"),
    "",
  ].join("\n");
  return { name: "banka-ekstresi.csv", mimeType: "text/csv", buffer: Buffer.from(csv, "utf-8"), asOf: last };
}

/**
 * A company that really is short of cash: 100.000 opening, and in each of three whole months a
 * 20.000 receipt against 10.000 rent and 40.000 salary (net -30.000 a month); it closes on 9.000,00,
 * a third of a month of cash at that pace.
 */
export function cashShortStatement() {
  const last = lastRowDate();
  const row = (date: Date, text: string, amount: string, balance: string) =>
    `${tr(date)};${text};"${amount}";"${balance}";TRY`;
  const months = [3, 2, 1].flatMap((back, i) => {
    const base = 120 - 30 * i; // balance after the month's receipt, rent and salary: 70, 40, 10 (thousand)
    const fmt = (thousand: number) => `${thousand}.000,00`;
    return [
      row(dayOfMonth(back, 2), "Satış tahsilatı - Mavi Tekstil", "20.000,00", fmt(base)),
      row(dayOfMonth(back, 3), "Ofis kirası", "-10.000,00", fmt(base - 10)),
      row(dayOfMonth(back, 4), "Personel maaş ödemesi", "-40.000,00", fmt(base - 50)),
    ];
  });
  const csv = ["Tarih;Açıklama;Tutar;Bakiye;Para Birimi", ...months, row(last, "Pazarlama gideri", "-1.000,00", "9.000,00"), ""].join("\n");
  return { name: "kisa-nakit-ekstresi.csv", mimeType: "text/csv", buffer: Buffer.from(csv, "utf-8"), asOf: last };
}

/** Two open invoices: one to collect (this week), one to pay (next week). */
export function invoiceList() {
  const receivableDue = daysFromToday(5);
  const payableDue = daysFromToday(9);
  const csv = [
    "Tarih;Fatura No;Cari;Açıklama;Tutar;Tip;Vade;Para Birimi",
    `${tr(daysFromToday(-5))};FAT2026000101;Mavi Tekstil Ltd;Satış faturası;"60.000,00";income;${tr(receivableDue)};TRY`,
    `${tr(daysFromToday(-3))};FAT2026000102;Yeşil Ambalaj AŞ;Hammadde alış faturası;"-24.000,00";expense;${tr(payableDue)};TRY`,
    "",
  ].join("\n");
  return {
    name: "fatura-listesi.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv, "utf-8"),
    receivableDue,
    payableDue,
  };
}

/** The same statement without a currency column, as most exports are: the product holds its rows. */
export function bankStatementWithoutCurrency() {
  const withCurrency = bankStatement();
  const text = withCurrency.buffer
    .toString("utf-8")
    .split(String.fromCharCode(10))
    .map((line) => line.replace(/;TRY$/, "").replace(/;Para Birimi$/, ""))
    .join(String.fromCharCode(10));
  return { ...withCurrency, name: "banka-ekstresi-para-birimsiz.csv", buffer: Buffer.from(text, "utf-8") };
}
