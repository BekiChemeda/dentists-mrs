import { describe, expect, it } from "vitest";
import { dashboardFor, hasAny, visibleNavItems } from "./navigation";

describe("visibleNavItems", () => {
  it("shows only the dashboard to a user without permissions", () => {
    expect(visibleNavItems([]).map((i) => i.key)).toEqual(["dashboard"]);
  });

  it("does not show administration to a receptionist", () => {
    const keys = visibleNavItems(["patients.view", "appointments.view", "queue.manage", "billing.view"]).map(
      (i) => i.key,
    );
    expect(keys).toContain("patients");
    expect(keys).not.toContain("users");
    expect(keys).not.toContain("consultations");
  });

  it("shows user administration and audit to a system administrator", () => {
    const keys = visibleNavItems(["users.view", "users.manage", "audit.view"]).map((i) => i.key);
    expect(keys).toEqual(expect.arrayContaining(["users", "roles", "audit"]));
    expect(keys).not.toContain("patients");
  });
});

describe("administration split", () => {
  const sys = [
    "users.view",
    "users.manage",
    "roles.manage",
    "audit.view",
    "system.health.view",
    "system.security.manage",
  ];
  const clinic = [
    "users.view",
    "staff.manage",
    "departments.manage",
    "announcements.manage",
    "settings.manage",
    "audit.operational",
    "patients.view",
    "reports.operational",
  ];
  it("gives the system administrator the system page but no clinic configuration", () => {
    const keys = visibleNavItems(sys).map((i) => i.key);
    expect(keys).toContain("system");
    expect(keys).not.toEqual(expect.arrayContaining(["clinic"]));
    expect(keys).not.toContain("departments");
    expect(keys).not.toContain("catalogue");
  });
  it("gives the clinic administrator operations but not the system page", () => {
    const keys = visibleNavItems(clinic).map((i) => i.key);
    expect(keys).toEqual(expect.arrayContaining(["departments", "announcements", "clinic", "users", "audit"]));
    expect(keys).not.toContain("system");
  });
  it("has a director dashboard", () => {
    expect(dashboardFor(["clinic_director"])).toBe("clinic_director");
  });
});

describe("dashboardFor", () => {
  it("gives clinical roles priority over administrative ones", () => {
    expect(dashboardFor(["clinic_admin", "doctor"])).toBe("doctor");
  });
  it("falls back to a general dashboard for custom roles", () => {
    expect(dashboardFor(["triage_assistant"])).toBe("general");
  });
  it("maps each shipped role to its own dashboard", () => {
    expect(dashboardFor(["receptionist"])).toBe("receptionist");
    expect(dashboardFor(["pharmacist"])).toBe("pharmacist");
  });
});

describe("hasAny", () => {
  it("treats an empty requirement as public", () => {
    expect(hasAny([], [])).toBe(true);
  });
});

describe("visibleNavItems with switched-off modules", () => {
  it("hides the triage page when triage is off, even for a nurse who keeps triage.record", () => {
    expect(visibleNavItems(["triage.record"]).map((i) => i.key)).toContain("triage");
    expect(visibleNavItems(["triage.record"], ["triage"]).map((i) => i.key)).not.toContain("triage");
  });
});
