"""In-memory background job registry for async generation with live trace."""

import threading
import time
import uuid
from typing import Callable

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def start_job(runner: Callable[[dict | None], dict], title: str = "") -> str:
    """在后台线程执行 runner，并把可变的 job 字典传给 runner 以便实时写入 trace。

    runner 签名：runner(job: dict | None) -> dict
    """
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "title": title,
        "status": "running",
        "progress": 0,
        "stage": "排队中",
        "result": None,
        "error": None,
        "trace": [],
        "total_tokens": 0,
        "elapsed_ms": 0,
    }
    with _lock:
        _jobs[job_id] = job

    def run() -> None:
        started = time.time()
        try:
            job["stage"] = "处理中"
            job["progress"] = 5
            result = runner(job)
            job["result"] = result
            job["status"] = "done"
            job["progress"] = 100
            job["stage"] = "完成"
        except Exception as exc:
            job["status"] = "error"
            job["stage"] = "失败"
            job["error"] = str(exc)
        finally:
            job["elapsed_ms"] = int((time.time() - started) * 1000)
            if not job.get("trace"):
                job["trace"] = []
            if job["status"] == "done":
                job["trace"] = job.get("trace") or []
                if not job["trace"] or job["trace"][-1].get("type") != "done":
                    job["trace"].append({
                        "type": "done",
                        "text": "生成完成",
                        "detail": "",
                        "tokens": 0,
                    })

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None
