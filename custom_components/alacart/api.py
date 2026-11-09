"""Authentication for the Alacart library, tied to a config entry's OAuth session."""

from typing import cast, override

from aiohttp import ClientSession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from alacart import AbstractAuth


class ConfigEntryAuth(AbstractAuth):
    """Gives the Alacart client the config entry's access token, refreshed when needed.

    A failed refresh raises Home Assistant's OAuth errors, and the client passes them on
    unchanged.
    """

    def __init__(self, websession: ClientSession, host: str, oauth_session: OAuth2Session) -> None:
        super().__init__(websession, host)
        self._oauth_session = oauth_session

    @override
    async def async_get_access_token(self) -> str:
        await self._oauth_session.async_ensure_token_valid()
        return cast(str, self._oauth_session.token["access_token"])
