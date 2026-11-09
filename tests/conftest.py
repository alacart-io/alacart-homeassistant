"""Shared fixtures for the Alacart integration's tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
import time
from unittest.mock import AsyncMock, MagicMock, patch

from alacart import Item, ItemList, ItemLists, Items, Me
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alacart.const import DOMAIN

ACCOUNT_ID = "481516"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from `custom_components`."""


@pytest.fixture(autouse=True)
def my_integration_loaded(hass: HomeAssistant) -> None:
    """Treat Home Assistant's `my` integration as loaded, as it is in a real instance.

    The integration depends on `my`, which needs the frontend that the test package leaves out.
    With `my` loaded, the sign-in redirects through `my.home-assistant.io`.
    """
    hass.config.components.add("my")


def make_item(
    item_id: str,
    text: str,
    *,
    list_id: str = "1",
    is_checked: bool = False,
    is_permanent: bool = False,
) -> Item:
    return Item(
        id=item_id,
        list_id=list_id,
        text=text,
        is_checked=is_checked,
        is_permanent=is_permanent,
        added_at=NOW,
        updated_at=NOW,
    )


def make_list(list_id: str, name: str) -> ItemList:
    return ItemList(id=list_id, name=name, is_default=list_id == "1", is_private=False)


ME = Me(
    id=ACCOUNT_ID, display_name="Kim Andersson", premium_expires_at=None, is_family_premium=False
)
LISTS = [make_list("1", "Handla"), make_list("2", "Bygghandeln")]
ITEMS = [
    make_item("11", "2 l mjölk"),
    make_item("12", "bröd", is_checked=True),
    make_item("21", "skruv", list_id="2"),
]


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A production entry with a token that is still valid."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Kim Andersson",
        unique_id=f"production_{ACCOUNT_ID}",
        data={
            "auth_implementation": DOMAIN,
            "server": "production",
            "token": {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
                "expires_at": time.time() + 3600,
                "token_type": "Bearer",
            },
        },
    )


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Replace the Alacart client that the integration creates for each entry."""
    with patch("custom_components.alacart.AlacartClient", autospec=True) as client_class:
        client = client_class.return_value
        client.get_items = AsyncMock(return_value=Items(items=list(ITEMS), etag='"i1"'))
        client.get_item_lists = AsyncMock(
            return_value=ItemLists(item_lists=list(LISTS), etag='"l1"')
        )
        yield client
