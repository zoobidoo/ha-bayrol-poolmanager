"""End-to-end tests in a real Home Assistant instance against the fake portal."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.bayrol_poolmanager import api
from custom_components.bayrol_poolmanager.const import DOMAIN
from mock_server import DEVICE, PASSWORD, USER, FakeBayrol


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
        DOMAIN, "set_timer_interval",
        {"interval": 2, "end": "03:00", "days": ["mon", "wed", "fri"], "mode": "eco"},
        blocking=True,
    )
    assert fake.values["40.8537.value"] == "03:00:00"
    assert fake.values["36.5204.value"] == str(1 | 4 | 16)
    assert fake.values["35.5185.value"] == "4"
    assert hass.states.get(_eid(hass, "select", "_interval_days_2")).state == "custom"

    # Pump mode
    await hass.services.async_call("select", "select_option", {"entity_id": _eid(hass, "select", "_pump_mode"), "option": "off"}, blocking=True)
    assert fake.values["60.5432.value"] == "4"


async def test_unload(hass: HomeAssistant, fake: FakeBayrol) -> None:
    entry = await _setup(hass)
    assert hass.services.has_service(DOMAIN, "set_timer_interval")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "set_timer_interval")


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
    auto = yaml.safe_load((pathlib.Path(__file__).parents[1] / "examples" / "automation_filtration_temperature.yaml").read_text())
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
    from homeassistant.exceptions import HomeAssistantError
    with pytest.raises(HomeAssistantError, match="refused"):
        await hass.services.async_call("time", "set_value", {"entity_id": start1, "time": "10:00:00"}, blocking=True)

    # Options: portal credentials -> writes through the cloud
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    res = await hass.config_entries.options.async_configure(flow["flow_id"], {"scan_interval": 60, "username": USER, "password": PASSWORD})
    assert res["type"] == "create_entry", res
    await hass.async_block_till_done()
    await hass.services.async_call("time", "set_value", {"entity_id": start1, "time": "09:30:00"}, blocking=True)
    assert ("40.8533.value", "09:30:00") in fake.writes

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
