"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

/** Pick one or many fields: dropdown of common options + custom free text.
    Selected fields render as removable chips. */
export function MultiFieldSelect({
  value,
  onChange,
}: {
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [options, setOptions] = useState<string[]>([]);
  const [custom, setCustom] = useState("");

  useEffect(() => {
    apiGet<string[]>("/profile/field-options")
      .then(setOptions)
      .catch(() => setOptions([]));
  }, []);

  function add(f: string) {
    const t = f.trim();
    if (!t || value.includes(t)) return;
    onChange([...value, t]);
  }
  function remove(f: string) {
    onChange(value.filter((x) => x !== f));
  }

  const available = options.filter((o) => o !== "Other" && !value.includes(o));

  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((f) => (
            <span
              key={f}
              className="inline-flex items-center gap-1 rounded-full bg-slate-800 px-3 py-1 text-xs"
            >
              {f}
              <button
                type="button"
                onClick={() => remove(f)}
                className="text-slate-400 hover:text-red-400"
                aria-label={`Remove ${f}`}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      <select
        value=""
        onChange={(e) => {
          if (e.target.value) add(e.target.value);
        }}
        className="w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
      >
        <option value="">Add a field…</option>
        {available.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        <input
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(custom);
              setCustom("");
            }
          }}
          placeholder="Or type a custom field"
          className="w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={() => {
            add(custom);
            setCustom("");
          }}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
        >
          Add
        </button>
      </div>
    </div>
  );
}
