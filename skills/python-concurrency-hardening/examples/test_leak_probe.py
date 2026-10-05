import asyncio
import unittest

from async_fanout import FanoutConfig, FanoutService, UpstreamBatchFailure, UpstreamFailure
from leak_probe import assert_returns_to_baseline


class LeakProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_detects_unowned_background_tasks(self) -> None:
        keep_alive: list[asyncio.Task] = []  # the classic leak: nothing owns or cancels these

        async def forever() -> None:
            await asyncio.Event().wait()

        async def leaky_request() -> None:
            keep_alive.append(asyncio.create_task(forever()))

        try:
            with self.assertRaisesRegex(AssertionError, "tasks .* -> .*forever"):
                await assert_returns_to_baseline(leaky_request, rounds=30)
        finally:
            for task in keep_alive:
                task.cancel()
            await asyncio.gather(*keep_alive, return_exceptions=True)

    async def test_fanout_returns_to_baseline_on_success_failure_and_timeout(self) -> None:
        service = FanoutService(FanoutConfig(max_calls_per_request=3, request_deadline_seconds=0.05))

        async def ok() -> str:
            await asyncio.sleep(0)
            return "ok"

        async def fails() -> str:
            raise UpstreamFailure("boom")

        async def hangs() -> str:
            await asyncio.Event().wait()
            return "never"

        async def mixed_request() -> None:
            await service.run({"a": ok, "b": ok})
            for calls in ({"a": ok, "b": fails, "c": hangs}, {"a": hangs, "b": hangs}):
                try:
                    await service.run(calls)
                except Exception:  # expected failure or deadline; leaks are what we measure
                    pass

        await assert_returns_to_baseline(mixed_request, rounds=40)

        # The permits must also be back, otherwise capacity leaked silently.
        self.assertEqual(service._outbound._value, service.config.max_outbound_per_process)


if __name__ == "__main__":
    unittest.main()
