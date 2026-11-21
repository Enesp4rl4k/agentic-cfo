/**
 * The product name must reach the browser as well as the server.
 *
 * Next inlines NEXT_PUBLIC_* variables into the client bundle only where they are
 * written as `process.env.NEXT_PUBLIC_NAME`. A dynamic `process.env[key]` is left
 * as a lookup that finds nothing in the browser, so the configured name showed in
 * the page title (server) and the default in the logo (client). A source check is
 * the honest test: a unit test runs on Node, where both forms work.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const source = readFileSync(resolve(__dirname, "../lib/branding.ts"), "utf8");

describe("branding env access", () => {
  it("never reads process.env through a variable key", () => {
    expect(source).not.toMatch(/process\.env\s*\[/);
  });

  it("reads every brand variable by its full name", () => {
    for (const name of [
      "NEXT_PUBLIC_BRAND_NAME",
      "NEXT_PUBLIC_BRAND_DOMAIN",
      "NEXT_PUBLIC_BRAND_APP_URL",
      "NEXT_PUBLIC_BRAND_CONTACT_EMAIL",
      "NEXT_PUBLIC_BRAND_TWITTER_URL",
      "NEXT_PUBLIC_BRAND_LINKEDIN_URL",
    ]) {
      expect(source).toContain(`process.env.${name}`);
    }
  });
});
