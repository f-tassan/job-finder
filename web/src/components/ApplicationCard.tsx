"use client";

import { useDraggable } from "@dnd-kit/core";
import type { Application } from "@/lib/types";

export function ApplicationCard({
  app,
  onDelete,
}: {
  app: Application;
  onDelete: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({ id: app.id });

  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={
        "rounded-lg border border-slate-200 bg-white p-3 shadow-sm " +
        (isDragging ? "opacity-60" : "")
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div {...listeners} {...attributes} className="cursor-grab">
          <p className="text-sm font-medium leading-tight">{app.job.title}</p>
          {app.job.company && (
            <p className="text-xs text-slate-500">{app.job.company}</p>
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
      {app.job.url && (
        <a
          href={app.job.url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-xs text-blue-600 hover:underline"
        >
          Open posting →
        </a>
      )}
    </div>
  );
}
