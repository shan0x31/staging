const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  return localStorage.getItem("pf_token");
}
export function setToken(token: string | null) {
  if (token) localStorage.setItem("pf_token", token);
  else localStorage.removeItem("pf_token");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (!(init.body instanceof FormData) && init.body) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* non-JSON error body */ }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: (path: string) => request<void>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method: "POST", body: form });
  },
};

// -- shared types mirroring backend schemas ----------------------------------

export interface AuthStatus { setup_complete: boolean; unlocked: boolean }
export interface Instrument {
  id: number; symbol: string; name: string; exchange: string;
  asset_class: string; sector: string | null; currency: string; country: string;
}
export interface Holding {
  instrument: Instrument; quantity: number; avg_cost: number; invested: number;
  current_price: number | null; price_date: string | null; current_value: number | null;
  unrealized_pnl: number | null; unrealized_pnl_pct: number | null;
  realized_pnl: number; dividends: number;
}
export interface Summary {
  base_currency: string; net_worth: number | null; equity_value: number | null;
  manual_assets_value: number | null; invested: number | null;
  unrealized_pnl: number | null; realized_pnl: number; dividends: number;
  xirr_pct: number | null; usdinr: number | null;
  allocation_by_class: Record<string, number>;
  allocation_by_currency: Record<string, number>;
  allocation_by_sector: Record<string, number>;
  priced_instruments: number; unpriced_instruments: number;
}
export interface Account {
  id: number; name: string; kind: string; currency: string; country: string;
  account_number: string | null;
}
export interface Txn {
  id: number; account_id: number; instrument_id: number | null; type: string;
  trade_date: string; quantity: string | null; price: string | null;
  fees: string | null; amount: string | null; notes: string | null;
}
export interface Reco {
  id: number; run_id: string; created_at: string; kind: string; category: string;
  severity: "info" | "warning" | "action"; symbol: string | null;
  title: string; rationale: string; data: Record<string, unknown> | null; dismissed: boolean;
}
export interface Mover { symbol: string; name: string; close: number; prev_close: number; change_pct: number }
export interface ImportSummary {
  batch_id: string; imported: number; skipped_duplicates: number;
  errors: string[]; detected_format: string;
}
