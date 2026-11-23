// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import { fakeServer, makeUser, renderApp } from "../test/render";
import type { Patient } from "../api/types";
import { PatientCard } from "./printouts";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PatientCard", () => {
  it("shows what reception needs and nothing clinical", async () => {
    fakeServer(makeUser(["patients.view"]), {
      "GET /settings/clinic/": {
        facility_name: "Demo Outpatient Clinic",
        phone: "0221 000 000",
        note_patient_card: "Bring this card to every visit.",
      },
    });
    const patient = {
      id: "p1",
      mrn: "00071",
      full_name: "Selam Synthetic",
      sex: "female",
      birth_date: "1990-01-01",
      age: 36,
      phone: "0911000000",
      known_conditions: "Hypertension",
      allergies: [{ substance: "Penicillin" }],
    } as unknown as Patient;
    renderApp(<PatientCard patient={patient} />);
    expect(await screen.findByText("Bring this card to every visit.")).toBeTruthy();
    expect(screen.getByText("00071")).toBeTruthy();
    expect(screen.getByText("Selam Synthetic")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/Hypertension|Penicillin/);
  });
});
