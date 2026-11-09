"""Application credentials for the Alacart integration.

A developer can sign in with the client id of their own developer app. The sign-in goes to the
server that `configuration.yaml` picks, which is production unless it says otherwise.
"""

from homeassistant.components.application_credentials import ClientCredential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2ImplementationWithPkce,
)

from .const import authorize_url, token_url
from .oauth import configured_server


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> LocalOAuth2ImplementationWithPkce:
    """Return a sign-in with PKCE for a developer app's credentials."""
    server = configured_server(hass)
    return LocalOAuth2ImplementationWithPkce(
        hass,
        auth_domain,
        credential.client_id,
        authorize_url(server),
        token_url(server),
        credential.client_secret,
    )
