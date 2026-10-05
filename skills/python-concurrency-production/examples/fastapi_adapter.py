"""Illustrative FastAPI/HTTPX adapter for async_fanout.py (Python 3.13).

Dependencies: fastapi, httpx, pydantic, uvicorn. Copy/adapt both modules into
your application package; do not import production code from a skill folder.
Set UPSTREAM_BASE_URL (host root) and UPSTREAM_TOKEN before startup.
"""

import json
import os
from contextlib import asynccontextmanager
from functools import partial

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from async_fanout import (
    DeadlineExceeded,
    FanoutConfig,
    FanoutService,
    UpstreamBatchFailure,
    UpstreamFailure,
)

AGENTS = ("research", "analysis", "review")  # Fixed, trusted routes.


class UpstreamTimeout(UpstreamFailure):
    """The upstream was reachable but too slow (maps to 504)."""


class UpstreamOverloaded(UpstreamFailure):
    """No pooled connection was free: this process is saturated (maps to 503)."""


class Prompt(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


async def call_agent(client: httpx.AsyncClient, name: str, prompt: str) -> str:
    try:
        response = await client.post(name, json={"prompt": prompt})
        response.raise_for_status()
        payload = response.json()
    # PoolTimeout subclasses TimeoutException, so it must be caught first.
    except httpx.PoolTimeout as exc:
        raise UpstreamOverloaded(f"no free connection for agent {name}") from exc
    except httpx.TimeoutException as exc:
        raise UpstreamTimeout(f"agent {name} timed out") from exc
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise UpstreamFailure(f"agent {name} request failed") from exc

    # A malformed provider response is an operational failure, not a valid answer.
    if not isinstance(payload, dict) or not isinstance(payload.get("answer"), str):
        raise UpstreamFailure(f"agent {name} returned an invalid response")
    return payload["answer"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    base_url = os.environ["UPSTREAM_BASE_URL"]
    token = os.environ["UPSTREAM_TOKEN"]
    timeout = httpx.Timeout(connect=2.0, read=8.0, write=3.0, pool=1.0)
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
        limits=limits,
    ) as client:
        app.state.client = client
        app.state.fanout = FanoutService(
            FanoutConfig(
                max_calls_per_request=len(AGENTS),
                max_outbound_per_process=50,
                request_deadline_seconds=15.0,
            )
        )
        yield


app = FastAPI(lifespan=lifespan)


def status_for(batch: UpstreamBatchFailure) -> tuple[int, str]:
    """Overload (503) and upstream timeout (504) need different client behavior."""
    leaves = getattr(batch.__cause__, "exceptions", ())
    if any(isinstance(leaf, UpstreamOverloaded) for leaf in leaves):
        return 503, "service at capacity"
    if any(isinstance(leaf, UpstreamTimeout) for leaf in leaves):
        return 504, "upstream timed out"
    return 502, "upstream service failed"


@app.post("/analyze")
async def analyze(body: Prompt, request: Request) -> dict[str, str]:
    calls = {
        name: partial(call_agent, request.app.state.client, name, body.text)
        for name in AGENTS
    }
    try:
        return await request.app.state.fanout.run(calls)
    except UpstreamBatchFailure as exc:
        status, detail = status_for(exc)
        raise HTTPException(status, detail) from exc
    except DeadlineExceeded as exc:
        raise HTTPException(504, "request deadline exceeded") from exc
