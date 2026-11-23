/**
 * Thin fetch wrapper for the MRS API.
 * - Cookie session (same origin), so no tokens are ever stored in JavaScript.
 * - Sends the CSRF token on every unsafe request.
 * - Turns the API's error format into ApiError.
 */

export interface ApiErrorBody {
  code: string;
  message: string;
  fields?: Record<string, string[]>;
  request_id?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: Record<string, string[]>;
  readonly requestId?: string;
  /** The whole error body, including extra data such as duplicate candidates. */
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.fields = body.fields ?? {};
    this.requestId = body.request_id;
    this.details = body as unknown as Record<string, unknown>;
  }
}

const BASE = "/api/v1";
const CSRF_COOKIE = "mrs_csrftoken";

function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`))
    ?.split("=")[1];
}

async function ensureCsrfToken(): Promise<string> {
  let token = readCookie(CSRF_COOKIE);
  if (!token) {
    await fetch(`${BASE}/auth/csrf/`, { credentials: "same-origin" });
    token = readCookie(CSRF_COOKIE);
  }
  return token ?? "";
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

let onUnauthenticated: (() => void) | null = null;
export function setUnauthenticatedHandler(handler: () => void) {
  onUnauthenticated = handler;
}

export interface RequestOptions {
  /** Version of the record the user loaded; the server refuses the save if it has changed since. */
  ifMatch?: number | null;
}

export async function apiRequest<T>(
  method: Method,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRFToken"] = await ensureCsrfToken();
  if (options.ifMatch != null) headers["If-Match"] = `"${options.ifMatch}"`;

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, {
      code: "network_error",
      message: "Cannot reach the clinic server. Check the network cable or Wi-Fi and try again.",
    });
  }

  if (response.status === 204) return undefined as T;

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await response.json() : null;

  if (!response.ok) {
    // 502/503/504 without our JSON body come from the web server while the application restarts.
    const restarting = [502, 503, 504].includes(response.status);
    const errorBody: ApiErrorBody = data?.error ?? {
      code: restarting ? "server_unavailable" : "server_error",
      message: restarting
        ? "The clinic server is restarting or not responding. Wait a minute and try again. If you were saving, check whether it was saved before entering it again."
        : `The server returned an unexpected response (${response.status}).`,
      request_id: response.headers.get("X-Request-ID") ?? undefined,
    };
    if (response.status === 401 && onUnauthenticated) onUnauthenticated();
    throw new ApiError(response.status, errorBody);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => apiRequest<T>("GET", path),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => apiRequest<T>("POST", path, body ?? {}, options),
  patch: <T>(path: string, body: unknown, options?: RequestOptions) => apiRequest<T>("PATCH", path, body, options),
  put: <T>(path: string, body: unknown, options?: RequestOptions) => apiRequest<T>("PUT", path, body, options),
  delete: <T>(path: string) => apiRequest<T>("DELETE", path),
  /** Multipart upload (e.g. the clinic logo). */
  upload: <T>(path: string, form: FormData) => apiRequest<T>("POST", path, form),
};

/** True when a save was refused because someone else changed the record first. */
export function isEditConflict(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === "edit_conflict";
}

export function queryString(params: Record<string, string | number | undefined | null>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}
