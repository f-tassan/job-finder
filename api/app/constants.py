"""Shared constants.

`FIELD_OPTIONS` powers the per-user `FieldSelect` (dropdown + "Other..." free
text). The final value is stored as free text in `answer_bank.field` (CLAUDE.md §4).
"""
from __future__ import annotations

FIELD_OPTIONS: list[str] = [
    "Software Engineering",
    "Data & AI",
    "IT & Cybersecurity",
    "Finance & Accounting",
    "Banking",
    "Project & Program Management",
    "Civil Engineering",
    "Mechanical Engineering",
    "Electrical Engineering",
    "Oil, Gas & Energy",
    "Healthcare & Medical",
    "Human Resources",
    "Sales & Business Development",
    "Marketing & Communications",
    "Supply Chain & Logistics",
    "Legal",
    "Education & Training",
    "Government & Public Sector",
    "Hospitality & Tourism",
    "Other",
]
