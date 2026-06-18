// Minimal API client base. Requests go through the reverse proxy at /api so the
// browser never talks to the API container directly. Expanded in Phase 1.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "/api";

export async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
