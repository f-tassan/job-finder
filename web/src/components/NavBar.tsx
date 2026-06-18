"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/dashboard", label: "Applications" },
  { href: "/jobs", label: "Jobs" },
  { href: "/searches", label: "Searches" },
  { href: "/profile", label: "Profile" },
  { href: "/cvs", label: "CVs" },
  { href: "/settings", label: "Settings" },
];

export function NavBar() {
  const { user, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const links = user?.is_admin
    ? [...LINKS, { href: "/admin/users", label: "Users" }]
    : LINKS;

  function handleSignOut() {
    signOut();
    router.replace("/login");
  }

  return (
    <header className="border-b border-slate-800 bg-slate-900">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
        <span className="font-semibold">job-finder</span>
        <nav className="flex gap-1 text-sm">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={
                "rounded-md px-3 py-1.5 " +
                (pathname?.startsWith(l.href)
                  ? "bg-indigo-600 text-white"
                  : "text-slate-300 hover:bg-slate-800")
              }
            >
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm text-slate-400">
          <span>{user?.display_name || user?.email}</span>
          <button
            onClick={handleSignOut}
            className="rounded-md border border-slate-700 px-3 py-1.5 hover:bg-slate-800"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
