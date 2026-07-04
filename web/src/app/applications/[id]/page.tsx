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
  const [cvUrl, setCvUrl] = useState<string | null>(null);
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

  // Load the tailored CV PDF (authed) as an object URL so it can be previewed
  // inline — lets you eyeball the exact CV that gets attached before submitting.
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

  // Standalone ATS only: fills, attaches the CV, clicks Submit, and confirms on
  // the browser worker. Disabled for LinkedIn/Bayt (you submit there yourself).
  const autoSubmit = useMutation({
    mutationFn: () => apiSend(`/applications/${id}/auto-submit`, "POST"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["application", id] });
      setMsg(
        "Finalizing on the browser worker — it re-fills (using your saved answers), attaches your CV, clicks Submit, and looks for a confirmation. Refresh in ~30s; you'll get a Telegram notification with the result.",
      );
      setTimeout(() => setMsg(null), 14000);
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : "Failed"),
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

  // Auto-submit is allowed for standalone ATS forms and for LinkedIn *redirect*
  // jobs (which resolve to a real ATS on the server). It's blocked only for
  // Bayt, missing URLs, and LinkedIn **Easy Apply** (which lives on LinkedIn and
  // must never be auto-submitted). A LinkedIn job we haven't resolved yet still
  // shows the button — the server resolves on click and routes Easy Apply to a
  // clear "submit it yourself" message.
  const jobUrl = (data.job.url || "").toLowerCase();
  const autoSubmitBlocked =
    !data.job.url ||
    jobUrl.includes("bayt.com") ||
    data.job.apply_kind === "easyapply";
  // A LinkedIn posting we haven't resolved to an external ATS yet: auto-submit is
  // still offered (the server resolves the "Apply" redirect on click), but the
  // confirmation copy needs to say so instead of naming the company's form.
  const isLinkedInUnresolved =
    jobUrl.includes("linkedin.com") && data.job.apply_kind !== "offsite";

  // Split the flagged gaps: diagnostic notes (start with ⚠) are shown read-only;
  // real field gaps become editable inputs whose values are saved into
  // prefilled_answers under the field's clean label. Auto-submit re-applies those
  // as overrides — the only way sensitive fields (salary, "why this company") and
  // other required blanks actually get filled on the form.
  const SENSITIVE_SUFFIX = " (left blank — sensitive)";
  const gapNotes = data.missing_fields.filter((m) => m.trim().startsWith("⚠"));
  const gapLabels = Array.from(
    new Set(
      data.missing_fields
        .filter((m) => !m.trim().startsWith("⚠"))
        .map((m) =>
          m.endsWith(SENSITIVE_SUFFIX)
            ? m.slice(0, -SENSITIVE_SUFFIX.length).trim()
            : m.trim(),
        )
        .filter(Boolean),
    ),
  );
  // Pre-filled answers to show in their own column — exclude gap labels so a value
  // the user typed into a gap doesn't also appear (and double-render) here.
  const visiblePrefilled = Object.entries(answers).filter(
    ([k]) => !gapLabels.includes(k),
  );

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
        {data.status !== "submitted" && !autoSubmitBlocked && (
          <button
            onClick={() => {
              if (
                confirm(
                  isLinkedInUnresolved
                    ? "This is a LinkedIn posting. The worker will follow its Apply redirect to the employer's real form (using your saved LinkedIn cookie), fill it from your saved answers, attach your CV, and submit. If it turns out to be Easy Apply, it stops and asks you to submit on LinkedIn yourself. Continue?"
                    : `This will open ${data.job.company || "the company"}'s form on the browser worker, re-fill it from your saved answers, attach your CV, click Submit, and try to confirm. Make sure you've completed the required fields below first. Continue?`,
                )
              )
                autoSubmit.mutate();
            }}
            disabled={autoSubmit.isPending}
            className="rounded-lg bg-rose-700 px-4 py-2 text-sm font-medium text-white hover:bg-rose-600 disabled:opacity-50"
            title="Standalone ATS only — fills, attaches CV, and submits on the company site"
          >
            {autoSubmit.isPending ? "Finalizing…" : "Auto-submit (finalize)"}
          </button>
        )}
        {data.status !== "submitted" && (
          <button
            onClick={() => submit.mutate()}
            className="rounded-lg bg-green-700 px-4 py-2 text-sm font-medium text-white hover:bg-green-600"
            title="Record that you submitted it yourself (LinkedIn/Bayt: you submit there)"
          >
            Mark submitted
          </button>
        )}
      </div>
      {data.job.apply_kind === "offsite" && data.job.apply_url && (
        <p className="mt-2 text-xs text-slate-400">
          LinkedIn redirect → auto-submit fills &amp; submits on the employer&rsquo;s
          site:{" "}
          <a
            href={data.job.apply_url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-400 hover:underline"
          >
            {(() => {
              try {
                return new URL(data.job.apply_url).hostname;
              } catch {
                return "company site";
              }
            })()}{" "}
            ↗
          </a>
        </p>
      )}
      {data.job.apply_kind === "easyapply" && (
        <p className="mt-2 text-xs text-amber-300/90">
          LinkedIn Easy Apply — submit it on LinkedIn yourself (we never
          auto-submit there), then hit “Mark submitted”.
        </p>
      )}
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
              {(data.ai_suggested_fields?.length ?? 0) > 0 && (
                <p className="mb-2 text-xs text-amber-300/90">
                  ⚠ Fields tagged{" "}
                  <span className="rounded bg-amber-500/20 px-1 font-medium text-amber-300">
                    Check
                  </span>{" "}
                  were guessed from your answer bank — verify them before
                  submitting.
                </p>
              )}
              <div className="space-y-2">
                {visiblePrefilled.map(([k, v]) => {
                  const needsCheck = data.ai_suggested_fields?.includes(k);
                  return (
                    <div key={k}>
                      <label className="mb-0.5 flex items-center gap-2 text-xs text-slate-400">
                        <span>{k}</span>
                        {needsCheck && (
                          <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                            Check
                          </span>
                        )}
                      </label>
                      <input
                        value={v}
                        onChange={(e) =>
                          setAnswers((a) => ({ ...a, [k]: e.target.value }))
                        }
                        className={`w-full rounded-lg border px-3 py-1.5 text-sm ${
                          needsCheck
                            ? "border-amber-600/60 bg-amber-950/20"
                            : "border-slate-700"
                        }`}
                      />
                    </div>
                  );
                })}
                {visiblePrefilled.length === 0 && (
                  <p className="text-xs text-slate-500">
                    Nothing pre-filled from your answer bank yet.
                  </p>
                )}
                {visiblePrefilled.length > 0 && (
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
                Fields to complete ({gapLabels.length})
              </h3>
              {gapLabels.length > 0 ? (
                <div className="space-y-2">
                  <p className="text-[11px] text-slate-500">
                    Fill these in — including salary and other blanks left for you.
                    Saved values are used to complete the form when you Auto-submit.
                  </p>
                  {gapLabels.map((label) => (
                    <div key={label}>
                      <label className="mb-0.5 block text-xs text-slate-400">
                        {label}
                      </label>
                      <input
                        value={answers[label] ?? ""}
                        onChange={(e) =>
                          setAnswers((a) => ({ ...a, [label]: e.target.value }))
                        }
                        className="w-full rounded-lg border border-amber-600/50 bg-amber-950/10 px-3 py-1.5 text-sm"
                      />
                    </div>
                  ))}
                  <button
                    onClick={() => saveAnswers.mutate()}
                    className="mt-1 rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
                  >
                    Save answers
                  </button>
                </div>
              ) : (
                <p className="text-xs text-slate-500">None flagged.</p>
              )}
              {gapNotes.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-300/90">
                  {gapNotes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {shotUrl && (
          <div className="mt-4">
            <div className="mb-2 flex items-center gap-3">
              <h3 className="text-xs font-medium text-slate-300">
                Form screenshot
              </h3>
              <a
                href={shotUrl}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-indigo-400 hover:underline"
              >
                Open full size in new tab ↗
              </a>
            </div>
            {/* Click the image to open the full-resolution screenshot to zoom. */}
            <a href={shotUrl} target="_blank" rel="noreferrer" title="Open full size">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={shotUrl}
                alt="Application form screenshot"
                className="max-h-[480px] w-auto cursor-zoom-in rounded-lg border border-slate-800 hover:border-indigo-500"
              />
            </a>
          </div>
        )}
      </div>

      {/* Tailored CV preview — review the exact PDF that gets attached. */}
      <div className="mt-6 rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-2 flex items-center gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Tailored CV (preview)
          </h2>
          {cvUrl && (
            <a
              href={cvUrl}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-indigo-400 hover:underline"
            >
              Open full size ↗
            </a>
          )}
        </div>
        {cvUrl ? (
          <iframe
            src={cvUrl}
            title="Tailored CV"
            className="h-[600px] w-full rounded-lg border border-slate-800 bg-white"
          />
        ) : (
          <p className="text-sm text-slate-500">
            No tailored CV yet — click “Tailor CV + cover letter” above to generate
            and preview it here before submitting.
          </p>
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
              No cover letter — either not generated yet (click “Tailor” above), or
              this application form doesn’t ask for one.
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
