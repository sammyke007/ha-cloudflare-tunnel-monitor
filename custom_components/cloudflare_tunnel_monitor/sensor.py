from __future__ import annotations

import logging
from typing import Any, Dict, List

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CloudflareTunnelCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Cloudflare Tunnel sensors."""
    api_key = entry.data["api_key"]
    account_id = entry.data["account_id"]
    friendly_name = entry.data["friendly_name"]

    coordinator = CloudflareTunnelCoordinator(hass, api_key, account_id, friendly_name)
    await coordinator.async_config_entry_first_refresh()

    entities = []
    for tunnel in coordinator.data:
        entities.append(CloudflareTunnelSensor(coordinator, tunnel))

    async_add_entities(entities)


class CloudflareTunnelSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Cloudflare tunnel."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["inactive", "degraded", "healthy", "down"]

    def __init__(self, coordinator: CloudflareTunnelCoordinator, tunnel: Dict[str, Any]) -> None:
        super().__init__(coordinator)

        self._tunnel_id = tunnel["id"]
        self._friendly_name = coordinator.friendly_name

        name = tunnel.get("name") or self._tunnel_id
        self._attr_unique_id = f"{DOMAIN}_{coordinator.account_id}_{self._tunnel_id}"
        self._attr_name = f"Tunnel {name}"

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    @property
    def _tunnel(self) -> Dict[str, Any]:
        """Return the current tunnel data from coordinator."""
        for t in self.coordinator.data or []:
            if t.get("id") == self._tunnel_id:
                return t
        return {}

    # -------------------------------------------------------------------------
    # Main sensor values
    # -------------------------------------------------------------------------
    @property
    def native_value(self) -> str | None:
        return self._tunnel.get("status")

    @property
    def icon(self) -> str:
        status = self.native_value
        return {
            "healthy": "mdi:cloud-check",
            "degraded": "mdi:cloud-alert",
            "inactive": "mdi:cloud-off-outline",
            "down": "mdi:cloud-alert-outline",
        }.get(status, "mdi:cloud-question")

    # -------------------------------------------------------------------------
    # ATTRIBUTES — the magic happens here
    # -------------------------------------------------------------------------
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        tunnel = self._tunnel
        sessions = tunnel.get("conns") or tunnel.get("connections") or []
        latest_version = tunnel.get("latest_cloudflared_version")

        grouped: Dict[str, Dict[str, Any]] = {}

        for s in sessions:
            client_id = s.get("client_id") or s.get("clientId")
            if not client_id:
                client_id = "unknown"

            connector = grouped.setdefault(
                client_id,
                {
                    "client_id": client_id,
                    "version": s.get("client_version") or s.get("clientVersion"),
                    "sessions": 0,
                    "edges": set(),
                    "origin_ips": set(),
                    "pending_reconnect": False,
                    "opened_at_latest": None,
                    "latest_version": latest_version,
                    "is_latest": None,
                    "update_available": None,
                    "version_diff": None,
                },
            )

            connector["sessions"] += 1

            # Edge POP
            edge = s.get("colo_name") or s.get("edge") or s.get("colo") or s.get("pop")
            if edge:
                connector["edges"].add(edge)

            # Origin IP
            ip = s.get("origin_ip") or s.get("client_address")
            if ip:
                connector["origin_ips"].add(ip)

            # Reconnect flag
            connector["pending_reconnect"] |= s.get("is_pending_reconnect", False)

            # Latest opened_at
            opened_at = s.get("opened_at") or s.get("run_at")
            if opened_at:
                current = connector["opened_at_latest"]
                if current is None or opened_at > current:
                    connector["opened_at_latest"] = opened_at

            # Version comparison
            version = connector["version"]
            if version and latest_version:
                connector["is_latest"] = version == latest_version
                connector["update_available"] = version != latest_version
                if version != latest_version:
                    connector["version_diff"] = f"{version} → {latest_version}"

        # Finalize the list
        connector_list = []
        for c in grouped.values():
            c["edges"] = sorted(c["edges"])
            c["origin_ips"] = sorted(c["origin_ips"])
            connector_list.append(c)

        return {
            "connector_count": len(connector_list),
            "connectors": connector_list,
            "session_count": len(sessions),
            "latest_cloudflared_version": latest_version,
        }

    # -------------------------------------------------------------------------
    # DEVICE INFO
    # -------------------------------------------------------------------------
    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self.coordinator.account_id)},
            "name": f"Cloudflare Tunnels {self._friendly_name}",
            "manufacturer": "Cloudflare",
        }
