"""Config and options flows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
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


def _opt(key: str, current: Mapping[str, Any]) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": current.get(key)})


@asynccontextmanager
async def _temp_session(hass: HomeAssistant) -> AsyncIterator[aiohttp.ClientSession]:
    """Short-lived session for a connection test, released right after it."""
    session = async_create_clientsession(hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar(unsafe=True))
    try:
        yield session
    finally:
        session.detach()


class BayrolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=[CONNECTION_LOCAL, CONNECTION_CLOUD])

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            async with _temp_session(self.hass) as session:
                client = BayrolClient(
                    session,
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
            # The unique id keeps the host used at creation time (entity ids
            # derive from it); an entry moved to a new IP is matched by host.
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            async with _temp_session(self.hass) as session:
                client = BayrolClient(session, host=user_input[CONF_HOST], access_code=user_input.get(CONF_ACCESS_CODE))
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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """New Bayrol portal password (cloud entry, or cloud writes of a local entry)."""
        entry = self._get_reauth_entry()
        local = entry.data.get(CONF_CONNECTION) == CONNECTION_LOCAL
        current = entry.options if local else entry.data
        errors: dict[str, str] = {}
        if user_input is not None:
            async with _temp_session(self.hass) as session:
                client = BayrolClient(
                    session,
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    device_id=current.get(CONF_DEVICE_ID) or None,
                )
                errors = await self._test(client)
            if not errors:
                if local:
                    return self.async_update_reload_and_abort(entry, options={**entry.options, **user_input})
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=current.get(CONF_USERNAME, "")): _EMAIL,
                vol.Required(CONF_PASSWORD): _PASSWORD,
            }
        )
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the IP address (local) or the credentials (cloud) without re-creating the entry."""
        entry = self._get_reconfigure_entry()
        local = entry.data.get(CONF_CONNECTION) == CONNECTION_LOCAL
        errors: dict[str, str] = {}
        if user_input is not None:
            if local and user_input[CONF_HOST] != entry.data.get(CONF_HOST):
                self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            async with _temp_session(self.hass) as session:
                if local:
                    client = BayrolClient(session, host=user_input[CONF_HOST])
                else:
                    client = BayrolClient(
                        session,
                        username=user_input[CONF_USERNAME],
                        password=user_input[CONF_PASSWORD],
                        device_id=entry.data.get(CONF_DEVICE_ID),
                    )
                errors = await self._test(client)
            if not errors:
                # The unique id is kept on purpose: entity unique ids derive from it.
                return self.async_update_reload_and_abort(
                    entry,
                    title=f"PoolManager ({user_input[CONF_HOST]})" if local else entry.title,
                    data_updates={CONF_ACCESS_CODE: "", **user_input},
                )
        current = {**entry.data, **(user_input or {})}
        if local:
            fields = {vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): str}
        else:
            fields = {
                vol.Required(CONF_USERNAME, default=current.get(CONF_USERNAME, "")): _EMAIL,
                vol.Required(CONF_PASSWORD): _PASSWORD,
            }
        fields[_opt(CONF_ACCESS_CODE, current)] = str
        return self.async_show_form(step_id="reconfigure", data_schema=vol.Schema(fields), errors=errors)

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
                async with _temp_session(self.hass) as session:
                    client = BayrolClient(
                        session,
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
        """Check that the remote user can log in on the local device.

        The check writes the current start time of interval 6 back to the
        device (same value, nothing changes) to prove that writes are accepted.
        """
        async with _temp_session(self.hass) as session:
            client = BayrolClient(
                session,
                host=self.config_entry.data[CONF_HOST],
                remote_user=user_input[CONF_REMOTE_USER],
                remote_password=user_input.get(CONF_REMOTE_PASSWORD),
            )
            return await self._probe_write(client)

    @staticmethod
    async def _probe_write(client: BayrolClient) -> dict[str, str]:
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
