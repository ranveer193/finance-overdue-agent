from database.db import get_connection


DDL = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL,
        file_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('queued', 'running', 'completed', 'failed')
        ),
        total_records INTEGER DEFAULT 0,
        processed_count INTEGER DEFAULT 0,
        sent_count INTEGER DEFAULT 0,
        escalated_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        invoice_no TEXT NOT NULL,
        client TEXT NOT NULL,
        contact_email_masked TEXT,
        stage_key TEXT,
        tone_used TEXT,
        days_overdue INTEGER,
        validation_status TEXT,
        send_status TEXT,
        retry_count INTEGER DEFAULT 0,
        error_message TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS failed_invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        invoice_no TEXT NOT NULL,
        invoice_state_json TEXT NOT NULL,
        error_type TEXT,
        error_message TEXT,
        retry_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 5,
        next_retry_at TEXT,
        status TEXT NOT NULL CHECK (
            status IN (
                'pending',
                'retried',
                'resolved',
                'permanent_failure'
            )
        ) DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_file_hash ON jobs(file_hash)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_failed_invoices_unique ON failed_invoices(job_id, invoice_no);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_unique ON audit_logs(job_id, invoice_no, send_status, retry_count);",
    (
        "CREATE INDEX IF NOT EXISTS idx_failed_status_retry "
        "ON failed_invoices(status, next_retry_at)"
    ),
]


def initialize_database() -> None:
    with get_connection() as conn:
        for statement in DDL:
            conn.execute(statement)
        conn.commit()