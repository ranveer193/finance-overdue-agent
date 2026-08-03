import json
from apscheduler.schedulers.background import BackgroundScheduler
from database.failed_repository import FailedInvoicesRepository
from database.audit_repository import AuditRepository
from graphs.worker_graph import agent as worker
from core.config import (
    FAILED_INVOICE_BATCH_SIZE,
    FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES,
    FAILED_INVOICE_SCHEDULER_MISFIRE_GRACE_SECONDS,
    FAILED_INVOICE_SCHEDULER_TIMEZONE,
)

failed_repository = FailedInvoicesRepository()
audit_repository = AuditRepository()

def retry_failed_invoices() -> None:
    failed_rows = failed_repository.get_retryable(
        limit=FAILED_INVOICE_BATCH_SIZE
    )

    print("\nRetrying for failed invoices:", len(failed_rows))

    for row in failed_rows:
        failed_id = row["id"]

        # Parse stored invoice state
        try:
            invoice_state = json.loads(row["invoice_state_json"])
        except (json.JSONDecodeError, KeyError) as exc:
            print(
                f"Invalid invoice_state_json for failed_id={failed_id}: {exc}"
            )
            continue

        try:
            invoice_no = invoice_state["invoice"]["invoice_no"]

            config = {
                "run_name": f"Retry Invoice {invoice_no}",
                "tags": ["retry", "worker"],
                "metadata": {
                    "invoice_no": invoice_no,
                    "failed_id": failed_id,
                    "retry": True,
                },
                "configurable": {
                    "thread_id": f"retry-invoice-{invoice_no}-{failed_id}",
                },
            }

            # Run the worker graph
            result = worker.invoke(
                invoice_state,
                config=config,
            )

            # Save audit log for every retry attempt
            audit_log = result.get("audit_log")
            job_id = row.get("job_id")

            if audit_log and job_id:
                try:
                    audit_repository.save(
                        job_id=job_id,
                        audit_log=audit_log,
                    )
                except Exception as exc:
                    print(f"Could not save audit log: {exc}")

            # Retry succeeded
            if result.get("send_status") != "failed":
                failed_repository.mark_resolved(failed_id)
                continue

            # Retry failed again
            retry_count = row["retry_count"] + 1
            max_retries = row["max_retries"]

            failed_repository.mark_retried(
                failed_id=failed_id,
                retry_count=retry_count,
                max_retries=max_retries,
                error_message=result.get(
                    "send_error",
                    "Unknown error",
                ),
            )

        except Exception as exc:
            retry_count = row["retry_count"] + 1
            max_retries = row["max_retries"]

            failed_repository.mark_retried(
                failed_id=failed_id,
                retry_count=retry_count,
                max_retries=max_retries,
                error_message=str(exc),
            )

def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone=FAILED_INVOICE_SCHEDULER_TIMEZONE
    )

    scheduler.add_job(
        retry_failed_invoices,
        trigger="interval",
        minutes=FAILED_INVOICE_SCHEDULER_INTERVAL_MINUTES,
        id="retry_failed_invoices",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=(
            FAILED_INVOICE_SCHEDULER_MISFIRE_GRACE_SECONDS
        ),
    )

    scheduler.start()
    return scheduler