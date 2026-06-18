"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

const OTHER = "Other";

/** Dropdown of common fields + "Other…" → free text (CLAUDE.md §4). */
export function FieldSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [options, setOptions] = useState<string[]>([]);
  const [custom, setCustom] = useState(false);

  useEffect(() => {
    apiGet<string[]>("/profile/field-options")
      .then(setOptions)
      .catch(() => setOptions([]));
  }, []);

  // If the stored value isn't one of the options, treat it as free text.
  useEffect(() => {
    if (value && options.length && !options.includes(value)) setCustom(true);
  }, [value, options]);

  const selectValue = custom ? OTHER : value;

  return (
    <div className="space-y-2">
      <select
        value={selectValue}
        onChange={(e) => {
          if (e.target.value === OTHER) {
            setCustom(true);
            onChange("");
          } else {
            setCustom(false);
            onChange(e.target.value);
          }
        }}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
      >
        <option value="">Select a field…</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      {custom && (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Type your field"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
      )}
    </div>
  );
}
