from langgraph.graph import StateGraph, START, END
from graphs.worker_graph import agent as worker,build_failed_result
from collections import defaultdict
from database.audit_repository import AuditRepository 
from database.failed_repository import FailedInvoicesRepository
from database.jobs_repository import JobsRepository
from langsmith import traceable
import time
from core.models import *
from core.utils import *
from core.config import *

jobs_repository = JobsRepository()
audit_repository = AuditRepository()
failed_repository = FailedInvoicesRepository()

def load_csv_node(state: MasterState) -> MasterState:
    csv_path = state["csv_path"]
    records: List[Dict[str, Any]] = load_csv(csv_path)

    return {
        "raw_records": records,
        "metrics": {
            "total_records_loaded": len(records),
        },
        "status": "csv_loaded",
    }

def normalize_records(state: MasterState) -> MasterState:
    records = state["raw_records"]
    normalized_records = []

    for record in records:
        days_overdue = get_overdue_days(record["due_date"])
        stage_details = get_stage_meta(days_overdue)
        stage_meta = stage_details["stage_meta"]
        stage_key = stage_details["stage_key"]

        invoice = {
            "invoice_no": record["invoice_number"],
            "client": record["client_name"],
            "amount": float(record["amount"]),
            "due_date": record["due_date"],
            "contact_email": record["recipient_email"],
            "followup_count": 1,
        }

        normalized_records.append({
            "invoice": invoice,
            "days_overdue": days_overdue,
            "stage_key": stage_key,
            "stage_meta": stage_meta,
            "escalation_required": stage_meta["escalation_required"],
            "retry_count": 0,
            "max_retries": 3,
        })

    return {"normalized_records": normalized_records}

def group_by_stage (state : MasterState) -> MasterState:

    records = state["normalized_records"]

    grouped_records = defaultdict(list)

    for record in records:
        grouped_records[record["stage_key"]].append(record)

    return {"grouped_records": dict(grouped_records)}

def create_batches (state : MasterState) -> MasterState:
    batch_size = state.get("batch_size", 10)
    grouped_records = state["grouped_records"]
    batches = []
    
    for stage in grouped_records:
        batch_number = 1
        records = grouped_records[stage]
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            batches.append({
                "batch_id": f"{stage}_{batch_number}",
                "stage": stage, 
                "records": batch
            })
            batch_number += 1

    return {
        "batches": batches,
        "raw_records": [],
        "normalized_records": [],
        "grouped_records": {}
    }

def process_batch(
    job_id: int,
    batch_id: str,
    stage: str,
    records: list,
) -> list[dict]:
    """
    Process all invoices in a single batch.

    LangSmith trace hierarchy:
        Master Workflow
        └── Batch 4th Follow-Up_1
            ├── Invoice INV-2026-001
            ├── Invoice INV-2026-002
            └── ...
    """
    # Create a dynamic batch-level trace with a human-readable name
    @traceable(name=f"Batch {batch_id}")
    def _process() -> list[dict]:
        worker_results = []

        for invoice_state in records:
            invoice_no = invoice_state["invoice"]["invoice_no"]

            config = {
                "run_name": f"Invoice {invoice_no}",
                "tags": [
                    "worker",
                    f"job-{job_id}",
                    f"batch-{batch_id}",
                    f"stage-{stage}",
                ],
                "metadata": {
                    "job_id": job_id,
                    "batch_id": batch_id,
                    "stage": stage,
                    "invoice_no": invoice_no,
                },
                "configurable": {
                    "thread_id": f"invoice-{invoice_no}",
                },
            }

            result = None

            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    result = worker.invoke(
                        invoice_state,
                        config=config,
                    )
                    break

                except Exception as e:
                    if not is_retryable_error(e):
                        result = build_failed_result(
                            invoice_state,
                            str(e),
                        )
                        break

                    if attempt == MAX_RETRY_ATTEMPTS - 1:
                        result = build_failed_result(
                            invoice_state,
                            (
                                f"Maximum retry attempts "
                                f"({MAX_RETRY_ATTEMPTS}) exceeded."
                            ),
                        )
                        break

                    wait_time = (
                        INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                    )

                    print(
                        f"[RETRY] {invoice_no} "
                        f"attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS} "
                        f"after {wait_time}s"
                    )

                    time.sleep(wait_time)

            if result is None:
                result = build_failed_result(
                    invoice_state,
                    "Unknown processing error.",
                )

            worker_results.append({
                "batch_id": batch_id,
                "stage": stage,
                "result": result,
            })

            # Persist audit trail
            audit_log = result.get("audit_log")
            if audit_log:
                audit_repository.save(
                    job_id=job_id,
                    audit_log=audit_log,
                )

            # Persist failed invoices for future retries
            if result.get("send_status") == "failed":
                failed_repository.save(
                    job_id=job_id,
                    invoice_state=result,
                    error_message=result.get(
                        "send_error",
                        "Unknown error",
                    ),
                )

            # Throttle requests to reduce rate limiting
            time.sleep(DELAY_BETWEEN_INVOICES)

        return worker_results

    return _process()

