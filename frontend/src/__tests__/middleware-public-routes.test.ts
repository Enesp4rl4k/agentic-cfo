/**
 * Which paths the auth middleware leaves public.
 *
 * The matcher is an exclusion pattern: a path the pattern matches is protected.
 * This pins the public surface so a change to the pattern cannot open a page by
 * accident, or close the landing (`/`) and the auth pages to visitors.
 */
import { describe, it, expect } from "vitest";
import { config } from "@/middleware";

function isProtected(pathname: string): boolean {
  const pattern = config.matcher[0];
  // Next compiles matchers with path-to-regexp; for this lookahead pattern a
  // plain anchored RegExp of the same source is equivalent.
  return new RegExp(`^${pattern}$`).test(pathname);
}

describe("auth middleware: public routes", () => {
  it.each(["/", "/pricing", "/auth/login", "/auth/register", "/api/auth/session"])("leaves %s public", (path) => {
    expect(isProtected(path)).toBe(false);
  });

  it.each(["/marka", "/pnl", "/upload", "/settings/workspace", "/pilot", "/nakit-radari", "/baslangic"])(
    "still protects %s",
    (path) => {
      expect(isProtected(path)).toBe(true);
    },
  );
});
