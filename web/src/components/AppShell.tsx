"use client";

import { useRequireAuth } from "@/lib/auth";
import { NavBar } from "@/components/NavBar";

/** Protected page wrapper: enforces auth and renders the nav chrome. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useRequireAuth();

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <NavBar />
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
