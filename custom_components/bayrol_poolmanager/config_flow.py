"""Config and options flows."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import BayrolAuthError, BayrolClient, BayrolError, BayrolWriteRefused
from .const import (
    CONF_ACCESS_CODE,
    CONF_CONNECTION,
    CONF_DEVICE_ID,
    CONF_REMOTE_PASSWORD,
    CONF_REMOTE_USER,
    CONF_SCAN_INTERVAL,
    CONNECTION_CLOUD,
    CONNECTION_LOCAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ITEM_PH,
    MIN_SCAN_INTERVAL,
    TIMER_INTERVALS,
)

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
# Hint browsers not to auto-fill the Home Assistant login here.
_EMAIL = TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="off"))


def _opt(key: str, current: dict[str, Any]) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": current.get(key)})


class BayrolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=[CONNECTION_LOCAL, CONNECTION_CLOUD])

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = BayrolClient(
                self._session(),
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                device_id=user_input.get(CONF_DEVICE_ID) or None,
                access_code=user_input.get(CONF_ACCESS_CODE),
            )
            errors = await self._test(client)
            if not errors:
                await self.async_set_unique_id(f"cloud_{client.device_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"PoolManager ({client.device_id})",
                    data={**user_input, CONF_CONNECTION: CONNECTION_CLOUD, CONF_DEVICE_ID: client.device_id},
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): _EMAIL,
                vol.Required(CONF_PASSWORD): _PASSWORD,
                vol.Optional(CONF_DEVICE_ID): str,
                vol.Optional(CONF_ACCESS_CODE): str,
            }
        )
        return self.async_show_form(
            step_id="cloud", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors
        )

    async def async_step_local(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = BayrolClient(self._session(), host=user_input[CONF_HOST], access_code=user_input.get(CONF_ACCESS_CODE))
            errors = await self._test(client)
            if not errors:
                await self.async_set_unique_id(f"local_{user_input[CONF_HOST]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"PoolManager ({user_input[CONF_HOST]})",
                    data={**user_input, CONF_CONNECTION: CONNECTION_LOCAL},
                )
        schema = vol.Schema({vol.Required(CONF_HOST): str, vol.Optional(CONF_ACCESS_CODE): str})
        return self.async_show_form(
            step_id="local", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors
        )

    def _session(self) -> aiohttp.ClientSession:
        return async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar(unsafe=True))

    @staticmethod
    async def _test(client: BayrolClient) -> dict[str, str]:
        try:
            values = await client.async_get([ITEM_PH])
        except BayrolAuthError:
            return {"base": "invalid_auth"}
        except (BayrolError, aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("PoolManager connection test failed: %r", err)
            return {"base": "cannot_connect"}
        if values.get(ITEM_PH) in (None, ""):
            return {"base": "no_data"}
        return {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BayrolOptionsFlow()


class BayrolOptionsFlow(OptionsFlow):
    """Options: polling interval, and how local entries perform writes."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        local = self.config_entry.data.get(CONF_CONNECTION) == CONNECTION_LOCAL
        opts = self.config_entry.options
        errors: dict[str, str] = {}
        if user_input is not None:
            if local and user_input.get(CONF_REMOTE_USER):
                errors = await self._test_local_write(user_input)
            elif local and user_input.get(CONF_USERNAME) and user_input.get(CONF_PASSWORD):
                client = BayrolClient(
                    async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar(unsafe=True)),
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    device_id=user_input.get(CONF_DEVICE_ID) or None,
                )
                errors = await BayrolConfigFlow._test(client)
                if not errors:
                    user_input[CONF_DEVICE_ID] = client.device_id
            if not errors:
                return self.async_create_entry(data=user_input)
        current = {**opts, **(user_input or {})}
        fields: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL, default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)
            )
        }
        if local:
            fields[_opt(CONF_REMOTE_USER, current)] = str
            fields[_opt(CONF_REMOTE_PASSWORD, current)] = _PASSWORD
            fields[_opt(CONF_USERNAME, current)] = _EMAIL
            fields[_opt(CONF_PASSWORD, current)] = _PASSWORD
            fields[_opt(CONF_DEVICE_ID, current)] = str
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields), errors=errors)

    async def _test_local_write(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Check that the remote user can log in on the local device."""
        client = BayrolClient(
            async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar(unsafe=True)),
            host=self.config_entry.data[CONF_HOST],
            remote_user=user_input[CONF_REMOTE_USER],
            remote_password=user_input.get(CONF_REMOTE_PASSWORD),
        )
        probe = TIMER_INTERVALS[6]["on"]
        try:
            current = (await client.async_get([probe]))[probe]
            if not client.remote_logged_in or not current:
                return {"base": "remote_login_failed"}
            # No-op write (same value) to prove the device accepts writes.
            await client.async_set({probe: current})
        except BayrolWriteRefused:
            return {"base": "remote_login_failed"}
        except (BayrolError, aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("PoolManager remote login test failed: %r", err)
            return {"base": "cannot_connect"}
        return {}
