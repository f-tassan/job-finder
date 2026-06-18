"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { FieldSelect } from "@/components/FieldSelect";
import { apiGet, apiSend } from "@/lib/api";
import type { AnswerBank } from "@/lib/types";

// Saudi-national answer bank fields (CLAUDE.md §6) — National ID, no Iqama/visa.
const FIELDS: { key: string; label: string; type?: string }[] = [
  { key: "full_name_en", label: "Full name (English)" },
  { key: "full_name_ar", label: "Full name (Arabic)" },
  { key: "national_id", label: "National ID" },
  { key: "date_of_birth", label: "Date of birth", type: "date" },
  { key: "city", label: "City" },
  { key: "national_address", label: "National Address" },
  { key: "nationality", label: "Nationality" },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email" },
  { key: "linkedin", label: "LinkedIn" },
  { key: "years_of_experience", label: "Years of experience" },
  { key: "education", label: "Education" },
  { key: "certifications", label: "Certifications" },
  { key: "notice_period", label: "Notice period" },
  { key: "current_salary", label: "Current salary (optional)" },
  { key: "expected_salary", label: "Expected salary (optional)" },
];

export default function ProfilePage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["profile"],
    queryFn: () => apiGet<AnswerBank>("/profile"),
  });

  const [field, setField] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!data) return;
    setField(data.field || "");
    const v: Record<string, string> = {};
    for (const f of FIELDS) {
      const raw = (data.data as Record<string, unknown>)[f.key];
      v[f.key] = raw == null ? "" : String(raw);
    }
    if (!v.nationality) v.nationality = "Saudi";
    setValues(v);
  }, [data]);

  const save = useMutation({
    mutationFn: () => {
      const cleaned: Record<string, string> = {};
      for (const [k, val] of Object.entries(values)) {
        if (val.trim() !== "") cleaned[k] = val.trim();
      }
      return apiSend("/profile", "PUT", { field: field || null, data: cleaned });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <AppShell>
      <h1 className="mb-4 text-xl font-semibold">Profile &amp; answer bank</h1>
      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
          className="max-w-2xl space-y-5 rounded-xl border border-slate-800 bg-slate-900 p-6"
        >
          <div>
            <label className="block text-sm font-medium">Field</label>
            <p className="mb-1 text-xs text-slate-400">
              Used to seed searches and weight relevance.
            </p>
            <FieldSelect value={field} onChange={setField} />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {FIELDS.map((f) => (
              <div key={f.key}>
                <label className="block text-sm font-medium">{f.label}</label>
                <input
                  type={f.type || "text"}
                  value={values[f.key] ?? ""}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [f.key]: e.target.value }))
                  }
                  className="mt-1 w-full rounded-lg border border-slate-700 px-3 py-2 text-sm"
                />
              </div>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {saved && <span className="text-sm text-green-600">Saved</span>}
          </div>
        </form>
      )}
    </AppShell>
  );
}
