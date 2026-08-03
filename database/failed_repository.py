import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from database.db import get_connection
from core.utils import is_retryable_error
from core.config import *


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_error(error_message: str) -> str:
    message = (error_message or "").lower()

    if (is_retryable_error(message)):
            return 'retryable'

    return 'permanent'

def compute_next_retry(retry_count: int) -> str:
    delay_minutes = min(
        FAILED_INVOICE_MAX_BACKOFF_MINUTES,
        2 ** retry_count,
    )
    next_time = datetime.now(timezone.utc) + timedelta(
        minutes=delay_minutes
    )
    return next_time.isoformat()


class FailedInvoicesRepository:
    def save(
        self,
        job_id: int,
        invoice_state: dict,
        error_message: str,
    ) -> None:
        invoice_no = invoice_state['invoice']['invoice_no'] 
        error_type = classify_error(error_message)
        retry_count = invoice_state.get('retry_count', 0)
        max_retries = invoice_state.get('max_retries', 5)

        status = 'pending'

        next_retry_at = compute_next_retry(retry_count)

        now = utc_now()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO failed_invoices (
                    job_id,
                    invoice_no,
                    invoice_state_json,
                    error_type,
                    error_message,
                    retry_count,
                    max_retries,
                    next_retry_at,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, invoice_no)
                DO UPDATE SET
                    invoice_state_json = excluded.invoice_state_json,
                    error_type = excluded.error_type,
                    error_message = excluded.error_message,
                    retry_count = excluded.retry_count,
                    max_retries = excluded.max_retries,
                    next_retry_at = excluded.next_retry_at,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    job_id,
                    invoice_no,
                    json.dumps(invoice_state, default=str),
                    error_type,
                    error_message,
                    retry_count,
                    max_retries,
                    next_retry_at,
                    status,
                    now,
                    now,
                ),
            )
            conn.commit()

    def get_retryable(self, limit: int = 100) -> list[dict]:
        now = utc_now()

        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM failed_invoices
                WHERE status = 'pending'
                  AND next_retry_at <= ?
                ORDER BY next_retry_at
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_resolved(self, failed_id: int) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE failed_invoices
                SET status = 'resolved',
                    updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), failed_id),
            )
            conn.commit()

    def mark_retried(
        self,
        failed_id: int,
        retry_count: int,
        max_retries: int,
        error_message: Optional[str] = None,
    ) -> None:
        if retry_count >= max_retries:
            status = 'permanent_failure'
            next_retry_at = None
        else:
            status = 'pending'
            next_retry_at = compute_next_retry(retry_count)

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE failed_invoices
                SET retry_count = ?,
                    next_retry_at = ?,
                    status = ?,
                    error_message = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    retry_count,
                    next_retry_at,
                    status,
                    error_message,
                    utc_now(),
                    failed_id,
                ),
            )
            conn.commit()

    def list_all(self, limit: int = 500) -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM failed_invoices
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]