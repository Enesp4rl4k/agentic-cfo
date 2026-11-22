/**
 * Finds hard-coded, user-visible string literals in JSX (text, copy-bearing
 * attributes) and in toast / dialog calls. Used by the `hardcoded-literals`
 * ratchet test. AST based, so comments, imports, class names, routes and
 * `data-testid`s never match.
 */
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

/** Attributes whose string value is shown to (or announced to) the user. */
export const COPY_ATTRS = new Set([
  "placeholder",
  "title",
  "aria-label",
  "aria-description",
  "aria-placeholder",
  "alt",
  "label",
  "description",
  "helperText",
  "emptyText",
  "emptyMessage",
]);

/** Call targets whose first string argument is shown to the user. */
const COPY_CALLS = new Set(["toast", "toast.error", "toast.success", "toast.info", "toast.warning", "alert", "window.alert", "window.confirm", "confirm"]);

/**
 * Tokens that are the same in every locale: brand and product names,
 * Turkish tax/e-document acronyms, file formats, units and currency codes.
 * A literal made only of these (plus digits/punctuation) is not copy.
 */
export const ALLOWED_TOKENS = new Set(
  [
    // brand / product / third-party names (proper nouns)
    "Tiphys", "Paraşüt", "Logo", "Mikro", "Netsis", "Luca", "Zirve", "Dia", "GitHub", "Google", "Slack", "Stripe", "OpenAI", "Claude",
    "Excel", "Microsoft", "Xero", "QuickBooks", "SAP", "Oracle", "Salesforce", "HubSpot", "Jira", "Notion", "Shopify", "iyzico", "Iyzico", "PayTR",
    "e-Fatura", "e-Arşiv", "e-Defter", "e-İrsaliye", "e-SMM", "GİB", "BDDK", "TCMB", "SGK", "TÜİK", "KVKK", "GDPR", "SOC",
    // tax / accounting acronyms used verbatim in Turkish practice
    "SMMM", "YMM", "KDV", "ÖTV", "MTV", "VUK", "TFRS", "BOBİ", "TMS", "IFRS", "GAAP", "VKN", "TCKN", "IBAN", "SWIFT", "BIC", "POS", "ERP", "CRM",
    "EBITDA", "EBIT", "P&L", "CFO", "CEO", "CTO", "COO", "CMO", "CHRO", "CRO", "KPI", "OKR", "SWOT", "KRI", "ROI", "ROE", "ROA", "DSO", "DPO", "DIO", "MRR", "ARR", "CAC", "LTV", "NPS", "FX",
    // formats / protocols / tech
    "CSV", "XLSX", "XLS", "PDF", "XML", "JSON", "TXT", "API", "URL", "SSO", "SAML", "OAuth", "OIDC", "2FA", "MFA", "OTP", "SMS", "SQL", "UUID", "ID", "HTTP", "HTTPS", "SFTP", "FTP", "AI", "UBL", "MCP", "RSS", "CPU", "RAM", "VAT",
    // units / currency codes
    "TL", "TRY", "USD", "EUR", "GBP", "CHF", "JPY", "SAR", "AED", "RUB", "kg", "MB", "KB", "GB", "px", "ms", "vs", "No", "Mn", "Mr", "Bn", "K", "M", "B", "a", "x",
    "p50", "p90", "p95", "p99", "Q1", "Q2", "Q3", "Q4", "H1", "H2", "YTD", "MoM", "YoY", "QoQ", "1D", "7D", "30D", "90D",
  ].map((s) => s.toLowerCase()),
);

const SEPARATED_NAMES = [...ALLOWED_TOKENS].filter((tok) => /[^\p{L}\d]/u.test(tok));
const LETTER = /\p{L}/u;
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** True when the text carries a word a person would read in a language. */
export function isUserCopy(raw: string): boolean {
  let text = raw.replace(/\s+/g, " ").trim();
  // Allowlisted names that contain a separator ("e-Fatura", "P&L") would be split below: drop them first.
  for (const name of SEPARATED_NAMES) text = text.split(new RegExp(escapeRe(name), "gi")).join(" ");
  if (!text.trim() || !LETTER.test(text)) return false;
  const tokens = text.split(/[\s/|:;,.()[\]{}<>+\-–—·•=*&!?"'`%_]+/u).filter(Boolean);
  const words = tokens.filter((tok) => LETTER.test(tok));
  if (words.length === 0) return false;
  // A list of column names ("employee_id, department, level") is a file format, not copy.
  if (/[a-z0-9]+_[a-z0-9_]+/.test(text)) return false;
  // single-token identifiers that look like code, not copy: snake_case, kebab-id, camelCase, paths
  if (words.length === 1) {
    const w = words[0];
    if (/^[a-z0-9]+(?:_[a-z0-9]+)+$/.test(w)) return false;
    if (/^[a-z]+[A-Z][A-Za-z0-9]*$/.test(w)) return false;
  }
  return !words.every((w) => ALLOWED_TOKENS.has(w.toLowerCase()) || /^[A-Z]{2,5}$/.test(w) || /^[A-Za-z]\d{1,3}$/.test(w) || /^\d/.test(w));
}

export interface LiteralFinding {
  file: string;
  line: number;
  kind: "jsx-text" | "attr" | "call";
  text: string;
}

function calleeName(expr: ts.Expression): string {
  if (ts.isIdentifier(expr)) return expr.text;
  if (ts.isPropertyAccessExpression(expr)) return `${calleeName(expr.expression)}.${expr.name.text}`;
  return "";
}

function stringOf(node: ts.Node | undefined): string | null {
  if (!node) return null;
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  if (ts.isJsxExpression(node) && node.expression) return stringOf(node.expression);
  if (ts.isTemplateExpression(node)) return node.head.text + node.templateSpans.map((s) => s.literal.text).join(" ");
  return null;
}

export function scanSource(file: string, source: string): LiteralFinding[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: LiteralFinding[] = [];
  const add = (node: ts.Node, kind: LiteralFinding["kind"], text: string) => {
    const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
    out.push({ file, line: line + 1, kind, text: text.replace(/\s+/g, " ").trim().slice(0, 90) });
  };
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) {
      if (isUserCopy(node.text)) add(node, "jsx-text", node.text);
    } else if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name) && COPY_ATTRS.has(node.name.text)) {
      const s = stringOf(node.initializer);
      if (s !== null && isUserCopy(s)) add(node, "attr", `${node.name.text}="${s}"`);
    } else if (ts.isCallExpression(node) && COPY_CALLS.has(calleeName(node.expression))) {
      const s = stringOf(node.arguments[0]);
      if (s !== null && isUserCopy(s)) add(node, "call", s);
    } else if (ts.isJsxExpression(node) && node.expression && ts.isStringLiteral(node.expression) && !ts.isJsxAttribute(node.parent)) {
      // {"literal"} used as a child
      if (isUserCopy(node.expression.text)) add(node, "jsx-text", node.expression.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return out;
}

export function listSourceFiles(srcRoot: string): string[] {
  const roots = ["app", "components"].map((d) => path.join(srcRoot, d));
  const files: string[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.name.endsWith(".tsx") && !/\.(test|spec)\.tsx$/.test(e.name)) files.push(p);
    }
  };
  roots.forEach(walk);
  return files.sort();
}

export function scanAll(srcRoot: string): LiteralFinding[] {
  return listSourceFiles(srcRoot).flatMap((f) => {
    const rel = path.relative(srcRoot, f).split(path.sep).join("/");
    return scanSource(rel, fs.readFileSync(f, "utf-8"));
  });
}
