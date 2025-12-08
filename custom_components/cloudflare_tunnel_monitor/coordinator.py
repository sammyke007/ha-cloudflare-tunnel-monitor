from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

import aiohttp
import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CF_TUNNELS_URL = "https://api.cloudflare.com/client/v4/accounts/{}/cfd_tunnel?is_deleted=false"

# GitHub latest version API
GITHUB_LATEST_URL = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
LATEST_CACHE_TTL = 3600  # 1 hour

latest_version_cache = {"version": None, "timestamp": 0}


class CloudflareTunnelCoordinator(DataUpdateCoordinator):
    """Coordinator: fetches raw tunnel data + latest cloudflared version."""

    def __init__(self, hass: HomeAssistant, api_key: str, account_id: str, friendly_name: str) -> None:
        self._hass = hass
        self._api_key = api_key
        self._account_id = account_id
        self._friendly_name = friendly_name

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{account_id}",
            update_interval=timedelta(minutes=1),
        )

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def friendly_name(self) -> str:
        return self._friendly_name

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _fetch_latest_version(self) -> Optional[str]:
        """Fetch cloudflared latest version with caching."""
        now = time.time()

        if latest_version_cache["version"] and now - latest_version_cache["timestamp"] < LATEST_CACHE_TTL:
            return latest_version_cache["version"]

        session = async_get_clientsession(self._hass)

        try:
            async with session.get(GITHUB_LATEST_URL) as resp:
                if resp.status != 200:
                    _LOGGER.debug("GitHub latest version returned %s", resp.status)
                    return latest_version_cache["version"]

                data = await resp.json()
                version = (data.get("tag_name") or data.get("name") or "").lstrip("v")

                if version:
                    latest_version_cache["version"] = version
                    latest_version_cache["timestamp"] = now
                    return version

        except Exception as err:
            _LOGGER.debug("Error fetching latest cloudflared version: %s", err)

        return latest_version_cache["version"]

    async def _fetch_tunnels(self) -> List[Dict[str, Any]]:
        """Fetch tunnels from Cloudflare (raw, including conns)."""
        url = CF_TUNNELS_URL.format(self._account_id)
        session = async_get_clientsession(self._hass)

        try:
            async with async_timeout.timeout(15):
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("result", [])

                    if resp.status == 401:
                        raise UpdateFailed("Unauthorized – check your API Token")

                    raise UpdateFailed(f"Cloudflare API error {resp.status}: {resp.reason}")

        except Exception as err:
            raise UpdateFailed(f"Error fetching tunnels: {err}") from err

    async def _async_update_data(self) -> List[Dict[str, Any]]:
        """Main coordinator update: return raw tunnels + attach latest version."""
        tunnels = await self._fetch_tunnels()
        latest_version = await self._fetch_latest_version()

        # Attach latest version for sensor logic
        for t in tunnels:
            t["latest_cloudflared_version"] = latest_version

        return tunnels
