"""Status mapping of the illustrative FastAPI adapter (skipped without fastapi/httpx)."""

import os
import unittest
from unittest import mock

try:
    import httpx
    import fastapi_adapter as adapter
except ImportError as exc:  # optional dependencies of the example only
    raise unittest.SkipTest(f"fastapi adapter dependencies missing: {exc}")

REAL_CLIENT = httpx.AsyncClient  # the test's own client must not be patched


def patched_client(handler):
    class Client(REAL_CLIENT):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    return Client


class AdapterStatusTests(unittest.IsolatedAsyncioTestCase):
    async def post(self, handler) -> int:
        env = {"UPSTREAM_BASE_URL": "http://upstream.test", "UPSTREAM_TOKEN": "t"}
        with mock.patch.dict(os.environ, env), mock.patch.object(
            adapter.httpx, "AsyncClient", patched_client(handler)
        ):
            async with adapter.app.router.lifespan_context(adapter.app):
                transport = httpx.ASGITransport(app=adapter.app)
                async with REAL_CLIENT(transport=transport, base_url="http://test") as client:
                    return (await client.post("/analyze", json={"text": "hi"})).status_code

    async def test_success(self) -> None:
        status = await self.post(lambda req: httpx.Response(200, json={"answer": "a"}))
        self.assertEqual(status, 200)

    async def test_upstream_timeout_is_504_not_502(self) -> None:
        def handler(req):
            raise httpx.ReadTimeout("slow", request=req)

        self.assertEqual(await self.post(handler), 504)

    async def test_pool_exhaustion_is_503_overload(self) -> None:
        def handler(req):
            raise httpx.PoolTimeout("no free connection", request=req)

        self.assertEqual(await self.post(handler), 503)

    async def test_upstream_error_status_and_bad_payload_are_502(self) -> None:
        self.assertEqual(await self.post(lambda req: httpx.Response(500)), 502)
        self.assertEqual(await self.post(lambda req: httpx.Response(200, json={"nope": 1})), 502)


if __name__ == "__main__":
    unittest.main()
