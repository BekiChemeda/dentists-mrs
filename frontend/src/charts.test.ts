import { describe, expect, it } from "vitest";
import { niceTicks, shortDate, thinLabels } from "./charts";

describe("chart axis", () => {
  it("uses clean steps that cover the data", () => {
    expect(niceTicks(0, 37)).toEqual([0, 10, 20, 30, 40]);
    const t = niceTicks(36.2, 39.1);
    expect(t[0]).toBeLessThanOrEqual(36.2);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(39.1);
    expect(t.length).toBeLessThanOrEqual(8);
  });
  it("handles a single value and no spread", () => {
    const t = niceTicks(120, 120);
    expect(t[0]).toBeLessThan(120);
    expect(t[t.length - 1]).toBeGreaterThan(120);
  });
  it("formats short dates", () => {
    expect(shortDate("2026-11-22")).toBe("22 Nov");
    expect(shortDate("2026-11-22T09:05:00")).toBe("22 Nov");
    expect(shortDate("2026-11-22T09:05:00", true)).toBe("22 Nov 09:05");
  });
});

describe("axis labels", () => {
  it("keeps labels apart and always shows the last one", () => {
    const kept = [...thinLabels([0, 30, 60, 90, 120, 150, 170], 56)];
    expect(kept).toContain(6);
    for (let i = 1; i < kept.length; i++)
      expect(
        [0, 30, 60, 90, 120, 150, 170][kept[i]] - [0, 30, 60, 90, 120, 150, 170][kept[i - 1]],
      ).toBeGreaterThanOrEqual(56);
  });
});
