// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fakeServer, makeUser, renderApp } from "../test/render";
import { ModulesPanel, PermissionMatrix } from "./modules";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const MODULES = [
  {
    key: "triage",
    name: "Triage (nurse step)",
    description: "Nurse step.",
    when_off: "Patients go straight to the doctor.",
    enabled: true,
    off_because_of: [],
    requires: [],
    needed_by: [],
    permissions: [],
  },
  {
    key: "inventory",
    name: "Stock (inventory)",
    description: "Stock.",
    when_off: "No stock records.",
    enabled: true,
    off_because_of: [],
    requires: [],
    needed_by: ["pharmacy"],
    permissions: [],
  },
  {
    key: "pharmacy",
    name: "Pharmacy",
    description: "Dispensing.",
    when_off: "Printed prescriptions.",
    enabled: true,
    off_because_of: [],
    requires: ["inventory"],
    needed_by: [],
    permissions: [],
  },
];

describe("ModulesPanel", () => {
  it("asks before switching a module off and names what else stops", async () => {
    const calls = fakeServer(makeUser(["system.security.manage"]), {
      "GET /system/modules/": MODULES,
      "PATCH /system/modules/inventory/": MODULES.map((m) => (m.key === "inventory" ? { ...m, enabled: false } : m)),
    });
    renderApp(<ModulesPanel editable />);
    await userEvent.click(await screen.findByRole("switch", { name: "Stock (inventory)" }));
    expect(screen.getByText(/Pharmacy will also stop working/)).toBeTruthy();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false); // nothing changed before confirming
    await userEvent.click(screen.getByRole("button", { name: "Switch off" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: false }));
  });

  it("shows the unfinished work when the server refuses", async () => {
    fakeServer(makeUser(["system.security.manage"]), {
      "GET /system/modules/": MODULES,
      "PATCH /system/modules/triage/": () => ({
        status: 409,
        json: {
          error: {
            code: "conflict",
            message: "Triage (nurse step) still has unfinished work. Finish or cancel it first.",
            open_work: ["Triage (nurse step): 3 patient(s) waiting for triage"],
          },
        },
      }),
    });
    renderApp(<ModulesPanel editable />);
    await userEvent.click(await screen.findByRole("switch", { name: "Triage (nurse step)" }));
    await userEvent.click(screen.getByRole("button", { name: "Switch off" }));
    expect(await screen.findByText("Triage (nurse step): 3 patient(s) waiting for triage")).toBeTruthy();
  });

  it("is read-only for the clinic administrator", async () => {
    fakeServer(makeUser(["settings.manage"]), { "GET /system/modules/": MODULES });
    renderApp(<ModulesPanel editable={false} />);
    expect(await screen.findByText("Pharmacy")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.getByText(/Only the system administrator can change them/)).toBeTruthy();
  });
});

describe("PermissionMatrix", () => {
  const LAYOUT = {
    actions: [
      { key: "view", label: "View" },
      { key: "work", label: "Do the work" },
    ],
    areas: [
      {
        key: "laboratory",
        name: "Laboratory",
        module: "laboratory",
        module_on: false,
        permissions: [
          { code: "lab.view", action: "view", label: "View laboratory results", privileged: false },
          { code: "lab.result.enter", action: "work", label: "Enter laboratory results", privileged: false },
        ],
      },
    ],
  };

  it("ticks a whole row from its name and greys switched-off modules", async () => {
    fakeServer(makeUser(["users.view"]), { "GET /system/permission-layout/": LAYOUT });
    const toggled: string[] = [];
    renderApp(<PermissionMatrix selected={new Set(["lab.view"])} onToggle={(c) => toggled.push(c)} />);
    await userEvent.click(await screen.findByRole("button", { name: "Laboratory" }));
    expect(toggled).toEqual(["lab.result.enter"]); // only the missing one is added
    expect(screen.getByText("Module switched off")).toBeTruthy();
  });
});
