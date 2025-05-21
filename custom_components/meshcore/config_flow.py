"""Config flow for MeshCore integration."""
import logging
import asyncio
import os
from typing import Any, Dict, Optional

import meshcore

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from bleak import BleakScanner
from meshcore.events import EventType

from .const import (
    CONF_NAME,
    CONF_PUBKEY,
    DOMAIN,
    CONF_CONNECTION_TYPE,
    CONF_USB_PATH,
    CONF_BLE_ADDRESS,
    CONF_TCP_HOST,
    CONF_TCP_PORT,
    CONF_BAUDRATE,
    CONNECTION_TYPE_USB,
    CONNECTION_TYPE_BLE,
    CONNECTION_TYPE_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_TCP_PORT,
    CONNECTION_TIMEOUT,
    CONF_REPEATER_SUBSCRIPTIONS,
    CONF_REPEATER_NAME,
    CONF_REPEATER_PASSWORD,
    CONF_REPEATER_UPDATE_INTERVAL,
    DEFAULT_REPEATER_UPDATE_INTERVAL,
    NodeType,
)
from .meshcore_api import MeshCoreAPI

_LOGGER = logging.getLogger(__name__)

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONNECTION_TYPE): vol.In(
            [CONNECTION_TYPE_USB, CONNECTION_TYPE_BLE, CONNECTION_TYPE_TCP]
        ),
    }
)

USB_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USB_PATH): str,
        vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): cv.positive_int
    }
)

BLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BLE_ADDRESS): str
    }
)

TCP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TCP_HOST): str,
        vol.Optional(CONF_TCP_PORT, default=DEFAULT_TCP_PORT): cv.port
    }
)

async def validate_common(api: MeshCoreAPI) -> Dict[str, Any]:
    """Validate the user input allows us to connect to the USB device."""
    try: 
        # Try to connect with timeout
        connect_success = await asyncio.wait_for(api.connect(), timeout=CONNECTION_TIMEOUT)
        
        # Check if connection was successful
        if not connect_success or not api._mesh_core:
            _LOGGER.error("Failed to connect to device - connect() returned False")
            raise CannotConnect("Device connection failed")
            
        # Get node info to verify communication
        node_info = await api._mesh_core.commands.send_appstart()
        
        # Validate we got meaningful info back
        if node_info.type == EventType.ERROR:
            _LOGGER.error("Failed to get node info - received error: %s", node_info.payload)
            raise CannotConnect("Failed to get node info")
            
        # Disconnect when done
        await api.disconnect()
        
        # Extract and log the device information
        device_name = node_info.payload.get('name', 'Unknown')
        public_key = node_info.payload.get('public_key', '')
        
        # Log the values we're extracting
        _LOGGER.info(f"Validating device - Name: {device_name}, Public Key: {public_key[:10]}")
        
        # If we get here, the connection was successful and we got valid info
        return {"title": f"MeshCore Node {device_name}", "name": device_name, "pubkey": public_key}
    except asyncio.TimeoutError:
        raise CannotConnect("Connection timed out")
    except Exception as ex:
        _LOGGER.error("Validation error: %s", ex)
        raise CannotConnect(f"Failed to connect: {str(ex)}")

async def validate_usb_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the user input allows us to connect to the USB device."""
    api = MeshCoreAPI(
        hass=hass,
        connection_type=CONNECTION_TYPE_USB,
        usb_path=data[CONF_USB_PATH],
        baudrate=data[CONF_BAUDRATE],
    )
    return await validate_common(api)


async def validate_ble_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the user input allows us to connect to the BLE device."""
    api = MeshCoreAPI(
        hass=hass,
        connection_type=CONNECTION_TYPE_BLE,
        ble_address=data[CONF_BLE_ADDRESS],
    ) 
    return await validate_common(api)


