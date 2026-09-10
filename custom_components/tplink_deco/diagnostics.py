"""Diagnostics support for TP-Link Deco."""

import asyncio
from datetime import datetime
from typing import Any

import async_timeout
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.const import CONF_PASSWORD
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import COORDINATOR_CLIENTS_KEY
from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .coordinator import TpLinkDeco
from .coordinator import TpLinkDecoClient
from .coordinator import TplinkDecoClientUpdateCoordinator
from .coordinator import TplinkDecoUpdateCoordinator

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    "access_token",
    "cookie",
    "refresh_token",
    "secret",
    "session",
    "session_id",
    "stok",
    "token",
}


def _coordinator_diagnostics(coordinator) -> dict[str, Any]:
    """Return non-sensitive coordinator state."""
    update_interval = coordinator.update_interval
    health = coordinator.health
    return {
        "last_update_success": coordinator.last_update_success,
        "last_successful_update": (
            health.last_successful_update.isoformat()
            if health.last_successful_update is not None
            else None
        ),
        "response_time_ms": health.response_time_ms,
        "timeout_count": health.timeout_count,
        "consecutive_failures": health.consecutive_failures,
        "last_error": health.last_error,
        "update_interval_seconds": (
            update_interval.total_seconds() if update_interval is not None else None
        ),
    }


def _deco_diagnostics(deco: TpLinkDeco, identifier: str) -> dict[str, Any]:
    """Return diagnostics for a Deco without personal identifiers."""
    return {
        "id": identifier,
        "device_model": deco.device_model,
        "hardware_version": deco.hw_version,
        "software_version": deco.sw_version,
        "online": deco.online,
        "internet_online": deco.internet_online,
        "master": deco.master,
        "connection_type": deco.connection_type,
        "interface": deco.interface,
        "signal_2_4_ghz": deco.signal_band2_4,
        "signal_5_ghz": deco.signal_band5,
        "backhaul_speed": deco.backhaul_speed,
        "backhaul_max_speed": deco.backhaul_max_speed,
        "cpu_usage": deco.cpu_usage,
        "cpu_usage_raw": deco.cpu_usage_raw,
        "memory_usage": deco.mem_usage,
        "memory_usage_raw": deco.mem_usage_raw,
    }


def _client_diagnostics(
    client: TpLinkDecoClient,
    identifier: str,
    deco_ids: dict[str, str],
) -> dict[str, Any]:
    """Return diagnostics for a client without personal identifiers."""
    last_activity: datetime | None = client.last_activity
    return {
        "id": identifier,
        "deco_id": deco_ids.get(client.deco_mac, "unassigned"),
        "online": client.online,
        "connection_type": client.connection_type,
        "interface": client.interface,
        "down_kilobytes_per_s": client.down_kilobytes_per_s,
        "up_kilobytes_per_s": client.up_kilobytes_per_s,
        "last_activity": last_activity.isoformat() if last_activity else None,
    }


# Temporary, local-only selection: add one known specified client and optionally
# one automatic client here. Use MACs from HA. Do not commit private MACs upstream.
CLIENT_PREFERENCE_PROBE_MACS: tuple[str, ...] = ()


async def _async_client_preference_diagnostics(coordinator) -> dict[str, Any]:
    """Always build the marker here, independently of the installed API module."""
    report = {
        "probe_version": 3,
        "diagnostics_module": __name__,
        "temporary": True,
        "budget_seconds": 20,
        "status": "not_attempted",
        "selected_client_macs": list(CLIENT_PREFERENCE_PROBE_MACS[:2]),
        "max_clients": 2,
        "request_timeout_seconds": 3,
        "selector_support": "unconfirmed",
        "probes": {},
    }
    try:
        async with async_timeout.timeout(20):
            await coordinator.api.async_probe_client_preferences(
                report, CLIENT_PREFERENCE_PROBE_MACS
            )
        report["status"] = "completed" if report["probes"] else "not_attempted"
        return async_redact_data(report, TO_REDACT)
    except asyncio.TimeoutError as err:
        report["status"] = "timeout"
        report["error_type"] = type(err).__name__
        for entry in report["probes"].values():
            if entry.get("status") == "not_attempted":
                entry["reason"] = "overall_budget_exhausted"
                if entry.get("attempted"):
                    entry["status"] = "timeout"
    except Exception as err:
        report["status"] = "unexpected_exception"
        report["error_type"] = type(err).__name__
    # Keep partial results, but do not let a redaction failure hide the marker.
    try:
        return async_redact_data(report, TO_REDACT)
    except Exception as err:
        return {
            "probe_version": 3,
            "diagnostics_module": __name__,
            "status": "unexpected_exception",
            "error_type": type(err).__name__,
            "stage": "redaction",
            "probes": {},
            "reason": "results_unavailable",
        }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    deco_coordinator: TplinkDecoUpdateCoordinator = data[COORDINATOR_DECOS_KEY]
    client_coordinator: TplinkDecoClientUpdateCoordinator = data[
        COORDINATOR_CLIENTS_KEY
    ]

    decos = sorted(deco_coordinator.data.decos.items())
    clients = sorted(client_coordinator.data.items())
    deco_ids = {mac: f"deco_{index}" for index, (mac, _) in enumerate(decos, 1)}

    return {
        "config_entry": {
            "version": config_entry.version,
            "minor_version": config_entry.minor_version,
            "data": async_redact_data(config_entry.data, TO_REDACT),
            "options": async_redact_data(config_entry.options, TO_REDACT),
        },
        # Temporary discovery data retains client identifiers for correlation.
        "client_connection_preference_probe": await _async_client_preference_diagnostics(
            deco_coordinator
        ),
        "deco_coordinator": {
            **_coordinator_diagnostics(deco_coordinator),
            "paused": deco_coordinator.paused,
            "master_deco_id": (
                deco_ids.get(deco_coordinator.data.master_deco.mac)
                if deco_coordinator.data.master_deco is not None
                else None
            ),
            "decos": [_deco_diagnostics(deco, deco_ids[mac]) for mac, deco in decos],
        },
        "client_coordinator": {
            **_coordinator_diagnostics(client_coordinator),
            "query_mode": client_coordinator.client_query_mode,
            "clients": [
                _client_diagnostics(client, f"client_{index}", deco_ids)
                for index, (_, client) in enumerate(clients, 1)
            ],
        },
    }
