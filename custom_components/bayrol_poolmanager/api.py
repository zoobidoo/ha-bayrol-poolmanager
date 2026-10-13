"""Async client for the PoolManager WebGUI protocol.

The PoolManager 5 exposes a small JSON API, both on the local network and
through the vendor cloud portal (bayrol-poolaccess.de):

    POST /cgi-bin/webgui.fcgi?sid=<session>
    body:     {"get": ["34.4001.value", ...], "set": {"40.8533.value": "10:00:00"}}
    response: {"data": {...}, "status": {"code": 0}, "event": {"type": 0, "data": "..."}}

Notes:
* Within one session the device only returns values that changed since the
  previous request, so the client keeps a cache.
* Every new session starts on a "User Login (remote access)" page. Until it is
  submitted, reads work but every write is rejected with status 113. Through
  the cloud portal the page is pre-filled with the account's remote user; on
  the local network it is empty, so local writes need the remote user's
  credentials (configured on the device in "User management").
"""

from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import json
import logging
import re
import time
from typing import Any

import aiohttp

from .const import CLOUD_BASE_URL, ITEM_LOGIN_CODE, LOGIN_PAGE, LOGIN_PASS, LOGIN_USER

_LOGGER = logging.getLogger(__name__)

_SID_RE = re.compile(r"wui\.init\(\s*['\"]([^'\"]+)['\"]")
_DEVICE_RE = re.compile(r"(?:device|plant_settings)\.php\?c=(\d+)")
_CLIENTS_RE = re.compile(r"var\s+clients\s*=\s*\[([\d,\s]+)\]")
_TIMEOUT = aiohttp.ClientTimeout(total=20)
# A fresh session returns every value: reopen one periodically so the cache
# never drifts for long.
_SESSION_MAX_AGE = 1800
STATUS_WRITE_REFUSED = 113


class BayrolError(Exception):
    """Generic communication error."""


class BayrolAuthError(BayrolError):
    """Portal credentials rejected."""


class BayrolWriteRefused(BayrolError):
    """The device rejected a write (status 113: remote user not logged in)."""


