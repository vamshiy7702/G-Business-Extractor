from __future__ import annotations

import asyncio
from typing import Callable
import json

from .adapters.base import SourceAdapter
from .db import Store
from .email_enricher import EmailEnricher
from .job_runner import run_job


class JobManager:
    def __init__(self, store: Store, adapter_factory: Callable[[str], SourceAdapter],
                 enricher_factory: Callable[[int], EmailEnricher], max_concurrent: int = 1):
        self.store = store
        self.adapter_factory = adapter_factory
        self.enricher_factory = enricher_factory
        self._sem = asyncio.Semaphore(max(1, max_concurrent))
        self._tasks: dict[int, asyncio.Task] = {}
        self._stop: set[int] = set()

    def is_active(self, job_id: int) -> bool:
        task = self._tasks.get(job_id)
        return bool(task and not task.done())

    def start(self, job_id: int) -> None:
        if self.is_active(job_id):
            return
        self._stop.discard(job_id)
        task = asyncio.create_task(self._run(job_id), name=f"leadx-job-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t, j=job_id: self._tasks.pop(j, None))

    def stop(self, job_id: int) -> None:
        if self.is_active(job_id):
            self._stop.add(job_id)

    async def stop_and_wait(self, job_id: int) -> None:
        """Request a graceful stop and wait until the worker releases the job."""
        task = self._tasks.get(job_id)
        if task is None or task.done():
            self._stop.discard(job_id)
            return
        self._stop.add(job_id)
        try:
            await task
        except asyncio.CancelledError:
            # Worker cancellation is converted to a paused job in run_job().
            pass
        finally:
            self._stop.discard(job_id)

    async def _run(self, job_id: int) -> None:
        async with self._sem:
            try:
                if job_id in self._stop:
                    self.store.set_status(job_id, "paused")
                    return
                job = self.store.get_job(job_id)
                if job is None:
                    return
                threads = 4
                try:
                    threads = int(json.loads(job["options_json"] or "{}").get("threads", 4))
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
                # The adapter is created INSIDE run_job (lazily). Previously a failure here escaped this
                # task silently and the job stayed 'queued' forever with no error shown.
                await run_job(
                    self.store, job_id, lambda: self.adapter_factory(job["source"]),
                    should_stop=lambda: job_id in self._stop,
                    email_enricher=self.enricher_factory(max(1, min(10, threads))),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:                      # last line of defence: make the failure visible
                self.store.set_status(job_id, "failed", error=f"{type(exc).__name__}: {exc}")

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
