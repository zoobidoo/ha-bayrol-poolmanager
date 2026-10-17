"""WebGUI client tests against the fake portal."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import aiohttp
from aiohttp.test_utils import TestServer
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# Load api.py / const.py without importing the HA package (__init__ needs HA)
pkg_dir = ROOT / "custom_components" / "bayrol_poolmanager"

pkg = types.ModuleType("bp")
pkg.__path__ = [str(pkg_dir)]
sys.modules["bp"] = pkg
for name in ("const", "api"):
    spec = importlib.util.spec_from_file_location(f"bp.{name}", pkg_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"bp.{name}"] = mod
    spec.loader.exec_module(mod)

from bp import api, const  # noqa: E402
from mock_server import DEVICE, PASSWORD, USER, FakeBayrol  # noqa: E402


@pytest.fixture
async def fake(socket_enabled):
    f = FakeBayrol()
    server = TestServer(f.app())
    await server.start_server()
    const_url = str(server.make_url("")).rstrip("/")
    api.CLOUD_BASE_URL = const_url
    yield f, const_url
    await server.close()


def _client(base, **kw):
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    c = api.BayrolClient(
        session, username=kw.get("u", USER), password=kw.get("p", PASSWORD), access_code=kw.get("code")
    )
    c._base = base
    return c, session


async def test_read_all_and_delta_cache(fake):
    f, base = fake
    c, s = _client(base)
    try:
        v1 = await c.async_get(const.ALL_ITEMS)
        assert c.device_id == DEVICE
        assert v1[const.ITEM_PH] == "7.22"
        assert v1["40.8533.value"] == "10:00:00"
        # 2nd read: the server returns nothing (unchanged) -> served from cache
        v2 = await c.async_get(const.ALL_ITEMS)
        assert v2 == v1
        f.values[const.ITEM_PH] = "7.30"
        v3 = await c.async_get(const.ALL_ITEMS)
        assert v3[const.ITEM_PH] == "7.30" and v3[const.ITEM_TEMP] == "24.0"
        assert f.pm5_calls == 1
    finally:
        await s.close()


async def test_write_requires_and_sends_code(fake):
    f, base = fake
    c, s = _client(base)
    try:
        await c.async_get(const.ALL_ITEMS)
        await c.async_set({"40.8536.value": "16:00:00", "35.5184.value": "4"})
        assert ("40.8536.value", "16:00:00") in f.writes
        assert f.values["35.5184.value"] == "4"
        v = await c.async_get(["40.8536.value"])
        assert v["40.8536.value"] == "16:00:00"
    finally:
        await s.close()


async def test_write_refused_without_remote_login(fake):
    """Without a remote user logged in, the PoolManager answers writes with 113."""
    f, base = fake
    f.prefill = False
    c, s = _client(base)
    try:
        with pytest.raises(api.BayrolError, match="113"):
            await c.async_set({"40.8536.value": "16:00:00"})
        assert f.writes == []
        assert (await c.async_get([const.ITEM_PH]))[const.ITEM_PH] == "7.22"  # reads still work
    finally:
        await s.close()


async def test_session_expiry_recovers(fake):
    f, base = fake
    c, s = _client(base)
    try:
        await c.async_get(const.ALL_ITEMS)
        f.expire_all = True
        v = await c.async_get(const.ALL_ITEMS)
        assert v[const.ITEM_PH] == "7.22"
        assert f.pm5_calls == 2
    finally:
        await s.close()


async def test_bad_password(fake):
    f, base = fake
    c, s = _client(base, p="wrong")
    try:
        with pytest.raises(api.BayrolAuthError):
            await c.async_get([const.ITEM_PH])
    finally:
        await s.close()


async def test_discover(fake):
    f, base = fake
    c, s = _client(base)
    try:
        assert await c.async_discover_devices() == [DEVICE]
    finally:
        await s.close()


async def test_local_write_with_remote_user(socket_enabled):
    from mock_server import REMOTE_PASS, REMOTE_USER, FakeLocal

    f = FakeLocal()
    server = TestServer(f.app())
    await server.start_server()
    host = str(server.make_url("")).rstrip("/")
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    try:
        ro = api.BayrolClient(session, host=host)
        with pytest.raises(api.BayrolWriteRefused):
            await ro.async_set({"40.8536.value": "16:00:00"})
        rw = api.BayrolClient(session, host=host, remote_user=REMOTE_USER, remote_password=REMOTE_PASS)
        await rw.async_set({"40.8536.value": "16:00:00"})
        assert ("40.8536.value", "16:00:00") in f.writes
        bad = api.BayrolClient(session, host=host, remote_user=REMOTE_USER, remote_password="wrong")
        with pytest.raises(api.BayrolWriteRefused):
            await bad.async_set({"40.8536.value": "15:00:00"})
    finally:
        await session.close()
        await server.close()
