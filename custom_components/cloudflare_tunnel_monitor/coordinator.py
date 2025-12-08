from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import aiohttp
import async_timeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import aiohttp_client

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CF_TUNNELS_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel?is_deleted=false"
CF_CONNECTIONS_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/connections"
GITHUB_LATEST_URL = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"


class CloudflareTunnelCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch and enrich Cloudflare tunnel data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_key: str,
        account_id: str,
        friendly_name: str,
    ) -> None:
        self._hass = hass
        self._api_key = api_key
        self._account_id = account_id
        self._friendly_name = friendly_name
        self._latest_version: Optional[str] = None

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

    async def _fetch_json(
        self, session: aiohttp.ClientSession, url: str, *, timeout: int = 15
    ) -> Any:
        """Fetch JSON from an endpoint, raising UpdateFailed on error."""
        try:
            async with async_timeout.timeout(timeout):
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 401:
                        raise UpdateFailed("Unauthorized (401). Check your API token.")
                    if resp.status != 200:
                        text = await resp.text()
                        raise UpdateFailed(
                            f"Error {resp.status} from {url}: {resp.reason} - {text[:200]}"
                        )
                    return await resp.json()
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout while communicating with Cloudflare") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed("Client error while communicating with Cloudflare") from err

    async def _fetch_latest_version(
        self, session: aiohttp.ClientSession
    ) -> Optional[str]:
        """Fetch latest cloudflared version from GitHub.

        We keep this best-effort: failures simply mean version info is missing.
        """
        try:
            async with async_timeout.timeout(15):
                async with session.get(GITHUB_LATEST_URL) as resp:
                    if resp.status != 200:
                        _LOGGER.debug(
                            "GitHub latest version request failed: %s %s",
                            resp.status,
                            resp.reason,
                        )
                        return None
                    data = await resp.json()
                    # Prefer tag_name (e.g. '2024.10.0') if present
                    version = data.get("tag_name") or data.get("name")
                    if isinstance(version, str):
                        return version.lstrip("v")
        except Exception as err:  # best-effort
            _LOGGER.debug("Error fetching latest cloudflared version: %s", err)
        return None

    async def _async_update_data(self) -> List[Dict[str, Any]]:
        """Fetch and enrich tunnel data from Cloudflare."""
        session = aiohttp_client.async_get_clientsession(self._hass)

        tunnels_url = CF_TUNNELS_URL.format(account_id=self._account_id)

        # Fetch tunnels and latest version in parallel
        tunnels_task = self._fetch_json(session, tunnels_url)
        version_task = self._fetch_latest_version(session)

        tunnels_resp, latest_version = await asyncio.gather(
            tunnels_task, version_task
        )

        result = tunnels_resp.get("result", [])
        if not isinstance(result, list):
            raise UpdateFailed("Unexpected tunnels payload from Cloudflare")

        self._latest_version = latest_version
        tunnels: List[Dict[str, Any]] = []

        for tunnel in result:
            tunnel_id = tunnel.get("id")
            if not tunnel_id:
                continue

            connections_url = CF_CONNECTIONS_URL.format(
                account_id=self._account_id, tunnel_id=tunnel_id
            )

            try:
                connections_resp = await self._fetch_json(session, connections_url)
                connections_raw: List[Dict[str, Any]] = connections_resp.get(
                    "result", []
                )
            except UpdateFailed as err:
                _LOGGER.warning(
                    "Could not fetch connections for tunnel %s: %s", tunnel_id, err
                )
                connections_raw = []

            connectors, connector_count, session_count = self._build_connectors(
                connections_raw, latest_version
            )

            tunnels.append(
                {
                    "id": tunnel_id,
                    "name": tunnel.get("name") or tunnel_id,
                    "status": tunnel.get("status"),
                    "created_at": tunnel.get("created_at"),
                    "connector_count": connector_count,
                    "session_count": session_count,
                    "connectors": connectors,
                    "latest_cloudflared_version": latest_version,
                }
            )

        return tunnels

    def _build_connectors(
        self,
        connections: List[Dict[str, Any]],
        latest_version: Optional[str],
    ) -> tuple[List[Dict[str, Any]], int, int]:
        """Group raw connections into logical connectors."""
        grouped: Dict[str, Dict[str, Any]] = {}
        total_sessions = 0

        for conn in connections or []:
            client_id = conn.get("client_id") or conn.get("clientId") or "unknown"
            version = (
                conn.get("client_version")
                or conn.get("clientVersion")
                or conn.get("version")
            )

            opened_at = (
                conn.get("opened_at")
                or conn.get("openedAt")
                or conn.get("started_at")
            )

            edge = (
                conn.get("colo_name")
                or conn.get("edge")
                or conn.get("colo")
                or conn.get("origin")
            )
            origin_ip = (
                conn.get("client_address")
                or conn.get("origin_ip")
                or conn.get("ip")
            )

            pending = bool(
                conn.get("is_pending_reconnect") or conn.get("pending_reconnect")
            )

            grouped_conn = grouped.setdefault(
                client_id,
                {
                    "client_id": client_id,
                    "version": version,
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

            grouped_conn["sessions"] += 1
            total_sessions += 1

            if edge:
                grouped_conn["edges"].add(edge)
            if origin_ip:
                grouped_conn["origin_ips"].add(origin_ip)

            if opened_at:
                prev = grouped_conn["opened_at_latest"]
                if prev is None or str(opened_at) > str(prev):
                    grouped_conn["opened_at_latest"] = opened_at

            if pending:
                grouped_conn["pending_reconnect"] = True

        connectors: List[Dict[str, Any]] = []
        for connector in grouped.values():
            # Finalize sets to lists for JSON-serializable attributes
            connector["edges"] = sorted(connector["edges"])
            connector["origin_ips"] = sorted(connector["origin_ips"])

            version = connector.get("version")
            latest = connector.get("latest_version")

            if version and latest:
                is_latest = version == latest
                connector["is_latest"] = is_latest
                connector["update_available"] = not is_latest
                connector["version_diff"] = (
                    f"{version} -> {latest}" if not is_latest else None
                )
            else:
                connector["is_latest"] = None
                connector["update_available"] = None
                connector["version_diff"] = None

            connectors.append(connector)

        return connectors, len(connectors), total_sessions
