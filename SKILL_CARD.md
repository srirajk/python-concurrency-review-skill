# Skill card: python-concurrency-hardening

**Version:** v1 (beta)
**Type:** Agent Skill (instructions plus reference files and runnable examples; no model, no service)
**Works with:** any client that supports Agent Skills (Claude Code, Codex, GitHub Copilot)

## In one sentence

A checklist-driven reviewer and implementation guide that helps an AI coding
assistant find and avoid concurrency, resource-leak, and capacity problems in
Python services, including agent services built on FastAPI, LangGraph, or
Google ADK.

> **This is not a production-grade validation.** It is a review aid with a
> narrow focus. It does not approve, certify, or sign off Python code for
> shipping, and a review that finds nothing does not mean the code is ready for
> production. Shipping decisions need your own tests, load testing, security
> review, and sign-off.

## Why it exists

- Concurrency bugs pass dev tests and fail under load: leaked tasks, hung
  requests, exhausted connection pools, memory growth.
- Generated code often looks idiomatic but is unsafe: blocking calls inside
  `async def`, unowned `create_task`, unbounded `gather`, no timeouts.
- Most builders have not learned the hardening checklist: ownership,
  cancellation, deadlines, bounds, and resource lifetime.
- The failures are silent. A blocked event loop shows up as latency on
  unrelated endpoints, not as an error.
- Agent workloads amplify this. One run fans out to models, tools, and
  databases, holds connections for a long time, and costs money, so many
  simultaneous users exhaust capacity quickly.

## What it does

- Traces the real call path from entry point to external effects instead of
  pattern-matching snippets.
- Checks core invariants: no blocking or heavy CPU on the event loop; bounded
  fan-out, queues, retries, and executors; owned tasks with a failure policy;
  finite timeouts and an overall deadline; resources released on every exit
  path (including cancellation before work starts); no scarce resource (a
  connection, transaction, row lock, or permit) held across slow waiting; clear
  lifetimes for pools and clients; bounded metric labels.
- Covers agent services: per-run budgets, streaming and client-disconnect
  cancellation, and where LangGraph and ADK hide their concurrency.
- Helps find leaks: a symptom-to-cause guide, diagnostic snippets, and a soak
  test helper that checks tasks, threads, file descriptors, and permits return
  to baseline.
- Produces structured review output: findings ordered by severity with exact
  file and line, evidence, impact, smallest fix, false-positive check, capacity
  math, unknowns, and test gaps.
- Supports implementation as well as review, and states what it verified.

## What it does not do

- It is not a security review. It flags security issues it notices as "adjacent
  concerns" (unauthenticated or client-supplied identity, injection through tool
  arguments, raw upstream errors returned to clients) and recommends a separate
  review. A clean concurrency review does not mean a service is secure.
- It is not a production-grade validation and does not certify production
  readiness. It is not a pre-ship gate for Python code, and it will not claim
  load readiness without load-test evidence.
- It does not guarantee it finds every concurrency bug. It is a checklist, and a
  rule being listed does not guarantee it is applied.
- It does not replace load testing, soak testing, or observability.
- It does not prove the absence of a slow leak. The soak helper checks counts in
  the paths you exercise; memory that creeps over hours needs a real soak run.
- It does not design agents (graphs, prompts, tools) or install any framework.
- It does not coordinate limits across processes or replicas, and it does not
  guarantee that a running thread can be cancelled.
- It does not cover durable workflow design beyond classifying durable work.
- It does not check correctness bugs unrelated to concurrency, such as a
  missing import.

## Evidence

What was done:

- Technical claims checked by an expert-style review and by direct probes
  (executor behavior, FastAPI thread limit, streaming disconnect on a real
  server, HTTPX timeout mapping).
- LangGraph behavior measured on 0.6.3. Google ADK notes come from its
  documentation and were not run against ADK.
- 12 runnable example tests pass (fan-out pattern, leak probe, FastAPI error
  mapping).
- Side-by-side reviews, each run in a fresh session with and without the
  skill, on five real repositories: a LangGraph template, a Google ADK sample,
  a FastAPI download service, and two held-out repos (a FastAPI LLM chatbot and
  an async FastAPI proxy) that the skill had not been tuned on.

What the reviews showed:

- Recall: about the same as an unaided strong model. Each side found a few valid
  issues the other missed.
- Calibration: the skill's reviews stayed on concurrency, put security items
  under "adjacent concerns", and added capacity math, measured numbers, and
  explicit non-findings. Unaided reviews mixed in correctness and security bugs
  and sometimes ranked them above resource leaks.
- Misses: the skill missed a real leak the baseline caught (a stream cancelled
  before it started never releases its resource) and a lock held across slow
  calls. Both were added to the checklist. A rerun then found the leak, but that
  is a check on a known miss, not independent proof.

## Known limitations

- Each comparison was a single run, so differences between runs are within
  normal run-to-run variation.
- There is no measured eval set with seeded bugs and clean controls yet.
- Whether the skill triggers automatically from its description is untested.
- Framework facts are version-dependent. Re-verify LangGraph and ADK behavior on
  the versions you install.
- Compatibility with Codex and Copilot is expected but not tested.

## Intended use

- Getting a concurrency-focused second look at a FastAPI or other async Python
  service, background worker, or agent service.
- Implementing concurrent request paths with bounds, deadlines, and cleanup.
- Investigating a service that hangs, slows down, or grows in memory, tasks,
  threads, or connections.

Use it to find concurrency problems earlier. Do not use it to decide that code
is safe to ship.

## Planned

- A companion skill for security and identity in agent services.
- A measured eval set (seeded bugs, clean controls, LangGraph and ADK samples).
- A trigger-reliability test for the skill description.
- Verifying the ADK notes against an installed ADK.
