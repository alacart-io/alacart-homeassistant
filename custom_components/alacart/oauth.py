"""Sign-in implementations for the Alacart integration."""

from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2Implementation,
    LocalOAuth2Implementation,
    LocalOAuth2ImplementationWithPkce,
    async_add_implementation_provider,
    async_get_config_entry_implementation,
    async_get_implementations,
)

from .const import (
    BUILTIN_IMPLEMENTATIONS,
    CLIENT_ID,
    CONF_SERVER,
    DATA_SERVER,
    DOMAIN,
    Server,
    authorize_url,
    token_url,
)

_PROVIDER: str = f"{DOMAIN}_builtin"


class AlacartImplementation(LocalOAuth2ImplementationWithPkce):
    """Signs in with the client id that Alacart created for Home Assistant.

    Each instance makes its own PKCE code verifier, so every sign-in gets a fresh one.
    """

    def __init__(self, hass: HomeAssistant, server: Server) -> None:
        super().__init__(
            hass,
            BUILTIN_IMPLEMENTATIONS[server],
            CLIENT_ID,
            authorize_url(server),
            token_url(server),
        )
        self.server = server

    @property
    @override
    def name(self) -> str:
        return "Alacart" if self.server is Server.PRODUCTION else "Alacart beta"


def configured_server(hass: HomeAssistant) -> Server:
    """Return the server that `configuration.yaml` picks, production when it picks none."""
    return hass.data.get(DATA_SERVER, Server.PRODUCTION)


def builtin_server(implementation_key: str) -> Server | None:
    """Return the server of a built-in sign-in, or None for application credentials."""
    for server, key in BUILTIN_IMPLEMENTATIONS.items():
        if key == implementation_key:
            return server
    return None


@callback
def async_register_builtin_implementation(hass: HomeAssistant) -> None:
    """Offer the built-in sign-in for the configured server to new config flows.

    Calling it again does nothing new. A provider makes a new implementation for each flow, so
    no two sign-ins share a PKCE code verifier.
    """
    async_add_implementation_provider(hass, _PROVIDER, _async_provide_implementations)


async def _async_provide_implementations(
    hass: HomeAssistant, domain: str
) -> list[AbstractOAuth2Implementation]:
    if domain != DOMAIN:
        return []
    return [AlacartImplementation(hass, configured_server(hass))]


def credentials_implementation(
    hass: HomeAssistant, implementation: AbstractOAuth2Implementation, server: Server
) -> AbstractOAuth2Implementation:
    """Return a developer app's sign-in, pointed at `server`.

    Home Assistant builds an application credentials implementation for the server that
    `configuration.yaml` picks now. An entry must keep the server it was created with, so the
    implementation is rebuilt with the same client for the entry's server.
    """
    if not isinstance(implementation, LocalOAuth2Implementation):
        return implementation
    return LocalOAuth2ImplementationWithPkce(
        hass,
        implementation.domain,
        implementation.client_id,
        authorize_url(server),
        token_url(server),
        implementation.client_secret,
    )


async def async_get_entry_implementation(
    hass: HomeAssistant, entry: ConfigEntry
) -> AbstractOAuth2Implementation:
    """Return the sign-in implementation that refreshes an entry's tokens.

    The sign-in keeps the server the entry was created with, even when `configuration.yaml` now
    picks another.
    """
    server = Server(entry.data[CONF_SERVER])
    if builtin_server(entry.data["auth_implementation"]) is not None:
        return AlacartImplementation(hass, server)
    implementation = await async_get_config_entry_implementation(hass, entry)
    return credentials_implementation(hass, implementation, server)


async def async_get_reauth_implementation(
    hass: HomeAssistant, entry: ConfigEntry
) -> AbstractOAuth2Implementation:
    """Return the sign-in for reauthorizing an entry on its own server."""
    server = Server(entry.data[CONF_SERVER])
    key = entry.data["auth_implementation"]
    if builtin_server(key) is not None:
        return AlacartImplementation(hass, server)
    implementation = (await async_get_implementations(hass, DOMAIN)).get(key)
    if implementation is None:
        # The user deleted the entry's application credentials, so the built-in sign-in for
        # the entry's server takes over.
        return AlacartImplementation(hass, server)
    return credentials_implementation(hass, implementation, server)
