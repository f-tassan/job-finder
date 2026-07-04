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
  type ApplicationDocument,
  type ApplicationStatus,
} from "@/lib/types";

function fmtDate(s: string): string {
  return new Date(s).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ApplicationDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [cvUrl, setCvUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [selectedCvId, setSelectedCvId] = useState<string | null>(null);
  const [selectedLetterId, setSelectedLetterId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["application", id],
    queryFn: () => apiGet<ApplicationDetail>(`/applications/${id}`),
  });

  // Feature flags (e.g. CV generation temporarily off).
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => apiGet<{ cv_generation_enabled: boolean }>("/config"),
  });
  const cvEnabled = config?.cv_generation_enabled ?? false;

  useEffect(() => {
    if (data) setNotes(data.notes || "");
  }, [data]);

  // Version lists, newest first. Computed from data (guarded for first render).
  const documents = data?.documents ?? [];
  const cvDocs = documents
    .filter((d) => d.kind === "cv")
    .sort((a, b) => b.version - a.version);
  const letterDocs = documents
    .filter((d) => d.kind === "cover_letter")
    .sort((a, b) => b.version - a.version);
  const selectedCv =
    cvDocs.find((d) => d.id === selectedCvId) ?? cvDocs[0] ?? null;
  const selectedLetter =
    letterDocs.find((d) => d.id === selectedLetterId) ?? letterDocs[0] ?? null;

  // Preview the selected CV version (authed PDF -> object URL).
  useEffect(() => {
    if (!selectedCv?.has_pdf) {
      setCvUrl(null);
      return;
    }
    let revoked: string | null = null;
    fetch(`${API_BASE}/applications/${id}/documents/${selectedCv.id}`, {
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
  }, [selectedCv?.id, selectedCv?.has_pdf, id]);

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend(`/applications/${id}`, "PATCH", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["application", id] });
      qc.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  // Generate a fresh version of the CV and/or cover letter (cheap model). Each
  // run APPENDS a version — saved here and sent to Telegram. Poll a few times
  // since generation takes ~20s.
  const tailor = useMutation({
    mutationFn: (which: { cv: boolean; cover_letter: boolean }) =>
      apiSend(`/applications/${id}/tailor`, "POST", which),
    onSuccess: (_r, which) => {
      const label = which.cv ? "CV" : "Cover letter";
      setMsg(`New ${label} generating — it appears here and on Telegram in ~20s.`);
      [6000, 14000, 24000].forEach((t) =>
        setTimeout(
          () => qc.invalidateQueries({ queryKey: ["application", id] }),
          t,
        ),
      );
      setTimeout(() => setMsg(null), 24000);
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : "Failed"),
  });

  async function downloadDoc(doc: ApplicationDocument) {
    const res = await fetch(
      `${API_BASE}/applications/${id}/documents/${doc.id}`,
      { headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {} },
    );
    if (!res.ok) {
      setMsg("That version's PDF isn't available.");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${doc.kind}_v${doc.version}.pdf`;
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

  // A row of selectable version chips (newest first). `latest` is chip index 0.
  function VersionChips({
    docs,
    selectedId,
    onSelect,
    showCoverage,
  }: {
    docs: ApplicationDocument[];
    selectedId: string | null | undefined;
    onSelect: (docId: string) => void;
    showCoverage?: boolean;
  }) {
    if (docs.length <= 1) return null;
    return (
      <div className="mb-3 flex flex-wrap gap-1.5">
        {docs.map((d, i) => {
          const active = d.id === selectedId;
          return (
            <button
              key={d.id}
              onClick={() => onSelect(d.id)}
              title={fmtDate(d.created_at)}
              className={
                "rounded-md border px-2 py-1 text-xs transition " +
                (active
                  ? "border-indigo-500 bg-indigo-500/15 text-indigo-200"
                  : "border-slate-700 text-slate-400 hover:border-slate-500")
              }
            >
              v{d.version}
              {i === 0 && " · latest"}
              {showCoverage && d.keyword_coverage != null && (
                <span className="ml-1 text-[10px] text-slate-500">
                  {Math.round(d.keyword_coverage * 100)}%
                </span>
              )}
            </button>
          );
        })}
      </div>
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
        {/* Tailored CV box — generate + version history + preview. */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              Tailored CV
              {cvDocs.length > 0 && (
                <span className="ml-2 text-xs font-normal text-slate-500">
                  {cvDocs.length} version{cvDocs.length > 1 ? "s" : ""}
                </span>
              )}
            </h2>
            <div className="flex items-center gap-2">
              {cvEnabled ? (
                <button
                  onClick={() => tailor.mutate({ cv: true, cover_letter: false })}
                  disabled={tailor.isPending}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  {tailor.isPending
                    ? "Queuing…"
                    : cvDocs.length > 0
                      ? "🔄 Regenerate CV"
                      : "Tailor CV"}
                </button>
              ) : (
                <span className="rounded-lg border border-amber-700/50 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
                  Temporarily disabled
                </span>
              )}
              {selectedCv?.has_pdf && (
                <button
                  onClick={() => downloadDoc(selectedCv)}
                  className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
                >
                  Download PDF
                </button>
              )}
            </div>
          </div>
          <VersionChips
            docs={cvDocs}
            selectedId={selectedCv?.id}
            onSelect={setSelectedCvId}
            showCoverage
          />
          {cvUrl ? (
            <iframe
              src={cvUrl}
              title="Tailored CV"
              className="h-[520px] w-full rounded-lg border border-slate-800 bg-white"
            />
          ) : cvEnabled ? (
            <p className="text-sm text-slate-500">
              No tailored CV yet. Generate one here (or tap 📄 Generate CV on the
              job’s Telegram message) — it’s tailored to this job from your
              answer bank, saved here, and sent to you on Telegram. Every version
              you generate is kept.
            </p>
          ) : (
            <p className="text-sm text-slate-500">
              Tailored CV generation is temporarily turned off while we improve
              its quality. Cover letters are unaffected. Any versions you already
              generated remain available above.
            </p>
          )}
        </div>

        {/* Cover letter box — generate + version history + text. */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
              Cover letter
              {letterDocs.length > 0 && (
                <span className="ml-2 text-xs font-normal text-slate-500">
                  {letterDocs.length} version{letterDocs.length > 1 ? "s" : ""}
                </span>
              )}
            </h2>
            <div className="flex items-center gap-2">
              <button
                onClick={() => tailor.mutate({ cv: false, cover_letter: true })}
                disabled={tailor.isPending}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {tailor.isPending
                  ? "Queuing…"
                  : letterDocs.length > 0
                    ? "🔄 Regenerate letter"
                    : "Tailor cover letter"}
              </button>
              {selectedLetter?.has_pdf && (
                <button
                  onClick={() => downloadDoc(selectedLetter)}
                  className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
                >
                  Download PDF
                </button>
              )}
            </div>
          </div>
          <VersionChips
            docs={letterDocs}
            selectedId={selectedLetter?.id}
            onSelect={setSelectedLetterId}
          />
          {selectedLetter?.text ? (
            <div className="max-h-[520px] overflow-y-auto pr-2">
              <pre className="whitespace-pre-wrap font-sans text-sm text-slate-200">
                {selectedLetter.text}
              </pre>
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              No cover letter yet. Generate one here (or tap ✉️ Generate Cover
              Letter on Telegram) — written for this job and company from your
              real background, never invented. Every version is kept.
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
