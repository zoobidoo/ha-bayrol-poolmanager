"""Fake PoolManager / Bayrol portal reproducing the observed WebGUI protocol."""

from __future__ import annotations

import json
import secrets

from aiohttp import web

USER, PASSWORD, DEVICE = "user@example.com", "secret", "12345"
REMOTE_USER, REMOTE_PASS = "remoteuser", "1111"
LOGIN_FORM = (
    '<form id="login"><input type="text" id="9.17401.user" value="{u}">'
    '<input type="password" id="9.17401.pass" value="{p}"><input type="submit" value="Valider"></form>'
)


class FakeBayrol:
    def __init__(self) -> None:
        self.values = {
            "34.4001.value": "7.22", "34.4022.value": "707", "34.4033.value": "24.0",
            "34.3001.value": "7.20", "34.3049.value": "720",
            "55.17106.status": "1", "55.17106.opmode": "0", "60.5432.value": "2",
            "14.16601.mode": "No Flow", "14.16604.mode": "No Flow",
            "44.2001.value": "0", "44.2003.value": "0",
            "35.5184.value": "2", "36.5203.value": "127", "40.8533.value": "10:00:00", "40.8536.value": "18:00:00",
            "1.1257.value": "Timer interval 1 (Monday - Sunday, 10:00-18:00, Normal mode)",
            "35.5185.value": "2", "36.5204.value": "127", "40.8534.value": "00:00:00", "40.8537.value": "02:00:00",
            "1.1258.value": "Timer interval 2 (Monday - Sunday, 00:00-02:00, Normal mode)",
            "35.5186.value": "1", "36.5205.value": "0", "40.8535.value": "09:00:00", "40.8538.value": "18:00:00",
            "1.1259.value": "Timer interval 3 (Off)",
        }
        for n, (m, d, on, off, lbl) in {
            4: ("35.5187", "36.5206", "40.8539", "40.8542", "1.1260"),
            5: ("35.5188", "36.5207", "40.8540", "40.8543", "1.1261"),
            6: ("35.5189", "36.5208", "40.8541", "40.8544", "1.1262"),
        }.items():
            self.values.update({m + ".value": "2", d + ".value": "0", on + ".value": "08:00:00", off + ".value": "08:00:00", lbl + ".value": f"Timer interval {n} (Off)"})
        self.sessions: dict[str, dict] = {}  # sid -> {"last": {item: value}, "level": int}
        self.logged_cookies: set[str] = set()
        self.writes: list[tuple[str, str]] = []
        self.pm5_calls = 0
        self.expire_all = False
        self.prefill = True  # the portal pre-fills the remote user

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/webview/p/login.php", self.login_page)
        app.router.add_post("/webview/p/login.php", self.login_post)
        app.router.add_get("/webview/p/plants.php", self.plants)
        app.router.add_get("/webview/p/device.php", self.device)
        app.router.add_get("/webview/pm5/", self.pm5)
        app.router.add_post("/cgi-bin/webgui.fcgi", self.fcgi)
        app.router.add_get("/cgi-bin/webgui.fcgi", self.fcgi_page)
        return app

    async def fcgi_page(self, request):
        sid = request.query.get("sid")
        if sid and sid in self.sessions and request.query.get("cmd") == "9.17401.0":
            u, p = (REMOTE_USER, REMOTE_PASS) if self.prefill else ("", "")
            return web.Response(text=LOGIN_FORM.format(u=u, p=p), content_type="text/html")
        return await self.main(request)

    async def main(self, request):
        sid = secrets.token_hex(16)
        self.sessions[sid] = {"last": {}, "level": 1, "remote": False}
        return web.Response(text=f"<script>wui.init('{sid}',false);</script>", content_type="text/html")

    def _authed(self, request) -> bool:
        return request.cookies.get("PHPSESSID") in self.logged_cookies

    async def login_page(self, request):
        return web.Response(text='<form action="login.php?r=reg" method="post"><input name="username"><input type="password" name="password"></form>', content_type="text/html")

    async def login_post(self, request):
        form = await request.post()
        if form.get("username") == USER and form.get("password") == PASSWORD:
            cookie = secrets.token_hex(8)
            self.logged_cookies.add(cookie)
            resp = web.HTTPFound("/webview/p/plants.php")
            resp.set_cookie("PHPSESSID", cookie)
            raise resp
        return web.Response(text='Anmeldung <input type="password" name="password">', content_type="text/html")

    async def plants(self, request):
        if not self._authed(request):
            raise web.HTTPFound("/webview/p/login.php")
        return web.Response(text=f'<a href="plant_settings.php?c={DEVICE}">Device data</a><script>var clients = [{DEVICE}];</script>', content_type="text/html")

    async def device(self, request):
        if not self._authed(request):
            raise web.HTTPFound("/webview/p/login.php")
        return web.Response(text=f'<iframe src="../pm5/?c={DEVICE}" name="device"></iframe>', content_type="text/html")

    async def pm5(self, request):
        if not self._authed(request):
            return web.Response(status=401, text="<h1>Error 401 Unauthorized</h1>")
        if request.query.get("c") != DEVICE:
            return web.Response(status=400, text="<h1>Error 400 Bad Request</h1>")
        self.pm5_calls += 1
        sid = secrets.token_hex(16)
        self.sessions[sid] = {"last": {}, "level": 1, "remote": False}
        return web.Response(text=f"<script>wui.init('{sid}',false);\n    wui.write(3,'9.17401.0')</script>", content_type="text/html")

    async def fcgi(self, request):
        sid = request.query.get("sid")
        if self.expire_all:
            self.sessions.clear()
            self.expire_all = False
        sess = self.sessions.get(sid)
        if sess is None:
            return web.Response(text=json.dumps({"data": {}, "status": {"code": 3}, "event": {"type": 0, "data": ""}}))
        body = json.loads(await request.text())
        event = {"type": 0, "data": "1.1257.0"}
        if "set" in body:
            sets = {k: str(v).strip() for k, v in body["set"].items()}
            if "9.17401.user" in sets:
                sess["remote"] = (sets["9.17401.user"], sets.get("9.17401.pass")) == (REMOTE_USER, REMOTE_PASS)
                return web.Response(text=json.dumps({"data": {}, "status": {"code": 0}, "event": {"type": 1, "data": "3.16901.0"}}))
            if not sess["remote"]:
                return web.Response(text=json.dumps({"data": {}, "status": {"code": 113}, "event": {"type": 0, "data": "3.16901.0"}}))
            for k, v in sets.items():
                if k == "42.8028.code":
                    sess["level"] = 2 if v == "0000" else 1
                else:
                    self.values[k] = v
                    self.writes.append((k, v))
            event = {"type": 1, "data": "1.1256.0"}
        data = {}
        for k in body.get("get", []):
            if k in self.values and sess["last"].get(k) != self.values[k]:
                data[k] = self.values[k]
        sess["last"] = {k: self.values[k] for k in body.get("get", []) if k in self.values}
        return web.Response(text=json.dumps({"data": data, "status": {"code": 0}, "event": event}, indent="\t"))


class FakeLocal(FakeBayrol):
    """PoolManager on the LAN: login page not pre-filled, writes refused (113) until the remote user logs in."""

    def __init__(self) -> None:
        super().__init__()
        self.prefill = False

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.root)
        app.router.add_get("/cgi-bin/webgui.fcgi", self.fcgi_page)
        app.router.add_post("/cgi-bin/webgui.fcgi", self.fcgi)
        return app

    async def root(self, request):
        return web.Response(text="<html>PM5 redirect</html>", content_type="text/html")
