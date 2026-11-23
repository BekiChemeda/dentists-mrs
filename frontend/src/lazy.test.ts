// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { lazyPage } from "./lazy";

describe("lazyPage", () => {
  it("reloads once when a page file is missing after an upgrade, not in a loop", async () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    sessionStorage.clear();
    const failing = () => Promise.reject(new Error("Failed to fetch dynamically imported module"));
    const load = lazyPage(failing, "X" as never) as unknown as { _init: (p: unknown) => unknown; _payload: unknown };
    const attempt = async () => {
      try {
        await (load._init(load._payload) as Promise<unknown>);
      } catch (e) {
        if (e instanceof Promise) await e.catch(() => {});
      }
    };
    await attempt();
    await new Promise((r) => setTimeout(r, 0));
    expect(reload).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem("mrs-reloaded-for-update")).toBe("1");
    vi.unstubAllGlobals();
  });
});
