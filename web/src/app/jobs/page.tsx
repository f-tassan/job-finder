"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiSend } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { JobMatch } from "@/lib/types";

interface DiscoveryStatus {
  state: "PENDING" | "PROGRESS" | "SUCCESS" | "FAILURE" | string;
  pct: number;
  phase?: string | null;
  detail?: string | null;
  error?: string | null;
}

export default function JobsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);

  const feed = useQuery({
    queryKey: ["jobs"],
    queryFn: () => apiGet<JobMatch[]>("/jobs"),
  });

  // Poll discovery progress while a run is active; stop when it settles.
  const progress = useQuery({
    queryKey: ["discovery-status", taskId],
    queryFn: () => apiGet<DiscoveryStatus>(`/jobs/discovery-status/${taskId}`),
    enabled: !!taskId,
    refetchInterval: (q) => {
      const s = (q.state.data as DiscoveryStatus | undefined)?.state;
      return s === "SUCCESS" || s === "FAILURE" ? false : 1200;
    },
  });

  const dstate = progress.data?.state;
  useEffect(() => {
    if (dstate === "SUCCESS" || dstate === "FAILURE") {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      const t = setTimeout(() => setTaskId(null), 2500); // let the bar hit 100%
      return () => clearTimeout(t);
    }
  }, [dstate, qc]);

  const track = useMutation({
    mutationFn: (jobId: string) => apiSend(`/jobs/${jobId}/track`, "POST"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  const discover = useMutation({
    mutationFn: () =>
      apiSend<{ task_id: string; status: string }>("/jobs/discover", "POST"),
    onSuccess: (data) => {
      setTaskId(data.task_id);
      setMsg(null);
    },
    onError: (e) =>
      setMsg(e instanceof Error ? e.message : "Failed to queue discovery"),
  });

  const running = !!taskId && dstate !== "SUCCESS" && dstate !== "FAILURE";

  function pct(score: number) {
    return `${Math.round(score * 100)}%`;
  }

  return (
    <AppShell>
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Ranked jobs</h1>
        {user?.is_admin && (
          <button
            onClick={() => discover.mutate()}
            disabled={discover.isPending || running}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {running
              ? "Discovering…"
              : discover.isPending
                ? "Queuing…"
                : "Run discovery now"}
          </button>
        )}
      </div>

      {taskId && progress.data && (
        <div className="mb-4 mt-2">
          <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
            <span>
              {dstate === "SUCCESS"
                ? "Discovery complete — re-ranking done."
                : dstate === "FAILURE"
                  ? `Discovery failed: ${progress.data.error ?? "unknown error"}`
                  : `${progress.data.phase ?? "Working"}${
                      progress.data.detail ? ` · ${progress.data.detail}` : ""
                    }`}
            </span>
            <span className="tabular-nums">{progress.data.pct ?? 0}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className={
                "h-full rounded-full transition-all duration-500 " +
                (dstate === "FAILURE" ? "bg-rose-500" : "bg-indigo-500")
              }
              style={{ width: `${progress.data.pct ?? 0}%` }}
            />
          </div>
        </div>
      )}
      <p className="mb-4 text-xs text-slate-400">
        The % is <span className="font-medium text-slate-300">relevance</span> —
        how closely the job text matches your profile (fields, skills, summary).
        Higher = more similar.
      </p>
      {msg && <p className="mb-4 text-sm text-indigo-300">{msg}</p>}

      {feed.isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : feed.data && feed.data.length > 0 ? (
        <ul className="space-y-2">
          {feed.data.map((m) => (
            <li
              key={m.job.id}
              className="flex items-center justify-between gap-4 rounded-lg border border-slate-800 bg-slate-900 p-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{m.job.title}</p>
                <p className="truncate text-xs text-slate-400">
                  {[m.job.company, m.job.location].filter(Boolean).join(" · ")}
                  {m.job.source && ` · ${m.job.source}`}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span
                  className="rounded-full bg-slate-800 px-2.5 py-1 text-xs font-medium text-indigo-300"
                  title="Relevance score"
                >
                  {pct(m.relevance_score)}
                </span>
                {m.job.url && (
                  <a
                    href={m.job.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-blue-400 hover:underline"
                  >
                    Open
                  </a>
                )}
                {m.tracked ? (
                  <span className="rounded-md bg-green-900/40 px-3 py-1.5 text-xs text-green-300">
                    Tracked
                  </span>
                ) : (
                  <button
                    onClick={() => track.mutate(m.job.id)}
                    className="rounded-md border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
                  >
                    Track
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-slate-400">
          No matches yet. Add a saved search, then run discovery.
        </p>
      )}
    </AppShell>
  );
}
