# Production Verification Contract

Read this when implementing a concurrent request path or claiming that an
existing path is ready for production. A reference example is a pattern, not
proof that the target service is production-ready.

## Evidence to collect

1. Draw the request path through every I/O or CPU dependency. Record the
   request-owned tasks, process-owned clients/executors, and durable work.
2. State the failure policy (fail-fast, partial, first-success, or durable)
   and which exceptions are expected. Unknown programming errors stay visible.
3. Record the actual per-request fan-out, per-process admission and outbound
   bounds, pool or thread size, worker count, replica count, upstream quota,
   and timeout budget. Mark unknown values unknown rather than guessing.
4. Run the repository's relevant format, type, unit, and integration checks.
   Add focused tests for the changed concurrency invariant.
5. If making a throughput or readiness claim, load-test beyond the intended
   operating point with realistic upstream latency/failures. Measure peak
   active work, queue wait/depth, latency distribution, errors/rejections,
   memory, event-loop lag, and recovery after overload.

## Minimum behavioral tests by risk

| Changed behavior | Prove with a focused test |
| --- | --- |
| Fan-out or semaphore | Peak concurrent calls never exceeds the limit across overlapping requests; oversized input is rejected before scheduling. |
| TaskGroup failure policy | A known failure has the chosen response, siblings are cancelled and awaited, and an unexpected defect is not mislabeled as an upstream error. |
| Overall deadline | Time spent waiting for a semaphore/pool counts; timeout cancels async children and releases permits. |
| Blocking SDK / executor | Running **and submitted** work are bounded; caller cancellation does not falsely release capacity while a thread is still running. |
| Shared client / lifespan | One pool per worker is reused and closed on shutdown; request-scoped sessions are not shared between children. |
| Any per-request resource (tasks, permits, streams, connections) | A soak test returns tasks, threads, fds, permits, and registry size to baseline after success, failure, timeout, and cancellation paths ([leak probe](../examples/leak_probe.py)). |
| Streaming or agent run | Cancelling the call mid-run (client disconnect) cancels async work, closes the upstream stream, and returns to baseline; a hung tool hits the deadline ([agent services](agent-services.md)). |
| Retry or side effect | Attempts and elapsed time are bounded; duplicate side effects are prevented or reconciled. |
| Durable background work | Acknowledgment follows durable enqueue/state write; worker restart resumes or safely retries work. |

The [runnable fan-out example](../examples/async_fanout.py) and its
[behavioral tests](../examples/test_async_fanout.py) demonstrate the first
three rows, and [`test_leak_probe.py`](../examples/test_leak_probe.py) demonstrates
the resource row for that pattern. The
[FastAPI adapter](../examples/fastapi_adapter.py) demonstrates lifespan ownership,
HTTPX timeouts, and the 502/503/504 mapping, covered by
[`test_fastapi_adapter.py`](../examples/test_fastapi_adapter.py) against a mocked
upstream. It has not been run under real Uvicorn load.

## Output contract for a coding harness

For a review, report each evidence-backed risk with exact file/line, runtime
impact, smallest correction, and a false-positive check. Then report capacity
math, unknowns, and test gaps. If no actionable risk is found, say so.

For an implementation, report what changed, which tests actually ran and
their results, observed capacity evidence, and remaining unknowns. Never
replace a missing load test with a claim of production readiness.
