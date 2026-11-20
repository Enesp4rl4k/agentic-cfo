// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { render } from "../../scripts/gen-api-types.mjs";

// The pilot routes' types are generated from the backend's schema
// (pilot-openapi.json, itself checked by backend/tests/test_api_contract.py).
// A hand edit, or a schema change without regenerating, fails here.

describe("generated API types", () => {
  it("match the committed backend schema", async () => {
    const committed = readFileSync(new URL("../lib/api/generated/pilot-schema.ts", import.meta.url), "utf-8");
    // Line endings are the checkout's business (core.autocrlf), not the schema's.
    const lf = (text: string) => text.replace(/\r\n/g, "\n");
    expect(lf(committed)).toBe(lf(await render()));
  });
});
