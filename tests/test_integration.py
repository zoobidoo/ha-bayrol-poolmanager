"""End-to-end tests in a real Home Assistant instance against the fake portal."""

from __future__ import annotations

from aiohttp.test_utils import TestServer
from mock_server import DEVICE, PASSWORD, USER, FakeBayrol
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bayrol_poolmanager import api
from custom_components.bayrol_poolmanager.const import DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def fake(socket_enabled):
    f = FakeBayrol()
    server = TestServer(f.app())
    await server.start_server()
    old = api.CLOUD_BASE_URL
    api.CLOUD_BASE_URL = str(server.make_url("")).rstrip("/")
    yield f
    api.CLOUD_BASE_URL = old
    await server.close()


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"cloud_{DEVICE}",
        data={"connection": "cloud", "username": USER, "password": PASSWORD, "device_id": DEVICE},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _eid(hass, platform, key):
    reg = er.async_get(hass)
    for e in reg.entities.values():
        if e.platform == DOMAIN and e.domain == platform and e.unique_id.endswith(key):
            return e.entity_id
    raise AssertionError(f"no entity {platform} {key}: {[x.unique_id for x in reg.entities.values()]}")


async def test_entities_and_writes(hass: HomeAssistant, fake: FakeBayrol) -> None:
    await _setup(hass)

    ph = hass.states.get(_eid(hass, "sensor", "_ph"))
    assert ph.state == "7.22"
    assert hass.states.get(_eid(hass, "sensor", "_water_temperature")).state == "24.0"
    assert hass.states.get(_eid(hass, "sensor", "_pump_status")).state == "stopped"
    assert hass.states.get(_eid(hass, "binary_sensor", "_pump_running")).state == "off"
    assert hass.states.get(_eid(hass, "select", "_pump_mode")).state == "auto"
    # 8 h (10-18) + 2 h (0-2)
    assert float(hass.states.get(_eid(hass, "sensor", "_daily_filtration")).state) == 10.0
    start1 = _eid(hass, "time", "_interval_start_1")
    assert hass.states.get(start1).state == "10:00:00"
    assert hass.states.get(_eid(hass, "select", "_interval_days_1")).state == "every_day"
    assert hass.states.get(_eid(hass, "select", "_interval_mode_3")).state == "off"
    summary = hass.states.get(_eid(hass, "sensor", "_interval_summary_1"))
    assert summary.state == "Monday - Sunday, 10:00-18:00, Normal mode"
    print("NOMS:", ph.name, "|", hass.states.get(start1).name, "|", summary.name)

    # Write through the time entity
    await hass.services.async_call("time", "set_value", {"entity_id": start1, "time": "10:30:00"}, blocking=True)
    assert fake.values["40.8533.value"] == "10:30:00"
    assert hass.states.get(start1).state == "10:30:00"

    # Write through the dedicated action
    await hass.services.async_call(
        DOMAIN,
        "set_timer_interval",
        {"interval": 2, "end": "03:00", "days": ["mon", "wed", "fri"], "mode": "eco"},
        blocking=True,
    )
    assert fake.values["40.8537.value"] == "03:00:00"
    assert fake.values["36.5204.value"] == str(1 | 4 | 16)
    assert fake.values["35.5185.value"] == "4"
    assert hass.states.get(_eid(hass, "select", "_interval_days_2")).state == "custom"

    # Pump mode
    await hass.services.async_call(
        "select", "select_option", {"entity_id": _eid(hass, "select", "_pump_mode"), "option": "off"}, blocking=True
    )
    assert fake.values["60.5432.value"] == "4"


async def test_unload(hass: HomeAssistant, fake: FakeBayrol) -> None:
    entry = await _setup(hass)
    assert hass.services.has_service(DOMAIN, "set_timer_interval")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    # The action is registered once for the integration (async_setup) and
    # reports a clear error while no PoolManager is loaded.
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "set_timer_interval", {"interval": 1, "start": "10:00"}, blocking=True)
    assert err.value.translation_key == "no_device"


async def test_config_flow_cloud(hass: HomeAssistant, fake: FakeBayrol) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USER, "password": "bad", "device_id": ""}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": USER, "password": PASSWORD, "device_id": ""}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["device_id"] == DEVICE


async def test_example_automation(hass: HomeAssistant, fake: FakeBayrol) -> None:
    import pathlib

    import yaml

    await _setup(hass)
    auto = yaml.safe_load(
        (pathlib.Path(__file__).parents[1] / "examples" / "automation_filtration_temperature.yaml").read_text()
    )
    auto["id"] = "piscine"
    assert await async_setup_component(hass, "automation", {"automation": [auto]})
    await hass.async_block_till_done()
    eid = next(s.entity_id for s in hass.states.async_all("automation"))
    # 24.0 °C -> 12 h; night 2 h -> day 10 h; 10:00 + 10 h = 20:00
    await hass.services.async_call("automation", "trigger", {"entity_id": eid, "skip_condition": False}, blocking=True)
    await hass.async_block_till_done()
    assert fake.values["40.8536.value"] == "20:00:00", fake.writes
    assert fake.values["40.8533.value"] == "10:00:00"


