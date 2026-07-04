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
  const [cvUrl, setCvUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["application", id],
    queryFn: () => apiGet<ApplicationDetail>(`/applications/${id}`),
  });

  useEffect(() => {
    if (data) setNotes(data.notes || "");
  }, [data]);

  // Load the tailored CV PDF (authed) as an object URL for the inline preview.
  useEffect(() => {
    if (!data?.has_tailored_cv) {
      setCvUrl(null);
      return;
    }
    let revoked: string | null = null;
    fetch(`${API_BASE}/applications/${id}/cv`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (b) {
          revoked = URL.createObjectURL(b);
          setCvUrl(revoked);
        }
      });
    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [data?.has_tailored_cv, id]);

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend(`/applications/${id}`, "PATCH", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["application", id] });
      qc.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  // Generate the tailored CV and/or the cover letter (cheap model). The PDFs
  // are stored here for reference AND sent to the user's Telegram chat.
  const tailor = useMutation({
    mutationFn: (which: { cv: boolean; cover_letter: boolean }) =>
      apiSend(`/applications/${id}/tailor`, "POST", which),
    onSuccess: (_r, which) => {
      setMsg(
        `${which.cv && which.cover_letter ? "CV + cover letter" : which.cv ? "CV" : "Cover letter"} queued — the PDF lands here and on Telegram in ~20s.`,
      );
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["application", id] });
        setMsg(null);
      }, 8000);
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : "Failed"),
  });

  async function download(path: string, filename: string) {
    const res = await fetch(`${API_BASE}/applications/${id}/${path}`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    });
    if (!res.ok) {
      setMsg("Not generated yet.");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
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
            Open posting &amp; apply ↗
          </a>
        )}
        {data.job.apply_kind === "offsite" && data.job.apply_url && (
          <a
            href={data.job.apply_url}
            target="_blank"
            rel="noreferrer"
            className="ml-3 mt-1 inline-block text-sm text-blue-400 hover:underline"
          >
            Direct employer form ↗
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
          <span className="text-xs text-slate-500">
            Tip: tap “✅ I applied” on Telegram after submitting — it flips this
            to Submitted for you.
          </span>
        </div>
        {msg && <p className="mt-3 text-sm text-indigo-300">{msg}</p>}
      </div>

      {/* The extracted posting, so the job can be read without leaving the app. */}
      <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
          Job description
        </h2>
        {data.job.description ? (
          <div className="max-h-[420px] overflow-y-auto pr-2">
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-200">
              {data.job.description}
            </pre>
          </div>
        ) : (
          <p className="text-sm text-slate-500">
            No description was extracted for this posting — use “Open posting”
            above to read it at the source.
          </p>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Tailored CV box — generation lives here, per document. */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              Tailored CV
            </h2>
            <div className="flex items-center gap-2">
              <button
                onClick={() => tailor.mutate({ cv: true, cover_letter: false })}
                disabled={tailor.isPending}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {tailor.isPending
                  ? "Queuing…"
                  : data.has_tailored_cv
                    ? "Re-tailor CV"
                    : "Tailor CV"}
              </button>
              {data.has_tailored_cv && (
                <button
                  onClick={() => download("cv", "tailored_cv.pdf")}
                  className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
                >
                  Download PDF
                </button>
              )}
            </div>
          </div>
          {cvUrl ? (
            <iframe
              src={cvUrl}
              title="Tailored CV"
              className="h-[520px] w-full rounded-lg border border-slate-800 bg-white"
            />
          ) : (
            <p className="text-sm text-slate-500">
              No tailored CV yet. Generate one here (or tap 📄 CV on the job’s
              Telegram message) — it’s tailored to this job from your answer
              bank, saved here, and sent to you on Telegram.
            </p>
          )}
        </div>

        {/* Cover letter box — generation lives here too. */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              Cover letter
            </h2>
            <div className="flex items-center gap-2">
              <button
                onClick={() => tailor.mutate({ cv: false, cover_letter: true })}
                disabled={tailor.isPending}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {tailor.isPending
                  ? "Queuing…"
                  : data.cover_letter
                    ? "Regenerate letter"
                    : "Tailor cover letter"}
              </button>
              {data.has_cover_letter_pdf && (
                <button
                  onClick={() => download("cover-letter", "cover_letter.pdf")}
                  className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
                >
                  Download PDF
                </button>
              )}
            </div>
          </div>
          {data.cover_letter ? (
            <div className="max-h-[520px] overflow-y-auto pr-2">
              <pre className="whitespace-pre-wrap font-sans text-sm text-slate-200">
                {data.cover_letter}
              </pre>
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              No cover letter yet. Generate one here (or tap ✉️ Letter on
              Telegram) — written for this job and company from your real
              background, never invented.
            </p>
          )}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
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
                <span className="text-slate-300">{ev.type}</span>
                {typeof ev.payload?.via === "string" && (
                  <span className="text-slate-500"> via {ev.payload.via}</span>
                )}{" "}
                · {new Date(ev.created_at).toLocaleString()}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </AppShell>
  );
}