async def validate_tcp_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the user input allows us to connect to the TCP device."""
    api = MeshCoreAPI(
        hass=hass,
        connection_type=CONNECTION_TYPE_TCP,
        tcp_host=data[CONF_TCP_HOST],
        tcp_port=data[CONF_TCP_PORT],
    )
    return await validate_common(api)


class MeshCoreConfigFlow(config_entries.ConfigFlow, domain=DOMAIN): # type: ignore
    """Handle a config flow for MeshCore."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self.connection_type: Optional[str] = None
        self.discovery_info: Optional[Dict[str, Any]] = None
        
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self.connection_type = user_input[CONF_CONNECTION_TYPE]
            
            if self.connection_type == CONNECTION_TYPE_USB:
                return await self.async_step_usb()
            if self.connection_type == CONNECTION_TYPE_BLE:
                return await self.async_step_ble()
            if self.connection_type == CONNECTION_TYPE_TCP:
                return await self.async_step_tcp()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_usb(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle USB configuration."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_usb_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data={
                    CONF_CONNECTION_TYPE: CONNECTION_TYPE_USB,
                    CONF_USB_PATH: user_input[CONF_USB_PATH],
                    CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                    CONF_NAME: info.get("name"),
                    CONF_PUBKEY: info.get("pubkey"),
                    CONF_REPEATER_SUBSCRIPTIONS: [],  # Initialize with empty repeater subscriptions
                })
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # Always allow manual entry for USB path
        # Skip trying to detect ports completely
        return self.async_show_form(
            step_id="usb", 
            data_schema=vol.Schema({
                vol.Required(CONF_USB_PATH): str,
                vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): cv.positive_int,
            }),
            errors=errors
        )

    async def async_step_ble(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle BLE configuration."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_ble_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data={
                    CONF_CONNECTION_TYPE: CONNECTION_TYPE_BLE,
                    CONF_BLE_ADDRESS: user_input[CONF_BLE_ADDRESS],
                    CONF_NAME: info.get("name"),
                    CONF_PUBKEY: info.get("pubkey"),
                    CONF_REPEATER_SUBSCRIPTIONS: [],  # Initialize with empty repeater subscriptions
                })
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # Scan for BLE devices
        devices = {}
        try:
            scanner = BleakScanner()
            discovered_devices = await scanner.discover(timeout=5.0)
            for device in discovered_devices:
                if device.name and "MeshCore" in device.name:
                    devices[device.address] = f"{device.name} ({device.address})"
        except Exception as ex:
            _LOGGER.warning("Failed to scan for BLE devices: %s", ex)

        # If we have discovered devices, show them in a dropdown
        if devices:
            schema = vol.Schema(
                {
                    vol.Required(CONF_BLE_ADDRESS): vol.In(devices),
                }
            )
        else:
            # Otherwise, allow manual entry, but with simplified schema
            schema = vol.Schema({
                vol.Required(CONF_BLE_ADDRESS): str,
            })

        return self.async_show_form(
            step_id="ble", data_schema=schema, errors=errors
        )

    async def async_step_tcp(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle TCP configuration."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_tcp_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data={
                    CONF_CONNECTION_TYPE: CONNECTION_TYPE_TCP,
                    CONF_TCP_HOST: user_input[CONF_TCP_HOST],
                    CONF_TCP_PORT: user_input[CONF_TCP_PORT],
                    CONF_NAME: info.get("name"),
                    CONF_PUBKEY: info.get("pubkey"),
                    CONF_REPEATER_SUBSCRIPTIONS: [] # Initialize with empty repeater subscriptions
                })
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="tcp", 
            data_schema=vol.Schema({
                vol.Required(CONF_TCP_HOST): str,
                vol.Optional(CONF_TCP_PORT, default=DEFAULT_TCP_PORT): cv.port
            }),
            errors=errors
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for MeshCore."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self.repeater_subscriptions = list(config_entry.data.get(CONF_REPEATER_SUBSCRIPTIONS, []))
        self.hass = None

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            # Get the action from the input
            action = user_input.get("action")
            
            if action == "add_repeater":
                # Go to add repeater screen
                return await self.async_step_add_repeater()
                
            elif action == "remove_repeater" and user_input.get("repeater_to_remove"):
                # Remove the selected repeater
                repeater_to_remove = user_input.get("repeater_to_remove")

                # The repeater_to_remove has format: "Name (prefix)"
                selected_str = repeater_to_remove
                # Extract the pubkey from between parentheses
                start = selected_str.rfind("(") + 1
                end = selected_str.rfind(")")
                pubkey_prefix_to_remove = selected_str[start:end]

                # Update the list without the removed repeater by comparing pubkey prefix
                self.repeater_subscriptions = [
                    r for r in self.repeater_subscriptions
                    if not (r.get("pubkey_prefix") and
                           r.get("pubkey_prefix").startswith(pubkey_prefix_to_remove))
                ]
                
                # Update the config entry data
                new_data = dict(self.config_entry.data)
                new_data[CONF_REPEATER_SUBSCRIPTIONS] = self.repeater_subscriptions
                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data) # type: ignore
                
                # Return to the init step to show updated list
                return await self.async_step_init()
                
            else:
                # Save options
                new_options = {}
                return self.async_create_entry(title="", data=new_options)

        # Build the schema with a list of options
        schema = {
            vol.Optional(
                "action"
            ): vol.In({
                "add_repeater": "Add Repeater",
                "remove_repeater": "Remove Repeater",
            }),
        }
        
        # If there are repeaters and the action is remove, add a selection dropdown
        if self.repeater_subscriptions and "action" in schema:
            # Create a dictionary for dropdown with pubkey_prefix as the value
            repeater_entries = {}
            for r in self.repeater_subscriptions:
                name = r.get("name", "")
                pubkey_prefix = r.get("pubkey_prefix", "")
                if name and pubkey_prefix:
                    # Display name includes pubkey prefix
                    display_name = f"{name} ({pubkey_prefix})"
                    # Value is the pubkey_prefix for unique identification
                    repeater_entries[display_name] = display_name

            if repeater_entries:
                schema["repeater_to_remove"] = vol.In(repeater_entries)
        
        # Filter out None values, defaults, or empty strings
        repeater_display_names = []
        for r in self.repeater_subscriptions:
            name = r.get("name")
            pubkey_prefix = r.get("pubkey_prefix", "")
            if name and isinstance(name, str):
                # Include prefix in display name if available
                if pubkey_prefix:
                    repeater_display_names.append(f"{name} ({pubkey_prefix})")
                else:
                    repeater_display_names.append(name)

        repeater_str = ", ".join(repeater_display_names) if repeater_display_names else "None configured"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "repeaters": repeater_str
            },
        )
        
        
    def _get_repeater_contacts(self):
        """Get repeater contacts from coordinator's cached data."""
        # Get the coordinator
        if not self.hass or DOMAIN not in self.hass.data:
            return []

        coordinator = self.hass.data[DOMAIN].get(self.config_entry.entry_id) # type: ignore
        if not coordinator:
            return []

        # Get contacts from the _contacts attribute
        repeater_contacts = []

        # Only proceed if _contacts attribute exists
        if not hasattr(coordinator, "_contacts"):
            return []

        for contact in coordinator._contacts: # type: ignore
            if not isinstance(contact, dict):
                continue

            contact_name = contact.get("adv_name", "")
            if not contact_name:
                continue

            contact_type = contact.get("type")

            # Check for repeater (2) or room server (3) node types
            if contact_type == NodeType.REPEATER or contact_type == NodeType.ROOM_SERVER:
                public_key = contact.get("public_key", "")
                pubkey_prefix = public_key[:12] if public_key else ""

                # Add tuple of (pubkey_prefix, name)
                if pubkey_prefix:
                    repeater_contacts.append((pubkey_prefix, contact_name))

        return repeater_contacts
        
    def _show_add_repeater_form(self, repeater_dict, errors=None, user_input=None):
        """Helper to show repeater form with current values preserved."""
        if errors is None:
            errors = {}
            
        # Get values from user_input or use defaults
        default_password = ""
        default_interval = DEFAULT_REPEATER_UPDATE_INTERVAL
        
        if user_input:
            default_password = user_input.get(CONF_REPEATER_PASSWORD, "")
            default_interval = user_input.get(CONF_REPEATER_UPDATE_INTERVAL, DEFAULT_REPEATER_UPDATE_INTERVAL)
            
        return self.async_show_form(
            step_id="add_repeater",
            data_schema=vol.Schema({
                vol.Required(CONF_REPEATER_NAME): vol.In(repeater_dict.keys()),
                vol.Optional(CONF_REPEATER_PASSWORD, default=default_password): str,
                vol.Optional(CONF_REPEATER_UPDATE_INTERVAL, default=default_interval): int,
            }),
            errors=errors,
        )
        
    async def async_step_add_repeater(self, user_input=None):
        """Handle adding a new repeater subscription."""
        errors = {}
        
        # Get repeater contacts
        repeater_contacts = self._get_repeater_contacts()
        
        # Show the form with repeater selection
        if not repeater_contacts:
            # No repeaters found
            return self.async_show_form(
                step_id="add_repeater",
                data_schema=vol.Schema({
                    vol.Required("no_repeaters", default="No repeaters found in contacts. Please ensure your device has repeaters in its contacts list."): str,
                }),
                errors=errors,
            )

        # Create a dictionary with name as key and (prefix, name) tuple as value
        repeater_dict = {}
        for prefix, name in repeater_contacts:
            display_name = f"{name} ({prefix})"
            repeater_dict[display_name] = (prefix, name)
            
        if user_input is None:
            # First time showing form
            return self._show_add_repeater_form(repeater_dict)
            
        selected_repeater = user_input.get(CONF_REPEATER_NAME)
        password = user_input.get(CONF_REPEATER_PASSWORD)
        update_interval = user_input.get(CONF_REPEATER_UPDATE_INTERVAL, DEFAULT_REPEATER_UPDATE_INTERVAL)

        # The selected_repeater has format: "Name (prefix)"
        selected_str = selected_repeater
        # Extract the pubkey from between parentheses
        start = selected_str.rfind("(") + 1
        end = selected_str.rfind(")")
        pubkey_prefix = selected_str[start:end]
        # Extract name (everything before the open parenthesis)
        repeater_name = selected_str[:start-1].strip()

        # Check if this repeater is already in the subscriptions by prefix
        existing_prefixes = [r.get("pubkey_prefix") for r in self.repeater_subscriptions]
        if pubkey_prefix in existing_prefixes:
            errors["base"] = "Repeater is already configured"
            return self._show_add_repeater_form(repeater_dict, errors, user_input)

        coordinator = self.hass.data[DOMAIN].get(self.config_entry.entry_id) # type: ignore
        meshcore = coordinator.api.mesh_core # type: ignore

        # validate the repeater can be logged into
        contact = meshcore.get_contact_by_key_prefix(pubkey_prefix)
        if not contact:
            _LOGGER.error(f"Contact not found with public key prefix: {pubkey_prefix}")
            errors["base"] = "Contact not found"
            return self._show_add_repeater_form(repeater_dict, errors, user_input)
            
        # Try to login
        send_result = await meshcore.commands.send_login(contact, password)
        
        if send_result.type == EventType.ERROR:
            error_message = send_result.payload
            _LOGGER.error("Failed to login to repeater - received error: %s", error_message)
            errors["base"] = "Failed to log in to repeater. Check password and try again."
            return self._show_add_repeater_form(repeater_dict, errors, user_input)
        
        result = await meshcore.wait_for_event(EventType.LOGIN_SUCCESS, timeout=10)
        if not result:
            _LOGGER.error("Timed out waiting for login success")
            errors["base"] = "Timed out waiting for login response"
            return self._show_add_repeater_form(repeater_dict, errors, user_input)
        
        if result.type == EventType.ERROR:
            error_message = result.payload if hasattr(result, 'payload') else "Unknown error"
            _LOGGER.error("Failed to login to repeater - received error: %s", error_message)
            errors["base"] = "Failed to log in to repeater. Check password and try again."
            return self._show_add_repeater_form(repeater_dict, errors, user_input)
            
            
        # Login successful, now optionally check for version
        send_result = await meshcore.commands.send_cmd(contact, "ver")
        
        if send_result.type == EventType.ERROR:
            _LOGGER.error("Failed to get repeater version - received error: %s", send_result.payload)
            
        filter = { "pubkey_prefix": contact.get("public_key")[:12] }

        msg = await meshcore.wait_for_event(EventType.CONTACT_MSG_RECV, filter, timeout=15)
        _LOGGER.debug("Received ver message: %s", msg)
        ver = "Unknown"
        if not msg or msg.type == EventType.ERROR:
            _LOGGER.error("Failed to get repeater version")
        elif msg.type == EventType.CONTACT_MSG_RECV:
            ver = msg.payload.get("text")
            _LOGGER.info("Repeater version: %s", ver)
        
        # Add the new repeater subscription with pubkey_prefix
        self.repeater_subscriptions.append({
            "name": repeater_name,
            "pubkey_prefix": pubkey_prefix,
            "firmware_version": ver,
            "password": password,
            "update_interval": update_interval,
            "enabled": True,
        })

        # Update the config entry data
        new_data = dict(self.config_entry.data)
        new_data[CONF_REPEATER_SUBSCRIPTIONS] = self.repeater_subscriptions
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data) # type: ignore

        # Return to the init step
        return await self.async_step_init() # type: ignore
        
