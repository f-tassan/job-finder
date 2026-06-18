"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { API_BASE, apiGet, apiSend, getToken, uploadCv } from "@/lib/api";
import type { CvVersion } from "@/lib/types";

export default function CvsPage() {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["cvs"],
    queryFn: () => apiGet<CvVersion[]>("/cvs"),
  });

  const upload = useMutation({
    mutationFn: () => uploadCv(file as File, label),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cvs"] });
      setFile(null);
      setLabel("");
      setError(null);
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Upload failed"),
  });

  const setDefault = useMutation({
    mutationFn: (id: string) =>
      apiSend(`/cvs/${id}`, "PATCH", { is_default: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cvs"] }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiSend(`/cvs/${id}`, "DELETE"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cvs"] }),
  });

  // The download endpoint is authed, so fetch with the Bearer token and stream
  // the blob rather than using a bare <a href> (which wouldn't send the header).
  async function download(cv: CvVersion) {
    const res = await fetch(`${API_BASE}/cvs/${cv.id}/download`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = cv.original_filename || cv.label || "cv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <AppShell>
      <h1 className="mb-4 text-xl font-semibold">CVs</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (file) upload.mutate();
        }}
        className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4"
      >
        <div>
          <label className="block text-sm font-medium">File</label>
          <input
            type="file"
            accept=".pdf,.docx,.doc,.txt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Label (optional)</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Software Engineer CV"
            className="mt-1 rounded-lg border border-slate-700 px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={!file || upload.isPending}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {upload.isPending ? "Uploading…" : "Upload"}
        </button>
      </form>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {list.isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : list.data && list.data.length > 0 ? (
        <ul className="space-y-2">
          {list.data.map((cv) => (
            <li
              key={cv.id}
              className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900 p-3"
            >
              <div>
                <p className="text-sm font-medium">
                  {cv.label}
                  {cv.is_default && (
                    <span className="ml-2 rounded bg-green-100 px-2 py-0.5 text-xs text-green-700">
                      default
                    </span>
                  )}
                  {cv.parsed && (
                    <span className="ml-2 rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700">
                      parsed
                    </span>
                  )}
                </p>
                <p className="text-xs text-slate-400">{cv.original_filename}</p>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <button
                  onClick={() => download(cv)}
                  className="rounded-md border border-slate-700 px-3 py-1.5 hover:bg-slate-800"
                >
                  Download
                </button>
                {!cv.is_default && (
                  <button
                    onClick={() => setDefault.mutate(cv.id)}
                    className="rounded-md border border-slate-700 px-3 py-1.5 hover:bg-slate-800"
                  >
                    Make default
                  </button>
                )}
                <button
                  onClick={() => remove.mutate(cv.id)}
                  className="rounded-md border border-slate-700 px-3 py-1.5 text-red-600 hover:bg-red-950"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-slate-400">No CVs uploaded yet.</p>
      )}
    </AppShell>
  );
}
