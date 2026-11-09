"""The Alacart integration shows each Alacart shopping list as a to-do list."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.helpers.typing import ConfigType
import probatio

from alacart import AlacartClient

from .api import ConfigEntryAuth
from .const import API_URLS, CONF_SERVER, DATA_SERVER, DOMAIN, Server
from .coordinator import AlacartConfigEntry, AlacartCoordinator
from .oauth import async_get_entry_implementation, async_register_builtin_implementation

PLATFORMS: list[Platform] = [Platform.TODO]

# Testers and developers of the integration set `server: beta` to sign in to Alacart's beta,
# which holds test data. Ordinary users never set it, so the user interface never offers it.
CONFIG_SCHEMA = probatio.Schema(
    {
        # A bare `alacart:` line, with nothing under it, leaves the server at production.
        DOMAIN: probatio.Any(
            None,
            probatio.Schema(
                {
                    probatio.Optional(CONF_SERVER, default=Server.PRODUCTION.value): probatio.In(
                        [server.value for server in Server]
                    )
                }
            ),
        )
    },
    extra=probatio.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Read the server that new config entries sign in to."""
    if config.get(DOMAIN):
        hass.data[DATA_SERVER] = Server(config[DOMAIN][CONF_SERVER])
    async_register_builtin_implementation(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AlacartConfigEntry) -> bool:
    """Set up one Alacart account."""
    async_register_builtin_implementation(hass)
    implementation = await async_get_entry_implementation(hass, entry)
    session = OAuth2Session(hass, entry, implementation)
    auth = ConfigEntryAuth(
        async_get_clientsession(hass), API_URLS[Server(entry.data[CONF_SERVER])], session
    )
    coordinator = AlacartCoordinator(hass, entry, AlacartClient(auth))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlacartConfigEntry) -> bool:
    """Unload one Alacart account."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
