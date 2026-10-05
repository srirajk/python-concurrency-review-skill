"""Behavioral checks for the reference pattern; run with unittest discover."""

import asyncio
import unittest

from async_fanout import (
    DeadlineExceeded,
    FanoutConfig,
    FanoutService,
    UpstreamBatchFailure,
    UpstreamFailure,
)


class FanoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_process_limit_across_overlapping_requests(self) -> None:
        service = FanoutService(FanoutConfig(max_outbound_per_process=2))
        active = 0
        peak = 0

        async def call() -> int:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                return 1
            finally:
                active -= 1

        await asyncio.gather(
            *(service.run({str(i): call for i in range(3)}) for _ in range(4))
        )
        self.assertEqual(peak, 2)
        self.assertEqual(active, 0)

    async def test_failing_child_cancels_and_awaits_sibling(self) -> None:
        service = FanoutService(FanoutConfig())
        sibling_started = asyncio.Event()
        sibling_cleaned_up = asyncio.Event()

        async def sibling() -> str:
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cleaned_up.set()

        async def fail() -> str:
            await sibling_started.wait()
            raise UpstreamFailure("known transport failure")

        with self.assertRaises(UpstreamBatchFailure):
            await service.run({"slow": sibling, "failed": fail})
        self.assertTrue(sibling_cleaned_up.is_set())

    async def test_deadline_includes_capacity_wait_and_releases_permit(self) -> None:
        service = FanoutService(
            FanoutConfig(max_outbound_per_process=1, request_deadline_seconds=0.05)
        )
        occupied = asyncio.Event()

        async def never_finishes() -> str:
            occupied.set()
            await asyncio.Event().wait()
            return "unreachable"

        first = asyncio.create_task(service.run({"first": never_finishes}))
        await occupied.wait()
        with self.assertRaises(DeadlineExceeded):
            await service.run({"waiting": never_finishes})
        with self.assertRaises(DeadlineExceeded):
            await first

        async def healthy() -> str:
            return "ok"

        self.assertEqual(await service.run({"next": healthy}), {"next": "ok"})

    async def test_programming_error_is_not_mapped_to_upstream_failure(self) -> None:
        service = FanoutService(FanoutConfig())

        async def bug() -> str:
            raise TypeError("programming defect")

        with self.assertRaises(ExceptionGroup) as caught:
            await service.run({"bug": bug})
        self.assertTrue(any(isinstance(e, TypeError) for e in caught.exception.exceptions))

    async def test_caller_cancellation_releases_capacity(self) -> None:
        service = FanoutService(FanoutConfig(max_outbound_per_process=1))
        started = asyncio.Event()
        cleaned_up = asyncio.Event()

        async def waiting_call() -> str:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned_up.set()

        request = asyncio.create_task(service.run({"slow": waiting_call}))
        await started.wait()
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertTrue(cleaned_up.is_set())

        async def healthy() -> str:
            return "ok"

        self.assertEqual(await service.run({"next": healthy}), {"next": "ok"})

    async def test_rejects_oversized_fanout_before_creating_tasks(self) -> None:
        service = FanoutService(FanoutConfig(max_calls_per_request=2))
        invoked = False

        async def call() -> str:
            nonlocal invoked
            invoked = True
            return "ok"

        with self.assertRaises(ValueError):
            await service.run({"a": call, "b": call, "c": call})
        self.assertFalse(invoked)


if __name__ == "__main__":
    unittest.main()
