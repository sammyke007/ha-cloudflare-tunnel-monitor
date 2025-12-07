import aiohttp
import async_timeout
import voluptuous as vol
from homeassistant import config_entries, exceptions

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_ACCOUNT_ID,
    LABEL_API_KEY,
    LABEL_ACCOUNT_ID,
    LABEL_FRIENDLY_NAME,
    PLACEHOLDER_API_KEY,
    PLACEHOLDER_ACCOUNT_ID,
    PLACEHOLDER_FRIENDLY_NAME,
)

# Constants
URL = "https://api.cloudflare.com/client/v4/user/tokens/verify"
TIMEOUT = 10

# Custom exceptions
class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""


async def validate_credentials(hass, data):
    """Validate the provided API token is valid via Cloudflare API."""
    api_key = data[CONF_API_KEY]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with async_timeout.timeout(TIMEOUT):
                async with session.get(URL, headers=headers) as response:
                    if response.status == 200:
                        return True
                    elif response.status == 401:
                        raise InvalidAuth
                    else:
                        raise CannotConnect
    except aiohttp.ClientError:
        raise CannotConnect
    except async_timeout.TimeoutError:
        raise CannotConnect


class CloudflareConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Cloudflare Tunnel Monitor config flow."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        errors = {}

        # Build schema including 'friendly_name' with proper label
        schema = vol.Schema({
            vol.Required(CONF_ACCOUNT_ID, description={LABEL_ACCOUNT_ID}): str,
            vol.Required(CONF_API_KEY, description={LABEL_API_KEY}): str,
            vol.Required("friendly_name", description={LABEL_FRIENDLY_NAME}): str,
        })

        if user_input is not None:
            # Validate credentials first
            try:
                await validate_credentials(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                # SUCCESS → save config
                return self.async_create_entry(
                    title=f"Cloudflare Tunnels {user_input['friendly_name']}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                CONF_API_KEY: PLACEHOLDER_API_KEY,
                CONF_ACCOUNT_ID: PLACEHOLDER_ACCOUNT_ID,
                "friendly_name": PLACEHOLDER_FRIENDLY_NAME,
            },
        )
