"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiGet, apiSend, ApiError } from "@/lib/api";
import type { PortalCredential } from "@/lib/types";

const HOST = "linkedin.com";

// A dedicated, friendlier entry for the LinkedIn session cookie. It writes to the
// same /credentials store (host linkedin.com) the resolver reads — pasting a
// cookie here lets the app turn a LinkedIn posting's "Apply" redirect into the
// employer's direct application link (the 🔗 button on Telegram job messages).
export function LinkedInCookieCard() {
  const qc = useQueryClient();
  const [cookie, setCookie] = useState("");
  const [howto, setHowto] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const { data: creds } = useQuery({
    queryKey: ["credentials"],
    queryFn: () => apiGet<PortalCredential[]>("/credentials"),
  });
  const saved = (creds ?? []).find((c) => c.host === HOST);

  const hasLiAt = /li_at=/.test(cookie);
  const hasJsession = /JSESSIONID=/.test(cookie);

  const save = useMutation({
    mutationFn: () =>
      apiSend("/credentials", "PUT", {
        host: HOST,
        username: "linkedin-session",
        password: cookie.trim(),
        label: "LinkedIn session",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credentials"] });
      setCookie("");
      setErr(null);
      setMsg("Saved — direct apply links can now be resolved.");
      setTimeout(() => setMsg(null), 5000);
    },
    onError: (e) =>
      setErr(e instanceof ApiError ? e.message : "Could not save the cookie."),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiSend(`/credentials/${id}`, "DELETE"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["credentials"] }),
  });

  return (
    <div className="mt-4 max-w-3xl space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div>
        <h2 className="text-sm font-semibold">LinkedIn session cookie</h2>
        <p className="mt-1 text-xs text-slate-400">
          Lets the app follow a LinkedIn posting&rsquo;s{" "}
          <span className="text-slate-300">&ldquo;Apply&rdquo; redirect</span> and
          hand you the employer&rsquo;s direct application link (the 🔗 button on
          Telegram). LinkedIn hides that link behind its login, so it needs your
          own session. We never act <em>on</em> LinkedIn itself. Stored
          encrypted; the cookie is your login — keep it private.
        </p>
      </div>

      <div className="flex items-center gap-2 text-xs">
        {saved ? (
          <>
            <span className="rounded bg-green-500/10 px-2 py-0.5 text-green-400">
              ✓ Cookie saved
            </span>
            <span className="text-slate-500">
              updated {new Date(saved.updated_at).toLocaleString()}
            </span>
            <button
              onClick={() => remove.mutate(saved.id)}
              disabled={remove.isPending}
              className="ml-1 text-red-400 hover:text-red-300 disabled:opacity-50"
            >
              Remove
            </button>
          </>
        ) : (
          <span className="rounded bg-amber-500/10 px-2 py-0.5 text-amber-400">
            No cookie yet — direct apply links can&rsquo;t be resolved
          </span>
        )}
      </div>

      <button
        onClick={() => setHowto((v) => !v)}
        className="text-xs text-indigo-300 hover:text-indigo-200"
      >
        {howto ? "Hide" : "How do I get my cookie?"}
      </button>
      {howto && (
        <ol className="list-decimal space-y-1 rounded-lg border border-slate-800 bg-slate-950 p-3 pl-7 text-xs text-slate-300">
          <li>
            Be logged into <span className="text-slate-100">linkedin.com</span> in
            your browser.
          </li>
          <li>
            <b>Safari:</b> enable Settings → Advanced → &ldquo;Show features for web
            developers&rdquo;, then Develop → Show Web Inspector (⌥⌘I).{" "}
            <b>Chrome/Edge:</b> press F12.
          </li>
          <li>
            Open the <b>Network</b> tab, reload the page, click any{" "}
            <span className="text-slate-100">linkedin.com</span> request → look at{" "}
            <b>Request Headers</b> → copy the whole <b>Cookie</b> value.
          </li>
          <li>Paste it below and Save. (It must contain both li_at and JSESSIONID.)</li>
        </ol>
      )}

      <textarea
        value={cookie}
        onChange={(e) => setCookie(e.target.value)}
        placeholder={'li_at=AQED...; JSESSIONID="ajax:1234567890"'}
        rows={3}
        className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs"
      />
      {cookie && (!hasLiAt || !hasJsession) && (
        <p className="text-xs text-amber-400">
          {!hasLiAt && "Missing li_at. "}
          {!hasJsession && "Missing JSESSIONID. "}
          Copy the full Cookie header — both are required.
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending || !hasLiAt || !hasJsession}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : saved ? "Update cookie" : "Save cookie"}
        </button>
        {msg && <span className="text-sm text-indigo-300">{msg}</span>}
        {err && <span className="text-sm text-red-400">{err}</span>}
      </div>
    </div>
  );
}
