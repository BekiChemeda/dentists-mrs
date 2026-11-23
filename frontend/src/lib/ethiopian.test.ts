import { describe, expect, it } from "vitest";
import { ecMonthLength, formatEc, fromEthiopian, toEthiopian } from "./ethiopian";

describe("Ethiopian calendar", () => {
  it("places Ethiopian New Year on 11 or 12 September", () => {
    // New Year falls on 12 September before a Gregorian leap year, otherwise on 11 September.
    expect(toEthiopian(2026, 9, 11)).toEqual({ year: 2019, month: 1, day: 1 });
    expect(toEthiopian(2024, 9, 11)).toEqual({ year: 2017, month: 1, day: 1 });
    expect(toEthiopian(2023, 9, 12)).toEqual({ year: 2016, month: 1, day: 1 });
    expect(toEthiopian(2023, 9, 11)).toEqual({ year: 2015, month: 13, day: 6 });
  });

  it("converts known dates", () => {
    expect(toEthiopian(2026, 11, 21)).toEqual({ year: 2019, month: 3, day: 12 }); // Hidar 12, 2019
    expect(toEthiopian(2025, 1, 7)).toEqual({ year: 2017, month: 4, day: 29 }); // Genna: Tahsas 29
    expect(toEthiopian(2000, 1, 1)).toEqual({ year: 1992, month: 4, day: 22 });
  });

  it("round-trips every day over twelve years", () => {
    const start = Date.UTC(2015, 0, 1);
    for (let i = 0; i < 365 * 12; i++) {
      const d = new Date(start + i * 86_400_000);
      const iso = d.toISOString().slice(0, 10);
      const ec = toEthiopian(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
      expect(fromEthiopian(ec.year, ec.month, ec.day)).toBe(iso);
    }
  });

  it("rejects impossible dates and knows Pagume's length", () => {
    expect(ecMonthLength(2015, 13)).toBe(6);
    expect(ecMonthLength(2016, 13)).toBe(5);
    expect(fromEthiopian(2016, 13, 6)).toBeNull();
    expect(fromEthiopian(2016, 2, 31)).toBeNull();
    expect(fromEthiopian(2016, 14, 1)).toBeNull();
  });

  it("formats in words", () => {
    expect(formatEc("2026-11-21")).toBe("Hidar 12, 2019 EC");
  });
});
