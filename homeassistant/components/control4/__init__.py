"""The Control4 integration."""
import asyncio
import voluptuous as vol
import datetime
import logging
import re
import json

from pyControl4.account import C4Account
from pyControl4.director import C4Director

from homeassistant.helpers import entity
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
PLATFORMS = ["light"]


async def async_setup(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stub to allow setting up this component.

    Configuration through YAML is not supported at this time.
    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Control4 from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.title, {})

    config = entry.data
    account = C4Account(config["username"], config["password"])
    await account.getAccountBearerToken()
    hass.data[DOMAIN][entry.title]["account"] = account

    director_token_dict = await account.getDirectorBearerToken(entry.title)
    director = C4Director(config["host"], director_token_dict["token"])
    hass.data[DOMAIN][entry.title]["director"] = director
    hass.data[DOMAIN][entry.title]["director_token_expiry"] = director_token_dict[
        "token_expiration"
    ]

    controller_href = (await account.getAccountControllers())["href"]
    hass.data[DOMAIN][entry.title][
        "director_sw_version"
    ] = await account.getControllerOSVersion(controller_href)

    result = re.search("_(.*)_", entry.title)
    hass.data[DOMAIN][entry.title]["director_model"] = result.group(1).upper()

    device_registry = await dr.async_get_registry(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.title)},
        manufacturer="Control4",
        name=entry.title,
        model=hass.data[DOMAIN][entry.title]["director_model"],
        sw_version=hass.data[DOMAIN][entry.title]["director_sw_version"],
    )

    director_all_items = await director.getAllItemInfo()
    director_all_items = json.loads(director_all_items)
    hass.data[DOMAIN][entry.title]["director_all_items"] = director_all_items

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        controller_name = entry.title
        hass.data[DOMAIN].pop(entry.title)
        _LOGGER.debug("Unloaded entry for %s", controller_name)

    return unload_ok


async def get_items_of_category(hass: HomeAssistant, entry: ConfigEntry, category: str):
    director_all_items = hass.data[DOMAIN][entry.title]["director_all_items"]
    return_list = []
    for item in director_all_items:
        if "categories" in item.keys() and category in item["categories"]:
            return_list.append(item)
    return return_list


class Control4Entity(entity.Entity):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: DataUpdateCoordinator,
        name: str,
        idx: int,
        device_name: str,
        device_manufacturer: str,
        device_model: str,
        device_id: int,
    ):
        self.entry = entry
        self.account = hass.data[DOMAIN][self.entry.title]["account"]
        self.director = hass.data[DOMAIN][self.entry.title]["director"]
        self.director_token_expiry = hass.data[DOMAIN][self.entry.title][
            "director_token_expiry"
        ]
        self._name = name
        self._idx = idx
        self._coordinator = coordinator
        self._device_name = device_name
        self._device_manufacturer = device_manufacturer
        self._device_model = device_model
        self._device_id = device_id

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._idx

    @property
    def device_info(self):
        return {
            "config_entry_id": self.entry.entry_id,
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": self._device_manufacturer,
            "model": self._device_model,
            "via_device": (DOMAIN, self.entry.title),
        }

    @property
    def should_poll(self):
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self):
        """Return if entity is available."""
        return self._coordinator.last_update_success

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the state of the device."""
        if (
            self.director_token_expiry is not None
            and datetime.datetime.now() < self.director_token_expiry
        ):
            _LOGGER.debug("Old director token is still valid. Not getting a new one.")
        else:
            config = self.entry.data
            self.account = C4Account(config["username"], config["password"])
            director_token_dict = await self.account.getDirectorBearerToken(
                self.entry.title
            )
            self.director = C4Director(config["host"], director_token_dict["token"])
            self.director_token_expiry = director_token_dict["token_expiration"]

            _LOGGER.debug("Saving new tokens in config_entry")
            self.hass.data[DOMAIN][self.entry.title]["account"] = self.account
            self.hass.data[DOMAIN][self.entry.title]["director"] = self.director
            self.hass.data[DOMAIN][self.entry.title][
                "director_token_expiry"
            ] = self.director_token_expiry
        await self._coordinator.async_request_refresh()
