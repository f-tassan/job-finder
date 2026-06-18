"""Per-user CV upload / versioning. Files live on the volume under per-user paths
and are served back only through this authed router."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import settings
from app.db import get_session
from app.models import AppUser, CvVersion
from app.schemas import CvUpdate, CvVersionOut
from app.services.cv_parse import parse_cv

router = APIRouter(prefix="/cvs", tags=["cvs"])

_ALLOWED = {".pdf", ".docx", ".doc", ".txt"}


def _user_cv_dir(user_id: uuid.UUID) -> Path:
    return Path(settings.files_dir) / str(user_id) / "cvs"


async def _owned_cv(session: AsyncSession, user_id, cv_id) -> CvVersion:
    cv = await session.get(CvVersion, cv_id)
    if cv is None or cv.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return cv


@router.get("", response_model=list[CvVersionOut])
async def list_cvs(
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[CvVersion]:
    result = await session.execute(
        select(CvVersion)
        .where(CvVersion.user_id == user.id)
        .order_by(CvVersion.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=CvVersionOut, status_code=status.HTTP_201_CREATED)
async def upload_cv(
    file: UploadFile = File(...),
    label: str | None = Form(None),
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> CvVersion:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type {suffix!r}. Allowed: {sorted(_ALLOWED)}",
        )

    cv_id = uuid.uuid4()
    cv_dir = _user_cv_dir(user.id)
    cv_dir.mkdir(parents=True, exist_ok=True)
    dest = cv_dir / f"{cv_id}{suffix}"
    dest.write_bytes(await file.read())

    parsed = await parse_cv(str(dest), file.filename)

    # First CV becomes the default automatically.
    existing = await session.scalar(
        select(CvVersion).where(CvVersion.user_id == user.id).limit(1)
    )
    cv = CvVersion(
        id=cv_id,
        user_id=user.id,
        label=label or (file.filename or "CV"),
        original_filename=file.filename,
        file_path=str(dest),
        parsed=parsed,
        is_default=existing is None,
    )
    session.add(cv)
    await session.commit()
    await session.refresh(cv)
    return cv


@router.patch("/{cv_id}", response_model=CvVersionOut)
async def update_cv(
    cv_id: uuid.UUID,
    body: CvUpdate,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> CvVersion:
    cv = await _owned_cv(session, user.id, cv_id)
    if body.label is not None:
        cv.label = body.label
    if body.is_default:
        # Exactly one default per user.
        await session.execute(
            update(CvVersion)
            .where(CvVersion.user_id == user.id)
            .values(is_default=False)
        )
        cv.is_default = True
    await session.commit()
    await session.refresh(cv)
    return cv


@router.get("/{cv_id}/download")
async def download_cv(
    cv_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    cv = await _owned_cv(session, user.id, cv_id)
    return FileResponse(cv.file_path, filename=cv.original_filename or "cv")


@router.delete("/{cv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cv(
    cv_id: uuid.UUID,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    cv = await _owned_cv(session, user.id, cv_id)
    Path(cv.file_path).unlink(missing_ok=True)
    await session.delete(cv)
    await session.commit()
