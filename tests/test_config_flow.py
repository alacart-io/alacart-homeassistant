"""Tests of linking an Alacart account."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from alacart import AlacartConnectionError, PremiumRequiredError
from homeassistant import config_entries
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.alacart.const import DOMAIN, Server
from custom_components.alacart.oauth import configured_server

from .conftest import ACCOUNT_ID, ME

REDIRECT_URI = "https://my.home-assistant.io/redirect/oauth"
TOKEN = {
    "access_token": "access-new",
    "refresh_token": "refresh-new",
    "expires_in": 3600,
    "token_type": "Bearer",
}


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[AsyncMock]:
    """Keep the created entries from setting up, so these tests stay on the flow."""
    with patch("custom_components.alacart.async_setup_entry", return_value=True) as mock:
        yield mock


@pytest.fixture
def mock_get_me() -> Generator[AsyncMock]:
    with patch(
        "custom_components.alacart.config_flow.AlacartClient.get_me", return_value=ME
    ) as mock:
        yield mock


async def _start_sign_in(hass: HomeAssistant) -> tuple[str, dict[str, list[str]], str]:
    """Start a flow and return its id, the sign-in URL's parameters, and its host."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return _external_step(result)


def _external_step(
    result: config_entries.ConfigFlowResult,
) -> tuple[str, dict[str, list[str]], str]:
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    url = urlparse(result["url"])
    return result["flow_id"], parse_qs(url.query), f"{url.scheme}://{url.netloc}{url.path}"


