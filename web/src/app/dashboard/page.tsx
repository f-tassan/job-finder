"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { KanbanBoard } from "@/components/KanbanBoard";
import { apiGet, apiSend } from "@/lib/api";
import type { Application } from "@/lib/types";

function AddApplication() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [url, setUrl] = useState("");

  const add = useMutation({
    mutationFn: () =>
      apiSend("/applications", "POST", {
        title,
        company: company || null,
        location: location || null,
        url: url || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["applications"] });
      setTitle("");
      setCompany("");
      setLocation("");
      setUrl("");
      setOpen(false);
    },
  });

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        + Add application
      </button>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) add.mutate();
      }}
      className="flex flex-wrap items-end gap-2 rounded-xl border border-slate-200 bg-white p-3"
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Job title *"
        required
        className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
      />
      <input
        value={company}
        onChange={(e) => setCompany(e.target.value)}
        placeholder="Company"
        className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
      />
      <input
        value={location}
        onChange={(e) => setLocation(e.target.value)}
        placeholder="Location"
        className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
      />
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="URL"
        className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
      />
      <button
        type="submit"
        disabled={add.isPending}
        className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        Add
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100"
      >
        Cancel
      </button>
    </form>
  );
}

export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["applications"],
    queryFn: () => apiGet<Application[]>("/applications"),
  });

  return (
    <AppShell>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Applications</h1>
        <AddApplication />
      </div>
      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : data && data.length > 0 ? (
        <KanbanBoard apps={data} />
      ) : (
        <p className="text-slate-400">
          No applications yet. Add one to get started.
        </p>
      )}
    </AppShell>
  );
}
