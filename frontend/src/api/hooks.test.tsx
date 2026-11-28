// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fakeServer, makeUser, renderApp } from "../test/render";
import { ApiError } from "./client";
import { useAction, useGet } from "./hooks";
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