async def _finish_sign_in(
    hass: HomeAssistant,
    hass_client_no_auth,
    aioclient_mock: AiohttpClientMocker,
    flow_id: str,
    params: dict[str, list[str]],
    token_url: str,
) -> config_entries.ConfigFlowResult:
    client = await hass_client_no_auth()
    response = await client.get(f"/auth/external/callback?code=abcd&state={params['state'][0]}")
    assert response.status == 200
    aioclient_mock.post(token_url, json=TOKEN)
    return await hass.config_entries.flow.async_configure(flow_id)


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_sign_in_to_production(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock: AiohttpClientMocker
) -> None:
    flow_id, params, authorize = await _start_sign_in(hass)

    assert authorize == "https://auth.alacart.io/connect/authorize"
    assert params["client_id"] == ["home-assistant"]
    assert params["redirect_uri"] == [REDIRECT_URI]
    assert params["scope"] == ["read write"]
    assert params["code_challenge_method"] == ["S256"]
    expected_state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": flow_id, "redirect_uri": REDIRECT_URI}
    )
    assert params["state"] == [expected_state]

    result = await _finish_sign_in(
        hass,
        hass_client_no_auth,
        aioclient_mock,
        flow_id,
        params,
        "https://auth.alacart.io/connect/token",
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kim Andersson"
    entry = result["result"]
    assert entry.unique_id == f"production_{ACCOUNT_ID}"
    assert entry.data["server"] == "production"
    assert entry.data["auth_implementation"] == DOMAIN
    assert entry.data["token"]["access_token"] == "access-new"

    token_request = aioclient_mock.mock_calls[-1][2]
    assert token_request["client_id"] == "home-assistant"
    assert "client_secret" not in token_request
    assert len(token_request["code_verifier"]) >= 43


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_each_sign_in_gets_its_own_code_verifier(hass: HomeAssistant) -> None:
    _, first, _ = await _start_sign_in(hass)
    _, second, _ = await _start_sign_in(hass)

    assert first["code_challenge"] != second["code_challenge"]


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_the_yaml_switch_signs_in_to_beta(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock: AiohttpClientMocker
) -> None:
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {"server": "beta"}})

    flow_id, params, authorize = await _start_sign_in(hass)

    assert authorize == "https://auth.test.alacart.io/connect/authorize"
    assert params["client_id"] == ["home-assistant"]
    result = await _finish_sign_in(
        hass,
        hass_client_no_auth,
        aioclient_mock,
        flow_id,
        params,
        "https://auth.test.alacart.io/connect/token",
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kim Andersson (beta)"
    entry = result["result"]
    assert entry.unique_id == f"beta_{ACCOUNT_ID}"
    assert entry.data["server"] == "beta"
    assert entry.data["auth_implementation"] == f"{DOMAIN}_beta"


async def test_an_unknown_server_in_yaml_is_refused(hass: HomeAssistant) -> None:
    assert not await async_setup_component(hass, DOMAIN, {DOMAIN: {"server": "staging"}})


@pytest.mark.usefixtures("current_request_with_host")
async def test_an_account_without_premium_is_refused(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock: AiohttpClientMocker
) -> None:
    flow_id, params, _ = await _start_sign_in(hass)
    with patch(
        "custom_components.alacart.config_flow.AlacartClient.get_me",
        side_effect=PremiumRequiredError(403, "premium_required", "No premium."),
    ):
        result = await _finish_sign_in(
            hass,
            hass_client_no_auth,
            aioclient_mock,
            flow_id,
            params,
            "https://auth.alacart.io/connect/token",
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "premium_required"


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_the_same_account_cannot_be_linked_twice(
    hass: HomeAssistant,
    hass_client_no_auth,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    flow_id, params, _ = await _start_sign_in(hass)

    result = await _finish_sign_in(
        hass,
        hass_client_no_auth,
        aioclient_mock,
        flow_id,
        params,
        "https://auth.alacart.io/connect/token",
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_signing_in_again_updates_the_entry(
    hass: HomeAssistant,
    hass_client_no_auth,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    mock_setup_entry: AsyncMock,
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    flow_id, params, authorize = _external_step(result)
    assert authorize == "https://auth.alacart.io/connect/authorize"
    result = await _finish_sign_in(
        hass,
        hass_client_no_auth,
        aioclient_mock,
        flow_id,
        params,
        "https://auth.alacart.io/connect/token",
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["token"]["access_token"] == "access-new"
    assert config_entry.data["token"]["refresh_token"] == "refresh-new"
    assert config_entry.data["server"] == "production"
    await hass.async_block_till_done()
    assert mock_setup_entry.await_count == 1


@pytest.mark.usefixtures("current_request_with_host")
async def test_signing_in_again_with_another_account_is_refused(
    hass: HomeAssistant,
    hass_client_no_auth,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    flow_id, params, _ = _external_step(result)

    other = type(ME)(id="999", display_name=None, premium_expires_at=None, is_family_premium=False)
    with patch("custom_components.alacart.config_flow.AlacartClient.get_me", return_value=other):
        result = await _finish_sign_in(
            hass,
            hass_client_no_auth,
            aioclient_mock,
            flow_id,
            params,
            "https://auth.alacart.io/connect/token",
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_a_beta_entry_signs_in_again_to_beta_without_the_yaml_switch(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    beta_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kim Andersson (beta)",
        unique_id=f"beta_{ACCOUNT_ID}",
        data={**config_entry.data, "auth_implementation": f"{DOMAIN}_beta", "server": "beta"},
    )
    beta_entry.add_to_hass(hass)

    result = await beta_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    _, _, authorize = _external_step(result)
    assert authorize == "https://auth.test.alacart.io/connect/authorize"


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_a_developer_can_sign_in_with_their_own_app(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock: AiohttpClientMocker
) -> None:
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential("my-app", "my-secret"), "my_app"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick_implementation"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": "my_app"}
    )
    flow_id, params, authorize = _external_step(result)
    assert authorize == "https://auth.alacart.io/connect/authorize"
    assert params["client_id"] == ["my-app"]

    result = await _finish_sign_in(
        hass,
        hass_client_no_auth,
        aioclient_mock,
        flow_id,
        params,
        "https://auth.alacart.io/connect/token",
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data["server"] == "production"
    assert result["result"].data["auth_implementation"] == "my_app"
    assert aioclient_mock.mock_calls[-1][2]["client_secret"] == "my-secret"


async def test_a_bare_yaml_key_keeps_production(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: None})

    assert configured_server(hass) is Server.PRODUCTION


@pytest.mark.usefixtures("current_request_with_host")
async def test_an_unreachable_api_aborts_the_flow(
    hass: HomeAssistant, hass_client_no_auth, aioclient_mock: AiohttpClientMocker
) -> None:
    flow_id, params, _ = await _start_sign_in(hass)
    with patch(
        "custom_components.alacart.config_flow.AlacartClient.get_me",
        side_effect=AlacartConnectionError("down"),
    ):
        result = await _finish_sign_in(
            hass,
            hass_client_no_auth,
            aioclient_mock,
            flow_id,
            params,
            "https://auth.alacart.io/connect/token",
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_a_developer_app_entry_signs_in_again_on_its_own_server(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential("my-app", "my-secret"), "my_app"
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kim Andersson (beta)",
        unique_id=f"beta_{ACCOUNT_ID}",
        data={**config_entry.data, "auth_implementation": "my_app", "server": "beta"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    _, params, authorize = _external_step(result)
    assert authorize == "https://auth.test.alacart.io/connect/authorize"
    assert params["client_id"] == ["my-app"]


@pytest.mark.usefixtures("current_request_with_host", "mock_get_me")
async def test_signing_in_again_after_the_credentials_are_gone_keeps_the_server(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    assert await async_setup_component(hass, "application_credentials", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kim Andersson (beta)",
        unique_id=f"beta_{ACCOUNT_ID}",
        data={**config_entry.data, "auth_implementation": "deleted_app", "server": "beta"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    _, params, authorize = _external_step(result)
    assert authorize == "https://auth.test.alacart.io/connect/authorize"
    assert params["client_id"] == ["home-assistant"]
