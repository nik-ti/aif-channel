// Every fetch call the app makes. The base URL always comes from the
// environment (never hardcoded — see SPEC.md FAILURE #10) so the same build
// works against localhost in dev and the VPS through Vercel in prod.
import type {
  PostFilters,
  GraphResponse,
  NodesResponse,
  PostsResponse,
  StatsRange,
  StatsResponse,
  CompaniesResponse,
  Pulse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

if (!API_URL) {
  // Loud in the browser console during dev if the env var was never set,
  // instead of every request silently failing against a blank URL.
  console.error(
    "NEXT_PUBLIC_API_URL is not set. Create .env.local from .env.example."
  );
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // FastAPI puts the human-readable reason in `detail` (e.g. "that item is
    // already published"); surface it instead of a bare status code.
    const detail = typeof data?.detail === "string" ? data.detail : `${res.status} ${res.statusText}`;
    throw new Error(detail);
  }
  return data as T;
}

export function fetchPosts(filters: PostFilters, limit: number, offset: number) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (filters.source) params.set("source", filters.source);
  if (filters.company) params.set("company", filters.company);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.statuses.length) params.set("status", filters.statuses.join(","));
  if (filters.q.trim()) params.set("q", filters.q.trim());
  return get<PostsResponse>(`/posts?${params.toString()}`);
}

// The two write actions (backend api/actions.py): overrule a rejection, or
// label a post that should not have gone out. Both record a human verdict.
export function forcePublish(itemId: number, note = "") {
  return post<{ ok: boolean; message: string }>(
    `/actions/force`,
    { item_id: itemId, note }
  );
}

export function markShouldNotHavePosted(itemId: number, note = "") {
  return post<{ ok: boolean }>(
    `/actions/should-not-have-posted`,
    { item_id: itemId, note }
  );
}

export function fetchCompanies() {
  return get<CompaniesResponse>("/companies");
}

export function fetchStats(range: StatsRange = "7d") {
  return get<StatsResponse>(`/stats?${new URLSearchParams({ range }).toString()}`);
}

export function fetchPulse() {
  return get<Pulse>("/pulse");
}

export function fetchGraph() {
  return get<GraphResponse>("/graph");
}

export function fetchNodes() {
  return get<NodesResponse>("/nodes");
}

// /health is not under /api/v1 in api.ts's base path sense — it lives at
// the API root's /api/v1/health, which NEXT_PUBLIC_API_URL already points
// under (see .env.example), so this reuses the same base.
export function fetchHealth() {
  return get<{ status: string }>("/health");
}
