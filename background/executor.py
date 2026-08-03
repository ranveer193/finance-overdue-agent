from concurrent.futures import ThreadPoolExecutor
from background.run_job import run_job

executor = ThreadPoolExecutor(max_workers=2)

def submit_job(job_id: int, csv_path: str) -> None:
    executor.submit(run_job, job_id, csv_path)