// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { fakeServer, makeUser, renderApp } from "../test/render";
import { ApiError } from "./client";
import { RECENT_MS, useAction, useGet } from "./hooks";
import { ErrorBanner } from "../ui";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useAction", () => {
  it("reports success only after the refreshed data is on the page", async () => {
    let saved = false;
    const calls = fakeServer(makeUser([]), {
      "GET /things/": () => ({ json: { state: saved ? "reviewed" : "no review yet" } }),
      "POST /things/": () => {
        saved = true;
        return { json: {} };
      },
    });
    const seenAtSuccess: string[] = [];
    function Probe() {
      const q = useGet<{ state: string }>(["things"], "/things/");
      const save = useAction(
        () => fetch("/api/v1/things/", { method: "POST" }),
        [["things"]],
        // How many times the data had been loaded, and its last answer, when success is reported.
        () => seenAtSuccess.push(`${calls.filter((c) => c.method === "GET" && c.path.endsWith("/things/")).length}`),
        false,
      );
      return (
        <>
          <span id="state">{q.data?.state}</span>
          <button onClick={() => save.mutate(undefined)}>Save</button>
        </>
      );
    }
    renderApp(<Probe />);
    expect(await screen.findByText("no review yet")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(seenAtSuccess).toHaveLength(1));
    expect(seenAtSuccess[0]).toBe("2"); // the reload after the save had already come back
    expect(await screen.findByText("reviewed")).toBeTruthy();
  });
});

describe("ErrorBanner", () => {
  it("lists what to correct instead of a bare 'Invalid input.'", () => {
    const error = new ApiError(400, {
      code: "validation_error",
      message: "Invalid input.",
      fields: { items: ["line 2, drug_name: This field may not be blank."] },
    });
    renderApp(<ErrorBanner error={error} />);
    expect(screen.getByText("Please correct the following:")).toBeTruthy();
    expect(screen.getByText("Line 2, drug name: This field may not be blank.")).toBeTruthy();
    expect(screen.queryByText("Invalid input.")).toBeNull();
  });
});

describe("useGet on opening a page", () => {
  function setup(answer: { state: string }) {
    const server = { answer };
    fakeServer(makeUser([]), { "GET /things/": () => ({ json: server.answer }) });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function Probe() {
      const q = useGet<{ state: string }>(["things"], "/things/");
      return <span data-testid="out">{q.isLoading ? "loading" : (q.data?.state ?? "-")}</span>;
    }
    const mount = () =>
      render(
        <QueryClientProvider client={qc}>
          <Probe />
        </QueryClientProvider>,
      );
    return { server, qc, mount };
  }
  const shown: string[] = [];
  const watch = () => {
    const el = screen.getByTestId("out");
    shown.push(el.textContent ?? "");
    new MutationObserver(() => shown.push(el.textContent ?? "")).observe(el, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  };

  it("never shows data a save marked out of date", async () => {
    shown.length = 0;
    const { server, qc, mount } = setup({ state: "unpaid" });
    qc.setQueryData(["things"], { state: "unpaid" }, { updatedAt: Date.now() - 1000 }); // loaded on an earlier visit
    server.answer = { state: "paid" };
    await qc.invalidateQueries({ queryKey: ["things"] }); // nothing mounted: only marked out of date
    mount();
    watch();
    await waitFor(() => expect(screen.getByTestId("out").textContent).toBe("paid"));
    expect(shown).not.toContain("unpaid");
  });

  it("shows recent data at once while refreshing it", async () => {
    shown.length = 0;
    const { server, qc, mount } = setup({ state: "a" });
    qc.setQueryData(["things"], { state: "a" });
    server.answer = { state: "b" };
    mount();
    watch();
    expect(shown[0]).toBe("a");
    await waitFor(() => expect(screen.getByTestId("out").textContent).toBe("b"));
  });

  it("waits for the refresh when the saved data is old", async () => {
    shown.length = 0;
    const { server, qc, mount } = setup({ state: "old" });
    qc.setQueryData(["things"], { state: "old" }, { updatedAt: Date.now() - RECENT_MS - 1000 });
    server.answer = { state: "new" };
    mount();
    watch();
    await waitFor(() => expect(screen.getByTestId("out").textContent).toBe("new"));
    expect(shown).not.toContain("old");
  });

  it("keeps showing the page's data while it refreshes after a save", async () => {
    shown.length = 0;
    const { server, qc, mount } = setup({ state: "one" });
    mount();
    await waitFor(() => expect(screen.getByTestId("out").textContent).toBe("one"));
    watch();
    server.answer = { state: "two" };
    await qc.invalidateQueries({ queryKey: ["things"] });
    await waitFor(() => expect(screen.getByTestId("out").textContent).toBe("two"));
    expect(shown).not.toContain("loading");
  });
});
