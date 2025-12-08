from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CloudflareTunnelCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cloudflare Tunnel sensors from a config entry."""
    api_key: str = config_entry.data["api_key"]
    account_id: str = config_entry.data["account_id"]
    friendly_name: str = config_entry.data.get("friendly_name", account_id)

    coordinator = CloudflareTunnelCoordinator(
        hass=hass,
        api_key=api_key,
        account_id=account_id,
        friendly_name=friendly_name,
    )

    # Store the coordinator so other platforms (if any) could reuse it
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(config_entry.entry_id, {})
    hass.data[DOMAIN][config_entry.entry_id]["coordinator"] = coordinator

    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data:
        _LOGGER.warning(
            "No Cloudflare tunnels found for account %s; no sensors created.",
            account_id,
        )
        return

    entities: List[CloudflareTunnelSensor] = []
    for tunnel in coordinator.data:
        tunnel_id = tunnel.get("id")
        if not tunnel_id:
            continue
        entities.append(
            CloudflareTunnelSensor(
                coordinator=coordinator,
                tunnel_id=tunnel_id,
                account_id=account_id,
                friendly_name=friendly_name,
            )
        )

    async_add_entities(entities)


class CloudflareTunnelSensor(CoordinatorEntity, SensorEntity):
    """Representation of a single Cloudflare tunnel."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["inactive", "degraded", "healthy", "down"]

    def __init__(
        self,
        coordinator: CloudflareTunnelCoordinator,
        tunnel_id: str,
        account_id: str,
        friendly_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._tunnel_id = tunnel_id
        self._account_id = account_id
        self._friendly_name = friendly_name

        tunnel = self._tunnel
        name = tunnel.get("name") or tunnel_id

        self._attr_unique_id = f"{DOMAIN}_{account_id}_{tunnel_id}"
        self._attr_name = f"Cloudflare Tunnel {name}"

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    @property
    def _tunnel(self) -> Dict[str, Any]:
        """Return the current tunnel dict for this entity from the coordinator."""
        data = self.coordinator.data or []
        for tunnel in data:
            if tunnel.get("id") == self._tunnel_id:
                return tunnel
        return {}

    # -------------------------------------------------------------------------
    # Entity properties
    # -------------------------------------------------------------------------
    @property
    def state(self) -> str | None:
        """Return the current status of the tunnel (enum)."""
        return self._tunnel.get("status")

    @property
    def icon(self) -> str:
        status = self.state
        if status == "healthy":
            return "mdi:cloud-check"
        if status == "degraded":
            return "mdi:cloud-alert"
        if status == "inactive":
            return "mdi:cloud-off-outline"
        if status == "down":
            return "mdi:cloud-alert-outline"
        return "mdi:cloud-question"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extended attributes for this tunnel.

        These power the Lovelace examples and advanced diagnostics:
        - connector_count
        - session_count
        - connectors (grouped list)
        - latest_cloudflared_version
        """
        tunnel = self._tunnel
        if not tunnel:
            return {}

        attrs: Dict[str, Any] = {}

        for key in (
            "connector_count",
            "session_count",
            "connectors",
            "latest_cloudflared_version",
        ):
            value = tunnel.get(key)
            if value is not None:
                attrs[key] = value

        return attrs

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information for the Cloudflare account.

        One device per Cloudflare account; multiple tunnel entities attach here.
        """
        return {
            "identifiers": {(DOMAIN, self._account_id)},
            "name": self._friendly_name or "Cloudflare Tunnels",
            "manufacturer": "Cloudflare",
        }
