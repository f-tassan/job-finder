"use client";

import { useDraggable } from "@dnd-kit/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { apiSend } from "@/lib/api";
import type { Application } from "@/lib/types";

export function ApplicationCard({
  app,
  onDelete,
}: {
  app: Application;
  onDelete: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [retried, setRetried] = useState(false);
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({ id: app.id });

  const retry = useMutation({
    mutationFn: () => apiSend(`/applications/${app.id}/prefill`, "POST"),
    onSuccess: () => {
      setRetried(true);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["applications"] }), 4000);
    },
  });

  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={
        "rounded-lg border border-slate-800 bg-slate-900 p-3 shadow-sm " +
        (isDragging ? "opacity-60" : "")
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div {...listeners} {...attributes} className="cursor-grab">
          <p className="text-sm font-medium leading-tight">{app.job.title}</p>
          {app.job.company && (
            <p className="text-xs text-slate-400">{app.job.company}</p>
          )}
          {app.job.location && (
            <p className="text-xs text-slate-400">{app.job.location}</p>
          )}
        </div>
        <button
          onClick={() => onDelete(app.id)}
          className="text-xs text-slate-300 hover:text-red-500"
          title="Delete"
          aria-label="Delete application"
        >
          ✕
        </button>
      </div>
      {app.needs_credentials && (
        <div className="mt-2 rounded-md border border-amber-700/50 bg-amber-500/10 p-2 text-xs">
          <p className="font-medium text-amber-300">🔐 Needs a portal login</p>
          <p className="mt-0.5 text-amber-200/80">
            Add this employer&apos;s account in{" "}
            <Link href="/settings" className="underline hover:text-amber-100">
              Settings
            </Link>
            , then retry — or open the posting and apply manually.
          </p>
          <button
            onClick={() => retry.mutate()}
            disabled={retry.isPending || retried}
            className="mt-1.5 rounded border border-amber-600 px-2 py-0.5 text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
          >
            {retried ? "Retrying…" : retry.isPending ? "Queuing…" : "Retry prefill"}
          </button>
        </div>
      )}
      <div className="mt-2 flex items-center gap-3 text-xs">
        <Link
          href={`/applications/${app.id}`}
          className="text-indigo-400 hover:underline"
        >
          Details →
        </Link>
        {app.job.url && (
          <a
            href={app.job.url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-400 hover:underline"
          >
            Posting ↗
          </a>
        )}
      </div>
    </div>
  );
}
