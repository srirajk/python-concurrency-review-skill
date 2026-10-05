"""Soak-test helper: does a workload return the process to its baseline?

Leaks in async services are slow growth in tasks, threads, or file
descriptors after load has stopped. This helper runs a workload many times,
lets finished work settle, and fails with a task-name breakdown if anything
grew. Standard library only; adapt it to the service's own test harness.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    tasks: int
    threads: int
    fds: int | None  # None where the platform has no fd listing
    task_names: Counter


def _open_fds() -> int | None:
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    return None


def snapshot() -> Snapshot:
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    names = Counter(getattr(t.get_coro(), "__qualname__", t.get_name()) for t in pending)
    return Snapshot(len(pending), threading.active_count(), _open_fds(), names)


async def settle(rounds: int = 20) -> None:
    """Let done-callbacks, cancellations and cleanup run before measuring."""
    for _ in range(rounds):
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)


async def assert_returns_to_baseline(
    workload: Callable[[], Awaitable[object]],
    *,
    rounds: int = 200,
    concurrency: int = 20,
    fd_slack: int = 2,
) -> None:
    """Run `workload` `rounds` times, `concurrency` at a time, then compare.

    One warm-up run first, so lazily created pools and clients are part of the
    baseline instead of being reported as growth. Failing workloads are
    tolerated: error paths are where leaks hide.
    """
    await asyncio.gather(workload(), return_exceptions=True)
    await settle()
    before = snapshot()

    sem = asyncio.Semaphore(concurrency)

    async def one() -> None:
        async with sem:
            await asyncio.gather(workload(), return_exceptions=True)

    await asyncio.gather(*(one() for _ in range(rounds)))
    await settle()
    after = snapshot()

    grown = after.task_names - before.task_names
    problems = []
    if after.tasks > before.tasks:
        problems.append(f"tasks {before.tasks} -> {after.tasks}; growth by coroutine: {dict(grown)}")
    if after.threads > before.threads:
        problems.append(f"threads {before.threads} -> {after.threads}")
    if before.fds is not None and after.fds is not None and after.fds > before.fds + fd_slack:
        problems.append(f"file descriptors {before.fds} -> {after.fds}")
    if problems:
        raise AssertionError(f"not back to baseline after {rounds} runs: " + "; ".join(problems))
