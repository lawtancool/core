"""Test the Control4 config flow."""
from homeassistant import config_entries, setup
from homeassistant.components.control4.const import DOMAIN

from tests.async_mock import patch, AsyncMock, MagicMock
import datetime
from pyControl4.error_handling import Unauthorized


def _get_mock_c4_account(
    getAccountControllers={
        "controllerCommonName": "control4_model_00AA00AA00AA",
        "href": "https://apis.control4.com/account/v3/rest/accounts/000000",
        "name": "Name",
    },
    getDirectorBearerToken={
        "token": "token",
        "token_expiration": datetime.datetime(2020, 7, 15, 13, 50, 15, 26940),
    },
):
    c4_account_mock = AsyncMock()
    type(c4_account_mock).getAccountControllers = AsyncMock(
        return_value=getAccountControllers
    )
    type(c4_account_mock).getDirectorBearerToken = AsyncMock(
        return_value=getDirectorBearerToken
    )

    return c4_account_mock


def _get_mock_c4_director(getAllItemInfo={}):
    c4_director_mock = AsyncMock()
    type(c4_director_mock).getAllItemInfo = AsyncMock(return_value=getAllItemInfo)

    return c4_director_mock


async def test_form(hass):
    """Test we get the form."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}

    c4_account = _get_mock_c4_account()
    c4_director = _get_mock_c4_director()
    with patch(
        "homeassistant.components.control4.config_flow.C4Account",
        return_value=c4_account,
    ), patch(
        "homeassistant.components.control4.config_flow.C4Director",
        return_value=c4_director,
    ), patch(
        "homeassistant.components.control4.async_setup", return_value=True
    ) as mock_setup, patch(
        "homeassistant.components.control4.async_setup_entry", return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "1.1.1.1",
                "username": "test-username",
                "password": "test-password",
            },
        )

    assert result2["type"] == "create_entry"
    assert result2["title"] == "control4_model_00AA00AA00AA"
    assert result2["data"] == {
        "host": "1.1.1.1",
        "username": "test-username",
        "password": "test-password",
        "controller_unique_id": "control4_model_00AA00AA00AA",
    }
    await hass.async_block_till_done()
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_invalid_auth(hass):
    """Test we handle invalid auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.control4.config_flow.C4Account",
        side_effect=Unauthorized("message"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "1.1.1.1",
                "username": "test-username",
                "password": "test-password",
            },
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_form_cannot_connect(hass):
    """Test we handle cannot connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "homeassistant.components.control4.config_flow.Control4Validator.authenticate",
        return_value=True,
    ), patch(
        "homeassistant.components.control4.config_flow.C4Director",
        side_effect=Unauthorized("message"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "1.1.1.1",
                "username": "test-username",
                "password": "test-password",
            },
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "cannot_connect"}
