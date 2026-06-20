"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiGet, apiSend, ApiError } from "@/lib/api";
import type { PortalCredential } from "@/lib/types";

const EMPTY = { host: "", username: "", password: "", label: "" };

export function PortalCredentialsCard() {
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const { data: creds, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => apiGet<PortalCredential[]>("/credentials"),
  });

  const upsert = useMutation({
    mutationFn: () =>
      apiSend("/credentials", "PUT", {
        host: form.host.trim(),
        username: form.username.trim(),
        password: form.password,
        label: form.label.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credentials"] });
      setForm(EMPTY);
      setErr(null);
      setMsg("Saved. The pre-fill worker will sign in and save a draft on this portal.");
      setTimeout(() => setMsg(null), 5000);
    },
    onError: (e) =>
      setErr(e instanceof ApiError ? e.message : "Could not save credential."),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiSend(`/credentials/${id}`, "DELETE"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["credentials"] }),
  });

  const canSave = form.host.trim() && form.username.trim() && form.password;

  return (
    <div className="mt-4 max-w-2xl space-y-5 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div>
        <h2 className="text-sm font-semibold">Employer portal logins</h2>
        <p className="mt-1 text-xs text-slate-400">
          For big ATS portals (Workday, SuccessFactors, Oracle/Taleo), each company
          has its <span className="text-slate-300">own</span> account. Create the
          account yourself on the company site, then store the login here. The pre-fill
          worker uses it to sign in and{" "}
          <span className="text-slate-300">save a draft</span> on your account — it
          never submits and never creates accounts. Passwords are encrypted at rest and
          never shown again.
        </p>
      </div>

      {/* existing credentials */}
      {isLoading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : creds && creds.length > 0 ? (
        <ul className="divide-y divide-slate-800 rounded-lg border border-slate-800">
          {creds.map((c) => (
            <li key={c.id} className="flex items-center justify-between px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-200">
                  {c.label || c.host}
                </p>
                <p className="truncate text-xs text-slate-400">
                  {c.host} · {c.username}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <button
                  onClick={() =>
                    setForm({
                      host: c.host,
                      username: c.username,
                      password: "",
                      label: c.label || "",
                    })
                  }
                  className="text-xs text-indigo-300 hover:text-indigo-200"
                >
                  Edit
                </button>
                <button
                  onClick={() => remove.mutate(c.id)}
                  disabled={remove.isPending}
                  className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-400">No portal logins saved yet.</p>
      )}

      {/* add / update form */}
      <div className="space-y-3 border-t border-slate-800 pt-4">
        <div>
          <label className="block text-sm font-medium">Portal host or job URL</label>
          <input
            value={form.host}
            onChange={(e) => setForm({ ...form, host: e.target.value })}
            placeholder="acme.wd1.myworkdayjobs.com  (or paste a full job URL)"
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">
            Paste the company portal address or any job link from it — we store the
            employer&apos;s host. Saving the same host again updates it.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium">Username / email</label>
            <input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium">Password</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              autoComplete="new-password"
              placeholder="••••••••"
              className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
            />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium">Label (optional)</label>
          <input
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
            placeholder="e.g. Aramco Workday"
            className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => upsert.mutate()}
            disabled={!canSave || upsert.isPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {upsert.isPending ? "Saving…" : "Save login"}
          </button>
          {(form.host || form.username || form.password || form.label) && (
            <button
              onClick={() => {
                setForm(EMPTY);
                setErr(null);
              }}
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
            >
              Clear
            </button>
          )}
          {msg && <span className="text-sm text-indigo-300">{msg}</span>}
          {err && <span className="text-sm text-red-400">{err}</span>}
        </div>
      </div>
    </div>
  );
}
