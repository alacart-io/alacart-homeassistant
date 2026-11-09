"""One to-do list per Alacart shopping list."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import override

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    HomeAssistantError,
    OAuth2TokenRequestBaseError,
    OAuth2TokenRequestReauthError,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from alacart import (
    AlacartError,
    InsufficientScopeError,
    InvalidTokenError,
    Item,
    LimitReachedError,
    NotFoundError,
    PremiumRequiredError,
    RetryLaterError,
)

from .const import DOMAIN
from .coordinator import AlacartConfigEntry, AlacartCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlacartConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a to-do list for each shopping list, and follow lists as they come and go."""
    coordinator = entry.runtime_data
    known: set[str] = set()
    registry = er.async_get(hass)

    @callback
    def _sync_lists() -> None:
        if not coordinator.last_update_success:
            return
        current = set(coordinator.data.item_lists)
        added = current - known
        if added:
            known.update(added)
            async_add_entities(AlacartTodoList(coordinator, list_id) for list_id in added)
        # The registry also holds lists that were deleted while Home Assistant was off.
        wanted = {_unique_id(entry, list_id) for list_id in current}
        for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if registry_entry.domain == "todo" and registry_entry.unique_id not in wanted:
                registry.async_remove(registry_entry.entity_id)
        known.intersection_update(current)

    _sync_lists()
    entry.async_on_unload(coordinator.async_add_listener(_sync_lists))


def _unique_id(entry: AlacartConfigEntry, list_id: str) -> str:
    return f"{entry.unique_id}_{list_id}"


def _todo_item(item: Item) -> TodoItem:
    return TodoItem(
        uid=item.id,
        summary=item.text,
        status=TodoItemStatus.COMPLETED if item.is_checked else TodoItemStatus.NEEDS_ACTION,
    )


class AlacartTodoList(CoordinatorEntity[AlacartCoordinator], TodoListEntity):
    """A shopping list, newest items first.

    A checked item shows as completed until Alacart drops it from the list, 180 minutes after
    the check. A permanent item never shows as completed, because checking it only records the
    purchase.
    """

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: AlacartCoordinator, list_id: str) -> None:
        super().__init__(coordinator)
        self._list_id = list_id
        self._attr_unique_id = _unique_id(coordinator.config_entry, list_id)

    @property
    @override
    def name(self) -> str | None:
        item_list = self.coordinator.data.item_lists.get(self._list_id)
        return item_list.name if item_list is not None else None

    @property
    @override
    def available(self) -> bool:
        return super().available and self._list_id in self.coordinator.data.item_lists

    @property
    @override
    def todo_items(self) -> list[TodoItem]:
        return [
            _todo_item(item)
            for item in self.coordinator.data.items
            if item.list_id == self._list_id
        ]

    @override
    async def async_create_todo_item(self, item: TodoItem) -> None:
        if not item.summary:
            return
        summary = item.summary
        await self._change(
            lambda: self.coordinator.client.add_items([summary], list_id=self._list_id)
        )

    @override
    async def async_update_todo_item(self, item: TodoItem) -> None:
        current = self._current_item(item.uid)
        if current is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="item_not_found")
        text = item.summary if item.summary and item.summary != current.text else None
        is_checked: bool | None = None
        if item.status is not None:
            wanted = item.status == TodoItemStatus.COMPLETED
            if wanted != current.is_checked:
                is_checked = wanted
        if text is None and is_checked is None:
            return
        await self._change(
            lambda: self.coordinator.client.change_item(
                current.id, text=text, is_checked=is_checked
            )
        )

    @override
    async def async_delete_todo_items(self, uids: list[str]) -> None:
        async def remove_all() -> None:
            for uid in uids:
                try:
                    await self.coordinator.client.remove_item(uid)
                except NotFoundError:
                    # Someone already removed it, which is what the user asked for.
                    continue

        await self._change(remove_all)

    def _current_item(self, uid: str | None) -> Item | None:
        for item in self.coordinator.data.items:
            if item.id == uid and item.list_id == self._list_id:
                return item
        return None

    async def _change(self, call: Callable[[], Awaitable[object]]) -> None:
        """Make a change through the API, then read the list again at once."""
        try:
            await call()
        except OAuth2TokenRequestReauthError as err:
            # Home Assistant has already asked the user to sign in again.
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_token"
            ) from err
        except OAuth2TokenRequestBaseError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="token_refresh_failed"
            ) from err
        except InvalidTokenError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_token"
            ) from err
        except InsufficientScopeError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="insufficient_scope"
            ) from err
        except PremiumRequiredError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="premium_required"
            ) from err
        except RetryLaterError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="try_later"
            ) from err
        except LimitReachedError as err:
            await self.coordinator.async_refresh()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="list_full"
            ) from err
        except NotFoundError as err:
            await self.coordinator.async_refresh()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="item_not_found"
            ) from err
        except AlacartError as err:
            # A call that removes several items can fail partway, so the list is read again.
            await self.coordinator.async_refresh()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_refresh()
