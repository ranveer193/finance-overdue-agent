from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database.db import get_connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobsRepository:
    def create_job(
    self,
    file_path: str,
    file_hash: str,
    ) -> int:
        with get_connection() as conn:
            cursor = conn.execute(
            """
            INSERT INTO jobs (
                file_path,
                file_hash,
                status,
                created_at
            )
            VALUES (?, ?, 'queued', ?)
            """,
            (
                file_path,
                file_hash,
                utc_now(),
            ),
        )
            conn.commit()
            return cursor.lastrowid
        
    def update_status(
        self,
        job_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        now = utc_now()

        if status == 'running':
            sql = """
                UPDATE jobs
                SET status = ?, started_at = ?, error_message = ?
                WHERE id = ?
            """
            params = (status, now, error_message, job_id)

        elif status in ('completed', 'failed'):
            sql = """
                UPDATE jobs
                SET status = ?, completed_at = ?, error_message = ?
                WHERE id = ?
            """
            params = (status, now, error_message, job_id)

        else:
            sql = "UPDATE jobs SET status = ?, error_message = ? WHERE id = ?"
            params = (status, error_message, job_id)

        with get_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

    def update_metrics(self, job_id: int, metrics: Dict[str, Any]) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET total_records = ?,
                    processed_count = ?,
                    sent_count = ?,
                    escalated_count = ?,
                    failed_count = ?
                WHERE id = ?
                """,
                (
                    metrics.get('total_records_loaded', 0),
                    metrics.get('processed_count', 0),
                    metrics.get('sent_count', 0),
                    metrics.get('escalated_count', 0),
                    metrics.get('failed_count', 0),
                    job_id,
                ),
            )
            conn.commit()

    def get_job_by_hash(self, file_hash: str) -> dict | None:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM jobs
                WHERE file_hash = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (file_hash,),
            ).fetchone()

        return dict(row) if row else None

    def get_job(self, job_id: int) -> Optional[dict]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]