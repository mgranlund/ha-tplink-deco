"""Isolated probe tests without importing Home Assistant or contacting a Deco.

Run: python -m unittest discover -s tests
The actual API methods are compiled from source; only transport/crypto are mocked.
"""

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


class ApiError(Exception):
    """Stub for API exceptions in the isolated method harness."""


ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "custom_components/tplink_deco/api.py").read_text())
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef))
METHODS = {
    "async_probe_client_preferences",
    "_async_probe_client_preferences",
    "_async_call_with_retry",
}
CLASS.body = [n for n in CLASS.body if getattr(n, "name", "") in METHODS]
SCOPE = {
    "asyncio": asyncio,
    "async_timeout": SimpleNamespace(timeout=asyncio.timeout),
    "UnexpectedApiException": ApiError,
    "EmptyDataException": type("EmptyDataException", (Exception,), {}),
    "ForbiddenException": type("ForbiddenException", (Exception,), {}),
    "TimeoutException": type("TimeoutException", (Exception,), {}),
    "_LOGGER": logging.getLogger(__name__),
}
exec(compile(ast.Module(body=[CLASS], type_ignores=[]), "api.py", "exec"), SCOPE)


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    """Exercise failure isolation, authentication and lock behavior."""

    def make_api(self):
        api = SCOPE["TplinkDecoApi"]()
        api._operation_lock = asyncio.Lock()
        api._host = "http://example.invalid"
        api._stok = api._cookie = "existing"
        api._aes_key_bytes = api._aes_iv_bytes = b"existing"
        api._seq = 1
        api._encode_payload = lambda payload: payload
        api._decrypt_data = lambda context, data: data
        api.async_login_if_needed = AsyncMock(side_effect=AssertionError("login"))
        api.async_login = AsyncMock(side_effect=AssertionError("login"))
        return api

    async def test_raw_response_and_read_only_requests(self):
        api = self.make_api()
        raw = {"error_code": 0, "result": {"unknown_preference": {"mac": "AA"}}}

        async def post(*args, **kwargs):
            self.assertTrue(api._operation_lock.locked())
            self.assertEqual(kwargs["data"]["operation"], "read")
            return {"data": raw}

        api._async_post = AsyncMock(side_effect=post)
        result = await api.async_probe_client_preferences()
        self.assertEqual(list(result["probes"]), ["client_list", "client_access"])
        self.assertIs(result["probes"]["client_list"]["response"], raw)
        self.assertEqual(api._async_post.await_count, 2)
        self.assertFalse(api._operation_lock.locked())
        api.async_login.assert_not_called()
        api.async_login_if_needed.assert_not_called()

    async def test_missing_auth_never_posts(self):
        api = self.make_api()
        api._stok = None
        api._async_post = AsyncMock()
        result = await api.async_probe_client_preferences()
        self.assertTrue(all(e["status"] == "error" for e in result["probes"].values()))
        api._async_post.assert_not_called()
        api.async_login.assert_not_called()

    async def test_error_isolation_and_decrypted_api_error(self):
        api = self.make_api()
        raw = {"error_code": -1, "result": {"unknown": True}}
        api._async_post = AsyncMock(
            side_effect=[ValueError("secret URL"), {"data": raw}]
        )
        result = await api.async_probe_client_preferences()
        self.assertNotIn("secret URL", str(result))
        self.assertEqual(result["probes"]["client_list"]["error_type"], "ValueError")
        self.assertEqual(result["probes"]["client_access"]["response"], raw)

    async def test_forbidden_retry_cannot_login(self):
        api = self.make_api()

        async def forbidden(*args, **kwargs):
            api._stok = None  # Real transport clears auth on HTTP 403.
            raise SCOPE["ForbiddenException"]()

        api._async_post = AsyncMock(side_effect=forbidden)
        await api.async_probe_client_preferences()
        self.assertEqual(api._async_post.await_count, 1)
        api.async_login.assert_not_called()
        api.async_login_if_needed.assert_not_called()

    async def test_budget_releases_lock(self):
        api = self.make_api()
        api._async_post = AsyncMock(side_effect=lambda *a, **kw: None)

        async def slow(*args, **kwargs):
            await asyncio.sleep(10)

        api._async_post.side_effect = slow
        original = SCOPE["async_timeout"]
        SCOPE["async_timeout"] = SimpleNamespace(
            timeout=lambda seconds: asyncio.timeout(0.01)
        )
        try:
            result = await api.async_probe_client_preferences()
        finally:
            SCOPE["async_timeout"] = original
        self.assertFalse(api._operation_lock.locked())
        self.assertTrue(
            all(
                e["status"] == "probe_budget_exhausted"
                for e in result["probes"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
