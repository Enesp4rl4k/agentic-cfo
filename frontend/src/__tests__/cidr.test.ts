/**
 * The allow-list entry check mirrors the server's (`ip_allowlist.normalise`, tests/test_ip_allowlist.py):
 * what the server would refuse is refused here before the person saves, and what it stores is shown the same way.
 */
import { describe, expect, it } from "vitest";
import { cidrContains, parseCidr } from "@/lib/cidr";

const stored = (text: string) => {
  const r = parseCidr(text);
  return r.ok ? r.cidr : r.reason;
};

describe("parseCidr", () => {
  it("stores an address the way the server does: a bare address is one host", () => {
    expect(stored("203.0.113.5")).toBe("203.0.113.5/32");
    expect(stored(" 10.0.0.0/8 ")).toBe("10.0.0.0/8");
    expect(stored("2001:db8::/32")).toBe("2001:db8::/32");
    expect(stored("2001:db8::1")).toBe("2001:db8::1/128");
    expect(stored("2001:0DB8:0:0:0:0:0:1")).toBe("2001:db8::1/128");
    expect(stored("fe80:0:0:1:0:0:0:0/64")).toBe("fe80:0:0:1::/64");
  });

  it("refuses what the server refuses", () => {
    for (const bad of ["nope", "10.0.0.5/8", "999.1.1.1", "10.0.0.0/33", "10.0.0.1/24/1", "", "10.0.0", "010.0.0.1", "2001:db8::/129", "1::2::3", "10.0.0.0/x"]) {
      expect(stored(bad), bad).toBe("invalid");
    }
  });

  it("refuses the catch-all and the IPv4-mapped form with their own reasons", () => {
    expect(stored("0.0.0.0/0")).toBe("catchAll");
    expect(stored("::/0")).toBe("catchAll");
    expect(stored("::ffff:10.0.0.1")).toBe("mapped");
    expect(stored("::ffff:a00:1")).toBe("mapped");
  });
});

describe("cidrContains", () => {
  it("says whether the caller's address is inside an entry", () => {
    expect(cidrContains("10.0.0.0/8", "10.20.30.40")).toBe(true);
    expect(cidrContains("10.0.0.0/8", "11.0.0.1")).toBe(false);
    expect(cidrContains("203.0.113.5/32", "203.0.113.5")).toBe(true);
    expect(cidrContains("203.0.113.5/32", "203.0.113.6")).toBe(false);
    expect(cidrContains("2001:db8::/32", "2001:db8:1::5")).toBe(true);
    expect(cidrContains("2001:db8::/32", "10.0.0.1")).toBe(false);
    expect(cidrContains("10.0.0.0/8", "not an address")).toBe(false);
  });
});
