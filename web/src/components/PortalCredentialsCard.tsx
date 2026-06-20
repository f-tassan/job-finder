"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiGet, apiSend, ApiError } from "@/lib/api";
import type { PortalCredential, SavedSearch } from "@/lib/types";

type Draft = { username: string; password: string };
const EMPTY_DRAFT: Draft = { username: "", password: "" };

function hostFromUrl(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "";
  }
}

// A company login row, derived from a "company" saved search.
type CompanyLogin = { name: string; url: string; host: string };

export function PortalCredentialsCard() {
  const qc = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [editing, setEditing] = useState<Set<string>>(new Set());
  const [busyHost, setBusyHost] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const { data: creds } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => apiGet<PortalCredential[]>("/credentials"),
  });
  const { data: searches } = useQuery({
    queryKey: ["searches"],
    queryFn: () => apiGet<SavedSearch[]>("/searches"),
  });

  // Each "company" search becomes a login row (first careers URL → host).
  const companies: CompanyLogin[] = (searches ?? [])
    .filter((s) => s.platform === "company")
    .map((s) => {
      const f = (s.filters || {}) as Record<string, unknown>;
      const urls = Array.isArray(f.careers_urls) ? (f.careers_urls as string[]) : [];
      const url = urls[0] || "";
      return { name: s.name, url, host: hostFromUrl(url) };
    })
    .filter((c) => c.host);

  const savedByHost = new Map((creds ?? []).map((c) => [c.host, c]));
  const draftFor = (host: string) => drafts[host] ?? EMPTY_DRAFT;
  const setDraft = (host: string, patch: Partial<Draft>) =>
    setDrafts((d) => ({ ...d, [host]: { ...draftFor(host), ...patch } }));

  const flash = (m: string) => {
    setMsg(m);
    setErr(null);
    setTimeout(() => setMsg(null), 4000);
  };

  const save = useMutation({
    mutationFn: (v: { host: string; username: string; password: string; label: string }) =>
      apiSend("/credentials", "PUT", {
        host: v.host,
        username: v.username.trim(),
        password: v.password,
        label: v.label || null,
      }),
    onMutate: (v) => setBusyHost(v.host),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["credentials"] });
      setDrafts((d) => {
        const next = { ...d };
        delete next[v.host];
        return next;
      });
      setEditing((s) => {
        const next = new Set(s);
        next.delete(v.host);
        return next;
      });
      flash(`Saved login for ${v.label || v.host}.`);
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Could not save login."),
    onSettled: () => setBusyHost(null),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiSend(`/credentials/${id}`, "DELETE"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["credentials"] }),
  });

  // Per-host editor — a plain render function (NOT a nested component) so the
  // inputs keep focus across re-renders.
  const renderCred = (host: string, label: string, saved?: PortalCredential) => {
    const isEditing = editing.has(host) || !saved;
    const d = draftFor(host);
    const busy = busyHost === host && save.isPending;

    if (saved && !isEditing) {
      return (
        <div className="flex items-center gap-3">
          <span className="rounded bg-green-500/10 px-2 py-0.5 text-xs text-green-400">
            ✓ {saved.username}
          </span>
          <button
            onClick={() => {
              setDraft(host, { username: saved.username, password: "" });
              setEditing((s) => new Set(s).add(host));
            }}
            className="text-xs text-indigo-300 hover:text-indigo-200"
          >
            Edit
          </button>
          <button
            onClick={() => remove.mutate(saved.id)}
            disabled={remove.isPending}
            className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      );
    }

    return (
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={d.username}
          onChange={(e) => setDraft(host, { username: e.target.value })}
          placeholder="username / email"
          autoComplete="off"
          className="w-44 rounded-lg border border-slate-700 px-2.5 py-1.5 text-sm"
        />
        <input
          type="password"
          value={d.password}
          onChange={(e) => setDraft(host, { password: e.target.value })}
          placeholder={saved ? "new password" : "password"}
          autoComplete="new-password"
          className="w-40 rounded-lg border border-slate-700 px-2.5 py-1.5 text-sm"
        />
        <button
          onClick={() =>
            save.mutate({ host, username: d.username, password: d.password, label })
          }
          disabled={busy || !d.username.trim() || !d.password}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save"}
        </button>
        {saved && (
          <button
            onClick={() =>
              setEditing((s) => {
                const next = new Set(s);
                next.delete(host);
                return next;
              })
            }
            className="text-xs text-slate-400 hover:text-slate-300"
          >
            Cancel
          </button>
        )}
      </div>
    );
  };

  const companyHosts = new Set(companies.map((c) => c.host));
  const otherSaved = (creds ?? []).filter((c) => !companyHosts.has(c.host));

  return (
    <div className="mt-4 max-w-3xl space-y-5 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div>
        <h2 className="text-sm font-semibold">Employer portal logins</h2>
        <p className="mt-1 text-xs text-slate-400">
          One row per company from your{" "}
          <a href="/searches" className="text-indigo-300 hover:text-indigo-200">
            Searches
          </a>
          . Click a company to open its careers site and{" "}
          <span className="text-slate-300">create your own account</span>, then enter
          that username &amp; password here. The pre-fill worker uses it to sign in and{" "}
          <span className="text-slate-300">save a draft</span> — it never submits and
          never creates accounts. Many portals need no login; those just fill directly.
          Passwords are encrypted at rest and never shown again.
        </p>
      </div>

      {companies.length > 0 ? (
        <ul className="divide-y divide-slate-800 rounded-lg border border-slate-800">
          {companies.map((c) => (
            <li
              key={c.host + c.name}
              className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <a
                  href={c.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-indigo-300 underline decoration-dotted underline-offset-2 hover:text-indigo-200"
                >
                  {c.name} ↗
                </a>
                <p className="truncate text-xs text-slate-500">{c.host}</p>
              </div>
              {renderCred(c.host, c.name, savedByHost.get(c.host))}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-400">
          No companies yet — add some under{" "}
          <a href="/searches" className="text-indigo-300 hover:text-indigo-200">
            Searches
          </a>{" "}
          and they&apos;ll appear here for credentials.
        </p>
      )}

      {otherSaved.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Other saved logins
          </h3>
          <ul className="divide-y divide-slate-800 rounded-lg border border-slate-800">
            {otherSaved.map((c) => (
              <li
                key={c.id}
                className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-200">
                    {c.label || c.host}
                  </p>
                  <p className="truncate text-xs text-slate-500">{c.host}</p>
                </div>
                {renderCred(c.host, c.label || c.host, c)}
              </li>
            ))}
          </ul>
        </div>
      )}

      <OtherPortalForm onSave={(v) => save.mutate(v)} saving={save.isPending} />

      {msg && <p className="text-sm text-indigo-300">{msg}</p>}
      {err && <p className="text-sm text-red-400">{err}</p>}
    </div>
  );
}

// Free-form add for a portal that isn't tied to a company search.
function OtherPortalForm({
  onSave,
  saving,
}: {
  onSave: (v: { host: string; username: string; password: string; label: string }) => void;
  saving: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [host, setHost] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [label, setLabel] = useState("");

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-sm text-indigo-300 hover:text-indigo-200"
      >
        + Add a portal login manually
      </button>
    );
  }

  const can = host.trim() && username.trim() && password;
  return (
    <div className="space-y-3 border-t border-slate-800 pt-4">
      <div>
        <label className="block text-sm font-medium">Portal host or job URL</label>
        <input
          value={host}
          onChange={(e) => setHost(e.target.value)}
          placeholder="careers.example.com  (or paste a full job URL)"
          className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
        />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="username / email"
          autoComplete="off"
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password"
          autoComplete="new-password"
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm"
        />
      </div>
      <input
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder="label (optional)"
        className="w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
      />
      <div className="flex items-center gap-3">
        <button
          onClick={() => {
            onSave({ host: host.trim(), username, password, label: label.trim() });
            setHost("");
            setUsername("");
            setPassword("");
            setLabel("");
            setOpen(false);
          }}
          disabled={!can || saving}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          Save login
        </button>
        <button
          onClick={() => setOpen(false)}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
