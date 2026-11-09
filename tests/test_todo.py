"""Tests of the to-do lists and the polling behind them."""

from __future__ import annotations

from datetime import timedelta
import time
from unittest.mock import MagicMock

from alacart import (
    AlacartConnectionError,
    InsufficientScopeError,
    InvalidTokenError,
    ItemLists,
    Items,
    LimitReachedError,
    NotFoundError,
    PremiumRequiredError,
    RateLimitedError,
)
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.components.todo import DOMAIN as TODO_DOMAIN, TodoServices
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.alacart.const import DOMAIN

from .conftest import ITEMS, LISTS, make_item, make_list

HANDLA = "todo.handla"
BYGG = "todo.bygghandeln"


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: int = 5) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _items_of(hass: HomeAssistant, entity_id: str) -> list[dict[str, str]]:
    result = await hass.services.async_call(
        TODO_DOMAIN,
        TodoServices.GET_ITEMS,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
        return_response=True,
    )
    return result[entity_id]["items"]  # type: ignore[index, return-value]


@pytest.mark.usefixtures("mock_client")
async def test_each_list_becomes_a_todo_list(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await _set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(HANDLA).state == "1"
    assert hass.states.get(BYGG).state == "1"
    assert await _items_of(hass, HANDLA) == [
        {"uid": "11", "summary": "2 l mjölk", "status": "needs_action"},
        {"uid": "12", "summary": "bröd", "status": "completed"},
    ]


async def test_polls_send_the_etag_and_keep_items_when_unchanged(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _set_up(hass, config_entry)
    mock_client.get_items.reset_mock()
    mock_client.get_items.return_value = None

    await _poll(hass, freezer)

    mock_client.get_items.assert_awaited_once_with(etag='"i1"')
    assert hass.states.get(HANDLA).state == "1"


async def test_lists_are_read_again_only_when_needed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _set_up(hass, config_entry)
    assert mock_client.get_item_lists.await_count == 1

    await _poll(hass, freezer)
    assert mock_client.get_item_lists.await_count == 1

    # An item on a list the integration does not know makes it read the lists at once.
    mock_client.get_items.return_value = Items(
        items=[*ITEMS, make_item("31", "ballonger", list_id="3")], etag='"i2"'
    )
    mock_client.get_item_lists.return_value = ItemLists(
        item_lists=[*LISTS, make_list("3", "Fest")], etag='"l2"'
    )
    await _poll(hass, freezer)
    assert mock_client.get_item_lists.await_count == 2
    mock_client.get_item_lists.assert_awaited_with(etag='"l1"')
    assert hass.states.get("todo.fest").state == "1"

    # Otherwise it reads them again once an hour, which catches a renamed or removed list.
    mock_client.get_items.return_value = None
    mock_client.get_item_lists.return_value = ItemLists(item_lists=[LISTS[0]], etag='"l3"')
    await _poll(hass, freezer, minutes=60)
    assert mock_client.get_item_lists.await_count == 3
    entity_registry = er.async_get(hass)
    assert entity_registry.async_get(BYGG) is None
    assert hass.states.get(BYGG) is None


async def test_adding_an_item(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)
    mock_client.get_items.reset_mock()

    await hass.services.async_call(
        TODO_DOMAIN,
        TodoServices.ADD_ITEM,
        {ATTR_ENTITY_ID: HANDLA, "item": "ägg"},
        blocking=True,
    )

    mock_client.add_items.assert_awaited_once_with(["ägg"], list_id="1")
    mock_client.get_items.assert_awaited_once()


async def test_renaming_and_checking_an_item(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)

    await hass.services.async_call(
        TODO_DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ENTITY_ID: HANDLA, "item": "11", "rename": "1 l mjölk", "status": "completed"},
        blocking=True,
    )

    mock_client.change_item.assert_awaited_once_with("11", text="1 l mjölk", is_checked=True)


async def test_unchecking_an_item_sends_only_the_check(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)

    await hass.services.async_call(
        TODO_DOMAIN,
        TodoServices.UPDATE_ITEM,
        {ATTR_ENTITY_ID: HANDLA, "item": "bröd", "status": "needs_action"},
        blocking=True,
    )

    mock_client.change_item.assert_awaited_once_with("12", text=None, is_checked=False)


async def test_removing_items_ignores_an_item_already_gone(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)
    mock_client.remove_item.side_effect = [NotFoundError(404, "not_found", "Gone."), None]

    await hass.services.async_call(
        TODO_DOMAIN,
        TodoServices.REMOVE_ITEM,
        {ATTR_ENTITY_ID: HANDLA, "item": ["11", "12"]},
        blocking=True,
    )

    assert [call.args for call in mock_client.remove_item.await_args_list] == [("11",), ("12",)]


async def test_a_full_list_gives_a_clear_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)
    mock_client.add_items.side_effect = LimitReachedError(409, "limit_reached", "Full.")

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            TODO_DOMAIN,
            TodoServices.ADD_ITEM,
            {ATTR_ENTITY_ID: HANDLA, "item": "ägg"},
            blocking=True,
        )

    assert caught.value.translation_key == "list_full"


