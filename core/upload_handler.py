"""
core/upload_handler.py
Handles CSV upload: deduplication by SHA-256 hash, in-progress detection,
and background job dispatch.
"""

import os
import shutil
import threading
import logging
from typing import Literal

from core.utils import compute_file_hash
from background.run_job import run_job
from database.jobs_repository import JobsRepository

logger = logging.getLogger(__name__)

# Permanent storage for uploaded CSVs (survives temp-file cleanup)
_UPLOADS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "data", "uploads"
)

_jobs_repo = JobsRepository()


UploadResult = tuple[int, bool | Literal["in_progress"]]
#   (job_id, False)            → new job started
#   (job_id, True)             → duplicate, show cached result
#   (job_id, "in_progress")    → same file is currently running


def handle_csv_upload(tmp_path: str) -> UploadResult:
    """
    1. Hash the uploaded file.
    2. Look up the hash in the jobs table.
       - running / queued  →  return (job_id, "in_progress")
       - completed         →  return (job_id, True)   [cached]
       - failed            →  create a fresh job and retry
       - not found         →  create a fresh job
    3. For new jobs: persist the file, create the DB record,
       and launch run_job() on a daemon thread.
    """
    file_hash = compute_file_hash(tmp_path)
    existing = _jobs_repo.get_job_by_hash(file_hash)

    if existing:
        status = existing.get("status", "")
        job_id = int(existing.get("id", existing.get("job_id", 0)))

        if status in ("running", "queued"):
            logger.info(
                "Duplicate upload (hash=%s) — job #%d is %s.",
                file_hash[:8], job_id, status,
            )
            return (job_id, "in_progress")

        if status == "completed":
            logger.info(
                "Duplicate upload (hash=%s) — returning cached job #%d.",
                file_hash[:8], job_id,
            )
            return (job_id, True)

        # status == "failed": fall through to create a fresh job

    # ── Persist the file to a stable location ──────────────────────────────
    os.makedirs(_UPLOADS_DIR, exist_ok=True)
    permanent_path = os.path.join(_UPLOADS_DIR, f"{file_hash}.csv")

    # Don't copy if a previous failed job already has this file on disk
    if not os.path.exists(permanent_path):
        shutil.copy2(tmp_path, permanent_path)
        logger.info("Saved upload to %s", permanent_path)

    # ── Create job record ───────────────────────────────────────────────────
    job_id = _jobs_repo.create_job(
        file_path=permanent_path,
        file_hash=file_hash,
    )
    logger.info("Created job #%d for hash %s.", job_id, file_hash[:8])

    # ── Launch background worker ────────────────────────────────────────────
    thread = threading.Thread(
        target=_run_job_safe,
        args=(job_id, permanent_path),
        name=f"job-{job_id}",
        daemon=True,
    )
    thread.start()

    return (job_id, False)


def _run_job_safe(job_id: int, csv_path: str) -> None:
    """Wrapper so thread exceptions are always logged."""
    try:
        run_job(job_id, csv_path)
    except Exception:
        logger.exception("Unhandled error in background job #%d", job_id)