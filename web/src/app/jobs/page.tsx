"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
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
  const [display, setDisplay] = useState(0); // smoothed % actually shown
  const [stalled, setStalled] = useState(false); // gave up waiting (never-hang guard)
  const startedAt = useRef(0);

  // A discovery run that never reports a terminal state shouldn't trap the UI.
  const RUN_TIMEOUT_MS = 15 * 60 * 1000;

  const feed = useQuery({
    queryKey: ["jobs"],
    queryFn: () => apiGet<JobMatch[]>("/jobs"),
  });

  // Poll discovery progress while a run is active; stop when it settles.
  const progress = useQuery({
    queryKey: ["discovery-status", taskId],
    queryFn: () => apiGet<DiscoveryStatus>(`/jobs/discovery-status/${taskId}`),
    enabled: !!taskId && !stalled,
    refetchInterval: (q) => {
      const s = (q.state.data as DiscoveryStatus | undefined)?.state;
      return s === "SUCCESS" || s === "FAILURE" ? false : 1500;
    },
  });

  const dstate = progress.data?.state;
  const serverPct = progress.data?.pct ?? 0;
  const terminal = dstate === "SUCCESS" || dstate === "FAILURE";

  // Smooth creep: ease the displayed % toward a moving ceiling just above the
  // server's last value, so the bar always drifts forward (capped at 97%) even
  // while a single slow source — e.g. paced LinkedIn fetching — sits at one pct.
  useEffect(() => {
    if (!taskId) {
      setDisplay(0);
      return;
    }
    if (terminal) {
      setDisplay(100);
      return;
    }
    setDisplay((d) => Math.max(d, serverPct)); // never go backward; snap up on jumps
    const id = setInterval(() => {
      setDisplay((d) => {
        // Inch up to ~12pts above the last server value, easing toward a 99% cap,
        // so a slow phase (LLM re-rank, big embed batch) keeps visibly moving
        // instead of parking at a fixed number until the run finishes.
        const ceil = Math.min(99, Math.max(serverPct, d) + 12);
        if (d >= ceil) return d;
        return Math.min(ceil, d + Math.max(0.25, (ceil - d) * 0.04));
      });
    }, 400);
    return () => clearInterval(id);
  }, [taskId, serverPct, terminal]);

  // Watchdog: if the run never settles (worker died, backend lost the task,
  // status fetch keeps failing) within the timeout, stop polling and re-enable
  // the button so the user is never stuck on "Discovering…" forever.
  useEffect(() => {
    if (!taskId || terminal) return;
    const id = setInterval(() => {
      if (startedAt.current && Date.now() - startedAt.current > RUN_TIMEOUT_MS) {
        setStalled(true);
      }
    }, 5000);
    return () => clearInterval(id);
  }, [taskId, terminal, RUN_TIMEOUT_MS]);

  useEffect(() => {
    if (dstate === "SUCCESS" || dstate === "FAILURE") {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      if (dstate === "FAILURE") {
        setMsg(`Discovery failed: ${progress.data?.error ?? "unknown error"}`);
      }
      const t = setTimeout(() => setTaskId(null), 2500); // let the bar hit 100%
      return () => clearTimeout(t);
    }
  }, [dstate, qc, progress.data?.error]);

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
      setDisplay(0);
      setStalled(false);
      startedAt.current = Date.now();
      setTaskId(data.task_id);
      setMsg(null);
    },
    onError: (e) =>
      setMsg(e instanceof Error ? e.message : "Failed to queue discovery"),
  });

  const running = !!taskId && !terminal && !stalled;

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

      {(taskId || stalled) && (
        <div className="mb-4 mt-2">
          <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
            <span>
              {stalled
                ? "Discovery is taking unusually long — it may still finish in the background. You can re-run."
                : dstate === "SUCCESS"
                  ? "Discovery complete — re-ranking done."
                  : dstate === "FAILURE"
                    ? `Discovery failed: ${progress.data?.error ?? "unknown error"}`
                    : !dstate || dstate === "PENDING"
                      ? "Queued — waiting for a free worker…"
                      : dstate === "STARTED"
                        ? "Starting…"
                        : `${progress.data?.phase ?? "Working"}${
                            progress.data?.detail
                              ? ` · ${progress.data.detail}`
                              : ""
                          }`}
            </span>
            <span className="tabular-nums">{Math.round(display)}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className={
                "h-full rounded-full transition-all duration-500 " +
                (dstate === "FAILURE" || stalled ? "bg-rose-500" : "bg-indigo-500")
              }
              style={{ width: `${stalled ? 100 : display}%` }}
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
                <p className="truncate text-sm font-medium">
                  {m.job.title}
                  {m.job.apply_kind === "easyapply" && (
                    <span className="ml-2 rounded bg-sky-500/15 px-1.5 py-0.5 align-middle text-[10px] font-semibold uppercase tracking-wide text-sky-300">
                      Easy Apply
                    </span>
                  )}
                </p>
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