def dispatch_batches(state: MasterState) -> MasterState:
    job_id = state["job_id"]
    worker_results = []

    for batch in state["batches"]:
        batch_id = batch["batch_id"]
        stage = batch["stage"]

        # Creates a dedicated LangSmith trace:
        #   Batch 4th Follow-Up_1
        # and nested invoice traces:
        #   Invoice INV-2026-001
        #   Invoice INV-2026-002
        batch_results = process_batch(
            job_id=job_id,
            batch_id=batch_id,
            stage=stage,
            records=batch["records"],
        )

        worker_results.extend(batch_results)

    return {
        "worker_results": worker_results,
        "status": "workers_completed",
    }

def monitor_node(state: MasterState) -> MasterState:
    job_id = state["job_id"]
    worker_results = state.get("worker_results", [])
    metrics = state.get("metrics", {}).copy()

    processed = len(worker_results)
    sent = 0
    escalated = 0
    failed = 0
    not_sent = 0
    total_retries = 0

    for item in worker_results:
        result = item["result"]

        send_status = result.get("send_status")
        escalation_required = result.get(
            "escalation_required",
            False,
        )

        if send_status == "sent":
            sent += 1
        elif send_status == "failed":
            failed += 1
        elif send_status == "not_sent":
            not_sent += 1

            if escalation_required:
                escalated += 1

        total_retries += result.get("retry_count", 0)

    successful = processed - failed

    metrics.update({
        "processed_count": processed,
        "sent_count": sent,
        "escalated_count": escalated,
        "failed_count": failed,
        "not_sent_count": not_sent,
        "successful_count": successful,
        "total_retries": total_retries,
        "success_rate": round(
            (successful / processed) * 100,
            2,
        ) if processed else 0.0,
        "failure_rate": round(
            (failed / processed) * 100,
            2,
        ) if processed else 0.0,
        "escalation_rate": round(
            (escalated / processed) * 100,
            2,
        ) if processed else 0.0,
        "average_retries_per_invoice": round(
            total_retries / processed,
            2,
        ) if processed else 0.0,
    })

    jobs_repository.update_metrics(
        job_id=job_id,
        metrics=metrics,
    )

    return {
        "metrics": metrics,
        "status": "completed",
    } 

graph = StateGraph(MasterState)

graph.add_node("load_data",load_csv_node)
graph.add_node("normalize_records",normalize_records)
graph.add_node("group_by_stage",group_by_stage)
graph.add_node("create_batches",create_batches)
graph.add_node("dispatch_batches",dispatch_batches)
graph.add_node("monitor",monitor_node)

graph.add_edge(START,"load_data")
graph.add_edge("load_data","normalize_records")
graph.add_edge("normalize_records","group_by_stage")
graph.add_edge("group_by_stage","create_batches")
graph.add_edge("create_batches","dispatch_batches")
graph.add_edge("dispatch_batches","monitor")
graph.add_edge("monitor",END)

workflow = graph.compile()