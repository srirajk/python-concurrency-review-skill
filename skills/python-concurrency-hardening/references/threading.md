# Threading in Async Python Services

## Contents

- [When threads fit](#1-decide-whether-threads-are-appropriate)
- [Worker and queue bounds](#2-bound-both-running-work-and-queued-submissions)
- [Cancellation](#3-cancellation-is-not-thread-termination)
- [Context and errors](#4-context-and-error-propagation)
- [Shared state](#5-thread-safety-and-shared-state)
- [FastAPI](#6-fastapi-specific-checks)
- [Verification](#7-thread-focused-tests-and-metrics)

Read this whenever the service uses threads, executors, synchronous SDKs, or a
free-threaded CPython build.

## 1. Decide whether threads are appropriate

Threads are valid for blocking I/O libraries that cannot be replaced safely.
They are not a defect by themselves.

Under the standard CPython 3.13 build, the GIL normally prevents threads from
speeding up CPU-bound Python bytecode. Use processes, external workers, or
native code that releases the GIL for CPU parallelism.

The free-threaded build uses regular OS threads, not Java-style virtual threads.
It was experimental in Python 3.13 and became officially supported, but still
optional and shipped as a separate build, in Python 3.14 (PEP 779). Do not assume
it is enabled: check `sys._is_gil_enabled()` (present from 3.13) and dependency
support, because an incompatible extension can re-enable the GIL. Free-threading
also makes real data races possible and increases the need for explicit
synchronization.

## 2. Bound both running work and queued submissions

- Give each blocking integration a documented concurrency budget.
- Own a dedicated `ThreadPoolExecutor(max_workers=N)` during application
  lifespan when capacity isolation matters.
- Do not rely on the default executor size as a business capacity limit.
- `ThreadPoolExecutor` has an internal submission queue; submitting an
  unbounded collection can still exhaust memory even when worker count is
  bounded. Gate submissions with validated batch sizes, admission control, or a
  bounded adapter.
- Include queue wait in the request's overall deadline and instrument it.
- Avoid nested submission where a pool worker submits to the same saturated
  pool and waits for the result; this can deadlock.

## 3. Cancellation is not thread termination

Cancelling a coroutine awaiting `asyncio.to_thread()` or executor work usually
does not stop a callable already running in an OS thread. Therefore:

- Configure a finite timeout in the blocking library itself.
- Make long-running custom callables cooperatively stop through an event or
  other library-supported mechanism.
- Keep executor worker count as the hard bound on actual running thread work.
- Do not release an application permit early and claim the underlying operation
  stopped merely because the awaiter was cancelled.
- During shutdown, stop accepting submissions, request cooperative
  cancellation, and drain/join the executor within a finite grace period.
- If a blocking operation cannot be timed out or interrupted, call out that
  shutdown and capacity risk explicitly.

`TaskGroup` structures the awaiting coroutines; it cannot forcibly terminate
their underlying threads.

## 4. Context and error propagation

- `asyncio.to_thread()` propagates the current `contextvars.Context`.
- For direct executor submission or `run_in_executor`, verify request/trace
  context propagation explicitly; use `contextvars.copy_context()` or the
  tracing library's supported adapter when necessary.
- Preserve exceptions raised by the blocking callable. Translate only known
  transport/operational failures; unexpected defects must remain visible.
- Never log secrets or entire prompts from thread exceptions.

## 5. Thread safety and shared state

- Verify from library documentation whether clients, sessions, connections,
  cursors, and model objects are safe for concurrent use.
- Do not share request-scoped database sessions/transactions across threads.
- Protect shared mutable state with `threading.Lock`, `RLock`, queues, immutable
  messages, or another documented mechanism. The GIL is not a data-consistency
  design, especially on a free-threaded build.
- Keep lock regions small and never hold a thread lock while waiting on async
  work. Do not use `asyncio.Lock` as protection against other OS threads.
- Define lock ordering when multiple locks are acquired to prevent deadlocks.
- Prefer message passing or immutable values over shared mutation.

## 6. FastAPI-specific checks

FastAPI offloads normal `def` endpoints and dependencies to its thread pool.
Review the framework's capacity limiter together with any custom executor; they
can create multiple independent blocking-work budgets.

An ordinary synchronous helper called directly from an `async def` route is not
automatically offloaded. It still blocks the event-loop thread.

For each blocking path, calculate the deployment concurrency separately from
the maximum duration of an in-flight call:

```text
maximum concurrent blocking calls
  = maximum running threads per process
    × worker processes per replica × replica count

maximum duration of one in-flight call
  = blocking library timeout, or unknown if it has none
```

Compare concurrency with downstream quotas. Account for queued work and
in-flight call duration when estimating shutdown time.

## 7. Thread-focused tests and metrics

Test the behaviors affected by the change, especially:

- peak actual running callables never exceeds the configured worker limit;
- submissions are bounded under user-controlled fan-out;
- request cancellation while a callable is running;
- library timeout and stuck-call behavior;
- context/trace propagation;
- shared-client thread safety or isolation;
- executor shutdown with work in flight;
- standard and free-threaded builds only when both are claimed supported.

Measure active workers, queued/submitted work, queue wait, execution duration,
timeouts, abandoned awaiters, cooperative cancellations, executor saturation,
and shutdown drain time.

## Sources

- Python 3.13 threads and GIL:
  <https://docs.python.org/3.13/library/threading.html>
- Python 3.13 `asyncio.to_thread`:
  <https://docs.python.org/3.13/library/asyncio-task.html#asyncio.to_thread>
- Python 3.13 executors:
  <https://docs.python.org/3.13/library/concurrent.futures.html>
- Python 3.13 free-threading:
  <https://docs.python.org/3/whatsnew/3.13.html#free-threaded-cpython>
- FastAPI async and thread-pool behavior:
  <https://fastapi.tiangolo.com/async/>
