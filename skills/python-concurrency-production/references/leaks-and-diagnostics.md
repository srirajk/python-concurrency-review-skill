# Leaks and Diagnostics

## Contents

- [What a leak looks like](#1-what-a-leak-looks-like)
- [Symptom to cause](#2-symptom-to-cause)
- [Tools and snippets](#3-tools-and-snippets)
- [Soak test](#4-soak-test-the-leak-regression-test)
- [Production signals](#5-production-signals)

Read this when a service slows down, hangs, or grows over time, or when a review
must show that a concurrency design does not leak. The other references prevent
leaks by design (ownership, bounds, lifetimes). This one finds them.

## 1. What a leak looks like

A leak is something that is still held after the work that created it has
finished: a task, thread, connection, file descriptor, permit, or retained
payload. Load stops, but the count does not return to its baseline.

Leaks hide on error paths. A happy-path test passes while timeouts,
cancellations, and upstream failures each strand one task or permit. Always
exercise those paths.

## 2. Symptom to cause

| Symptom | Likely cause | Confirm with | Fix |
| --- | --- | --- | --- |
| Task count rises and stays up after load stops | Unowned `create_task`; tasks kept in a list with no removal; tasks awaiting an event nothing sets | Group `asyncio.all_tasks()` by coroutine name (`leak_probe.snapshot`) | A `TaskGroup`, or a registry that discards on completion, logs exceptions, and drains at shutdown |
| Memory rises while task count is flat | Finished tasks or results retained in a list (a task keeps its coroutine arguments and result); caches, dicts, per-key locks or semaphores never evicted; unbounded queues | `tracemalloc` snapshot diff; count objects by type with `gc.get_objects()` | Bound and evict; never retain payloads, log a summary |
| Background failures are silent | A strong reference hides "Task exception was never retrieved" until interpreter exit | Look for tasks that finished with an exception: `t.done() and t.exception()` | Attach a done-callback that logs exceptions; do not rely on the warning |
| File descriptors or connections rise | A client built per request; a response or stream not closed; an async generator abandoned instead of closed | fd count (`leak_probe`, `lsof -p`); run tests with `python -X dev -W error::ResourceWarning` | One lifespan-owned client; `async with client.stream(...)`; `contextlib.aclosing()` for generators |
| Threads or the executor queue rise | An executor per request; unbounded submission; a blocking call with no timeout holding a worker | `threading.enumerate()`; `py-spy dump --pid <pid>` | One bounded, lifecycle-owned executor; the library's own timeout |
| Latency spikes on unrelated endpoints | Blocking or CPU-heavy code on the event-loop thread | Debug mode (below) and the loop-lag probe; `py-spy dump` shows the loop thread inside the blocking call | Offload or replace the call |
| A page, slot, counter, or stream stays held after clients disconnect | The release sits in a generator's `finally`, but the generator was never started (a generator that never runs its first step never runs its `finally`, even if closed); or a counter or slot is taken before a cancellable `await` (such as waiting for a lock) and released only after it | Cancel the request before the first chunk and while waiting for the lock, then check the counter, permit, or page count returns to baseline | Release in the code that acquired it: take the resource, then enter `try/finally` immediately; take counters after the lock, or inside the same `try`; wrap the response so close always releases, not only a started generator |
| Throughput decays and never recovers | Permits not returned after cancellation or error | Idle `Semaphore._value` below its limit; a permit gauge in metrics | Acquire with `async with`; cover cancel and timeout in a test |
| `RuntimeWarning: coroutine ... was never awaited` | A call missing `await`, or a task never scheduled | Run tests with `-W error::RuntimeWarning` | Await it, or own it as a task |

## 3. Tools and snippets

**Debug mode.** `python -X dev`, `PYTHONASYNCIODEBUG=1`, or
`asyncio.run(main(), debug=True)` logs any callback that blocks the loop longer
than `loop.slow_callback_duration` (default 0.1 s) and reports never-awaited
coroutines with creation tracebacks. It adds overhead; use it in tests and
staging.

**Loop-lag probe.** A task that sleeps for an interval and measures how late it
wakes. Lag is the time the loop was unavailable to everyone.

```python
async def monitor_loop_lag(interval=0.1, warn_after=0.05, report=print):
    loop = asyncio.get_running_loop()
    expected = loop.time() + interval
    while True:
        await asyncio.sleep(interval)
        lag = loop.time() - expected
        if lag > warn_after:
            report(f"loop lag {lag:.2f}s")
        expected = loop.time() + interval
```

**Memory growth.** Start `tracemalloc.start(25)`, take a snapshot, run the
workload, take another, and print `after.compare_to(before, "lineno")[:10]`.
Growth that tracks request count points at retained payloads or unbounded
collections. Python-level growth that `tracemalloc` cannot see points at native
extensions.

**Live process.** `py-spy dump --pid <pid>` shows every thread's stack without
stopping the service. It identifies which thread is stuck in a blocking call.

**Task and permit census.** [`leak_probe.py`](../examples/leak_probe.py) counts
live tasks by coroutine name, threads, and file descriptors, and fails with the
names of whatever grew.

## 4. Soak test (the leak regression test)

1. Run the workload once to warm lazily created pools and clients, then take a
   baseline: tasks, threads, fds, permits, registry size.
2. Run it many times with realistic concurrency. Include the error paths: an
   upstream failure, a timeout, a cancellation in the middle, an oversized input.
3. Let cleanup finish, then compare. Everything must return to baseline.
4. For memory, repeat in batches and look for a plateau, not a slope.

[`leak_probe.assert_returns_to_baseline`](../examples/leak_probe.py) implements
steps 1 to 3 and is exercised against both a deliberate leak and the fan-out
pattern in [`test_leak_probe.py`](../examples/test_leak_probe.py). The counts it
checks prove there is no task, thread, or fd leak in the paths exercised. They do
not prove memory is flat over hours; that needs a real soak run with RSS or
`tracemalloc` trended over time.

## 5. Production signals

Export these so a leak shows up as a trend before it becomes an outage:

- live task count, and tasks by name where cardinality is bounded;
- event-loop lag (p99 and max);
- executor queue depth and active workers;
- open file descriptors and pool utilization;
- permits in use against the limit, and registry size;
- RSS, and worker restarts as an indicator of OOM kills.

Alert on a rising floor (the minimum over a window), not on peaks. Peaks follow
traffic; a rising floor is the leak.
