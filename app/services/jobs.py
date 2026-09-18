"""In-memory background job registry for async generation with live trace.

Jobs are intentionally process-local for the current SQLite/FastAPI deployment, but
they still expose the lifecycle states needed by the rebuilt UI: cooperative cancel,
timeouts and retrying a failed run without losing the original trace.
"""

import threading
import time
import uuid
from typing import Callable

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class JobCancelled(RuntimeError):
    """Raised by a runner when a user cancelled the current job."""


class JobTimeout(RuntimeError):
    """Raised by a runner when its cooperative deadline has elapsed."""


def start_job(
    runner: Callable[[dict | None], dict],
    title: str = "",
    timeout_seconds: float | None = 180.0,
) -> str:
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
        "cancel_requested": False,
        "timeout_seconds": timeout_seconds,
        "started_at": None,
        "finished_at": None,
        "attempt": 1,
        "_runner": runner,
    }
    with _lock:
        _jobs[job_id] = job

    def run() -> None:
        started = time.time()
        job["started_at"] = started
        try:
            job["stage"] = "处理中"
            job["progress"] = 5
            result = runner(job)
            ensure_job_active(job)
            job["result"] = result
            job["status"] = "done"
            job["progress"] = 100
            job["stage"] = "完成"
        except JobCancelled:
            job["status"] = "cancelled"
            job["stage"] = "已取消"
            job["error"] = "任务已由用户取消"
        except JobTimeout:
            job["status"] = "timeout"
            job["stage"] = "已超时"
            job["error"] = "任务超过允许处理时间"
        except Exception as exc:
            job["status"] = "error"
            job["stage"] = "失败"
            job["error"] = str(exc)
        finally:
            job["elapsed_ms"] = int((time.time() - started) * 1000)
            job["finished_at"] = time.time()
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
        return _snapshot(_jobs.get(job_id))


def _snapshot(job: dict | None) -> dict | None:
    if not job:
        return None
    snapshot = dict(job)
    snapshot.pop("_runner", None)
    return snapshot


def ensure_job_active(job: dict | None) -> None:
    """让长任务在安全边界主动响应取消和超时。"""

    if not job:
        return
    if job.get("cancel_requested"):
        raise JobCancelled()
    timeout_seconds = job.get("timeout_seconds")
    started_at = job.get("started_at")
    if timeout_seconds and started_at and time.time() - started_at > timeout_seconds:
        raise JobTimeout()


def cancel_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if job.get("status") in {"running", "pending"}:
            job["cancel_requested"] = True
            job["stage"] = "正在取消…"
        return _snapshot(job)


def retry_job(job_id: str) -> str | None:
    """Create a fresh attempt for a failed/cancelled/timeout job."""

    with _lock:
        job = _jobs.get(job_id)
        if not job or job.get("status") not in {"error", "cancelled", "timeout"}:
            return None
        runner = job.get("_runner")
        title = str(job.get("title") or "")
        timeout_seconds = job.get("timeout_seconds")
    new_id = start_job(runner, title=title, timeout_seconds=timeout_seconds)
    with _lock:
        _jobs[new_id]["attempt"] = int(job.get("attempt") or 1) + 1
        _jobs[new_id]["retry_of"] = job_id
    return new_id
