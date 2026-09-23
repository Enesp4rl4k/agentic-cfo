"""
Upload Service — pure business logic, no HTTP concerns.

Responsibilities:
  - File type validation (extension + magic bytes)
  - Size enforcement with streaming (PERF-1: never holds full file in RAM)
  - Disk persistence via async streaming write
  - AnalysisJob DB record creation

The HTTP layer (upload.py router) calls these functions and handles
FastAPI-specific concerns (UploadFile, HTTPException, Depends).
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import aiofiles
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.analysis_job import AnalysisJob, JobStatus

# ── File validation rules ─────────────────────────────────────────────────────

# extension → magic bytes (empty bytes = no magic check, e.g. CSV)
ALLOWED_EXTENSIONS: dict[str, bytes] = {
    "csv":  b"",
    "xlsx": b"PK\x03\x04",
    "xls":  b"\xd0\xcf\x11\xe0",
    "pdf":  b"%PDF",
    # e-Fatura / e-Arşiv, the document a Turkish company actually holds. No
    # fixed signature, so the check is in validate_xml_payload below.
    "xml":  b"",
}

_CHUNK_SIZE = 64 * 1024  # 64 KB read chunks


class FileValidationError(ValueError):
    """Raised when the uploaded file fails validation."""


def get_extension(filename: str) -> str:
    """Extract and lowercase the file extension. Returns '' if none."""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_extension(ext: str) -> None:
    """Raise FileValidationError if extension is not in the allowlist."""
    if ext not in ALLOWED_EXTENSIONS:
        allowed = sorted(ALLOWED_EXTENSIONS)
        raise FileValidationError(
            f"Desteklenmeyen dosya türü '.{ext}'. İzin verilenler: {allowed}"
        )


def validate_magic_bytes(ext: str, header: bytes) -> None:
    """
    Validate the file header bytes against the expected magic signature.
    CSV has no signature — skipped.

    `header` is the first chunk of the file (at least as long as the magic bytes).
    """
    expected = ALLOWED_EXTENSIONS.get(ext)
    if expected is None:
        raise FileValidationError(f"Bilinmeyen uzantı: {ext}")
    if not expected:
        return  # CSV — no magic bytes to check
    if header[: len(expected)] != expected:
        raise FileValidationError(
            "Dosya içeriği uzantısıyla eşleşmiyor. "
            "Dosya geçersiz veya bozuk olabilir."
        )


def validate_xml_payload(data: bytes) -> None:
    """An uploaded .xml must be XML, and must declare no DTD or entity.

    ElementTree expands internal entities, so a few hundred bytes can expand to
    gigabytes while parsing ("billion laughs"); a size limit does not catch it.
    """
    from app.core.xml_safety import UnsafeXMLError, guvenli_mi

    try:
        guvenli_mi(data)
    except UnsafeXMLError as exc:
        raise FileValidationError(str(exc)) from exc


# ── Persistence (PERF-1: streaming write) ─────────────────────────────────────

@dataclass
class UploadResult:
    job_id: str
    file_path: str
    ext: str
    size_bytes: int
    # The name the person gave the file. Every job used to be called
    # "document.xlsx", so a job list, the setup page and an accountant's
    # client screen all showed the same word for every upload.
    original_name: str | None = None


async def stream_to_disk(upload: UploadFile, ext: str, max_mb: int) -> UploadResult:
    """
    PERF-1: Stream the UploadFile directly to disk in 64 KB chunks.

    Avoids loading the entire file into memory. Magic bytes are validated
    on the first chunk. Size is accumulated; if the limit is exceeded the
    partial file is cleaned up and FileValidationError is raised.

    Uses aiofiles for non-blocking disk I/O.
    """
    settings = get_settings()
    max_bytes = max_mb * 1024 * 1024

    job_id = str(uuid.uuid4())
    upload_dir = os.path.join(settings.storage_local_path, "uploads", job_id)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"document.{ext}"
    file_path = os.path.join(upload_dir, safe_name)

    total_bytes = 0
    first_chunk = True
    # Stream into a side file: the final path only appears via os.replace, so
    # a crash (or a size-limit abort) can never leave a truncated upload at a
    # path the parser trusts as complete (DDIA Ch.5 — no partial writes).
    tmp_path = file_path + ".part"

    def _discard_tmp() -> None:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

    try:
        async with aiofiles.open(tmp_path, "wb") as out:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break

                # Inspect first chunk for magic bytes before writing
                if first_chunk:
                    validate_magic_bytes(ext, chunk)
                    first_chunk = False

                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise FileValidationError(
                        f"Dosya çok büyük (>{max_mb} MB). Maksimum: {max_mb} MB."
                    )

                await out.write(chunk)

        # An entity declaration can sit anywhere in the document, so the whole
        # file is checked once it is on disk — before anything parses it and
        # before the atomic publish below makes it reachable at file_path.
        if ext == "xml":
            async with aiofiles.open(tmp_path, "rb") as f:
                validate_xml_payload(await f.read())

        os.replace(tmp_path, file_path)

    except FileValidationError:
        # Clean up partial file and directory on failure
        _discard_tmp()
        try:
            os.rmdir(upload_dir)
        except OSError:
            pass
        raise
    except BaseException:
        _discard_tmp()
        raise

    return UploadResult(
        job_id=job_id,
        file_path=file_path,
        ext=ext,
        size_bytes=total_bytes,
        original_name=upload.filename,
    )


def _safe_name(name: str | None) -> str | None:
    """The file's own name, without any path, short enough for the column."""
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return base[:500] or None


async def create_analysis_job(
    result: UploadResult,
    user_id: str | None,
    org_id: str | None,
    db: AsyncSession,
    smmm_client_id: str | None = None,
) -> AnalysisJob:
    """Insert an AnalysisJob record scoped to the uploading user's org.

    `smmm_client_id` names one of an accountant's client companies when the
    uploader is working on someone else's books. Callers must have checked that
    the accountant owns that client — this does not, because it has no session
    context to check it with.
    """
    job = AnalysisJob(
        id=result.job_id,
        status=JobStatus.PENDING,
        filename=_safe_name(result.original_name) or f"document.{result.ext}",
        file_path=result.file_path,
        file_type=result.ext,
        user_id=user_id,
        org_id=org_id,
        smmm_client_id=smmm_client_id,
    )
    db.add(job)
    await db.commit()
    return job
