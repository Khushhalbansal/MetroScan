/*
  The API client.

  One place that knows the token, one place that turns a non-2xx into a readable
  message. Errors carry what the server actually said — an interface that swallows
  "the database is behind its migrations, run alembic upgrade head" and shows
  "Something went wrong" has taken a solved problem and made it a mystery.
*/

import type {
  Dashboard,
  Health,
  ScanPage,
  ScanResult,
  ScanRevision,
  User,
} from "./types";

// Same-origin by default (dev proxy, or a single host in production). Set
// VITE_API_BASE_URL at build time to point the client at a backend on another
// origin — e.g. the frontend on Vercel and the API on a Python host.
const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const BASE = `${API_ORIGIN}/api/v1`;
const TOKEN_KEY = "metroscan.token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** The sign-in has lapsed, as opposed to the action being refused. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
}

export function storedToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private browsing, or storage disabled. Signing in still works for this tab.
    return null;
  }
}

export function storeToken(token: string | null): void {
  try {
    if (token === null) localStorage.removeItem(TOKEN_KEY);
    else localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* nothing to do; the in-memory session is unaffected */
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail) && body.detail.length) {
      // FastAPI validation errors: name the field rather than dumping the shape.
      return body.detail
        .map((d: { loc?: unknown[]; msg?: string }) => {
          const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null;
          return field ? `${String(field)}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
  } catch {
    /* fall through to the status line */
  }
  return `${response.status} ${response.statusText}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = storedToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "The compliance bench is not responding. Check it is running.");
  }

  if (!response.ok) throw new ApiError(response.status, await readError(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),

  dashboard: (days = 90) => request<Dashboard>(`/dashboard?days=${days}`),

  signIn: async (email: string, password: string) => {
    const tokens = await request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    storeToken(tokens.access_token);
    return tokens;
  },

  signOut: () => storeToken(null),

  me: () => request<User>("/auth/me"),

  scans: (params: Record<string, string | number | undefined> = {}) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") query.set(key, String(value));
    }
    const suffix = query.toString();
    return request<ScanPage>(`/scans${suffix ? `?${suffix}` : ""}`);
  },

  scan: (scanId: string) => request<ScanResult>(`/scans/${scanId}`),

  /**
   * File a scan. Note there is no scale parameter: millimetre findings require a
   * fiducial the camera actually saw, and the endpoint offers no way to assert one.
   */
  createScan: (form: FormData) =>
    request<ScanResult>("/scans", { method: "POST", body: form }),

  /**
   * Image edits. Each of these re-runs the whole pipeline server-side and returns the
   * re-judged scan, so the caller never has to remember to refresh the findings.
   */
  addImage: (scanId: string, file: File, kind = "SIDE") => {
    const form = new FormData();
    form.append("image", file);
    form.append("kind", kind);
    return request<ScanResult>(`/scans/${scanId}/images`, { method: "POST", body: form });
  },

  removeImage: (scanId: string, imageId: string) =>
    request<ScanResult>(`/scans/${scanId}/images/${imageId}`, { method: "DELETE" }),

  replaceImage: (scanId: string, imageId: string, file: File) => {
    const form = new FormData();
    form.append("image", file);
    return request<ScanResult>(`/scans/${scanId}/images/${imageId}:replace`, {
      method: "POST",
      body: form,
    });
  },

  revisions: (scanId: string) => request<ScanRevision[]>(`/scans/${scanId}/revisions`),

  /**
   * Record the officer's retention answer. `caseOpen` true keeps the scan
   * indefinitely; false starts the auto-deletion clock from now. Every call is
   * audit-logged server-side with the previous answer.
   */
  setRetention: (scanId: string, caseOpen: boolean) =>
    request<ScanResult>(`/scans/${scanId}/retention`, {
      method: "POST",
      body: JSON.stringify({ case_open: caseOpen }),
    }),

  /**
   * Soft-delete a filed scan. The row, its images and its findings stay in the
   * database and the removal is audit-logged; the scan is only withheld from the
   * working repository. An officer may delete a scan they filed; an administrator
   * may delete any. A case being open does not block this — that is the whole point
   * of a manual delete, as opposed to the scheduled job.
   */
  deleteScan: (scanId: string, reason?: string) =>
    request<ScanResult>(`/scans/${scanId}`, {
      method: "DELETE",
      body: reason ? JSON.stringify({ reason }) : undefined,
    }),

  overrideFinding: (scanId: string, ruleId: string, status: string, reason: string) =>
    request<ScanResult>(`/scans/${scanId}/findings/${ruleId}:override`, {
      method: "POST",
      body: JSON.stringify({ status, reason }),
    }),

  generateReport: (scanId: string) =>
    request<{ pdf_url: string; json_url: string }>(`/scans/${scanId}/report`, {
      method: "POST",
    }),

  /** Evidence and reports are behind auth, so they are fetched and blob-URL'd. */
  authedBlob: async (path: string): Promise<string> => {
    const token = storedToken();
    const response = await fetch(`${BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!response.ok) throw new ApiError(response.status, await readError(response));
    return URL.createObjectURL(await response.blob());
  },

  imageUrl: (scanId: string, imageId: string) => `/scans/${scanId}/images/${imageId}`,
  reportPdfUrl: (scanId: string) => `/scans/${scanId}/report.pdf`,
  reportJsonUrl: (scanId: string) => `/scans/${scanId}/report.json`,
};
