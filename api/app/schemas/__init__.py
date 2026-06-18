"""Pydantic DTOs (API request/response models)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import ApplicationStatus


# --- Auth ---
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Users ---
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str | None = None
    is_admin: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None
    is_admin: bool = False


# --- Profile / answer bank ---
class AnswerBankOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: str | None = None
    data: dict[str, Any] = {}
    updated_at: datetime | None = None


class AnswerBankUpdate(BaseModel):
    field: str | None = None
    data: dict[str, Any] = {}


# --- CVs ---
class CvVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    original_filename: str | None = None
    parsed: dict[str, Any] | None = None
    is_default: bool
    created_at: datetime


class CvUpdate(BaseModel):
    label: str | None = None
    is_default: bool | None = None


# --- Jobs ---
class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    title: str
    company: str | None = None
    location: str | None = None
    url: str


# --- Applications ---
class ApplicationCreate(BaseModel):
    """Manual add: creates a `manual` job row then the application."""

    title: str
    company: str | None = None
    location: str | None = None
    url: str | None = None
    status: ApplicationStatus = ApplicationStatus.discovered
    notes: str | None = None
    cv_version_id: uuid.UUID | None = None


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    notes: str | None = None
    cv_version_id: uuid.UUID | None = None


class ApplicationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    payload: dict[str, Any] = {}
    created_at: datetime


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ApplicationStatus
    notes: str | None = None
    job: JobOut
    cv_version_id: uuid.UUID | None = None
    keyword_coverage: float | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApplicationDetailOut(ApplicationOut):
    cover_letter: str | None = None
    has_tailored_cv: bool = False
    prefilled_answers: dict[str, Any] = {}
    missing_fields: list[Any] = []
    has_screenshot: bool = False
    events: list[ApplicationEventOut] = []


class AnswersUpdate(BaseModel):
    prefilled_answers: dict[str, Any]


# --- Notification settings (Phase 5) ---
class NotificationSettingsOut(BaseModel):
    telegram_chat_id: str | None = None
    enabled: bool = True
    telegram_configured: bool = False  # is the server bot token set?


class NotificationSettingsUpdate(BaseModel):
    telegram_chat_id: str | None = None
    enabled: bool = True


# --- Discovery / auto-apply prefs ---
class DiscoveryPrefsOut(BaseModel):
    ksa_only: bool = True
    auto_apply_enabled: bool = False
    auto_apply_threshold: float = 0.6


class DiscoveryPrefsUpdate(BaseModel):
    ksa_only: bool = True
    auto_apply_enabled: bool = False
    auto_apply_threshold: float = Field(0.6, ge=0.0, le=1.0)


# --- Saved searches (Phase 2) ---
class SavedSearchCreate(BaseModel):
    name: str
    platform: str  # greenhouse|lever|ashby|gov_portals|email_alerts
    query: str | None = None
    filters: dict[str, Any] = {}
    enabled: bool = True


class SavedSearchUpdate(BaseModel):
    name: str | None = None
    query: str | None = None
    filters: dict[str, Any] | None = None
    enabled: bool | None = None


class SavedSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    platform: str
    query: str | None = None
    filters: dict[str, Any] = {}
    enabled: bool
    last_run_at: datetime | None = None


# --- Ranked jobs feed (Phase 2) ---
class JobMatchOut(BaseModel):
    job: JobOut
    relevance_score: float
    tracked: bool  # whether the user already has an application for this job
