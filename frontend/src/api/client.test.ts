// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, isEditConflict } from "./client";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "mrs_csrftoken=test-token";
  return fetchMock;
}

describe("edit-conflict protection", () => {
  it("sends the loaded version as If-Match", async () => {
    const fetchMock = stubFetch(200, { ok: true });
    await api.patch("/patients/1/", { city: "Adama" }, { ifMatch: 7 });
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers["If-Match"]).toBe('"7"');
    expect(headers["X-CSRFToken"]).toBe("test-token");
  });

  it("sends no If-Match when no version is known", async () => {
    const fetchMock = stubFetch(200, {});
    await api.patch("/patients/1/", {});
    expect((fetchMock.mock.calls[0][1].headers as Record<string, string>)["If-Match"]).toBeUndefined();
  });

  it("turns a 409 edit_conflict into an error the UI recognises, with who and when", async () => {
    stubFetch(409, {
      error: {
        code: "edit_conflict",
        message: "changed by Abebe",
        changed_by: "Abebe K",
        changed_at: "2026-11-22T09:00:00+03:00",
      },
    });
    const err = (await api.patch("/patients/1/", {}, { ifMatch: 1 }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(isEditConflict(err)).toBe(true);
    expect(err.details.changed_by).toBe("Abebe K");
  });

  it("uploads a file as multipart, without a JSON content type", async () => {
    const fetchMock = stubFetch(200, { has_logo: true });
    const form = new FormData();
    form.append("logo", new Blob(["x"], { type: "image/png" }), "logo.png");
    await api.upload("/settings/clinic/logo/", form);
    const init = fetchMock.mock.calls[0][1];
    expect(init.body).toBe(form);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });
});

describe("server restarting or database down", () => {
  it("explains a gateway error from nginx instead of showing a code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>502 Bad Gateway</html>", {
          status: 502,
          headers: { "content-type": "text/html" },
        }),
      ),
    );
    const error = (await api.get("/visits/").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("server_unavailable");
    expect(error.message).toMatch(/restarting or not responding/);
    expect(error.message).toMatch(/check whether it was saved/);
  });

  it("passes the server's database message through", async () => {
    stubFetch(503, { error: { code: "database_unavailable", message: "The database is not responding." } });
    const error = (await api.post("/patients/", {}).catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(503);
    expect(error.code).toBe("database_unavailable");
  });
});
