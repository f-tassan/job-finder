"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiSend } from "@/lib/api";
import { PLATFORMS, type Platform, type SavedSearch } from "@/lib/types";

const QUERY_HINT: Record<Platform, string> = {
  greenhouse: "Greenhouse board token (e.g. company slug)",
  lever: "Lever company slug",
  ashby: "Ashby org slug",
  linkedin: "Keywords, e.g. 'backend engineer' (discovery only)",
  bayt: "Keywords, e.g. 'accountant' (discovery only; KSA)",
  company_site: "Careers page URL, e.g. https://company.com/careers",
  gov_portals: "(set feed_url in filters)",
  email_alerts: "(uses configured IMAP inbox)",
};

function toList(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

export default function SearchesPage() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<Platform>("greenhouse");
  const [query, setQuery] = useState("");
  const [locations, setLocations] = useState("");
  const [include, setInclude] = useState("");
  const [exclude, setExclude] = useState("");
  const [error, setError] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["searches"],
    queryFn: () => apiGet<SavedSearch[]>("/searches"),
  });

  const add = useMutation({
    mutationFn: () =>
      apiSend("/searches", "POST", {
        name,
        platform,
        query: query || null,
        filters: {
          locations: toList(locations),
          include_keywords: toList(include),
          exclude_keywords: toList(exclude),
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["searches"] });
      setName("");
      setQuery("");
      setLocations("");
      setInclude("");
      setExclude("");
      setError(null);
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Failed"),
  });

  const toggle = useMutation({
    mutationFn: (s: SavedSearch) =>
      apiSend(`/searches/${s.id}`, "PATCH", { enabled: !s.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["searches"] }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiSend(`/searches/${id}`, "DELETE"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["searches"] }),
  });

  return (
    <AppShell>
      <h1 className="mb-4 text-xl font-semibold">Saved searches</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) add.mutate();
        }}
        className="mb-6 grid max-w-3xl grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 sm:grid-cols-2"
      >
        <div>
          <label className="block text-sm font-medium">Name *</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Platform</label>
          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value as Platform)}
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label className="block text-sm font-medium">Query / token</label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={QUERY_HINT[platform]}
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Locations</label>
          <input
            value={locations}
            onChange={(e) => setLocations(e.target.value)}
            placeholder="Riyadh, Jeddah, Remote (comma-separated)"
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Include keywords</label>
          <input
            value={include}
            onChange={(e) => setInclude(e.target.value)}
            placeholder="python, backend"
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Exclude keywords</label>
          <input
            value={exclude}
            onChange={(e) => setExclude(e.target.value)}
            placeholder="intern, sales"
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div className="sm:col-span-2">
          <button
            type="submit"
            disabled={add.isPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            Add search
          </button>
        </div>
      </form>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {list.isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : list.data && list.data.length > 0 ? (
        <ul className="space-y-2">
          {list.data.map((s) => (
            <li
              key={s.id}
              className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900 p-3"
            >
              <div>
                <p className="text-sm font-medium">
                  {s.name}
                  <span className="ml-2 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                    {s.platform}
                    {s.query ? `: ${s.query}` : ""}
                  </span>
                  {!s.enabled && (
                    <span className="ml-2 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-500">
                      disabled
                    </span>
                  )}
                </p>
                {s.last_run_at && (
                  <p className="text-xs text-slate-500">
                    last run {new Date(s.last_run_at).toLocaleString()}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 text-sm">
                <button
                  onClick={() => toggle.mutate(s)}
                  className="rounded-md border border-slate-700 px-3 py-1.5 hover:bg-slate-800"
                >
                  {s.enabled ? "Disable" : "Enable"}
                </button>
                <button
                  onClick={() => remove.mutate(s.id)}
                  className="rounded-md border border-slate-700 px-3 py-1.5 text-red-600 hover:bg-red-950"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-slate-400">
          No saved searches yet. Add one (e.g. a Greenhouse board) to populate the
          jobs feed.
        </p>
      )}
    </AppShell>
  );
}
