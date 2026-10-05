"""Runnable Python 3.13 reference for bounded, fail-fast async fan-out.

This is a concurrency core, not a complete HTTP deployment. Construct one
FanoutService per application worker and pass async, timeout-configured calls.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


class UpstreamFailure(Exception):
    """A known operational failure already classified by a call adapter."""


class UpstreamBatchFailure(Exception):
    """At least one related upstream call failed; siblings were cancelled."""


class DeadlineExceeded(Exception):
    """The complete fan-out, including waiting for capacity, took too long."""


@dataclass(frozen=True)
class FanoutConfig:
    max_calls_per_request: int = 3
    max_outbound_per_process: int = 50
    request_deadline_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.max_calls_per_request < 1:
            raise ValueError("max_calls_per_request must be positive")
        if self.max_outbound_per_process < 1:
            raise ValueError("max_outbound_per_process must be positive")
        if not math.isfinite(self.request_deadline_seconds) or self.request_deadline_seconds <= 0:
            raise ValueError("request_deadline_seconds must be finite and positive")


class FanoutService:
    """Share this instance across requests within one event-loop worker."""

    def __init__(self, config: FanoutConfig) -> None:
        self.config = config
        self._outbound = asyncio.Semaphore(config.max_outbound_per_process)

    async def run(self, calls: Mapping[str, Callable[[], Awaitable[T]]]) -> dict[str, T]:
        if not 1 <= len(calls) <= self.config.max_calls_per_request:
            raise ValueError("fan-out size is outside the configured request limit")

        async def bounded(call: Callable[[], Awaitable[T]]) -> T:
            # The outer deadline includes time spent waiting for this permit.
            async with self._outbound:
                return await call()

        try:
            async with asyncio.timeout(self.config.request_deadline_seconds):
                try:
                    async with asyncio.TaskGroup() as group:
                        tasks = {
                            name: group.create_task(bounded(call), name=f"upstream:{name}")
                            for name, call in calls.items()
                        }
                except* UpstreamFailure as failures:
                    # Only known operational leaves are translated. If a child
                    # also raised a programming error, that leaf remains visible.
                    raise UpstreamBatchFailure("related upstream call failed") from failures
                return {name: task.result() for name, task in tasks.items()}
        except TimeoutError as exc:
            raise DeadlineExceeded("fan-out deadline exceeded") from exc
