from database.db import get_connection


class AuditRepository:
    def save(self, job_id: int, audit_log: dict) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (
                    job_id,
                    invoice_no,
                    client,
                    contact_email_masked,
                    stage_key,
                    tone_used,
                    days_overdue,
                    validation_status,
                    send_status,
                    retry_count,
                    error_message,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, invoice_no, send_status, retry_count)
                DO NOTHING
                """,
                (
                    job_id,
                    audit_log.get("invoice_no"),
                    audit_log.get("client"),
                    audit_log.get("contact_email"),
                    audit_log.get("stage_key"),
                    audit_log.get("tone_used"),
                    audit_log.get("days_overdue"),
                    audit_log.get("validation_status"),
                    audit_log.get("send_status"),
                    audit_log.get("retry_count", 0),
                    audit_log.get("send_error", ""),
                    audit_log.get("timestamp"),
                ),
            )
            conn.commit()

    def get_by_job(self, job_id: int) -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs WHERE job_id = ? ORDER BY id",
                (job_id,),
            ).fetchall()
            return [dict(row) for row in rows]