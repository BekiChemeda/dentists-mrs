// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fakeServer, makeUser, renderApp } from "../test/render";
import type { Visit } from "../api/types";
import { CompleteVisitDialog } from "./complete-visit";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const visit = {
  id: "v1",
  status: "after_consult",
  queue_number: 4,
  patient: {
    id: "p1",
    mrn: "00071",
    full_name: "Selam Synthetic",
    sex: "female",
    birth_date: "1990-01-01",
    age: 36,
    phone: "",
  },
} as unknown as Visit;

describe("CompleteVisitDialog", () => {
  it("lists what is still open and needs a reason before closing anyway", async () => {
    const calls = fakeServer(makeUser(["queue.manage"]), {
      "GET /visits/v1/outstanding/": {
        draft_notes: [],
        lab_pending: ["Haemoglobin: collected"],
        medicines_pending: [],
        unbilled: [],
        open_invoices: [],
        balance_due: "0.00",
        any: true,
        blocking: false,
      },
      "POST /visits/v1/complete/": { ...visit, status: "completed" },
    });
    renderApp(<CompleteVisitDialog visit={visit} onClose={() => {}} />);
    expect(await screen.findByText(/Haemoglobin: collected/)).toBeTruthy();
    const submit = screen.getByRole("button", { name: /Complete visit/ });
    await userEvent.click(submit);
    expect(calls.some((c) => c.path.endsWith("/complete/"))).toBe(false); // not sent without a reason
    const reason = screen.getByRole("textbox");
    await userEvent.type(reason, "Patient will return for the result tomorrow");
    const confirm = screen.queryByRole("checkbox");
    if (confirm) await userEvent.click(confirm);
    await userEvent.click(submit);
    await waitFor(() => {
      const sent = calls.find((c) => c.path.endsWith("/complete/"));
      expect(sent?.body).toMatchObject({
        outcome: "completed",
        acknowledge_outstanding: true,
        note: "Patient will return for the result tomorrow",
      });
    });
  });
});
