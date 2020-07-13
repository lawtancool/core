"""Platform for Control4 Lights."""
import asyncio
from datetime import timedelta
import logging

from pyControl4.error_handling import C4Exception
from pyControl4.light import C4Light

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    SUPPORT_BRIGHTNESS,
    SUPPORT_TRANSITION,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import Control4Entity, get_items_of_category
from .const import (
    CONF_LIGHT_COLD_START_TRANSITION_TIME,
    CONF_LIGHT_TRANSITION_TIME,
    DOMAIN,
)
from .director_utils import director_update_data

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "lights"
CONTROL4_NON_DIMMER_VAR = "LIGHT_STATE"
CONTROL4_DIMMER_VAR = "LIGHT_LEVEL"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up Control4 lights from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    scan_interval = entry_data[CONF_SCAN_INTERVAL]
    light_transition_time = entry_data[CONF_LIGHT_TRANSITION_TIME]
    light_cold_start_transition_time = entry_data[CONF_LIGHT_COLD_START_TRANSITION_TIME]
    _LOGGER.debug(
        "Scan interval = %s, light transition time = %s, light cold start transition time = %s",
        scan_interval,
        light_transition_time,
        light_cold_start_transition_time,
    )

    async def async_update_data_non_dimmer():
        """Fetch data from Control4 director for non-dimmer lights."""
        try:
            return await director_update_data(hass, entry, CONTROL4_NON_DIMMER_VAR)
        except C4Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def async_update_data_dimmer():
        """Fetch data from Control4 director for dimmer lights."""
        try:
            return await director_update_data(hass, entry, CONTROL4_DIMMER_VAR)
        except C4Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    non_dimmer_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="light",
        update_method=async_update_data_non_dimmer,
        update_interval=timedelta(seconds=scan_interval),
    )
    dimmer_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="light",
        update_method=async_update_data_dimmer,
        update_interval=timedelta(seconds=scan_interval),
    )

    # Fetch initial data so we have data when entities subscribe
    await non_dimmer_coordinator.async_refresh()
    await dimmer_coordinator.async_refresh()

    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)
    for item in items_of_category:
        if item["type"] == 7:
            item_name = item["name"]
            item_id = item["id"]
            item_parent_id = item["parentId"]
            item_is_dimmer = item["capabilities"]["dimmer"]

            if item_is_dimmer:
                item_coordinator = dimmer_coordinator
            else:
                item_coordinator = non_dimmer_coordinator

            for parent_item in items_of_category:
                if parent_item["id"] == item_parent_id:
                    item_manufacturer = parent_item["manufacturer"]
                    item_device_name = parent_item["name"]
                    item_model = parent_item["model"]
            async_add_entities(
                [
                    Control4Light(
                        hass,
                        entry,
                        item_coordinator,
                        item_name,
                        item_id,
                        item_device_name,
                        item_manufacturer,
                        item_model,
                        item_parent_id,
                        item_is_dimmer,
                        light_transition_time,
                        light_cold_start_transition_time,
                    )
                ],
                True,
            )


class Control4Light(Control4Entity, LightEntity):
    """Control4 light entity."""

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
        is_dimmer: bool,
        light_transition_time: int,
        light_cold_start_transition_time: int,
    ):
        """Initialize Control4 light entity."""
        super().__init__(
            hass,
            entry,
            coordinator,
            name,
            idx,
            device_name,
            device_manufacturer,
            device_model,
            device_id,
        )
        self._is_dimmer = is_dimmer
        self._transition_time = light_transition_time
        self._cold_start_transition_time = light_cold_start_transition_time
        # pylint: disable=invalid-name
        self._C4Light = C4Light(self.director, idx)

    @property
    def is_on(self):
        """Return whether this light is on or off."""
        return bool(self._coordinator.data[self._idx]["value"] > 0)

    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        if self._is_dimmer:
            return self._coordinator.data[self._idx]["value"] * 2.55
        return None

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        flags = 0
        if self._is_dimmer:
            flags |= SUPPORT_BRIGHTNESS
            flags |= SUPPORT_TRANSITION
        return flags

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the entity on."""
        if self._is_dimmer:
            if ATTR_TRANSITION in kwargs:
                transition_length = kwargs[ATTR_TRANSITION] * 1000
            elif self.brightness == 0:
                transition_length = self._cold_start_transition_time * 1000
            else:
                transition_length = self._transition_time * 1000
            if ATTR_BRIGHTNESS in kwargs:
                brightness = (kwargs[ATTR_BRIGHTNESS] / 255) * 100
            else:
                brightness = 100
            await self._C4Light.rampToLevel(brightness, transition_length)
        else:
            transition_length = 0
            await self._C4Light.setLevel(100)
        if transition_length == 0:
            transition_length = 1000
        delay_time = (transition_length / 1000) + 0.7
        _LOGGER.debug("Delaying light update by %s seconds", delay_time)
        await asyncio.sleep(delay_time)
        await self._coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        if self._is_dimmer:
            if ATTR_TRANSITION in kwargs:
                transition_length = kwargs[ATTR_TRANSITION] * 1000
            else:
                transition_length = self._cold_start_transition_time * 1000
            await self._C4Light.rampToLevel(0, transition_length)
        else:
            transition_length = 0
            await self._C4Light.setLevel(0)
        if transition_length == 0:
            transition_length = 1500
        delay_time = (transition_length / 1000) + 0.7
        _LOGGER.debug("Delaying light update by %s seconds", delay_time)
        await asyncio.sleep(delay_time)
        await self._coordinator.async_request_refresh()
