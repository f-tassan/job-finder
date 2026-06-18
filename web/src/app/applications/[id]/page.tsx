"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { API_BASE, apiGet, apiSend, getToken } from "@/lib/api";
import {
  STATUS_LABELS,
  STATUSES,
  type ApplicationDetail,
  type ApplicationStatus,
} from "@/lib/types";

export default function ApplicationDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [shotUrl, setShotUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["application", id],
    queryFn: () => apiGet<ApplicationDetail>(`/applications/${id}`),
  });

  useEffect(() => {
    if (data) {
      setNotes(data.notes || "");
      setAnswers(data.prefilled_answers || {});
    }
  }, [data]);

  // Load the prefill screenshot (authed) as an object URL for <img>.
  useEffect(() => {
    if (!data?.has_screenshot) {
      setShotUrl(null);
      return;
    }
    let revoked: string | null = null;
    fetch(`${API_BASE}/applications/${id}/screenshot`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b) {
          revoked = URL.createObjectURL(b);
          setShotUrl(revoked);
        }
      });
    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [data?.has_screenshot, id]);

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend(`/applications/${id}`, "PATCH", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["application", id] });
      qc.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  const tailor = useMutation({
    mutationFn: () => apiSend(`/applications/${id}/tailor`, "POST"),
    onSuccess: () => {
      setMsg("Tailoring queued — refresh in a few seconds.");
      setTimeout(() => setMsg(null), 6000);
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : "Failed"),
  });

  const prefill = useMutation({
    mutationFn: () => apiSend(`/applications/${id}/prefill`, "POST"),
    onSuccess: () => {
      setMsg("Pre-fill queued on the browser worker — refresh in ~15s.");
      setTimeout(() => setMsg(null), 8000);
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : "Failed"),
  });

  const saveAnswers = useMutation({
    mutationFn: () =>
      apiSend(`/applications/${id}/answers`, "PATCH", {
        prefilled_answers: answers,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["application", id] }),
  });

  const submit = useMutation({
    mutationFn: () => apiSend(`/applications/${id}/submit`, "POST"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["application", id] });
      qc.invalidateQueries({ queryKey: ["applications"] });
      setMsg("Marked as submitted.");
      setTimeout(() => setMsg(null), 5000);
    },
  });

  async function downloadCv() {
    const res = await fetch(`${API_BASE}/applications/${id}/cv`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    });
    if (!res.ok) {
      setMsg("No tailored CV yet — run Tailor first.");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "tailored_cv.pdf";
    a.click();
    URL.revokeObjectURL(url);
  }

  if (isLoading || !data) {
    return (
      <AppShell>
        <p className="text-slate-400">Loading…</p>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <Link href="/dashboard" className="text-sm text-indigo-400 hover:underline">
        ← Back to board
      </Link>

      <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h1 className="text-xl font-semibold">{data.job.title}</h1>
        <p className="text-sm text-slate-400">
          {[data.job.company, data.job.location].filter(Boolean).join(" · ")}
          {data.job.source && ` · ${data.job.source}`}
        </p>
        {data.job.url && (
          <a
            href={data.job.url}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-block text-sm text-blue-400 hover:underline"
          >
            Open posting ↗
          </a>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <label className="text-sm">
            Status:&nbsp;
            <select
              value={data.status}
              onChange={(e) =>
                patch.mutate({ status: e.target.value as ApplicationStatus })
              }
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </label>
          {data.keyword_coverage != null && (
            <span className="rounded-full bg-slate-800 px-3 py-1 text-xs text-indigo-300">
              Keyword coverage {Math.round(data.keyword_coverage * 100)}%
            </span>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          onClick={() => tailor.mutate()}
          disabled={tailor.isPending}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {tailor.isPending ? "Queuing…" : "Tailor CV + cover letter"}
        </button>
        {data.has_tailored_cv && (
          <button
            onClick={downloadCv}
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
          >
            Download tailored CV (PDF)
          </button>
        )}
        <button
          onClick={() => prefill.mutate()}
          disabled={prefill.isPending}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
        >
          {prefill.isPending ? "Queuing…" : "Pre-fill form"}
        </button>
        {data.status !== "submitted" && (
          <button
            onClick={() => submit.mutate()}
            className="rounded-lg bg-green-700 px-4 py-2 text-sm font-medium text-white hover:bg-green-600"
          >
            Mark submitted
          </button>
        )}
      </div>
      {msg && <p className="mt-3 text-sm text-indigo-300">{msg}</p>}

      {/* Review queue: pre-filled answers, gaps to complete, and the screenshot */}
      <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-400">
          Review queue
        </h2>
        <p className="mb-3 text-xs text-slate-500">
          Pre-fill reads your answer bank into the form, leaves sensitive/unknown
          fields blank, and screenshots the page. You complete the gaps and submit
          — nothing is submitted automatically.
        </p>

        {Object.keys(answers).length === 0 && data.missing_fields.length === 0 ? (
          <p className="text-sm text-slate-500">
            Not pre-filled yet. Click “Pre-fill form”.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div>
              <h3 className="mb-2 text-xs font-medium text-slate-300">
                Pre-filled answers
              </h3>
              <div className="space-y-2">
                {Object.entries(answers).map(([k, v]) => (
                  <div key={k}>
                    <label className="block text-xs text-slate-400">{k}</label>
                    <input
                      value={v}
                      onChange={(e) =>
                        setAnswers((a) => ({ ...a, [k]: e.target.value }))
                      }
                      className="w-full rounded-lg border border-slate-700 px-3 py-1.5 text-sm"
                    />
                  </div>
                ))}
                {Object.keys(answers).length > 0 && (
                  <button
                    onClick={() => saveAnswers.mutate()}
                    className="mt-1 rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
                  >
                    Save answers
                  </button>
                )}
              </div>
            </div>
            <div>
              <h3 className="mb-2 text-xs font-medium text-slate-300">
                Fields to complete ({data.missing_fields.length})
              </h3>
              {data.missing_fields.length > 0 ? (
                <ul className="list-disc space-y-1 pl-5 text-xs text-amber-300/90">
                  {data.missing_fields.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-500">None flagged.</p>
              )}
            </div>
          </div>
        )}

        {shotUrl && (
          <div className="mt-4">
            <h3 className="mb-2 text-xs font-medium text-slate-300">
              Form screenshot
            </h3>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={shotUrl}
              alt="Application form screenshot"
              className="max-h-[480px] w-auto rounded-lg border border-slate-800"
            />
          </div>
        )}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
            Cover letter
          </h2>
          {data.cover_letter ? (
            <pre className="whitespace-pre-wrap font-sans text-sm text-slate-200">
              {data.cover_letter}
            </pre>
          ) : (
            <p className="text-sm text-slate-500">
              Not generated yet. Click “Tailor” above.
            </p>
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
              Notes
            </h2>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              className="w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
            />
            <button
              onClick={() => patch.mutate({ notes })}
              className="mt-2 rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
            >
              Save notes
            </button>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
              Timeline
            </h2>
            <ul className="space-y-1 text-xs text-slate-400">
              {data.events.map((ev, i) => (
                <li key={i}>
                  <span className="text-slate-300">{ev.type}</span> ·{" "}
                  {new Date(ev.created_at).toLocaleString()}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