async def test_a_refused_token_during_a_change_asks_to_sign_in_again(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)
    mock_client.add_items.side_effect = InvalidTokenError(401, "invalid_token", "Revoked.")

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            TODO_DOMAIN,
            TodoServices.ADD_ITEM,
            {ATTR_ENTITY_ID: HANDLA, "item": "ägg"},
            blocking=True,
        )
    await hass.async_block_till_done()

    assert caught.value.translation_key == "invalid_token"

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_a_refused_token_while_polling_asks_to_sign_in_again(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _set_up(hass, config_entry)
    mock_client.get_items.side_effect = InvalidTokenError(401, "invalid_token", "Revoked.")

    await _poll(hass, freezer)

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_lost_premium_makes_the_lists_unavailable(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _set_up(hass, config_entry)
    mock_client.get_items.side_effect = PremiumRequiredError(403, "premium_required", "No.")

    await _poll(hass, freezer)

    assert hass.states.get(HANDLA).state == STATE_UNAVAILABLE
    assert hass.config_entries.flow.async_progress() == []
    assert "The Alacart account has no premium" in caplog.text


async def test_a_rate_limit_waits_as_long_as_the_api_asks(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _set_up(hass, config_entry)
    mock_client.get_items.side_effect = RateLimitedError(
        429, "rate_limited", "Slow down.", retry_after=30
    )
    await _poll(hass, freezer)
    assert hass.states.get(HANDLA).state == STATE_UNAVAILABLE

    mock_client.get_items.side_effect = None
    mock_client.get_items.return_value = Items(items=list(ITEMS), etag='"i3"')
    await _poll(hass, freezer, minutes=1)

    assert hass.states.get(HANDLA).state == "1"


async def test_an_expired_token_is_refreshed_before_the_call(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            "token": {**config_entry.data["token"], "expires_at": time.time() - 10},
        },
    )
    aioclient_mock.post(
        "https://auth.alacart.io/connect/token",
        json={
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    aioclient_mock.get(
        "https://api.alacart.io/v1/items",
        json={"items": []},
        headers={"ETag": '"x"'},
    )
    aioclient_mock.get("https://api.alacart.io/v1/item-lists", json={"itemLists": []})

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data["token"]["access_token"] == "access-2"
    refresh = aioclient_mock.mock_calls[0][2]
    assert refresh["grant_type"] == "refresh_token"
    assert refresh["refresh_token"] == "refresh-1"
    api_call_headers = aioclient_mock.mock_calls[1][3]
    assert api_call_headers["Authorization"] == "Bearer access-2"


async def test_a_refused_refresh_asks_to_sign_in_again(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            "token": {**config_entry.data["token"], "expires_at": time.time() - 10},
        },
    )
    aioclient_mock.post(
        "https://auth.alacart.io/connect/token", status=400, json={"error": "invalid_grant"}
    )

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


@pytest.mark.usefixtures("mock_client")
async def test_unloading(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    await _set_up(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_a_list_deleted_while_home_assistant_was_off_is_removed(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    config_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    orphan = entity_registry.async_get_or_create(
        "todo",
        DOMAIN,
        f"{config_entry.unique_id}_99",
        config_entry=config_entry,
        suggested_object_id="gammal",
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(orphan.entity_id) is None
    assert hass.states.get(HANDLA) is not None


async def test_a_partly_failed_removal_reads_the_list_again(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)
    mock_client.get_items.reset_mock()
    mock_client.remove_item.side_effect = [None, AlacartConnectionError("down")]

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            TODO_DOMAIN,
            TodoServices.REMOVE_ITEM,
            {ATTR_ENTITY_ID: HANDLA, "item": ["11", "12"]},
            blocking=True,
        )

    assert caught.value.translation_key == "request_failed"
    mock_client.get_items.assert_awaited_once()


async def test_a_rate_limit_during_a_change_asks_to_try_later(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)
    mock_client.add_items.side_effect = RateLimitedError(429, "rate_limited", "Slow.")

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            TODO_DOMAIN,
            TodoServices.ADD_ITEM,
            {ATTR_ENTITY_ID: HANDLA, "item": "ägg"},
            blocking=True,
        )

    assert caught.value.translation_key == "try_later"


async def test_a_read_only_sign_in_asks_to_sign_in_again_to_change(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _set_up(hass, config_entry)
    mock_client.add_items.side_effect = InsufficientScopeError(403, "insufficient_scope", "No.")

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            TODO_DOMAIN,
            TodoServices.ADD_ITEM,
            {ATTR_ENTITY_ID: HANDLA, "item": "ägg"},
            blocking=True,
        )
    await hass.async_block_till_done()

    assert caught.value.translation_key == "insufficient_scope"
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


@pytest.mark.parametrize(
    ("auth_implementation", "with_credentials"),
    [(f"{DOMAIN}_beta", False), ("my_app", True)],
)
async def test_a_beta_entry_refreshes_and_calls_beta_without_the_yaml_switch(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    auth_implementation: str,
    with_credentials: bool,
) -> None:
    if with_credentials:
        assert await async_setup_component(hass, "application_credentials", {})
        await async_import_client_credential(
            hass, DOMAIN, ClientCredential("my-app", "my-secret"), "my_app"
        )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kim Andersson (beta)",
        unique_id="beta_481516",
        data={
            **config_entry.data,
            "auth_implementation": auth_implementation,
            "server": "beta",
            "token": {**config_entry.data["token"], "expires_at": time.time() - 10},
        },
    )
    entry.add_to_hass(hass)
    aioclient_mock.post(
        "https://auth.test.alacart.io/connect/token",
        json={
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    aioclient_mock.get("https://api.test.alacart.io/v1/items", json={"items": []})
    aioclient_mock.get("https://api.test.alacart.io/v1/item-lists", json={"itemLists": []})

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["token"]["access_token"] == "access-2"


async def test_a_revoked_refresh_during_a_change_says_to_sign_in_again(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get("https://api.alacart.io/v1/items", json={"items": []})
    aioclient_mock.get(
        "https://api.alacart.io/v1/item-lists",
        json={"itemLists": [{"id": "1", "name": "Handla", "isDefault": True, "isPrivate": False}]},
    )
    await _set_up(hass, config_entry)
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            "token": {**config_entry.data["token"], "expires_at": time.time() - 10},
        },
    )
    aioclient_mock.post(
        "https://auth.alacart.io/connect/token", status=400, json={"error": "invalid_grant"}
    )

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            TODO_DOMAIN,
            TodoServices.ADD_ITEM,
            {ATTR_ENTITY_ID: HANDLA, "item": "ägg"},
            blocking=True,
        )
    await hass.async_block_till_done()

    assert caught.value.translation_key == "invalid_token"
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_a_failed_refresh_during_a_change_says_it_tries_later(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get("https://api.alacart.io/v1/items", json={"items": []})
    aioclient_mock.get(
        "https://api.alacart.io/v1/item-lists",
        json={"itemLists": [{"id": "1", "name": "Handla", "isDefault": True, "isPrivate": False}]},
    )
    await _set_up(hass, config_entry)
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            "token": {**config_entry.data["token"], "expires_at": time.time() - 10},
        },
    )
    aioclient_mock.post("https://auth.alacart.io/connect/token", status=503)

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            TODO_DOMAIN,
            TodoServices.ADD_ITEM,
            {ATTR_ENTITY_ID: HANDLA, "item": "ägg"},
            blocking=True,
        )
    await hass.async_block_till_done()

    assert caught.value.translation_key == "token_refresh_failed"
    assert hass.config_entries.flow.async_progress() == []
