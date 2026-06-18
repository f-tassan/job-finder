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
  linkedin: "Keywords, comma-separated (e.g. 'software engineer, backend developer')",
  bayt: "Keywords, e.g. 'accountant' (discovery only; KSA)",
  company_site: "Careers page URL, e.g. https://company.com/careers",
  gov_portals: "(set feed_url in filters)",
  email_alerts: "(uses configured IMAP inbox)",
};

const csv = (s: string) =>
  s.split(",").map((x) => x.trim()).filter(Boolean);
const lines = (s: string) =>
  s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);

const blank = {
  id: null as string | null,
  name: "",
  platform: "greenhouse" as Platform,
  query: "",
  urls: "",
  locations: "",
  include: "",
  exclude: "",
};

export default function SearchesPage() {
  const qc = useQueryClient();
  const [form, setForm] = useState({ ...blank });
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<typeof blank>) =>
    setForm((f) => ({ ...f, ...patch }));

  const list = useQuery({
    queryKey: ["searches"],
    queryFn: () => apiGet<SavedSearch[]>("/searches"),
  });

  const save = useMutation({
    mutationFn: () => {
      const isSite = form.platform === "company_site";
      const filters: Record<string, unknown> = {
        locations: csv(form.locations),
        include_keywords: csv(form.include),
        exclude_keywords: csv(form.exclude),
      };
      if (isSite) filters.urls = lines(form.urls);
      const body = {
        name: form.name,
        query: isSite ? null : form.query || null,
        filters,
      };
      return form.id
        ? apiSend(`/searches/${form.id}`, "PATCH", body)
        : apiSend("/searches", "POST", { platform: form.platform, ...body });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["searches"] });
      setForm({ ...blank });
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

  function edit(s: SavedSearch) {
    const f = (s.filters || {}) as Record<string, unknown>;
    const arr = (k: string) =>
      Array.isArray(f[k]) ? (f[k] as string[]).join(", ") : "";
    setForm({
      id: s.id,
      name: s.name,
      platform: s.platform,
      query: s.query || "",
      urls: Array.isArray(f.urls) ? (f.urls as string[]).join("\n") : "",
      locations: arr("locations"),
      include: arr("include_keywords"),
      exclude: arr("exclude_keywords"),
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const isSite = form.platform === "company_site";

  return (
    <AppShell>
      <h1 className="mb-4 text-xl font-semibold">Saved searches</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (form.name.trim()) save.mutate();
        }}
        className="mb-6 grid max-w-3xl grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 sm:grid-cols-2"
      >
        <div>
          <label className="block text-sm font-medium">Name *</label>
          <input
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
            required
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Platform</label>
          <select
            value={form.platform}
            disabled={!!form.id}
            onChange={(e) => set({ platform: e.target.value as Platform })}
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm disabled:opacity-60"
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>

        {isSite ? (
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">
              Careers page URLs (one per line)
            </label>
            <p className="mb-1 text-xs text-slate-400">
              Paste your whole company list here. Add more later by editing and
              appending lines.
            </p>
            <textarea
              value={form.urls}
              onChange={(e) => set({ urls: e.target.value })}
              rows={6}
              placeholder={"https://careers.company-a.com\nhttps://company-b.com/careers"}
              className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 font-mono text-xs"
            />
          </div>
        ) : (
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Query / token</label>
            <input
              value={form.query}
              onChange={(e) => set({ query: e.target.value })}
              placeholder={QUERY_HINT[form.platform]}
              className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
            />
          </div>
        )}

        <div>
          <label className="block text-sm font-medium">Locations</label>
          <input
            value={form.locations}
            onChange={(e) => set({ locations: e.target.value })}
            placeholder="Riyadh, Jeddah, Remote (comma-separated)"
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Include keywords</label>
          <input
            value={form.include}
            onChange={(e) => set({ include: e.target.value })}
            placeholder="python, backend"
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Exclude keywords</label>
          <input
            value={form.exclude}
            onChange={(e) => set({ exclude: e.target.value })}
            placeholder="intern, sales"
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <div className="flex items-center gap-3 sm:col-span-2">
          <button
            type="submit"
            disabled={save.isPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {form.id ? "Save changes" : "Add search"}
          </button>
          {form.id && (
            <button
              type="button"
              onClick={() => setForm({ ...blank })}
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
            >
              Cancel edit
            </button>
          )}
        </div>
      </form>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {list.isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : list.data && list.data.length > 0 ? (
        <ul className="space-y-2">
          {list.data.map((s) => {
            const urlCount = Array.isArray(
              (s.filters as Record<string, unknown>)?.urls,
            )
              ? ((s.filters as Record<string, unknown>).urls as string[]).length
              : 0;
            return (
              <li
                key={s.id}
                className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900 p-3"
              >
                <div>
                  <p className="text-sm font-medium">
                    {s.name}
                    <span className="ml-2 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                      {s.platform}
                      {s.platform === "company_site"
                        ? `: ${urlCount} site${urlCount === 1 ? "" : "s"}`
                        : s.query
                          ? `: ${s.query}`
                          : ""}
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
                    onClick={() => edit(s)}
                    className="rounded-md border border-slate-700 px-3 py-1.5 hover:bg-slate-800"
                  >
                    Edit
                  </button>
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
            );
          })}
        </ul>
      ) : (
        <p className="text-slate-400">
          No saved searches yet. Add one (e.g. a Greenhouse board, LinkedIn
          keywords, or a list of company careers pages) to populate the jobs feed.
        </p>
      )}
    </AppShell>
  );
}