class BayrolClient:
    """Access to a PoolManager, either locally or through the cloud portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        host: str | None = None,
        username: str | None = None,
        password: str | None = None,
        device_id: str | None = None,
        access_code: str | None = None,
        remote_user: str | None = None,
        remote_password: str | None = None,
    ) -> None:
        self._session = session
        self._cloud = host is None
        self._base = CLOUD_BASE_URL if self._cloud else _normalize_host(host)
        self._username = username
        self._password = password
        self.device_id = device_id
        self._access_code = access_code or None
        self._remote_user = remote_user or None
        self._remote_password = remote_password or ""
        self._sid: str | None = None
        self._sid_opened = 0.0
        self._logged_in = False
        self.remote_logged_in = False
        self._cache: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ public

    @property
    def is_cloud(self) -> bool:
        return self._cloud

    @property
    def base_url(self) -> str:
        return self._base

    async def async_get(self, items: list[str]) -> dict[str, Any]:
        """Read variables (cached values are returned when unchanged)."""
        async with self._lock:
            data = await self._request({"get": items})
            self._cache.update(data)
            return {item: self._cache.get(item) for item in items}

    async def async_set(self, values: dict[str, str]) -> None:
        """Write one or more variables."""
        async with self._lock:
            if self._access_code:
                await self._request({"set": {ITEM_LOGIN_CODE: str(self._access_code)}})
            for item, value in values.items():
                await self._request({"set": {item: str(value)}})
                self._cache[item] = str(value)

    async def async_discover_devices(self) -> list[str]:
        """(Cloud) Device ids registered on the portal account."""
        if not self._cloud:
            return []
        await self._cloud_login()
        return _parse_devices(await self._get_text("/webview/p/plants.php"))

    # ----------------------------------------------------------------- session

    async def _request(self, payload: dict[str, Any], retry: bool = True) -> dict[str, Any]:
        try:
            if self._sid and time.monotonic() - self._sid_opened > _SESSION_MAX_AGE:
                self._sid = None
            if self._sid is None:
                await self._open_session()
            return await self._post(payload)
        except BayrolAuthError:
            raise
        except BayrolWriteRefused:
            if not retry:
                raise
            # The session may have lost its remote login: start a new one once.
            self._reset()
            return await self._request(payload, retry=False)
        except (BayrolError, aiohttp.ClientError, asyncio.TimeoutError) as err:
            if not retry:
                raise BayrolError(str(err)) from err
            _LOGGER.debug("WebGUI session lost (%s), retrying", err)
            self._reset()
            return await self._request(payload, retry=False)

    def _reset(self) -> None:
        self._sid = None
        self._logged_in = False
        self.remote_logged_in = False
        self._cache.clear()

    async def _open_session(self) -> None:
        if self._cloud:
            if not self._logged_in:
                await self._cloud_login()
            if not self.device_id:
                devices = _parse_devices(await self._get_text("/webview/p/plants.php"))
                if not devices:
                    raise BayrolError("No device found on the portal account")
                self.device_id = devices[0]
            await self._get_text(f"/webview/p/device.php?c={self.device_id}")
            match = _SID_RE.search(await self._get_text(f"/webview/pm5/?c={self.device_id}"))
            if not match:
                # Portal PHP session expired: log in again once.
                await self._cloud_login()
                await self._get_text(f"/webview/p/device.php?c={self.device_id}")
                match = _SID_RE.search(await self._get_text(f"/webview/pm5/?c={self.device_id}"))
        else:
            match = None
            for path in ("/cgi-bin/webgui.fcgi", "/"):
                try:
                    match = _SID_RE.search(await self._get_text(path))
                except aiohttp.ClientResponseError:
                    continue
                if match:
                    break
        if not match:
            raise BayrolError("Could not open a WebGUI session on the PoolManager")
        self._sid = match.group(1)
        self._sid_opened = time.monotonic()
        self._cache.clear()
        await self._remote_login()

    async def _remote_login(self) -> None:
        """Submit the "User Login (remote access)" page of a new session.

        Uses the values pre-filled by the device (cloud portal) or, if the page
        is empty (local network), the configured remote user credentials.
        """
        self.remote_logged_in = False
        html = await self._get_text(f"/cgi-bin/webgui.fcgi?sid={self._sid}&cmd={LOGIN_PAGE}")
        fields = _parse_inputs(html)
        user = fields.get(LOGIN_USER) or self._remote_user
        password = fields.get(LOGIN_PASS) if fields.get(LOGIN_USER) else self._remote_password
        if not user:
            _LOGGER.debug("No remote user available: session is read-only")
            return
        await self._post({"set": {LOGIN_USER: user, LOGIN_PASS: password or ""}})
        self.remote_logged_in = True

    async def _cloud_login(self) -> None:
        if not self._username or not self._password:
            raise BayrolAuthError("Missing portal credentials")
        await self._get_text("/webview/p/login.php")
        async with self._session.post(
            f"{self._base}/webview/p/login.php?r=reg",
            data={
                "username": self._username,
                "password": self._password,
                "autologin": "on",
                "login": "Anmelden",
            },
            timeout=_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            html = await resp.text()
        if 'type="password"' in html and "plants.php" not in str(resp.url):
            raise BayrolAuthError("Portal login rejected")
        self._logged_in = True

    # -------------------------------------------------------------------- http

    async def _get_text(self, path: str) -> str:
        async with self._session.get(f"{self._base}{path}", timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._session.post(
            f"{self._base}/cgi-bin/webgui.fcgi",
            params={"sid": self._sid},
            data=json.dumps(payload),
            headers={"Content-Type": "application/json;charset=UTF-8"},
            timeout=_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            text = await resp.text()
        try:
            body = json.loads(text)
        except ValueError as err:
            raise BayrolError("Unreadable WebGUI response") from err
        if not isinstance(body, dict):
            raise BayrolError(f"Unexpected WebGUI response: {body!r}")
        code = (body.get("status") or {}).get("code", 0)
        if code == STATUS_WRITE_REFUSED:
            raise BayrolWriteRefused(f"Write refused by the PoolManager (status {code})")
        if code != 0:
            raise BayrolError(f"Unexpected WebGUI status: {code}")
        return dict(body.get("data") or {})


class _InputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "input":
            a = dict(attrs)
            if a.get("id"):
                self.values[a["id"]] = a.get("value") or ""


def _parse_inputs(html: str) -> dict[str, str]:
    parser = _InputParser()
    parser.feed(html)
    return parser.values


def _parse_devices(html: str) -> list[str]:
    """Device ids found on the portal's plants.php page (links or JS variable)."""
    found = _DEVICE_RE.findall(html)
    match = _CLIENTS_RE.search(html)
    if match:
        found += [x.strip() for x in match.group(1).split(",") if x.strip()]
    return list(dict.fromkeys(found))


def _normalize_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host
