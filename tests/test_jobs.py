"""可取消、可超时后台任务的生命周期测试。"""

import threading
import time
import unittest

from app.services.jobs import ensure_job_active, retry_job, start_job


class JobsTestCase(unittest.TestCase):
    def test_cancel_and_retry(self):
        release = threading.Event()

        def runner(job):
            while not release.is_set():
                ensure_job_active(job)
                time.sleep(0.005)
            return {"ok": True}

        from app.services import jobs

        job_id = start_job(runner, title="测试任务", timeout_seconds=1)
        cancelled = jobs.cancel_job(job_id)
        self.assertEqual(cancelled["stage"], "正在取消…")

        for _ in range(100):
            snapshot = jobs.get_job(job_id)
            if snapshot["status"] == "cancelled":
                break
            time.sleep(0.01)
        self.assertEqual(jobs.get_job(job_id)["status"], "cancelled")

        release.set()
        retry_id = retry_job(job_id)
        self.assertIsNotNone(retry_id)
        for _ in range(100):
            retry_snapshot = jobs.get_job(retry_id)
            if retry_snapshot["status"] == "done":
                break
            time.sleep(0.01)
        self.assertEqual(jobs.get_job(retry_id)["status"], "done")
        self.assertEqual(jobs.get_job(retry_id)["attempt"], 2)


if __name__ == "__main__":
    unittest.main()
