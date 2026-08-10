"""In-memory background job registry for async generation."""

import threading
import uuid
from typing import Callable

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def start_job(runner: Callable[[], dict], title: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "title": title,
        "status": "running",
        "progress": 0,
        "stage": "排队中",
        "result": None,
        "error": None,
    }
    with _lock:
        _jobs[job_id] = job

    def run() -> None:
        try:
            job["stage"] = "处理中"
            job["progress"] = 5
            result = runner()
            job["result"] = result
            job["status"] = "done"
            job["progress"] = 100
            job["stage"] = "完成"
        except Exception as exc:
            job["status"] = "error"
            job["stage"] = "失败"
            job["error"] = str(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None
