/**
 * Which date changes the payment calendar offers: a payment in the first radar week cannot be brought
 * forward and one in the last week cannot be pushed later. Which payment is in week 1 depends on the
 * day (backend/tests/test_radar_week_boundaries.py), so the browser journey picks an enabled button.
 */
import { describe, it, expect } from "vitest";
import { canMoveEarlier, canMoveLater, WEEKS } from "@/components/calendar/scenario";

describe("calendar move bounds", () => {
  it("week 1 cannot go earlier; week 2 can", () => {
    expect(canMoveEarlier(1)).toBe(false);
    expect(canMoveEarlier(2)).toBe(true);
    expect(canMoveEarlier(WEEKS)).toBe(true);
  });

  it("the last week cannot go later; the one before can", () => {
    expect(canMoveLater(WEEKS)).toBe(false);
    expect(canMoveLater(WEEKS - 1)).toBe(true);
    expect(canMoveLater(1)).toBe(true);
    expect(canMoveLater(4, 4)).toBe(false); // a radar with fewer weeks
  });
});
