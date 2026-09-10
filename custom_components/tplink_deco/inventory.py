"""Read-only, on-demand network inventory."""

from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall
from homeassistant.core import ServiceResponse
from homeassistant.core import SupportsResponse
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import COORDINATOR_DECOS_KEY
from .const import DOMAIN
from .coordinator import TpLinkDeco

SERVICE_GET_NETWORK_INVENTORY = "get_network_inventory"


def network_inventory(devices: list[dict], reservations: dict) -> dict:
    """Build an explicit inventory without exposing unrelated raw API data."""
    decos = []
    for device in devices:
        deco = TpLinkDeco(device["mac"])
        deco.update(device)
        decos.append(deco)
    by_id = {deco.device_id: deco for deco in decos if deco.device_id}
    nodes = []
    for deco in decos:
        auto = deco.topology.get("auto")
        specified_id = deco.topology.get("device_id") if auto is False else None
        parent = by_id.get(specified_id) if specified_id else None
        nodes.append(
            {
                "name": deco.name,
                "mac": deco.mac,
                "ip": deco.ip_address,
                "online": deco.online,
                "internet_online": deco.internet_online,
                "master": deco.master,
                "connection_type": deco.connection_type,
                "backhaul_speed": deco.backhaul_speed,
                "backhaul_max_speed": deco.backhaul_max_speed,
                "device_id": deco.device_id,
                "parent_device_id": deco.parent_device_id,
                "previous": deco.previous,
                "topology": deco.topology,
                "topology_auto": auto,
                "specified_parent_device_id": specified_id,
                "specified_parent": (
                    {"name": parent.name, "mac": parent.mac} if parent else None
                ),
            }
        )
    # Index required keys: an unsupported/malformed response is not an empty table.
    return {
        "decos": nodes,
        "reservations": [
            {"mac": item["mac"], "ip": item["ip"]}
            for item in reservations["result"]["reservation_list"]
        ],
    }


@callback
def async_setup_inventory_service(hass: HomeAssistant) -> None:
    """Register once; resolve the selected loaded entry on every call."""

    async def get_network_inventory(call: ServiceCall) -> ServiceResponse:
        entries = {
            entry_id: data[COORDINATOR_DECOS_KEY]
            for entry_id, data in hass.data.get(DOMAIN, {}).items()
            if COORDINATOR_DECOS_KEY in data
        }
        entry_id = call.data.get("config_entry_id")
        if entry_id is None:
            if len(entries) != 1:
                raise ServiceValidationError(
                    "Select a loaded TP-Link Deco config entry; "
                    "config_entry_id is required unless exactly one is loaded."
                )
            entry_id = next(iter(entries))
        if entry_id not in entries:
            raise ServiceValidationError(
                "The selected TP-Link Deco entry is not loaded."
            )
        api = entries[entry_id].api
        try:
            # Fresh reads also work while periodic polling is paused. No client polling.
            devices = await api.async_list_devices()
            reservations = await api.async_list_address_reservations()
            return network_inventory(devices, reservations)
        except Exception as err:
            # Do not include decrypted payloads or identifiers in error messages.
            raise HomeAssistantError("Unable to read Deco network inventory.") from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_NETWORK_INVENTORY,
        get_network_inventory,
        schema=vol.Schema({vol.Optional("config_entry_id"): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
