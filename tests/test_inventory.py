"""Regression coverage for the fork's read-only network inventory action."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.exceptions import ServiceValidationError
import pytest

from custom_components.tplink_deco import async_setup
from custom_components.tplink_deco.api import TplinkDecoApi
from custom_components.tplink_deco.const import COORDINATOR_DECOS_KEY
from custom_components.tplink_deco.const import DOMAIN
from custom_components.tplink_deco.const import SERVICE_DOWNLOAD_SYSTEM_LOG
from custom_components.tplink_deco.coordinator import TpLinkDeco
from custom_components.tplink_deco.diagnostics import _deco_diagnostics
from custom_components.tplink_deco.exceptions import TransientConnectionException
from custom_components.tplink_deco.inventory import SERVICE_GET_NETWORK_INVENTORY
from custom_components.tplink_deco.inventory import network_inventory


def nodes():
    """Return six synthetic nodes, including the known specified-parent case."""
    names = [
        "Living Room",
        "Girls’ Bedroom",
        "Main Bedroom",
        "TV Lounge",
        "Garden",
        "Scullery",
    ]
    result = [
        {
            "mac": f"AA-BB-CC-DD-EE-{i:02d}",
            "device_id": f"node-{i}",
            "custom_nickname": name,
            "group_status": "connected",
        }
        for i, name in enumerate(names)
    ]
    result[2].update(
        topology={"auto": False, "device_id": "node-1"}, parent_device_id="node-0"
    )
    result[3]["topology"] = {"auto": True, "device_id": "node-1"}
    result[5]["wired_port_list"] = [{"device_id": "node-0"}]
    return result


def reservations():
    """Return an authoritative reservation absent from the live client list."""
    return {
        "result": {
            "reservation_list": [
                {"mac": "11-22-33-44-55-66", "ip": "192.168.0.50", "extra": "private"}
            ]
        }
    }


def test_inventory_topology_and_schema():
    """Keep configured/current parents separate and unknown wired topology null."""
    data = network_inventory(nodes(), reservations())
    assert set(data) == {"decos", "reservations"}
    assert len(data["decos"]) == 6
    main = data["decos"][2]
    assert main["topology_auto"] is False
    assert main["specified_parent_device_id"] == "node-1"
    assert main["specified_parent"] == {
        "name": "Girls’ Bedroom",
        "mac": nodes()[1]["mac"],
    }
    assert main["parent_device_id"] == "node-0"
    assert set(main) == {
        "name",
        "mac",
        "ip",
        "online",
        "internet_online",
        "master",
        "connection_type",
        "backhaul_speed",
        "backhaul_max_speed",
        "device_id",
        "parent_device_id",
        "previous",
        "topology",
        "topology_auto",
        "specified_parent_device_id",
        "specified_parent",
    }
    assert data["decos"][3]["specified_parent"] is None
    assert data["decos"][3]["specified_parent_device_id"] is None
    assert data["decos"][5]["topology_auto"] is None
    assert data["decos"][5]["specified_parent"] is None
    assert data["reservations"] == [{"mac": "11-22-33-44-55-66", "ip": "192.168.0.50"}]


def test_missing_parent_and_offline_topology():
    """Retain unresolved IDs but clear topology when later records omit it."""
    node = nodes()[2]
    data = network_inventory([node], reservations())["decos"][0]
    assert data["specified_parent_device_id"] == "node-1"
    assert data["specified_parent"] is None
    deco = TpLinkDeco(node["mac"])
    deco.update(node)
    deco.update({"mac": node["mac"], "group_status": "disconnected"})
    assert deco.topology == {"auto": None, "device_id": None}
    assert deco.device_id is None
    assert deco.parent_device_id is None
    assert not deco.online
    assert (
        not {"topology", "device_id", "mac"} & _deco_diagnostics(deco, "deco_1").keys()
    )


@pytest.mark.parametrize(
    "response", [{}, {"result": {}}, {"result": {"reservation_list": [{}]}}]
)
def test_malformed_reservations_fail(response):
    """A malformed reply must not masquerade as an empty reservation table."""
    with pytest.raises(KeyError):
        network_inventory(nodes(), response)


@pytest.mark.asyncio
async def test_shared_action_registration_routing_and_errors():
    """Register both action families and resolve entries freshly on every call."""
    registered = {}
    service_registry = MagicMock()
    service_registry.async_register.side_effect = (
        lambda domain, name, handler, **kw: registered.update({name: (handler, kw)})
    )
    hass = SimpleNamespace(data={DOMAIN: {}}, services=service_registry)
    assert await async_setup(hass, {})
    assert SERVICE_DOWNLOAD_SYSTEM_LOG in registered
    handler, options = registered[SERVICE_GET_NETWORK_INVENTORY]
    assert options["supports_response"] == SupportsResponse.ONLY
    with pytest.raises(ServiceValidationError):
        await handler(SimpleNamespace(data={}))
    api = SimpleNamespace(
        async_list_devices=AsyncMock(return_value=nodes()),
        async_list_address_reservations=AsyncMock(return_value=reservations()),
    )
    hass.data[DOMAIN]["one"] = {
        COORDINATOR_DECOS_KEY: SimpleNamespace(api=api, paused=True)
    }
    result = await handler(SimpleNamespace(data={}))
    assert len(result["decos"]) == 6
    hass.data[DOMAIN]["two"] = hass.data[DOMAIN]["one"]
    with pytest.raises(ServiceValidationError):
        await handler(SimpleNamespace(data={}))
    assert await handler(SimpleNamespace(data={"config_entry_id": "one"})) == result
    api.async_list_address_reservations.side_effect = RuntimeError("private payload")
    with pytest.raises(
        HomeAssistantError, match="^Unable to read Deco network inventory.$"
    ):
        await handler(SimpleNamespace(data={"config_entry_id": "one"}))
    hass.data[DOMAIN].pop("one")
    with pytest.raises(ServiceValidationError):
        await handler(SimpleNamespace(data={"config_entry_id": "one"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["expired", "transient"])
async def test_reservation_read_uses_shared_lock_and_auth_recovery(failure):
    """Exercise the real retry path without making any network requests."""
    api = TplinkDecoApi(MagicMock(), "http://router", "user", "password", False)
    api._stok = "existing"
    api._cookie = "sysauth=existing"
    api._seq = 1
    api._encode_payload = lambda payload: payload
    api.async_login_if_needed = AsyncMock()
    calls = []

    async def post(context, url, **kwargs):
        assert api._operation_lock.locked()
        calls.append(kwargs)
        assert url.endswith("/admin/client")
        if len(calls) == 1:
            if failure == "expired":
                return {"data": {"error_code": -5002}}
            raise TransientConnectionException("temporary")
        if failure == "expired":
            assert api._stok is None
        else:
            assert api._stok == "existing"
        return {"data": reservations()}

    api._async_post = post
    assert await api.async_list_address_reservations() == reservations()
    assert len(calls) == 2
    assert calls[0] == {
        "params": {"form": "addr_reservation"},
        "data": {"operation": "getlist"},
    }
    assert api.async_login_if_needed.await_count == 2
    assert not api._operation_lock.locked()


@pytest.mark.asyncio
async def test_inventory_domain_registration_survives_entry_reload(
    tmp_path, monkeypatch
):
    """Keep one domain action through entry setup, unload and setup again."""
    from homeassistant.core import HomeAssistant

    from custom_components import tplink_deco as integration
    from custom_components.tplink_deco.const import COORDINATOR_CLIENTS_KEY
    from custom_components.tplink_deco.const import COORDINATOR_MOBILE_KEY
    from custom_components.tplink_deco.const import COORDINATOR_WIRELESS_KEY

    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_forward_entry_unload = AsyncMock(return_value=True)
    entry = MagicMock(entry_id="network")
    # Entry refreshes are outside this lifecycle test; do not leave coroutines open.
    entry.async_create_background_task.side_effect = (
        lambda _hass, coro, **kw: coro.close()
    )
    apis = []

    async def create_data(_hass, _entry):
        api = SimpleNamespace(
            async_list_devices=AsyncMock(return_value=nodes()),
            async_list_address_reservations=AsyncMock(return_value=reservations()),
            async_logout=AsyncMock(),
        )
        apis.append(api)
        return {
            key: SimpleNamespace(
                api=api,
                paused=True,
                async_refresh=AsyncMock(),
                async_shutdown=AsyncMock(),
                async_close=AsyncMock(),
            )
            for key in (
                COORDINATOR_DECOS_KEY,
                COORDINATOR_CLIENTS_KEY,
                COORDINATOR_MOBILE_KEY,
                COORDINATOR_WIRELESS_KEY,
            )
        }

    monkeypatch.setattr(integration, "async_create_config_data", create_data)
    monkeypatch.setattr(
        integration, "async_setup_syslog_forwarder", AsyncMock(return_value=None)
    )
    register = MagicMock(wraps=hass.services.async_register)
    monkeypatch.setattr(
        type(hass.services),
        "async_register",
        lambda registry, *args, **kwargs: register(*args, **kwargs),
    )

    async def inventory():
        return await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_NETWORK_INVENTORY,
            {},
            blocking=True,
            return_response=True,
        )

    assert await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, SERVICE_GET_NETWORK_INVENTORY)
    assert hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD_SYSTEM_LOG)
    # An unloaded entry is a validation error, not an unknown action.
    with pytest.raises(ServiceValidationError):
        await inventory()
    handler = hass.services.async_services()[DOMAIN][SERVICE_GET_NETWORK_INVENTORY]
    assert await integration.async_setup_entry(hass, entry)
    expected = network_inventory(nodes(), reservations())
    assert await inventory() == expected
    assert await integration.async_unload_entry(hass, entry)
    assert hass.services.has_service(DOMAIN, SERVICE_GET_NETWORK_INVENTORY)
    assert hass.services.has_service(DOMAIN, SERVICE_DOWNLOAD_SYSTEM_LOG)
    with pytest.raises(ServiceValidationError):
        await inventory()
    assert await integration.async_setup_entry(hass, entry)
    assert await inventory() == expected
    assert apis[0].async_list_devices.await_count == 1
    assert apis[1].async_list_devices.await_count == 1
    assert (
        hass.services.async_services()[DOMAIN][SERVICE_GET_NETWORK_INVENTORY] is handler
    )
    for service in (SERVICE_GET_NETWORK_INVENTORY, SERVICE_DOWNLOAD_SYSTEM_LOG):
        assert (
            sum(call.args[:2] == (DOMAIN, service) for call in register.call_args_list)
            == 1
        )
    assert await integration.async_unload_entry(hass, entry)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_inventory_action_validation_does_not_require_registration(tmp_path):
    """HA can validate this ordinary service action before domain setup."""
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers import script

    hass = HomeAssistant(str(tmp_path))
    actions = cv.SCRIPT_SCHEMA(
        [
            {
                "action": "tplink_deco.get_network_inventory",
                "data": {},
                "response_variable": "inventory",
            }
        ]
    )
    assert not hass.services.has_service(DOMAIN, SERVICE_GET_NETWORK_INVENTORY)
    assert await script.async_validate_actions_config(hass, actions) == actions
    assert await async_setup(hass, {})
    assert await script.async_validate_actions_config(hass, actions) == actions
    await hass.async_block_till_done()
