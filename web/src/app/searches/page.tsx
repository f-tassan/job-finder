"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiSend } from "@/lib/api";
import type { SavedSearch } from "@/lib/types";

const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const lines = (s: string) => s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
const arr = (f: Record<string, unknown>, k: string) =>
  Array.isArray(f[k]) ? (f[k] as string[]) : [];

const blankCompany = { id: null as string | null, name: "", urls: "" };
const blankLi = {
  id: null as string | null,
  name: "",
  keywords: "",
  locations: "",
  include: "",
  exclude: "",
};

export default function SearchesPage() {
  const qc = useQueryClient();
  const [company, setCompany] = useState({ ...blankCompany });
  const [li, setLi] = useState({ ...blankLi });
  const [error, setError] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["searches"],
    queryFn: () => apiGet<SavedSearch[]>("/searches"),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["searches"] });
  const fail = (e: unknown) =>
    setError(e instanceof Error ? e.message : "Failed");

  const saveCompany = useMutation({
    mutationFn: () => {
      const filters = {
        careers_urls: lines(company.urls),
        company: company.name.trim(),
        location: "Saudi Arabia",
      };
      const body = { name: company.name.trim(), query: null, filters };
      return company.id
        ? apiSend(`/searches/${company.id}`, "PATCH", body)
        : apiSend("/searches", "POST", { platform: "company", ...body });
    },
    onSuccess: () => {
      invalidate();
      setCompany({ ...blankCompany });
      setError(null);
    },
    onError: fail,
  });

  const saveLi = useMutation({
    mutationFn: () => {
      const filters = {
        locations: csv(li.locations),
        include_keywords: csv(li.include),
        exclude_keywords: csv(li.exclude),
      };
      const body = { name: li.name.trim(), query: li.keywords.trim() || null, filters };
      return li.id
        ? apiSend(`/searches/${li.id}`, "PATCH", body)
        : apiSend("/searches", "POST", { platform: "linkedin", ...body });
    },
    onSuccess: () => {
      invalidate();
      setLi({ ...blankLi });
      setError(null);
    },
    onError: fail,
  });

  const toggle = useMutation({
    mutationFn: (s: SavedSearch) =>
      apiSend(`/searches/${s.id}`, "PATCH", { enabled: !s.enabled }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiSend(`/searches/${id}`, "DELETE"),
    onSuccess: invalidate,
  });

  const all = list.data ?? [];
  const companies = all.filter((s) => s.platform === "company");
  const liSearches = all.filter((s) => s.platform === "linkedin");
  const others = all.filter(
    (s) => s.platform !== "company" && s.platform !== "linkedin",
  );

  function editCompany(s: SavedSearch) {
    const f = (s.filters || {}) as Record<string, unknown>;
    setCompany({ id: s.id, name: s.name, urls: arr(f, "careers_urls").join("\n") });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function editLi(s: SavedSearch) {
    const f = (s.filters || {}) as Record<string, unknown>;
    setLi({
      id: s.id,
      name: s.name,
      keywords: s.query || "",
      locations: arr(f, "locations").join(", "),
      include: arr(f, "include_keywords").join(", "),
      exclude: arr(f, "exclude_keywords").join(", "),
    });
    window.scrollTo({ top: 360, behavior: "smooth" });
  }

  const rowActions = (s: SavedSearch, onEdit: (s: SavedSearch) => void) => (
    <div className="flex items-center gap-2 text-sm">
      <button
        onClick={() => onEdit(s)}
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
  );

  const inputCls =
    "mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm";

  return (
    <AppShell>
      <h1 className="mb-1 text-xl font-semibold">Searches</h1>
      <p className="mb-5 text-sm text-slate-400">
        Track <span className="text-slate-200">companies</span> (each is searched on
        its own careers portal <em>and</em> LinkedIn), plus open{" "}
        <span className="text-slate-200">LinkedIn keyword</span> searches by role.
      </p>
      {error && <p className="mb-4 text-sm text-red-500">{error}</p>}

      {/* ---------------- Companies ---------------- */}
      <section className="mb-8">
        <h2 className="mb-2 text-sm font-semibold">Companies</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (company.name.trim() && lines(company.urls).length) saveCompany.mutate();
          }}
          className="mb-4 grid max-w-3xl grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4"
        >
          <div>
            <label className="block text-sm font-medium">Company name *</label>
            <input
              value={company.name}
              onChange={(e) => setCompany({ ...company, name: e.target.value })}
              placeholder="e.g. NEOM"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-sm font-medium">
              Careers portal URL(s) — one per line *
            </label>
            <p className="mb-1 text-xs text-slate-400">
              The company&apos;s careers page(s). Discovery scrapes these and also
              searches LinkedIn for this company&apos;s roles in Saudi Arabia.
            </p>
            <textarea
              value={company.urls}
              onChange={(e) => setCompany({ ...company, urls: e.target.value })}
              rows={3}
              placeholder={"https://careers.neom.com/careers"}
              className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 font-mono text-xs"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saveCompany.isPending}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {company.id ? "Save company" : "Add company"}
            </button>
            {company.id && (
              <button
                type="button"
                onClick={() => setCompany({ ...blankCompany })}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
              >
                Cancel edit
              </button>
            )}
          </div>
        </form>

        {companies.length > 0 ? (
          <ul className="space-y-2">
            {companies.map((s) => {
              const n = arr((s.filters || {}) as Record<string, unknown>, "careers_urls").length;
              return (
                <li
                  key={s.id}
                  className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900 p-3"
                >
                  <div>
                    <p className="text-sm font-medium">
                      {s.name}
                      <span className="ml-2 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                        {n} careers URL{n === 1 ? "" : "s"} + LinkedIn
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
                  {rowActions(s, editCompany)}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">No companies yet.</p>
        )}
      </section>

      {/* ---------------- LinkedIn keyword searches ---------------- */}
      <section className="mb-8">
        <h2 className="mb-2 text-sm font-semibold">LinkedIn keyword searches</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (li.name.trim() && li.keywords.trim()) saveLi.mutate();
          }}
          className="mb-4 grid max-w-3xl grid-cols-1 gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 sm:grid-cols-2"
        >
          <div>
            <label className="block text-sm font-medium">Name *</label>
            <input
              value={li.name}
              onChange={(e) => setLi({ ...li, name: e.target.value })}
              placeholder="e.g. AI / Data roles"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-sm font-medium">Keywords *</label>
            <input
              value={li.keywords}
              onChange={(e) => setLi({ ...li, keywords: e.target.value })}
              placeholder="AI engineer, data scientist"
              className={inputCls}
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Locations</label>
            <input
              value={li.locations}
              onChange={(e) => setLi({ ...li, locations: e.target.value })}
              placeholder="Riyadh, Jeddah, Remote (comma-separated)"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-sm font-medium">Include keywords</label>
            <input
              value={li.include}
              onChange={(e) => setLi({ ...li, include: e.target.value })}
              placeholder="python, machine learning"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-sm font-medium">Exclude keywords</label>
            <input
              value={li.exclude}
              onChange={(e) => setLi({ ...li, exclude: e.target.value })}
              placeholder="intern, sales"
              className={inputCls}
            />
          </div>
          <div className="flex items-center gap-3 sm:col-span-2">
            <button
              type="submit"
              disabled={saveLi.isPending}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {li.id ? "Save search" : "Add search"}
            </button>
            {li.id && (
              <button
                type="button"
                onClick={() => setLi({ ...blankLi })}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
              >
                Cancel edit
              </button>
            )}
          </div>
        </form>

        {liSearches.length > 0 ? (
          <ul className="space-y-2">
            {liSearches.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900 p-3"
              >
                <div>
                  <p className="text-sm font-medium">
                    {s.name}
                    <span className="ml-2 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                      linkedin{s.query ? `: ${s.query}` : ""}
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
                {rowActions(s, editLi)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">No keyword searches yet.</p>
        )}
      </section>

      {/* ---------------- Other (legacy) ---------------- */}
      {others.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-slate-400">Other searches</h2>
          <ul className="space-y-2">
            {others.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900 p-3"
              >
                <p className="text-sm font-medium">
                  {s.name}
                  <span className="ml-2 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                    {s.platform}
                    {s.query ? `: ${s.query}` : ""}
                  </span>
                </p>
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
        </section>
      )}

      {list.isLoading && <p className="text-slate-400">Loading…</p>}
    </AppShell>
  );
}
