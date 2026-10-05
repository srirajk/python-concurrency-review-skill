# Portable Python concurrency production skill

This repository contains one reusable [Agent Skills](https://agentskills.io/)
package for reviewing and implementing Python concurrency in APIs, services,
and agent workflows. The skill is tool-neutral; it does not install LangChain,
LangGraph, Google ADK, or any other orchestration framework.

> **Status: v1.** The content has been checked by expert review and probes, and
> the example tests pass. It has been tried on a handful of real and planted
> codebases (FastAPI, LangGraph, Google ADK), where it produced better-calibrated
> reviews than an unaided model but did not find more bugs. It is a checklist,
> not complete coverage, and it is not yet backed by a measured eval set. It is
> not a production-grade validation and does not sign off code for shipping. See
> the [skill card](SKILL_CARD.md) for what it does, what it does not do, and the
> evidence.

## Why this skill exists

- **Concurrency bugs hide until production.** Tests pass in dev, then under
  load you get leaked tasks, hung requests, memory growth, and cascading
  failures.
- **AI-generated code makes this worse.** Models write code that looks
  idiomatic but is unsafe: unowned `create_task`, blocking SDK calls inside
  `async def`, unbounded `gather`, and `run_in_executor` with no limit.
- **Most builders don't know the hardening checklist.** Ownership,
  cancellation, deadlines, bounds, and resource lifetime are the parts people
  skip.
- **The failures are silent.** A blocked event loop shows up as latency in
  unrelated endpoints. A dropped task exception shows up as a log line, if
  that.
- **Agent workloads amplify it.** An agent run fans out to LLMs, tools, and
  databases. With many users running agents at once, one slow upstream call
  can tie up resources for everyone.
- **It makes review repeatable.** The same questions get asked of every
  change.

## Where it applies

- **FastAPI and other web services.** Includes a FastAPI/HTTPX adapter; the
  same principles apply to Starlette, Flask, Django, and similar frameworks.
- **Any Python code** that uses asyncio, threads, or executors: background
  workers, batch jobs, queue consumers, and scripts.
- **Agent code built on Google ADK, LangGraph, LangChain, or similar.** You
  write the agent with your framework; the skill hardens the concurrency
  around it so it holds up with many simultaneous users:
  - Blocking tool or LLM calls don't stall the event loop.
  - Parallel tool and node fan-out is bounded.
  - Model and tool calls have timeouts and an overall request deadline.
  - Cancellation works when a client disconnects mid-run.
  - Clients and pools have proper lifetimes.
  - Capacity math is explicit: concurrent runs × calls per run vs. provider
    quotas, per process and per deployment.

## What it does

- **Traces the real call path** from entry point through dependencies and
  external effects, instead of pattern-matching on snippets.
- **Classifies the work** as I/O, CPU, or durable, then decides the execution
  model: asyncio, threads, or executors.
- **Checks the core invariants:**
  - Blocking I/O or heavy CPU doesn't stall the event loop.
  - Fan-out, queues, executor submissions, and retries are bounded.
  - Related tasks have an owner and a deliberate failure policy.
  - Remote calls have finite timeouts, and the request deadline includes
    queue wait.
  - Cancellation releases async resources; cancelling an awaiter is not
    assumed to stop a running thread.
  - Shared pools and clients have a clear lifetime.
  - Known operational failures are translated, while programming bugs stay
    visible.
- **States the scope of every limit** as per request, per process, or per
  deployment.
- **Produces structured review output:** findings ordered by risk, each with
  severity, exact file and line, evidence, impact, and the smallest fix, plus
  a false-positive check when evidence is incomplete.
- **Supports implementation, not just review.** It makes the change and
  verifies the behavior most at risk.
- **Finds and prevents leaks.** Design rules (ownership, bounds, lifetimes) plus
  a diagnostic guide that maps symptoms (rising tasks, memory, fds, threads,
  loop lag) to causes, tools, and fixes, and a soak-test helper that checks
  tasks, threads, and fds return to baseline after success, failure, timeout,
  and cancellation.
- **Covers agent services.** Per-run budgets, streaming and client-disconnect
  cancellation, and where LangGraph and ADK hide their concurrency, so the
  service around the framework can bound and cancel it.
- **Ships runnable references:** an async fan-out pattern, a leak probe, and a
  FastAPI adapter with executable tests, plus a verification contract.
- **Loads only what's needed** by routing to the relevant reference file.
- **Is portable** across Codex, Claude Code, and Copilot.

## What it does not do

- **It does not prove production readiness.** It won't claim load readiness
  without load-test evidence.
- **It does not invent findings.** Missing capacity inputs are treated as
  unknown, not as defects, and it says so plainly when there is no actionable
  risk.
- **It does not replace load testing or observability.** You still need
  event-loop lag, queue depth, and task-count metrics.
- **It does not impose a framework.** It preserves your stack and won't add
  LangChain, LangGraph, ADK, or any other orchestration layer just to add
  concurrency.
- **It does not configure agent-framework internals.** It reviews the Python
  concurrency around your ADK or LangGraph code, not graph design, prompts, or
  agent logic. Framework facts are version-dependent: the LangGraph behavior was
  measured on 0.6.3 and the ADK notes come from its documentation without being
  run, so re-verify both on the versions you install.
- **It does not prove a service has no slow leak.** The soak helper checks
  counts (tasks, threads, fds, permits) in the paths you exercise. Memory that
  creeps over hours needs a real soak run with RSS or `tracemalloc` trended.
- **It is not a deployment preset.** You still configure admission, worker and
  replica counts, upstream quotas, shutdown, and disconnect handling.
- **It does not coordinate limits across processes.** That needs external
  coordination (Redis, a gateway, etc.).
- **It does not guarantee thread cancellation.** Stopping a running thread is
  outside what asyncio can do.
- **It does not cover durable workflow design.** That belongs to other tools
  (e.g. Restate or queues), though the skill does classify durable work.

## Package layout

```text
skills/python-concurrency-production/
├── SKILL.md                       # shared entry point and routing
├── references/
│   ├── production-standard.md     # async/API/service decisions
│   ├── threading.md               # sync SDKs, executors, free-threading
│   ├── leaks-and-diagnostics.md   # symptom-to-cause, tools, soak test
│   ├── agent-services.md          # streaming, budgets, LangGraph/ADK concurrency
│   └── verification.md            # evidence and production acceptance checks
└── examples/
    ├── async_fanout.py            # runnable standard-library core
    ├── test_async_fanout.py       # executable behavioral tests
    ├── leak_probe.py              # soak-test helper (tasks, threads, fds)
    ├── test_leak_probe.py         # proves the probe catches a leak
    ├── fastapi_adapter.py         # illustrative FastAPI/HTTPX integration
    └── test_fastapi_adapter.py    # 502/503/504 mapping (skips without fastapi)
```

## Use it in Codex, Claude Code, and GitHub Copilot or anywhere where Skills are supported

Install or link the **entire** `python-concurrency-production` folder, not just
`SKILL.md`, so relative references and examples remain available:

| Client | Personal discovery location | Repository discovery location |
| --- | --- | --- |
| Codex | `~/.agents/skills/python-concurrency-production/` | `.agents/skills/python-concurrency-production/` |
| Claude Code | `~/.claude/skills/python-concurrency-production/` | `.claude/skills/python-concurrency-production/` |
| GitHub Copilot | `~/.copilot/skills/python-concurrency-production/` or `~/.agents/skills/...` | `.github/skills/...`, `.agents/skills/...`, or `.claude/skills/...` |

Use a single source folder and links or copies in the discovery locations you
need. If a repository contains both `.agents/skills/` and `.claude/skills/`,
Copilot may discover the same skill twice; verify its effective skill list
before relying on automatic selection. A Codex personal copy may also live at
`~/.codex/skills/` in existing installations; avoid maintaining divergent
copies. Restart or reload a client if it does not notice a newly installed
skill. See the current [Codex](https://learn.chatgpt.com/docs/build-skills),
[Claude Code](https://code.claude.com/docs/en/skills), and
[Copilot](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)
instructions for version-specific discovery behavior.

## Validate the package and generated code

Run the reference tests from this repository root. The fan-out and leak tests
use only the standard library; the adapter test skips itself unless `fastapi`
and `httpx` are installed:

```sh
python3 -m unittest discover -s skills/python-concurrency-production/examples -p 'test_*.py' -v
```

The example proves bounded overlapping calls, fail-fast sibling cleanup,
deadline coverage of capacity wait, exception classification, and pre-schedule
fan-out validation, that the leak probe catches an unowned-task leak while the
fan-out pattern returns to baseline, and that the adapter maps upstream
timeouts, pool exhaustion, and bad replies to 504, 503, and 502. It does **not**
prove an application is production-ready.
When an assistant changes a real service, ask it to use
`references/verification.md`, run that service's tests, and show measured load
evidence before claiming a throughput target. For example:

> Use the python-concurrency-production skill to review this FastAPI request
> path. Cite exact code locations, calculate per-process and deployment limits,
> run relevant tests, and distinguish verified behavior from unknown capacity.

The FastAPI adapter requires `fastapi`, `httpx`, `pydantic`, and `uvicorn` in
the target application. It is illustrative, not a deployment preset: configure
admission, worker/replica counts, upstream quotas, observability, and
disconnect/shutdown behavior for the real environment.
