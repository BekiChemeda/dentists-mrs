// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { applyTheme, resolveTheme, storedTheme } from "./theme";

describe("theme", () => {
  afterEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });
  it("defaults to following the device", () => {
    expect(storedTheme()).toBe("system");
  });
  it("applies an explicit choice to <html>", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });
  it("reads a saved choice and ignores junk", () => {
    window.localStorage.setItem("mrs.theme", "dark");
    expect(storedTheme()).toBe("dark");
    window.localStorage.setItem("mrs.theme", "purple");
    expect(storedTheme()).toBe("system");
  });
  it("resolves system to light or dark", () => {
    expect(["light", "dark"]).toContain(resolveTheme("system"));
  });
});
