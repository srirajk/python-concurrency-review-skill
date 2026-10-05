# Agent Services: Streaming, Budgets, and Framework Concurrency

## Contents

- [Why agent workloads differ](#1-why-agent-workloads-differ)
- [Per-run budgets](#2-per-run-budgets)
- [Streaming (SSE, WebSocket)](#3-streaming-sse-websocket)
- [Where frameworks hide concurrency](#4-where-frameworks-hide-concurrency)
- [LangGraph](#5-langgraph-measured-on-063)
- [Google ADK](#6-google-adk-from-official-docs)
- [Wrap any framework the same way](#7-wrap-any-framework-the-same-way)
- [Tool inputs (adjacent concern)](#8-tool-inputs-adjacent-concern)

Read this for services built on LangGraph, Google ADK, LangChain, or a custom
agent loop, and for any endpoint that streams. The skill does not change your
framework. It tells you where the framework's concurrency lives so the
surrounding service can bound and cancel it.

## 1. Why agent workloads differ

A request can run for seconds or minutes, fan out to several model and tool
calls, hold a connection open while streaming, and spend real money. Each
request therefore holds a task, connections, and upstream quota for much longer
than a typical API call, so capacity per process is lower and a leak or an
uncancelled run costs more.

## 2. Per-run budgets

Bound every run on all of these, not only wall-clock time:

- overall deadline (include queue and permit wait);
- model calls and tool calls per run;
- loop or recursion depth;
- tokens and money per run, where the provider reports them;
- concurrent runs per process (admission), and concurrent streams.

Framework limits are guards, not budgets you can rely on alone. Check the
defaults: LangGraph's `recursion_limit` defaults to 25 supersteps. ADK's
`RunConfig.max_llm_calls` defaults to 500, and zero or a negative value means
unlimited, which the ADK docs advise against in production.

## 3. Streaming (SSE, WebSocket)

Verified with Starlette 0.38.6 and uvicorn 0.49 on a real socket: when a client
disconnects from a `StreamingResponse` over an async generator, the generator
receives `CancelledError` and its `finally` block runs. So:

- Release resources in `finally` and let `CancelledError` propagate.
- A generator's `finally` only runs if the generator started. If a client
  disconnects before the first chunk, the generator may never run, so any page,
  slot, or counter acquired before returning the response leaks. Acquire inside
  the generator, or release from a response background task or close hook.
- Keep upstream streams inside `async with` so cancelling the generator closes
  the model connection and stops paying for tokens nobody receives.
- The generator must `await` regularly. Blocking code inside it stalls the loop
  for every connection, not only this stream.
- Bound per-connection buffering. If a client reads slowly, do not park output in
  an unbounded queue; apply backpressure or drop the connection.
- Cap concurrent streams per process. Each holds a task, a socket, and usually
  an upstream stream.
- Set an idle timeout (no chunk for N seconds) and a total deadline. A stream
  that emits a heartbeat can otherwise live forever. Proxies have their own idle
  timeouts; keep heartbeats shorter.
- Test disconnect with the real middleware stack. This verification used the bare
  application; middleware can change cancellation behavior.

## 4. Where frameworks hide concurrency

Ask these of any framework, then test the answer on the installed version:

1. Are synchronous callables (nodes, tools) run on the event loop or in threads?
   If threads, whose pool, and how big?
2. How many branches or tool calls run in parallel, and what limits it?
3. Does cancelling the outer call reach async work inside? Do sync callables stop?
   (They cannot; a thread runs to completion.)
4. Who owns clients, checkpointer or session-store connections, and when are
   they closed?
5. Does the framework retry? Retries at several layers multiply.
6. What per-run limits exist, and what are their defaults?

## 5. LangGraph (measured on 0.6.3)

Measured with `langgraph` 0.6.3 on Python 3.12.7. Re-check on your version.

| Observation | Result |
| --- | --- |
| Five parallel branches, each a sync node blocking 0.3 s, run under `ainvoke` | ~0.3 s total; the loop stayed responsive; nodes ran off the loop thread |
| Five parallel branches, each an `async def` node that calls blocking `time.sleep(0.3)` | ~1.5 s total; the loop froze for the whole time; nodes ran serially on the loop thread |
| `config={"max_concurrency": 2}` with the five sync nodes | ~0.9 s: parallel execution was bounded |
| Cancel `ainvoke` mid-run | Async nodes received `CancelledError`; a running sync node's thread finished anyway |
| A cycle with no stop condition | `GraphRecursionError` at the default limit of 25 |

What this means for a service:

- A blocking call inside an `async def` node is the worst case: it is neither
  parallel nor loop-friendly. Use an async client, or make the node sync.
- Sync nodes run on framework-owned threads, so the thread count follows
  your graph width. Bound it with `max_concurrency` and keep node timeouts at the
  library level, since cancelling cannot stop them.
- Set `recursion_limit` deliberately, and set an overall deadline around
  `ainvoke` / `astream`.

Not verified here: the executor's size, checkpointer connection-pool behavior,
and cancellation propagation through subgraphs and `astream`.

## 6. Google ADK (from official docs)

Taken from the ADK documentation (event-loop and RunConfig pages), not run
locally. ADK moves quickly, so confirm against the installed version.

- Python ADK calls a synchronous tool function inline on the asyncio event loop,
  so blocking I/O inside it stalls the loop. Prefer `async def` tools with async
  clients.
- `RunConfig.tool_thread_pool_config` (`ToolThreadPoolConfig(max_workers=N)`) runs
  tools in a background thread pool. The docs describe it for live mode; at least
  one third-party report says newer releases also apply it to `run_async`.
  Check the changelog and test with a blocking tool before relying on it.
- The docs state that CPU-bound synchronous work still blocks its thread, and
  that the framework does not always prevent stalls on long blocking I/O.
- `RunConfig.max_llm_calls` defaults to 500.
- The docs do not say whether several tool calls in one model turn run in
  parallel. Test it, and bound it yourself if so.

## 7. Wrap any framework the same way

Whatever the framework, the surrounding service owns:

```text
admission (concurrent runs, streams)
→ per-run deadline: asyncio.timeout around the framework call
→ cancel on client disconnect (see section 3)
→ bounded concurrency inside the run (framework setting, or your semaphore)
→ cleanup in finally; clients and pools owned by lifespan
```

Prove it with tests, not by reading the docs: cancel a run mid-flight and assert
that async work saw the cancellation, permits and tasks returned to baseline
(see [leaks-and-diagnostics.md](leaks-and-diagnostics.md)), and a hung tool hits
the deadline. If a run must survive a disconnect or restart, it is durable work:
use a queue and persisted state, not a request task
(see [production-standard.md](production-standard.md), section 8).

## 8. Tool inputs (adjacent concern)

This is a security topic and a full review belongs to a separate security
review, but it decides capacity and cost too, so flag it when you see it:

- A tool name or argument that comes from a user or from model output is
  untrusted. Allowlist tool names and map each to a fixed route; never place user
  or model text in a URL host or path. An unvalidated name such as `../admin` or
  `x?admin=1` reaches a different endpoint on the same internal host.
- Cap the number of tools per run, the length of each argument, and the size of
  each result. Unbounded lists and arguments are also unbounded fan-out and cost.
- Treat tool results as untrusted before returning them to a client or feeding
  them back to a model. Return a validated, truncated shape, not a raw upstream
  body or `str(exception)`.
- Identity that decides which tools a caller may use must come from
  authentication, not from a request field. Per-user limits keyed on a
  client-supplied ID do not limit anything.
