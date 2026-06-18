"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiSend } from "@/lib/api";
import type { NotificationSettings } from "@/lib/types";

export default function SettingsPage() {
  const qc = useQueryClient();
  const [chatId, setChatId] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiGet<NotificationSettings>("/settings"),
  });

  useEffect(() => {
    if (data) {
      setChatId(data.telegram_chat_id || "");
      setEnabled(data.enabled);
    }
  }, [data]);

  const save = useMutation({
    mutationFn: () =>
      apiSend("/settings", "PUT", {
        telegram_chat_id: chatId || null,
        enabled,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      setMsg("Saved.");
      setTimeout(() => setMsg(null), 3000);
    },
  });

  const test = useMutation({
    mutationFn: () => apiSend<{ sent: boolean }>("/settings/test", "POST"),
    onSuccess: (r) =>
      setMsg(
        r.sent
          ? "Test message sent — check Telegram."
          : "Not sent — check the bot token (server) and your chat id.",
      ),
  });

  return (
    <AppShell>
      <h1 className="mb-4 text-xl font-semibold">Settings</h1>

      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <div className="max-w-2xl space-y-5 rounded-xl border border-slate-800 bg-slate-900 p-6">
          <div>
            <h2 className="text-sm font-semibold">Telegram notifications</h2>
            <p className="mt-1 text-xs text-slate-400">
              Get a push when discovery finds high matches and when tailoring /
              pre-fill / submission happen. Server bot token is{" "}
              {data?.telegram_configured ? (
                <span className="text-green-400">configured</span>
              ) : (
                <span className="text-amber-400">not set</span>
              )}
              . To get your chat id, message your bot then open{" "}
              <code className="text-slate-300">
                api.telegram.org/bot&lt;token&gt;/getUpdates
              </code>
              .
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium">Telegram chat ID</label>
            <input
              value={chatId}
              onChange={(e) => setChatId(e.target.value)}
              placeholder="e.g. 123456789"
              className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
            />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Enable notifications
          </label>

          <div className="flex items-center gap-3">
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => test.mutate()}
              disabled={test.isPending}
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
            >
              Send test
            </button>
            {msg && <span className="text-sm text-indigo-300">{msg}</span>}
          </div>
        </div>
      )}
    </AppShell>
  );
}
