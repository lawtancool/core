"""Platform for Control4 Lights."""
from datetime import timedelta
import logging

from pyControl4.alarm import C4SecurityPanel
from pyControl4.error_handling import C4Exception

from homeassistant.components.alarm_control_panel import (
    FORMAT_NUMBER,
    SUPPORT_ALARM_ARM_AWAY,
    SUPPORT_ALARM_ARM_HOME,
    AlarmControlPanelEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_DISARMED,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import Control4Entity, get_items_of_category
from .const import CONF_DIRECTOR, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import director_update_data_multi_variable

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "security"
CONTROL4_ARMED_AWAY_VAR = "AWAY_STATE"
CONTROL4_ARMED_HOME_VAR = "HOME_STATE"
CONTROL4_DISARMED_VAR = "DISARMED_STATE"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up Control4 lights from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    scan_interval = entry_data[CONF_SCAN_INTERVAL]
    _LOGGER.debug(
        "Scan interval = %s", scan_interval,
    )

    async def async_update_data():
        """Fetch data from Control4 director for dimmer lights."""
        try:
            return await director_update_data_multi_variable(
                hass,
                entry,
                CONTROL4_ARMED_AWAY_VAR
                + ","
                + CONTROL4_ARMED_HOME_VAR
                + ","
                + CONTROL4_DISARMED_VAR,
            )
        except C4Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="alarm_control_panel",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_refresh()

    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)
    for item in items_of_category:
        if (
            item["type"] == CONTROL4_ENTITY_TYPE
            and item["control"] == CONTROL4_CATEGORY
        ):
            item_name = item["name"]
            item_id = item["id"]
            item_parent_id = item["parentId"]
            item_coordinator = coordinator

            for parent_item in items_of_category:
                if parent_item["id"] == item_parent_id:
                    item_manufacturer = parent_item["manufacturer"]
                    item_device_name = parent_item["name"]
                    item_model = parent_item["model"]
            async_add_entities(
                [
                    Control4AlarmControlPanel(
                        entry_data,
                        entry,
                        item_coordinator,
                        item_name,
                        item_id,
                        item_device_name,
                        item_manufacturer,
                        item_model,
                        item_parent_id,
                    )
                ],
                True,
            )


class Control4AlarmControlPanel(Control4Entity, AlarmControlPanelEntity):
    """Control4 light entity."""

    def create_api_object(self):
        """Create a pyControl4 device object.

        This exists so the director token used is always the latest one, without needing to re-init the entire entity.
        """
        return C4SecurityPanel(self.entry_data[CONF_DIRECTOR], self._idx)

    @property
    def code_format(self):
        """Regex for code format or None if no code is required."""
        return FORMAT_NUMBER

    @property
    def state(self):
        """Return the state of the device."""
        disarmed = self._coordinator.data[self._idx][CONTROL4_DISARMED_VAR]
        armed_home = self._coordinator.data[self._idx][CONTROL4_ARMED_HOME_VAR]
        armed_away = self._coordinator.data[self._idx][CONTROL4_ARMED_AWAY_VAR]
        if disarmed == 1:
            return STATE_ALARM_DISARMED
        elif armed_home == 1:
            return STATE_ALARM_ARMED_HOME
        elif armed_away == 1:
            return STATE_ALARM_ARMED_AWAY

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        flags = SUPPORT_ALARM_ARM_AWAY | SUPPORT_ALARM_ARM_HOME
        return flags

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.setArmAway(code)

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.setArmHome(code)

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.setDisarm(code)
