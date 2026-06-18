"use client";

import { useEffect, useState } from "react";

type ApiState = "checking" | "ok" | "down";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [api, setApi] = useState<ApiState>("checking");

  // Phase 0: confirm the web app can reach the API through the proxy at /api.
  useEffect(() => {
    fetch("/api/health")
      .then((r) => setApi(r.ok ? "ok" : "down"))
      .catch(() => setApi("down"));
  }, []);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    // Auth is implemented in Phase 1.
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-semibold">job-finder</h1>
        <p className="mt-1 text-sm text-slate-500">Sign in to your account</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              placeholder="you@example.com"
              autoComplete="email"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              placeholder="••••••••"
              autoComplete="current-password"
            />
          </div>
          <button
            type="submit"
            className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Sign in
          </button>
        </form>

        <div className="mt-6 flex items-center gap-2 text-xs text-slate-500">
          <span
            className={
              "inline-block h-2 w-2 rounded-full " +
              (api === "ok"
                ? "bg-green-500"
                : api === "down"
                  ? "bg-red-500"
                  : "bg-amber-400")
            }
          />
          API:&nbsp;
          {api === "checking"
            ? "checking…"
            : api === "ok"
              ? "reachable at /api"
              : "unreachable"}
        </div>
      </div>
    </main>
  );
}
