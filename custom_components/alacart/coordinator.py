"""Polls the user's shopping lists and items."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    OAuth2TokenRequestBaseError,
    OAuth2TokenRequestReauthError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from alacart import (
    AlacartClient,
    AlacartError,
    InvalidTokenError,
    Item,
    ItemList,
    PremiumRequiredError,
    RetryLaterError,
)

from .const import DOMAIN, ITEM_LISTS_MAX_AGE, LOGGER, UPDATE_INTERVAL

type AlacartConfigEntry = ConfigEntry[AlacartCoordinator]


@dataclass(frozen=True)
class AlacartData:
    """The user's shopping lists and the items on them."""

    item_lists: dict[str, ItemList]
    """The lists, keyed by id."""
    items: list[Item]
    """The items of every list, newest first."""


class AlacartCoordinator(DataUpdateCoordinator[AlacartData]):
    """Reads every list's items in one call, and the lists themselves less often.

    Each poll sends the ETag of the last answer, so an unchanged list costs the API little. The
    lists change rarely, so the coordinator reads them again only when an item names a list it
    does not know, or when its copy is older than `ITEM_LISTS_MAX_AGE`.
    """

    config_entry: AlacartConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: AlacartConfigEntry, client: AlacartClient
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._items: list[Item] = []
        self._items_etag: str | None = None
        self._item_lists: dict[str, ItemList] = {}
        self._item_lists_etag: str | None = None
        self._item_lists_read_at: float | None = None

    @override
    async def _async_update_data(self) -> AlacartData:
        try:
            await self._read_items()
            if self._item_lists_are_stale():
                await self._read_item_lists()
        except OAuth2TokenRequestReauthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_token"
            ) from err
        except OAuth2TokenRequestBaseError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="token_refresh_failed"
            ) from err
        except InvalidTokenError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_token"
            ) from err
        except PremiumRequiredError as err:
            # Signing in again cannot give the account premium, so the entities only go
            # unavailable until the user has premium again.
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="premium_required"
            ) from err
        except RetryLaterError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
                retry_after=err.retry_after,
            ) from err
        except AlacartError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return AlacartData(item_lists=dict(self._item_lists), items=list(self._items))

    async def _read_items(self) -> None:
        if self._items_etag is None:
            result = await self.client.get_items()
        else:
            changed = await self.client.get_items(etag=self._items_etag)
            if changed is None:
                return
            result = changed
        self._items = result.items
        self._items_etag = result.etag

    def _item_lists_are_stale(self) -> bool:
        if self._item_lists_read_at is None:
            return True
        if time.monotonic() - self._item_lists_read_at >= ITEM_LISTS_MAX_AGE.total_seconds():
            return True
        return any(item.list_id not in self._item_lists for item in self._items)

    async def _read_item_lists(self) -> None:
        if self._item_lists_etag is None:
            result = await self.client.get_item_lists()
        else:
            changed = await self.client.get_item_lists(etag=self._item_lists_etag)
            if changed is None:
                self._item_lists_read_at = time.monotonic()
                return
            result = changed
        self._item_lists = {item_list.id: item_list for item_list in result.item_lists}
        self._item_lists_etag = result.etag
        self._item_lists_read_at = time.monotonic()
