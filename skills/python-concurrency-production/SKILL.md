---
name: python-concurrency-production
description: Review or implement production Python concurrency in APIs, services, and agent workloads (FastAPI, LangGraph, Google ADK, custom agent loops) using asyncio, threads, or executors. Use when task ownership, blocking work, cancellation, deadlines, capacity, or leaks affect correctness under load, for example a service that hangs, slows down, or keeps growing in memory, tasks, threads, or connections, or streaming and agent runs that must stop when the client disconnects.
---

# Python Concurrency Production

Help with concurrent Python code in ordinary APIs, background work, and agent
services. Preserve the user's framework choices and existing architecture.

## Read only what the task needs

- For a full service review, a new concurrent API, or a change to async request
  fan-out, read [the production standard](references/production-standard.md).
- For threads, executors, synchronous SDKs inside async code, or free-threaded
  CPython, read [the threading guide](references/threading.md). Read both when
  both execution models matter.
- For a narrow fix, use the relevant reference only if it changes the decision;
  inspect the actual call path and tests first.
- For a service that hangs, slows down, or grows over time, or when asked to
  show that a design does not leak, read
  [leaks and diagnostics](references/leaks-and-diagnostics.md). Use the
  [leak probe](examples/leak_probe.py) as the soak-test pattern.
- For agent services, streaming (SSE/WebSocket) endpoints, or code built on
  LangGraph, Google ADK, or a similar framework, read
  [agent services](references/agent-services.md). It covers per-run budgets,
  disconnect cancellation, and where each framework hides concurrency.
- For an implementation or a production-readiness claim, read
  [the verification contract](references/verification.md). Use the
  [runnable async fan-out pattern](examples/async_fanout.py) and
  [FastAPI adapter](examples/fastapi_adapter.py) only when they clarify the
  requested design; adapt them to the target service rather than copying
  assumptions about limits, endpoints, or dependencies.

## Working method

Trace the relevant call path from its entry point through dependencies and
external effects. Classify I/O, CPU work, and durable work. Determine ownership,
failure policy, limits, deadlines, and resource lifetime from code and config.
Treat missing capacity inputs as unknown, not as proven defects.

For a review, report only evidence-backed risks with exact file and line,
runtime impact, and the smallest correction. State whether limits are per
request, process, or deployment. For an implementation, make the change and
verify the behavior most at risk; do not declare load readiness without load
evidence.

## Invariants worth checking

- Blocking I/O and material CPU work must not stall an event-loop thread. CPU
  work is not only loops: password hashing (bcrypt, argon2), large
  (de)serialization, and regex over big input count, and an `async def` that
  wraps a synchronous database session blocks like any other blocking call.
- Fan-out, executor submissions, queues, and retries need bounds where load can
  grow. Related request tasks need an owner and a deliberate failure policy.
- Remote work needs appropriate finite timeouts and a request deadline that
  includes queue wait. Cancellation must release async resources; cancelling an
  awaiter does not necessarily stop a running thread.
- Shared pools and clients need a clear lifetime. In-memory limits apply only
  within their process unless coordinated externally.
- Concurrent requests that change the same logical entity (a session, thread,
  or conversation) need serialization or optimistic concurrency. Tasks and
  `gather` do not provide it, and a per-process lock does not cover several
  workers or replicas.
- Metric labels and log fields must not come from unbounded input such as the
  raw request path, which includes 404s from scanners. Use the route template.
- Scarce resources (a database connection or transaction, a row lock, a pool
  slot, a permit) must not be held while waiting on something slow or
  unbounded: an outbound call, a queue wait, a client reading a stream, or
  another scarce resource. Waiters pile up behind the holder and exhaust the
  pool for unrelated requests. For each such resource, ask what the request
  does between acquiring and releasing it.
- Anything created per request (tasks, permits, streams, connections) must be
  released on every exit path: success, failure, timeout, and cancellation.
  Check the error paths, since leaks hide there. Include cancellation before
  the work starts: a counter or slot taken before a cancellable `await` (a lock
  wait), or a release placed in a generator that never gets its first step,
  is never released.
- Framework code is not exempt. Find where a framework runs sync callables and
  fans out work, and bound and cancel it from the surrounding service.
- Translate known operational failures while leaving programming defects
  visible. Preserve user-requested frameworks; never introduce an agent
  orchestration framework merely to add concurrency.

## Review output

Lead with findings ordered by risk. Each finding needs severity, exact location,
evidence, impact, and correction. Rate severity by impact and likelihood, not by
category:

- **High:** under ordinary load or one bad input it can stall or exhaust a
  worker, or lose or corrupt data (blocking the loop, unbounded fan-out from user
  input, unowned work that is silently lost).
- **Medium:** it degrades capacity, leaks slowly, or fails unsafely under
  specific conditions (no deadline, stacked retries, an unbounded cache).
- **Low:** bounded impact or hygiene.

Add a false-positive check when evidence is incomplete. Summarize the observed
concurrency model, capacity calculation, unknowns, and material test gaps. Say
so plainly when no actionable risk was found; do not invent style findings.

Security issues are outside this skill. When you notice one (unauthenticated or
client-supplied identity, injection through tool arguments, raw upstream bodies
or exception text returned to clients, secrets or personal data in URLs or
logs), list it in one line under "Adjacent concerns" and recommend a separate
security review. A concurrency review that comes back clean is not a statement
that the service is secure or production-ready.
