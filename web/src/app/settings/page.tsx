"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiSend } from "@/lib/api";
import type { DiscoveryPrefs, NotificationSettings } from "@/lib/types";

export default function SettingsPage() {
  const qc = useQueryClient();
  const [chatId, setChatId] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [ksaOnly, setKsaOnly] = useState(true);
  const [autoApply, setAutoApply] = useState(false);
  const [autoThreshold, setAutoThreshold] = useState(60);
  const [msg, setMsg] = useState<string | null>(null);
  const [dmsg, setDmsg] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiGet<NotificationSettings>("/settings"),
  });

  const disc = useQuery({
    queryKey: ["discovery-prefs"],
    queryFn: () => apiGet<DiscoveryPrefs>("/settings/discovery"),
  });

  useEffect(() => {
    if (data) {
      setChatId(data.telegram_chat_id || "");
      setEnabled(data.enabled);
    }
  }, [data]);

  useEffect(() => {
    if (disc.data) {
      setKsaOnly(disc.data.ksa_only);
      setAutoApply(disc.data.auto_apply_enabled);
      setAutoThreshold(Math.round(disc.data.auto_apply_threshold * 100));
    }
  }, [disc.data]);

  const saveDisc = useMutation({
    mutationFn: () =>
      apiSend("/settings/discovery", "PUT", {
        ksa_only: ksaOnly,
        auto_apply_enabled: autoApply,
        auto_apply_threshold: autoThreshold / 100,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["discovery-prefs"] });
      setDmsg("Saved. Re-run discovery to apply.");
      setTimeout(() => setDmsg(null), 4000);
    },
  });

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

      {!disc.isLoading && (
        <div className="mt-4 max-w-2xl space-y-5 rounded-xl border border-slate-800 bg-slate-900 p-6">
          <div>
            <h2 className="text-sm font-semibold">Discovery &amp; auto-apply</h2>
            <p className="mt-1 text-xs text-slate-400">
              Controls how jobs are matched for you. Re-run discovery after saving.
            </p>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={ksaOnly}
              onChange={(e) => setKsaOnly(e.target.checked)}
            />
            Only show jobs in Saudi Arabia (or remote-KSA)
          </label>

          <div className="border-t border-slate-800 pt-4">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={autoApply}
                onChange={(e) => setAutoApply(e.target.checked)}
              />
              Auto-apply to strong matches
            </label>
            <p className="mt-1 text-xs text-slate-400">
              When a job scores at or above the threshold, the app automatically
              tailors the CV + cover letter and pre-fills the form, leaving it{" "}
              <span className="text-slate-300">ready to submit</span>. It does{" "}
              <span className="text-amber-300">not</span> submit for you — you do the
              final click (safety / anti-ban rule).
            </p>
            <div className="mt-3 flex items-center gap-3">
              <input
                type="range"
                min={30}
                max={95}
                step={1}
                value={autoThreshold}
                onChange={(e) => setAutoThreshold(Number(e.target.value))}
                disabled={!autoApply}
                className="w-64"
              />
              <span className="text-sm text-indigo-300">
                threshold {autoThreshold}%
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => saveDisc.mutate()}
              disabled={saveDisc.isPending}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {saveDisc.isPending ? "Saving…" : "Save"}
            </button>
            {dmsg && <span className="text-sm text-indigo-300">{dmsg}</span>}
          </div>
        </div>
      )}
    </AppShell>
  );
}
