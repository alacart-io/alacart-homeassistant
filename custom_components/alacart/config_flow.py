"""Config flow that links an Alacart account to Home Assistant."""

from collections.abc import Mapping
import logging
from typing import Any, override

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from alacart import (
    AlacartClient,
    AlacartError,
    InvalidTokenError,
    PremiumRequiredError,
    StaticTokenAuth,
)

from .const import API_URLS, CONF_SERVER, DOMAIN, LOGGER, SCOPES, Server
from .oauth import (
    AlacartImplementation,
    async_get_reauth_implementation,
    async_register_builtin_implementation,
    configured_server,
)


class AlacartFlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Signs the user in to Alacart and creates one config entry per account."""

    DOMAIN = DOMAIN

    @property
    @override
    def logger(self) -> logging.Logger:
        return LOGGER

    @property
    @override
    def extra_authorize_data(self) -> dict[str, Any]:
        return {"scope": SCOPES}

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        async_register_builtin_implementation(self.hass)
        return await super().async_step_user(user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Ask the user to sign in again after Alacart refused the token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then sign in again with the entry's own server and sign-in method."""
        entry = self._get_reauth_entry()
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders={"account": entry.title},
            )
        async_register_builtin_implementation(self.hass)
        # The configured server may have changed since the entry was created, so the entry's
        # own server picks the sign-in.
        self.flow_impl = await async_get_reauth_implementation(self.hass, entry)
        return await self.async_step_auth()

    @override
    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Identify the account, then create the entry or update the one being reauthorized."""
        server = self._server()
        client = AlacartClient(
            StaticTokenAuth(
                async_get_clientsession(self.hass),
                API_URLS[server],
                data["token"]["access_token"],
            )
        )
        try:
            me = await client.get_me()
        except PremiumRequiredError:
            return self.async_abort(reason="premium_required")
        except InvalidTokenError:
            return self.async_abort(reason="oauth_unauthorized")
        except AlacartError as err:
            LOGGER.warning("Could not read the Alacart account: %s", err)
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(f"{server}_{me.id}")
        data[CONF_SERVER] = server.value

        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)

        self._abort_if_unique_id_configured()
        title = me.display_name or "Alacart"
        if server is Server.BETA:
            title = f"{title} (beta)"
        return self.async_create_entry(title=title, data=data)

    def _server(self) -> Server:
        if self.source == SOURCE_REAUTH:
            return Server(self._get_reauth_entry().data[CONF_SERVER])
        if isinstance(self.flow_impl, AlacartImplementation):
            return self.flow_impl.server
        # A developer's application credentials sign in to the configured server.
        return configured_server(self.hass)
