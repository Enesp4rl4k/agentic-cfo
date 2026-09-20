"""Verilerimi bağla — drop files in; the system works out what they are and where they go.

POST /veri/ekle    one or more files, recognised and put in place
                   (app/services/ingest/ekle.py). A file that fits more than
                   one type is not saved; it is sent again with the person's
                   choice in `secimler`.
GET  /veri/turler  the types a person can choose from, in plain Turkish.

The person never picks a "source type", renames a column or reformats a
number. When the system cannot tell, it says so and asks; it does not guess.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import load_owned_job
from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.ingest.ekle import _MAX_DOSYA, Sahip, dosyalari_ekle, secilebilir_turler

router = APIRouter()


@router.get("/veri/turler")
async def veri_turleri(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"data": secilebilir_turler(), "error": None}


@router.post("/veri/ekle", status_code=status.HTTP_201_CREATED)
async def veri_ekle(
    files: list[UploadFile] = File(..., description="Bir ya da daha fazla dosya"),
    secimler: str | None = Form(default=None, description='{"dosya adı": "tür"} — belirsiz dosyalar için'),
    job_id: str | None = Form(default=None, description="Alan dosyalarının ekleneceği analiz; boşsa en son analiz"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if len(files) > _MAX_DOSYA:
        raise HTTPException(status_code=400, detail=f"Bir seferde en fazla {_MAX_DOSYA} dosya ekleyin.")
    try:
        secim: dict[str, str] = json.loads(secimler) if secimler else {}
        if not isinstance(secim, dict):
            raise ValueError
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="secimler bir {dosya adı: tür} nesnesi olmalı.") from exc

    # Checked before anything is saved: a job that is not the caller's is a 404
    # for the whole request, not after the first files are stored.
    istenen = await load_owned_job(db, job_id, current_user) if job_id else None

    okunan = [(f.filename or "dosya", await f.read()) for f in files]
    return {"data": await dosyalari_ekle(db, Sahip.kullanici(current_user), okunan, secim, istenen), "error": None}


