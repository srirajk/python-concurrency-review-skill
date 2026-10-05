# Production Standard

## Contents

- [Choose the execution mechanism](#1-choose-the-execution-mechanism)
- [Event loop and task safety](#2-event-loop-and-task-safety)
- [Failure semantics](#3-failure-semantics)
- [Deadlines, retries, and cancellation](#4-deadlines-retries-and-cancellation)
- [Backpressure and capacity](#5-backpressure-and-capacity)
- [Lifecycle and state](#6-lifecycle-and-state)
- [FastAPI and Uvicorn](#7-fastapi-and-uvicorn)
- [Agent and tool calls](#8-agent-and-tool-calls)
- [Observability](#9-observability)
- [Verification](#10-required-verification)

Use this standard for FastAPI/Uvicorn services and other I/O-heavy Python
applications. It is written against Python 3.13; `asyncio.TaskGroup`,
`asyncio.timeout`, and `except*` need 3.11 or later, and the examples were also
run on 3.12. Check the project's actual interpreter and the release notes of
newer versions before relying on version-specific behavior. Adapt mechanisms to
the repository; preserve the invariants.

## 1. Choose the execution mechanism

| Work | Preferred mechanism | Reject or justify |
| --- | --- | --- |
| Async HTTP, database, sockets, agent APIs | `async`/`await`; `TaskGroup` for related independent work | blocking client on event loop |
| Blocking I/O-only SDK | bounded, lifecycle-owned thread adapter | unbounded default-executor submission |
| CPU-heavy Python | process/external worker/native code that releases GIL | event loop or ordinary threads under standard CPython |
| Durable work surviving request/process | persistent queue plus idempotent worker/state | request task or in-memory background task |

Concurrency overlaps work; parallelism executes work simultaneously. Do not
parallelize calls with data dependencies or required ordering.

When CPU work goes to a `ProcessPoolExecutor`, the callable and its arguments
must be picklable, results are copied between processes, and the pool needs a
bound and a lifespan like any other executor. Forking a process that already has
threads is unsafe; prefer the `spawn` or `forkserver` start method and
create the pool once at startup, not per request.

## 2. Event-loop and task safety

- Trace async routes through helpers; a blocking call hidden three layers down
  still blocks the worker.
- Flag `requests`, `time.sleep`, synchronous database/SDK calls,
  `subprocess.run`, large synchronous file operations, and CPU-heavy loops in
  async call paths unless explicitly isolated.
- Use one request-scoped `TaskGroup` for related children that must complete
  before the response. A group creates ownership and fail-fast cancellation; it
  does not limit concurrency.
- Never create tasks over an unvalidated user-controlled collection. Validate
  batch size and use a semaphore, bounded queue, or worker pool as appropriate.
- Avoid request-scoped fire-and-forget work. Durable background operations need
  a queue/state store; short application-owned work needs a task registry,
  exception observation, and graceful shutdown.
- Do not swallow `CancelledError`. Cleanup in `finally`, then propagate it.
- Name important tasks and retain references until completion.

## 3. Failure semantics

Choose and test one policy:

- **Fail-fast:** `TaskGroup`; one unhandled child failure cancels siblings.
- **Partial result:** each child converts expected failure into a typed outcome;
  the group itself completes successfully and the response marks partial data.
- **First success:** cancel and await losers after accepting a valid winner.
- **Durable background:** acknowledge only after durable enqueue/state write.

Wrap known transport, timeout, rate-limit, and upstream-status failures in typed
domain exceptions. With `TaskGroup`, use `except* KnownFailure` or a helper that
translates only known leaves. Unexpected `TypeError`, `ValueError`, assertion,
or invariant failures must remain internal errors and reach telemetry.

Do not use `gather(..., return_exceptions=True)` unless every returned exception
is inspected and represented in the policy.

Keep overload and slowness distinct in the response: pool or permit exhaustion
is capacity (503), an upstream that is reachable but slow is a timeout (504), and
an upstream error or malformed reply is a bad gateway (502). Clients retry these
differently. Map validation failures on user input to 4xx explicitly; a bare
`ValueError` from a limit check otherwise surfaces as a 500.

## 4. Deadlines, retries, and cancellation

- Configure finite connect, pool-acquisition, write, read, and streaming-idle
  timeouts where supported.
- Wrap the complete workflow in an overall deadline. Include semaphore wait,
  pool wait, retries, tool calls, and response assembly.
- Keep inner timeouts below the remaining overall budget; do not rely on a
  timeout whose semantics reset for each received chunk when total duration
  matters.
- Retry only transient failures. Bound attempts and elapsed time, add
  backoff/jitter, honor `Retry-After`, and prevent retries at multiple layers
  from multiplying.
- Retry side effects only with idempotency keys or an equivalent reconciliation
  design. A client timeout does not prove the upstream failed to commit.
- On client disconnect or server shutdown, verify how the server and framework
  signal cancellation; cancel request-owned async work when the workflow should
  stop, and await cleanup. Thread cancellation has separate rules in
  [the threading guide](threading.md).

## 5. Backpressure and capacity

Apply limits at each layer:

```text
proxy/Uvicorn admission
→ active request tasks
→ per-integration semaphore or bounded worker queue
→ connection/executor pool
→ provider/database quota
```

Calculate and report:

```text
maximum child tasks per process
  = admitted requests per process × maximum fan-out per request

approximate deployment outbound maximum
  = per-process outbound limit × workers per replica × replica count
```

- A semaphore limits operations sharing that instance, not users, connections,
  workers, or replicas automatically.
- Waiting tasks are cheap but not free: they retain memory and consume deadline.
- Do not hold a database connection, transaction, or row lock across an outbound
  call, a long wait, or a slow client. Release it first (read, close the
  transaction, then call out), or give that wait its own bounded pool. A
  per-request write such as `last_used_at` that locks a shared row for the length
  of a slow request serializes every caller that shares the row.
- Align semaphore and pool limits so queue location is intentional. Instrument
  time waiting for both.
- Reject overload predictably rather than accepting an unbounded internal
  backlog. Distinguish overload (often 503) from an upstream timeout (often 504).
- Budget database connections, file descriptors, memory, rate limits, and cost
  across the whole deployment.

## 6. Lifecycle and state

- Reuse pool-owning HTTP clients, database engines, and executors across
  requests when their libraries support it. In FastAPI, application lifespan
  normally owns their creation and shutdown. Explicitly scope request-specific
  sessions and transactions to the request.
- Ensure pooled clients are documented safe for concurrent use. Do not share a
  transaction, cursor, or request-scoped session across concurrent children.
- Do not keep authoritative conversation/workflow state only in process memory
  when multiple workers/replicas or restart recovery matters.
- Protect shared mutable state with the primitive appropriate to its domain:
  `asyncio.Lock` within one loop, thread locks within threads, or transactional/
  distributed coordination across processes. Never use an async lock as a
  cross-thread or cross-process guarantee.
- Make startup fail fast on invalid configuration. Keep secrets out of source,
  logs, exceptions, and responses.

## 7. FastAPI and Uvicorn

- Prefer `async def` endpoints for async-native dependencies. FastAPI runs
  normal `def` endpoints/dependencies in a thread pool (AnyIO's default limiter
  allows 40 concurrent threads per process; verified with AnyIO 4.9); inventory
  and bound that capacity when blocking libraries are used.
- Do not call a normal blocking helper directly from `async def` merely because
  FastAPI can offload normal route functions; ordinary helpers are not
  automatically offloaded.
- Configure request/body/batch limits, server admission, keep-alive, graceful
  shutdown, worker health, and proxy timeouts coherently.
- Treat every worker as a separate process with its own loop, pools, semaphores,
  caches, and lifespan resources.
- Do not use development reload mode as the production process model. Derive
  worker count from load tests, memory, blocking leakage, downstream quotas,
  and failure isolation—not a generic CPU formula.

## 8. Agent and tool calls

For streaming endpoints, per-run budgets, and where LangGraph or ADK hide their
concurrency, also read [agent services](agent-services.md).

- Keep orchestration explicit in ordinary Python functions and typed models.
- Treat model output, retrieved text, and tool results as untrusted input.
  Validate structured outputs before use.
- Give tools least-privilege credentials, allowlisted capabilities, finite
  deadlines, input/output size limits, and an auditable identity.
- Require idempotency or approval/reconciliation for consequential side effects.
- Bound model/tool fan-out, tokens, retries, wall-clock time, and monetary cost.
- Separate request-scoped orchestration from durable multi-step workflows.
  Persistence/queues are required when work must survive disconnects or process
  restarts; an in-memory task is not durable.

## 9. Observability

For finding leaks, loop blocking, and memory growth, see
[leaks and diagnostics](leaks-and-diagnostics.md).

Propagate a request/trace ID without mutable globals. Record:

- request rate, latency, status, and active count;
- active/queued outbound operations and queue/semaphore wait;
- pool utilization and acquisition wait;
- upstream latency/status/rate limits;
- retry, timeout, cancellation, rejection, and partial-result counts;
- task/executor saturation, worker restarts, and event-loop lag;
- cost/token metrics when agent calls make them operationally relevant.

Use structured logs. Redact prompts, credentials, tool arguments, personal data,
and raw upstream bodies by default. Avoid high-cardinality metric labels. A label taken from the raw request path is
unbounded, because unmatched 404 paths create a new series each; use the matched
route template or a constant such as `unmatched`.

## 10. Required verification

Match verification to the path changed:

- Run relevant existing checks and focused tests for changed behavior.
- When changing a limit, measure actual peak active operations and queue depth.
- When changing task ownership or failure policy, test slow/failing children,
  cancellation, cleanup, and partial-result or fail-fast behavior.
- When changing clients or thread adapters, test their lifecycle, shutdown, and
  thread safety as applicable.
- Before claiming a new capacity target, load beyond it and verify bounded
  memory, intentional rejection, and recovery; calculate deployment totals
  against dependency quotas.

Do not declare production readiness merely because unit tests pass. State which
capacity inputs, integration behaviors, and load results remain unverified.

## Sources

- Python 3.13 tasks and structured concurrency:
  <https://docs.python.org/3.13/library/asyncio-task.html>
- Python 3.13 synchronization primitives:
  <https://docs.python.org/3.13/library/asyncio-sync.html>
- Python 3.13 executors:
  <https://docs.python.org/3.13/library/concurrent.futures.html>
- FastAPI async behavior: <https://fastapi.tiangolo.com/async/>
- FastAPI lifespan: <https://fastapi.tiangolo.com/advanced/events/>
- Uvicorn server behavior: <https://www.uvicorn.org/server-behavior/>
