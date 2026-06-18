"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiSend } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";

export default function AdminUsersPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["users"],
    queryFn: () => apiGet<User[]>("/users"),
    enabled: !!user?.is_admin,
  });

  const add = useMutation({
    mutationFn: () =>
      apiSend("/users", "POST", {
        email,
        password,
        display_name: displayName || null,
        is_admin: isAdmin,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setEmail("");
      setDisplayName("");
      setPassword("");
      setIsAdmin(false);
      setError(null);
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Failed"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiSend(`/users/${id}`, "DELETE"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  if (user && !user.is_admin) {
    return (
      <AppShell>
        <p className="text-slate-400">Admins only.</p>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <h1 className="mb-4 text-xl font-semibold">Users</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
        className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4"
      >
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email *"
          required
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm"
        />
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Display name"
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password (min 8) *"
          minLength={8}
          required
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm"
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isAdmin}
            onChange={(e) => setIsAdmin(e.target.checked)}
          />
          Admin
        </label>
        <button
          type="submit"
          disabled={add.isPending}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          Add user
        </button>
      </form>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {list.isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <ul className="space-y-2">
          {list.data?.map((u) => (
            <li
              key={u.id}
              className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900 p-3"
            >
              <div>
                <p className="text-sm font-medium">
                  {u.display_name || u.email}
                  {u.is_admin && (
                    <span className="ml-2 rounded bg-slate-700 px-2 py-0.5 text-xs">
                      admin
                    </span>
                  )}
                </p>
                <p className="text-xs text-slate-400">{u.email}</p>
              </div>
              {u.id !== user?.id && (
                <button
                  onClick={() => remove.mutate(u.id)}
                  className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-red-600 hover:bg-red-950"
                >
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
