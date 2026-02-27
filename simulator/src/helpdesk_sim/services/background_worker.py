from __future__ import annotations

import asyncio
import logging

from helpdesk_sim.services.poller_service import PollerService
from helpdesk_sim.services.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)


class BackgroundWorkers:
    def __init__(
        self,
        scheduler_service: SchedulerService,
        poller_service: PollerService,
        scheduler_interval_seconds: int,
        poll_interval_seconds: int,
    ) -> None:
        self.scheduler_service = scheduler_service
        self.poller_service = poller_service
        self.scheduler_interval_seconds = scheduler_interval_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._tasks: list[asyncio.Task] = []
        self._scheduler_lock = asyncio.Lock()
        self._poller_lock = asyncio.Lock()

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._scheduler_loop(), name="scheduler-loop"),
            asyncio.create_task(self._poller_loop(), name="poller-loop"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

    async def run_scheduler_once(self) -> dict[str, int]:
        async with self._scheduler_lock:
            return await asyncio.to_thread(self.scheduler_service.tick)

    async def run_poller_once(self) -> dict[str, int]:
        async with self._poller_lock:
            return await asyncio.to_thread(self.poller_service.tick)

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await self.run_scheduler_once()
            except Exception as exc:  # pragma: no cover
                logger.exception("scheduler loop error: %s", exc)
            await asyncio.sleep(self.scheduler_interval_seconds)

    async def _poller_loop(self) -> None:
        while True:
            try:
                await self.run_poller_once()
            except Exception as exc:  # pragma: no cover
                logger.exception("poller loop error: %s", exc)
            await asyncio.sleep(self.poll_interval_seconds)
