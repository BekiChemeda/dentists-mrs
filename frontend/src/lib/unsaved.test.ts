// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { clearUnsaved, hasUnsaved, useUnsavedGuard } from "./unsaved";

describe("useUnsavedGuard", () => {
  it("registers unsaved work only while it is unsaved", () => {
    clearUnsaved();
    const { rerender, unmount } = renderHook(({ on }) => useUnsavedGuard("exam", on), { initialProps: { on: false } });
    expect(hasUnsaved()).toBe(false);
    rerender({ on: true });
    expect(hasUnsaved()).toBe(true);
    rerender({ on: false });
    expect(hasUnsaved()).toBe(false);
    rerender({ on: true });
    unmount();
    expect(hasUnsaved()).toBe(false);
  });
});