async def test_local_read_cloud_write(hass: HomeAssistant, fake: FakeBayrol, socket_enabled) -> None:
    from mock_server import FakeLocal

    local = FakeLocal()
    local.values = fake.values  # same physical device
    srv = TestServer(local.app())
    await srv.start_server()
    host = str(srv.make_url("")).rstrip("/")
    entry = MockConfigEntry(domain=DOMAIN, unique_id="local_x", data={"connection": "local", "host": host})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    start1 = _eid(hass, "time", "_interval_start_1")
    assert hass.states.get(start1).state == "10:00:00"

    # No write credentials: explicit error
    with pytest.raises(HomeAssistantError, match="refused"):
        await hass.services.async_call("time", "set_value", {"entity_id": start1, "time": "10:00:00"}, blocking=True)

    # Options: portal credentials -> writes through the cloud
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    res = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"scan_interval": 60, "username": USER, "password": PASSWORD}
    )
    assert res["type"] == "create_entry", res
    await hass.async_block_till_done()
    await hass.services.async_call("time", "set_value", {"entity_id": start1, "time": "09:30:00"}, blocking=True)
    assert ("40.8533.value", "09:30:00") in fake.writes

    # Portal password changed: the write fails clearly and re-authentication starts
    fake.password = "new-secret"
    fake.logged_cookies.clear()
    fake.sessions.clear()
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("time", "set_value", {"entity_id": start1, "time": "09:45:00"}, blocking=True)
    assert err.value.translation_key == "portal_auth_failed"
    await hass.async_block_till_done()
    flows = [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == SOURCE_REAUTH]
    res = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"username": USER, "password": "new-secret"}
    )
    assert res["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.options["password"] == "new-secret"
    assert entry.options["scan_interval"] == 60
    await hass.services.async_call("time", "set_value", {"entity_id": start1, "time": "09:45:00"}, blocking=True)
    assert fake.values["40.8533.value"] == "09:45:00"

    await srv.close()


async def test_local_writes_with_remote_user(hass: HomeAssistant, socket_enabled) -> None:
    from mock_server import REMOTE_PASS, REMOTE_USER, FakeLocal

    local = FakeLocal()
    srv = TestServer(local.app())
    await srv.start_server()
    host = str(srv.make_url("")).rstrip("/")
    entry = MockConfigEntry(domain=DOMAIN, unique_id="local_y", data={"connection": "local", "host": host})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    res = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"scan_interval": 60, "remote_user": REMOTE_USER, "remote_password": "wrong"}
    )
    assert res["errors"] == {"base": "remote_login_failed"}
    res = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"scan_interval": 60, "remote_user": REMOTE_USER, "remote_password": REMOTE_PASS}
    )
    assert res["type"] == "create_entry", res
    await hass.async_block_till_done()

    await hass.services.async_call(
        "select", "select_option", {"entity_id": _eid(hass, "select", "_pump_mode"), "option": "on"}, blocking=True
    )
    assert local.values["60.5432.value"] == "1"
    await srv.close()


async def test_diagnostics_redacts_secrets(hass: HomeAssistant, fake: FakeBayrol) -> None:
    from custom_components.bayrol_poolmanager.diagnostics import async_get_config_entry_diagnostics

    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = repr(diag)
    for secret in (USER, PASSWORD, DEVICE):
        assert secret not in text
    assert diag["raw_values"]["34.4001.value"] == "7.22"
    assert diag["intervals"][1]["start"] == "10:00:00"


async def test_writes_are_grouped(hass: HomeAssistant, fake: FakeBayrol) -> None:
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "set_timer_interval", {"interval": 1, "start": "09:00", "end": "19:00"}, blocking=True
    )
    assert fake.set_requests[-1] == {"40.8533.value": "09:00:00", "40.8536.value": "19:00:00"}


async def test_write_not_applied(hass: HomeAssistant, fake: FakeBayrol) -> None:
    await _setup(hass)
    fake.ignore.add("40.8536.value")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "set_timer_interval", {"interval": 1, "end": "19:00"}, blocking=True)
    assert err.value.translation_key == "write_not_applied"
    assert hass.states.get(_eid(hass, "time", "_interval_end_1")).state == "18:00:00"


async def test_empty_active_interval_refused(hass: HomeAssistant, fake: FakeBayrol) -> None:
    await _setup(hass)
    # Interval 1 is active (every day): start == end is refused, nothing is sent
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "time",
            "set_value",
            {"entity_id": _eid(hass, "time", "_interval_start_1"), "time": "18:00:00"},
            blocking=True,
        )
    assert err.value.translation_key == "empty_interval"
    assert fake.set_requests == []
    # Interval 5 is unused (08:00-08:00, no day): activating it alone is refused...
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "set_timer_interval", {"interval": 5, "days": ["mon"]}, blocking=True)
    # ...but fine together with real times; midnight crossing is allowed
    await hass.services.async_call(
        DOMAIN, "set_timer_interval", {"interval": 5, "days": ["mon"], "start": "22:00", "end": "02:00"}, blocking=True
    )
    assert fake.values["40.8540.value"] == "22:00:00"
    # Unused intervals keep start == end without complaint
    await hass.services.async_call(
        DOMAIN, "set_timer_interval", {"interval": 6, "start": "07:00", "end": "07:00"}, blocking=True
    )


