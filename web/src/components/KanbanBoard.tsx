"use client";

import { DndContext, DragEndEvent, useDroppable } from "@dnd-kit/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiSend } from "@/lib/api";
import {
  Application,
  ApplicationStatus,
  STATUS_LABELS,
  STATUSES,
} from "@/lib/types";
import { ApplicationCard } from "@/components/ApplicationCard";

function Column({
  status,
  apps,
  onDelete,
}: {
  status: ApplicationStatus;
  apps: Application[];
  onDelete: (id: string) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <div className="flex w-64 shrink-0 flex-col">
      <div className="mb-2 flex items-center justify-between px-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {STATUS_LABELS[status]}
        </span>
        <span className="text-xs text-slate-400">{apps.length}</span>
      </div>
      <div
        ref={setNodeRef}
        className={
          "flex min-h-[120px] flex-col gap-2 rounded-xl border border-dashed p-2 " +
          (isOver ? "border-slate-400 bg-slate-100" : "border-slate-200")
        }
      >
        {apps.map((a) => (
          <ApplicationCard key={a.id} app={a} onDelete={onDelete} />
        ))}
      </div>
    </div>
  );
}

export function KanbanBoard({ apps }: { apps: Application[] }) {
  const qc = useQueryClient();

  const move = useMutation({
    mutationFn: ({ id, status }: { id: string; status: ApplicationStatus }) =>
      apiSend(`/applications/${id}`, "PATCH", { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["applications"] }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiSend(`/applications/${id}`, "DELETE"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["applications"] }),
  });

  function onDragEnd(e: DragEndEvent) {
    const id = e.active.id as string;
    const target = e.over?.id as ApplicationStatus | undefined;
    if (!target) return;
    const app = apps.find((a) => a.id === id);
    if (app && app.status !== target) move.mutate({ id, status: target });
  }

  return (
    <DndContext onDragEnd={onDragEnd}>
      <div className="flex gap-4 overflow-x-auto pb-4">
        {STATUSES.map((s) => (
          <Column
            key={s}
            status={s}
            apps={apps.filter((a) => a.status === s)}
            onDelete={(id) => remove.mutate(id)}
          />
        ))}
      </div>
    </DndContext>
  );
}
