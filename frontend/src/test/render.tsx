/**
 * Helpers for component tests: a fake server (fetch replaced by a table of answers), the real
 * AuthProvider signed in as the given user, React Query and the router. Synthetic data only.
 */
import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import "../i18n";
import type { CurrentUser } from "../api/types";
import { AuthProvider } from "../auth/AuthContext";

export type Handler = (body: unknown, url: URL) => { status?: number; json?: unknown } | undefined;
export interface Call {
  method: string;
  path: string;
  body: unknown;
}

export function makeUser(permissions: string[], extra: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: "u1",
    username: "tester",
    first_name: "Test",
    last_name: "User",
    full_name: "Test User",
    email: "",
    phone: "",
    job_title: "",
    registration_number: "",
    is_active: true,
    roles: [],
    department: null,
    last_login: null,
    permissions,
    mfa_setup_required: false,
    email_alerts: "off",
    modules_off: [],
    ...extra,
  } as unknown as CurrentUser;
}

/** Replace fetch. Keys are "METHOD /path/" (query string ignored) and answer with JSON. */
export function fakeServer(user: CurrentUser, routes: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  document.cookie = "mrs_csrftoken=test-token";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(input, "http://clinic.local");
      const method = (init.method ?? "GET").toUpperCase();
      const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
      calls.push({ method, path: url.pathname, body });
      const key = `${method} ${url.pathname.replace(/^\/api\/v1/, "")}`;
      let answer: { status?: number; json?: unknown } | undefined;
      if (key === "GET /auth/me/") answer = { json: user };
      else if (key in routes) {
        const r = routes[key];
        answer = typeof r === "function" ? (r as Handler)(body, url) : { json: r };
      }
      answer = answer ?? { status: 404, json: { error: { code: "not_found", message: `No fake answer for ${key}` } } };
      const status = answer.status ?? 200;
      return new Response(status === 204 ? null : JSON.stringify(answer.json ?? {}), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

export function renderApp(ui: ReactNode, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