async def test_custom_days_option(hass: HomeAssistant, fake: FakeBayrol) -> None:
    await _setup(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": _eid(hass, "select", "_interval_days_1"), "option": "custom"},
            blocking=True,
        )
    assert err.value.translation_key == "custom_days"


async def test_service_targets_device(hass: HomeAssistant, fake: FakeBayrol, socket_enabled) -> None:
    from mock_server import REMOTE_PASS, REMOTE_USER, FakeLocal

    cloud = await _setup(hass)
    local = FakeLocal()
    srv = TestServer(local.app())
    await srv.start_server()
    host = str(srv.make_url("")).rstrip("/")
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="local_z",
        data={"connection": "local", "host": host},
        options={"remote_user": REMOTE_USER, "remote_password": REMOTE_PASS},
    )
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "set_timer_interval", {"interval": 1, "start": "10:15"}, blocking=True)
    assert err.value.translation_key == "device_required"

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "local_z")})
    await hass.services.async_call(
        DOMAIN, "set_timer_interval", {"device_id": device.id, "interval": 1, "start": "10:15"}, blocking=True
    )
    assert local.values["40.8533.value"] == "10:15:00"
    assert fake.values["40.8533.value"] == "10:00:00"

    await hass.services.async_call(
        DOMAIN, "set_timer_interval", {"entry_id": cloud.entry_id, "interval": 1, "start": "10:45"}, blocking=True
    )
    assert fake.values["40.8533.value"] == "10:45:00"
    await srv.close()


async def test_reauth(hass: HomeAssistant, fake: FakeBayrol) -> None:
    entry = await _setup(hass)
    # Password changed on the portal; the portal session expires
    fake.password = "new-secret"
    fake.logged_cookies.clear()
    fake.sessions.clear()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flows = [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == SOURCE_REAUTH]
    assert len(flows) == 1
    flow_id = flows[0]["flow_id"]
    res = await hass.config_entries.flow.async_configure(flow_id, {"username": USER, "password": "wrong"})
    assert res["errors"] == {"base": "invalid_auth"}
    res = await hass.config_entries.flow.async_configure(flow_id, {"username": USER, "password": "new-secret"})
    assert res["type"] == "abort" and res["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data["password"] == "new-secret"
    assert hass.states.get(_eid(hass, "sensor", "_ph")).state == "7.22"


async def test_reconfigure_local_host(hass: HomeAssistant, socket_enabled) -> None:
    from mock_server import FakeLocal

    servers = []
    for _ in range(2):
        srv = TestServer(FakeLocal().app())
        await srv.start_server()
        servers.append(srv)
    old, new = (str(s.make_url("")).rstrip("/") for s in servers)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=f"local_{old}", title=f"PoolManager ({old})", data={"connection": "local", "host": old}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ph = _eid(hass, "sensor", "_ph")

    res = await entry.start_reconfigure_flow(hass)
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"host": new})
    assert res["type"] == "abort" and res["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["host"] == new
    assert entry.unique_id == f"local_{old}"  # kept: entities are not duplicated
    assert _eid(hass, "sensor", "_ph") == ph

    # Adding the device again under its new address is detected
    res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"next_step_id": "local"})
    res = await hass.config_entries.flow.async_configure(res["flow_id"], {"host": new})
    assert res["type"] == "abort" and res["reason"] == "already_configured"
    for srv in servers:
        await srv.close()


async def test_flows_release_sessions(hass: HomeAssistant, fake: FakeBayrol) -> None:
    """Connection tests in config flows must not leave sessions behind."""

    def close_listeners() -> int:
        return hass.bus.async_listeners().get("homeassistant_close", 0)

    async def run_flow() -> None:
        res = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"next_step_id": "cloud"})
        res = await hass.config_entries.flow.async_configure(res["flow_id"], {"username": USER, "password": "bad"})
        hass.config_entries.flow.async_abort(res["flow_id"])

    await run_flow()  # warm-up: shared connector, integration loading
    before = close_listeners()
    for _ in range(3):
        await run_flow()
    assert close_listeners() == before


def test_parse_time() -> None:
    from datetime import time

    from custom_components.bayrol_poolmanager.coordinator import parse_time

    assert parse_time("08:30:00") == time(8, 30)
    assert parse_time("8:30") == time(8, 30)
    assert parse_time("24:00:00") == time(0, 0)
    assert parse_time("25:00:00") is None
    assert parse_time("24:30") is None
    assert parse_time("") is None
    assert parse_time("abc") is None
