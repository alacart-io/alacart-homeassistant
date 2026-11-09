"""Constants for the Alacart integration."""

from datetime import timedelta
from enum import StrEnum
import logging
from typing import Final

from homeassistant.util.hass_dict import HassKey

from alacart import (
    API_URL,
    AUTH_URL,
    AUTHORIZE_PATH,
    BETA_API_URL,
    BETA_AUTH_URL,
    SCOPE_READ,
    SCOPE_WRITE,
    TOKEN_PATH,
)

DOMAIN: Final = "alacart"
LOGGER = logging.getLogger(__package__)

CLIENT_ID: Final = "home-assistant"
"""The client id that Alacart created for this integration. It has no secret."""

SCOPES: Final = f"{SCOPE_READ} {SCOPE_WRITE}"

CONF_SERVER: Final = "server"


class Server(StrEnum):
    """The Alacart environments the integration can talk to."""

    PRODUCTION = "production"
    BETA = "beta"
    """Beta holds test data. Only testers and developers of the integration use it."""


API_URLS: Final = {Server.PRODUCTION: API_URL, Server.BETA: BETA_API_URL}
AUTH_URLS: Final = {Server.PRODUCTION: AUTH_URL, Server.BETA: BETA_AUTH_URL}


def authorize_url(server: Server) -> str:
    """Return the authorization endpoint of a server's sign-in server."""
    return f"{AUTH_URLS[server]}{AUTHORIZE_PATH}"


def token_url(server: Server) -> str:
    """Return the token endpoint of a server's sign-in server."""
    return f"{AUTH_URLS[server]}{TOKEN_PATH}"


BUILTIN_IMPLEMENTATIONS: Final = {
    Server.PRODUCTION: DOMAIN,
    Server.BETA: f"{DOMAIN}_beta",
}
"""The key that a config entry stores for each server's built-in sign-in."""

DATA_SERVER: HassKey[Server] = HassKey(f"{DOMAIN}_server")
"""The server that `configuration.yaml` picks for new config entries."""

UPDATE_INTERVAL: Final = timedelta(minutes=5)
ITEM_LISTS_MAX_AGE: Final = timedelta(hours=1)
"""How long the integration trusts its copy of the user's lists before it reads them again."""
