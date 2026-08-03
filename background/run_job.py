from database.jobs_repository import JobsRepository
from graphs.master_graph import workflow


jobs_repository = JobsRepository()


def run_job(job_id: int, csv_path: str) -> None:
    jobs_repository.update_status(job_id, "running")

    try:
        final_state = workflow.invoke({
            "job_id": job_id,
            "csv_path": csv_path,
        })

        # Metrics are already persisted by monitor_node,
        # but this call guarantees the latest values are saved.
        if "metrics" in final_state:
            jobs_repository.update_metrics(
                job_id=job_id,
                metrics=final_state["metrics"],
            )

        jobs_repository.update_status(job_id, "completed")

    except Exception as e:
        jobs_repository.update_status(
            job_id=job_id,
            status="failed",
            error_message=str(e),
        )