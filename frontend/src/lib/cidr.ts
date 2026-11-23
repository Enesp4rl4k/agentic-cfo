/**
 * The IP allow-list's entry check, mirroring `normalise` in `backend/app/services/ip_allowlist.py`
 * (Python's `ipaddress.ip_network(text, strict=True)` plus the server's three extra refusals):
 * an IPv4 or IPv6 address or network, no host bits set, no catch-all (/0), no IPv4-mapped IPv6 form.
 * A bare address means a single host (/32, /128). The server stays the authority: this only saves a
 * round trip and says what is wrong before the person presses save. The one deliberate difference:
 * the dotted-netmask form ("10.0.0.0/255.0.0.0") that Python accepts is refused here (write /8).
 *
 * An address is a list of numbers: four octets (IPv4) or eight 16-bit groups (IPv6).
 */

export const MAX_ALLOWLIST_ENTRIES = 50;

export type CidrResult =
  | { ok: true; cidr: string }
  | { ok: false; reason: "invalid" | "catchAll" | "mapped" };

type Parsed = { v6: boolean; units: number[] };

function parseV4(text: string): number[] | null {
  const parts = text.split(".");
  if (parts.length !== 4) return null;
  const out: number[] = [];
  for (const part of parts) {
    if (!/^(0|[1-9]\d{0,2})$/.test(part)) return null; // no leading zeros, like Python 3.9.5+
    const n = Number(part);
    if (n > 255) return null;
    out.push(n);
  }
  return out;
}

function parseV6(text: string): number[] | null {
  if (!text.includes(":") || /[^0-9a-fA-F:.]/.test(text)) return null;
  let head = text;
  let tail: number[] | null = null;
  const lastColon = text.lastIndexOf(":");
  if (text.slice(lastColon + 1).includes(".")) {
    tail = parseV4(text.slice(lastColon + 1));
    if (tail === null) return null;
    head = `${text.slice(0, lastColon + 1)}0:0`; // two placeholder groups, replaced below
  }
  const halves = head.split("::");
  if (halves.length > 2) return null;
  const groups = (part: string) => (part === "" ? [] : part.split(":"));
  const left = groups(halves[0]);
  const right = halves.length === 2 ? groups(halves[1]) : [];
  const total = left.length + right.length;
  if (halves.length === 1 ? total !== 8 : total > 7) return null;
  const all = halves.length === 1 ? left : [...left, ...Array<string>(8 - total).fill("0"), ...right];
  if (all.some((g) => !/^[0-9a-fA-F]{1,4}$/.test(g))) return null;
  const units = all.map((g) => parseInt(g, 16));
  if (tail !== null) {
    units[6] = tail[0] * 256 + tail[1];
    units[7] = tail[2] * 256 + tail[3];
  }
  return units;
}

function parseAddress(text: string): Parsed | null {
  const v4 = parseV4(text);
  if (v4 !== null) return { v6: false, units: v4 };
  const v6 = parseV6(text);
  return v6 !== null ? { v6: true, units: v6 } : null;
}

/** RFC 5952: lower case, the longest run of zero groups (two or more) as "::", the first one on a tie. */
function formatV6(groups: number[]): string {
  let best = { start: -1, len: 0 };
  for (let i = 0; i < 8; ) {
    if (groups[i] !== 0) {
      i += 1;
      continue;
    }
    let j = i;
    while (j < 8 && groups[j] === 0) j += 1;
    if (j - i > best.len) best = { start: i, len: j - i };
    i = j;
  }
  const hex = groups.map((g) => g.toString(16));
  if (best.len < 2) return hex.join(":");
  return `${hex.slice(0, best.start).join(":")}::${hex.slice(best.start + best.len).join(":")}`;
}

/** The bits of `unit` that stay inside a network of `kept` leading bits (kept in 0..width). */
function networkMask(width: number, kept: number): number {
  if (kept >= width) return 2 ** width - 1;
  if (kept <= 0) return 0;
  return (2 ** width - 1) - (2 ** (width - kept) - 1);
}

function unitWidth(p: Parsed): number {
  return p.v6 ? 16 : 8;
}

/** One entry as the server would store it ("203.0.113.5" -> "203.0.113.5/32"), or why it would be refused. */
export function parseCidr(raw: string): CidrResult {
  const text = raw.trim();
  const slash = text.indexOf("/");
  const addr = slash === -1 ? text : text.slice(0, slash);
  const prefixText = slash === -1 ? null : text.slice(slash + 1);
  if (prefixText !== null && !/^\d{1,3}$/.test(prefixText)) return { ok: false, reason: "invalid" };

  const parsed = parseAddress(addr);
  if (parsed === null) return { ok: false, reason: "invalid" };
  const width = unitWidth(parsed);
  const bits = parsed.units.length * width;
  const prefix = prefixText === null ? bits : Number(prefixText);
  if (prefix > bits) return { ok: false, reason: "invalid" };

  const hostBits = parsed.units.some((unit, i) => {
    const mask = networkMask(width, prefix - i * width);
    return (unit & ~mask & (2 ** width - 1)) !== 0;
  });
  if (hostBits) return { ok: false, reason: "invalid" }; // host bits set (strict)
  if (prefix === 0) return { ok: false, reason: "catchAll" };
  const u = parsed.units;
  if (parsed.v6 && u.slice(0, 5).every((g) => g === 0) && u[5] === 0xffff) return { ok: false, reason: "mapped" };
  return { ok: true, cidr: `${parsed.v6 ? formatV6(u) : u.join(".")}/${prefix}` };
}

/** Whether `ip` (an address as the server reported it) is inside one stored entry. */
export function cidrContains(cidr: string, ip: string): boolean {
  const net = parseCidr(cidr);
  const host = parseAddress(ip.trim());
  if (!net.ok || host === null) return false;
  const [addr, prefixText] = net.cidr.split("/");
  const parsed = parseAddress(addr);
  if (parsed === null || parsed.v6 !== host.v6) return false;
  const width = unitWidth(parsed);
  const prefix = Number(prefixText);
  return parsed.units.every((unit, i) => {
    const mask = networkMask(width, prefix - i * width);
    return (unit & mask) === (host.units[i] & mask);
  });
}
