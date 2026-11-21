/**
 * The documents the journey uploads, written so the facts a reader can check stay fixed:
 * amounts, counterparties and invoice numbers never change; only the dates move with the day
 * the test runs, so the bank balance is "recent" and the invoices fall due in the coming weeks.
 */

export const OPENING_BALANCE_TL = "116.500,00"; // the statement's closing balance, as the screen writes it

const pad = (n: number) => String(n).padStart(2, "0");

export function daysFromToday(offset: number): Date {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d;
}

/** dd.mm.yyyy: how a Turkish export writes a date. */
export const tr = (d: Date) => `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
/** yyyy-mm-dd, the form the product's screens and e-mails use for data dates. */
export const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/**
 * Bank statement whose running balance chains: 120.000 opening, then the rows below, closing at
 * 116.500,00. Rent leaves in three different months, which is what lets the radar project the next
 * one as an estimate ("tahmini") rather than a document.
 */
export function bankStatement() {
  const last = daysFromToday(-2);
  const row = (offset: number, text: string, amount: string, balance: string) =>
    `${tr(daysFromToday(offset))};${text};"${amount}";"${balance}";TRY`;
  const csv = [
    "Tarih;Açıklama;Tutar;Bakiye;Para Birimi",
    row(-75, "Ofis kirası", "-12.000,00", "108.000,00"),
    row(-70, "Satış tahsilatı - Mavi Tekstil", "50.000,00", "158.000,00"),
    row(-40, "Ofis kirası", "-12.000,00", "146.000,00"),
    row(-20, "Personel maaş ödemesi", "-30.000,00", "116.000,00"),
    row(-5, "Ofis kirası", "-12.000,00", "104.000,00"),
    row(-2, "Danışmanlık geliri - Kara Holding", "12.500,00", "116.500,00"),
    "",
  ].join("\n");
  return { name: "banka-ekstresi.csv", mimeType: "text/csv", buffer: Buffer.from(csv, "utf-8"), asOf: last };
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
