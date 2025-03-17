"""Sensor platform for MeshCore integration."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    NODE_TYPE_CLIENT,
    NODE_TYPE_REPEATER,
    ENTITY_DOMAIN_SENSOR,
    DEFAULT_DEVICE_NAME,
    CONF_REPEATER_SUBSCRIPTIONS,
    CONF_REPEATER_NAME,
    CONF_REPEATER_PASSWORD,
    CONF_REPEATER_UPDATE_INTERVAL,
)
from .utils import (
    sanitize_name,
    get_device_name,
    format_entity_id,
)

_LOGGER = logging.getLogger(__name__)

# Battery voltage constants
MIN_BATTERY_VOLTAGE = 3.2  # Minimum LiPo voltage
MAX_BATTERY_VOLTAGE = 4.2  # Maximum LiPo voltage

# Define sensors for the main device
SENSORS = [
    SensorEntityDescription(
        key="node_status",
        name="Node Status",
        icon="mdi:radio-tower",
    ),
    SensorEntityDescription(
        key="battery_voltage",
        name="Battery Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key="battery_percentage",
        name="Battery Percentage",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key="node_count",
        name="Node Count",
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="tx_power",
        name="TX Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:power",
    ),
    SensorEntityDescription(
        key="latitude",
        name="Latitude",
        icon="mdi:map-marker",
    ),
    SensorEntityDescription(
        key="longitude",
        name="Longitude",
        icon="mdi:map-marker",
    ),
    SensorEntityDescription(
        key="frequency",
        name="Frequency",
        native_unit_of_measurement="MHz",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:radio",
    ),
    SensorEntityDescription(
        key="bandwidth",
        name="Bandwidth",
        native_unit_of_measurement="kHz",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:radio",
    ),
    SensorEntityDescription(
        key="spreading_factor",
        name="Spreading Factor",
        icon="mdi:radio",
    ),
]

# Sensors for remote nodes/contacts
CONTACT_SENSORS = [
    SensorEntityDescription(
        key="status",
        name="Status",
        icon="mdi:radio-tower",
    ),
    SensorEntityDescription(
        key="battery",
        name="Battery",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key="battery_percentage",
        name="Battery Percentage",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key="last_rssi",
        name="Last RSSI",
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal",
    ),
    SensorEntityDescription(
        key="last_snr",
        name="Last SNR",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal",
    ),
]

# Additional sensors only for repeaters (type 2)
REPEATER_SENSORS = [
    SensorEntityDescription(
        key="bat",
        name="Battery Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement="V",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key="battery_percentage",
        name="Battery Percentage",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key="uptime",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock",
    ),
    SensorEntityDescription(
        key="airtime",
        name="Airtime",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:radio",
    ),
    SensorEntityDescription(
        key="nb_sent",
        name="Messages Sent",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:message-arrow-right",
    ),
    SensorEntityDescription(
        key="nb_recv",
        name="Messages Received",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:message-arrow-left",
    ),
    SensorEntityDescription(
        key="tx_queue_len",
        name="TX Queue Length",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:playlist-edit",
    ),
    SensorEntityDescription(
        key="free_queue_len",
        name="Free Queue Length",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:playlist-plus",
    ),
    SensorEntityDescription(
        key="sent_flood",
        name="Sent Flood Messages",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:message-arrow-right-outline",
    ),
    SensorEntityDescription(
        key="sent_direct",
        name="Sent Direct Messages",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:message-arrow-right",
    ),
    SensorEntityDescription(
        key="recv_flood",
        name="Received Flood Messages",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:message-arrow-left-outline",
    ),
    SensorEntityDescription(
        key="recv_direct",
        name="Received Direct Messages",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:message-arrow-left",
    ),
    SensorEntityDescription(
        key="full_evts",
        name="Full Events",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:alert-circle",
    ),
    SensorEntityDescription(
        key="direct_dups",
        name="Direct Duplicates",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:content-duplicate",
    ),
    SensorEntityDescription(
        key="flood_dups",
        name="Flood Duplicates",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:content-duplicate",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up MeshCore sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    _LOGGER.debug("Setting up MeshCore sensors")
    
    entities = []
    
    # Create sensors for the main device
    for description in SENSORS:
        _LOGGER.debug("Adding sensor: %s", description.key)
        entities.append(MeshCoreSensor(coordinator, description))
    
    # Add a contact list sensor to track all contacts
    entities.append(MeshCoreContactListSensor(coordinator))
    
    # Create a diagnostic sensor for each contact
    contacts = coordinator.data.get("contacts", [])
    if contacts:
        _LOGGER.debug("Creating diagnostic sensors for %d contacts", len(contacts))
        
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
                
            try:
                name = contact.get("adv_name", "Unknown")
                public_key = contact.get("public_key", "")
                node_type = contact.get("type")
                
                if not public_key:
                    continue
                    
                # Create a unique ID for this contact - filter out any empty parts
                parts = [part for part in [entry.entry_id, "contact", public_key[:10]] if part]
                contact_id = "_".join(parts)
                
                # Create diagnostic sensor for this contact
                sensor = MeshCoreContactDiagnosticSensor(
                    coordinator, 
                    name,
                    public_key,
                    contact_id
                )
                
                # Initialize attributes, icon, and name based on node type
                sensor._update_attributes()
                entities.append(sensor)
                
            except Exception as ex:
                _LOGGER.error("Error setting up contact diagnostic sensor: %s", ex)
    
    # First, handle cleanup of removed repeater devices
    # Get registries
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    
    # Add repeater stat sensors if any repeaters are configured
    repeater_subscriptions = entry.data.get(CONF_REPEATER_SUBSCRIPTIONS, [])
    repeater_names = {r.get("name") for r in repeater_subscriptions if r.get("name") and r.get("enabled", True)}
    
    # Create a set of device IDs for active repeaters
    active_repeater_device_ids = set()
    for repeater_name in repeater_names:
        safe_name = sanitize_name(repeater_name)
        device_id = f"{entry.entry_id}_repeater_{safe_name}"
        active_repeater_device_ids.add(device_id)
    
    # Find and remove any repeater devices that are no longer in the configuration
    for device in list(device_registry.devices.values()):
        # Check if this is a device from this integration
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                device_id = identifier[1]
                
                # If this device is a repeater but not in our active list, remove it
                if "_repeater_" in device_id and device_id not in active_repeater_device_ids:
                    _LOGGER.info(f"Removing device {device.name} ({device_id}) as it's no longer configured")
                    device_registry.async_remove_device(device.id)
    
    if repeater_subscriptions:
        _LOGGER.debug("Creating sensors for %d repeater subscriptions", len(repeater_subscriptions))
        
        for repeater in repeater_subscriptions:
            if not repeater.get("enabled", True):
                continue
                
            repeater_name = repeater.get("name")
            if not repeater_name:
                continue
                
            _LOGGER.info(f"Creating sensors for repeater: {repeater_name}")
            
            # Create repeater status sensor
            for description in REPEATER_SENSORS:
                try:
                    # Create a sensor for this repeater stat
                    sensor = MeshCoreRepeaterSensor(
                        coordinator,
                        description,
                        repeater_name
                    )
                    entities.append(sensor)
                except Exception as ex:
                    _LOGGER.error(f"Error creating repeater sensor {description.key}: {ex}")
    
    async_add_entities(entities)


class MeshCoreSensor(CoordinatorEntity, SensorEntity):
    """Representation of a MeshCore sensor."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        
        # Set unique ID using consistent format - filter out any empty parts
        parts = [part for part in [coordinator.config_entry.entry_id, description.key] if part]
        self._attr_unique_id = "_".join(parts)
        
        # Set name
        self._attr_name = description.name
        
        # Get raw device name for display purposes
        raw_device_name = coordinator.data.get('name', 'Node') if coordinator.data else 'Node'
        
        # Set device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=f"MeshCore {raw_device_name}",
            manufacturer="MeshCore",
            model="Mesh Radio",
            sw_version=coordinator.data.get("version", "Unknown") if coordinator.data else "Unknown",
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None

        key = self.entity_description.key
        
        if key == "node_status":
            if getattr(self.coordinator, "last_update_success", False):
                return "online"
            return "offline"
            
        elif key == "battery_voltage":
            bat_value = self.coordinator.data.get("bat", 0)
            if isinstance(bat_value, (int, float)) and bat_value > 0:
                return bat_value / 10  # Convert to voltage
            return None
            
        elif key == "battery_percentage":
            bat_value = self.coordinator.data.get("bat", 0)
            if isinstance(bat_value, (int, float)) and bat_value > 0:
                voltage = bat_value / 10  # Convert to voltage
                # Calculate percentage based on min/max voltage range
                percentage = ((voltage - MIN_BATTERY_VOLTAGE) / 
                             (MAX_BATTERY_VOLTAGE - MIN_BATTERY_VOLTAGE)) * 100
                
                # Ensure percentage is within 0-100 range
                percentage = max(0, min(100, percentage))
                return round(percentage, 1)  # Round to 1 decimal place
            return None
            
        elif key == "node_count":
            contacts = self.coordinator.data.get("contacts", [])
            return len(contacts) + 1
            
        elif key == "tx_power":
            return self.coordinator.data.get("tx_power")
            
        elif key == "latitude":
            return self.coordinator.data.get("adv_lat")
            
        elif key == "longitude":
            return self.coordinator.data.get("adv_lon")
            
        elif key == "frequency":
            freq = self.coordinator.data.get("radio_freq")
            if freq is not None:
                return freq / 1000
            return None
            
        elif key == "bandwidth":
            bw = self.coordinator.data.get("radio_bw") 
            if bw is not None:
                # Check if already in kHz
                if bw < 1000:
                    return bw  # Already in kHz
                else:
                    return bw / 1_000  # Convert Hz to kHz
            return None
            
        elif key == "spreading_factor":
            return self.coordinator.data.get("radio_sf")
        
        return None


class MeshCoreContactListSensor(CoordinatorEntity, SensorEntity):
    """A sensor to track all MeshCore contacts in a single entity."""

    def __init__(self, coordinator: DataUpdateCoordinator) -> None:
        """Initialize the contact list sensor."""
        super().__init__(coordinator)
        
        # Set unique ID and name
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_contacts"
        self._attr_name = "MeshCore Contacts"
        
        # Set device info to link to the main device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        )
        
        # Set entity category to diagnostic
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        
        # Use a custom icon
        self._attr_icon = "mdi:account-group"

    @property
    def native_value(self) -> str:
        """Return the current number of contacts as the state."""
        if not self.coordinator.data:
            return "0"
            
        contacts = self.coordinator.data.get("contacts", [])
        return str(len(contacts))
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return details about all contacts as attributes."""
        if not self.coordinator.data:
            return {}
            
        contacts = self.coordinator.data.get("contacts", [])
        if not contacts:
            return {"contacts": []}
            
        contact_list = []
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
                
            # Extract the key info we want to display
            contact_info = {
                "name": contact.get("adv_name", "Unknown"),
                "type": "Repeater" if contact.get("type") == NODE_TYPE_REPEATER else "Client",
                "public_key": contact.get("public_key", "")[:16] + "...",  # Truncate for display
                "last_seen": contact.get("last_advert", 0),
            }
            
            # Add location if available
            if "adv_lat" in contact and "adv_lon" in contact:
                contact_info["location"] = f"{contact.get('adv_lat')}, {contact.get('adv_lon')}"
                
            contact_list.append(contact_info)
            
        # Sort by name
        contact_list.sort(key=lambda x: x.get("name", ""))
        
        return {
            "contacts": contact_list,
            "last_updated": datetime.now().isoformat(),
        }
        

class MeshCoreContactDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """A diagnostic sensor for a single MeshCore contact."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        contact_name: str,
        public_key: str,
        contact_id: str,
    ) -> None:
        """Initialize the contact diagnostic sensor."""
        super().__init__(coordinator)
        
        self.contact_name = contact_name
        self.public_key = public_key
        
        # Set unique ID
        self._attr_unique_id = contact_id
        
        # Initial name (will be updated in _update_attributes)
        self._attr_name = contact_name
        
        # Set device info to link to the main device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        )
        
        # Set entity category to diagnostic
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        
        # Icon will be set dynamically in the _update_attributes method

    def _get_contact_data(self) -> Dict[str, Any]:
        """Get the data for this contact from the coordinator."""
        if not self.coordinator.data or not isinstance(self.coordinator.data, dict):
            return {}
            
        contacts = self.coordinator.data.get("contacts", [])
        if not contacts:
            return {}
            
        # Find this contact by name or by public key
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
                
            # Match by name
            if contact.get("adv_name") == self.contact_name:
                return contact
                
            # Match by public key prefix
            if contact.get("public_key", "").startswith(self.public_key):
                return contact
                
        return {}

    def _update_attributes(self) -> Dict[str, Any]:
        """Update the attributes and icon based on contact data."""
        contact = self._get_contact_data()
        if not contact:
            # If contact not found, use default icon
            self._attr_icon = "mdi:radio-tower"
            self._attr_name = self.contact_name
            return {"status": "unknown"}
            
        # Create a copy of the contact data for attributes
        attributes = {}
        
        # Add all contact properties directly as attributes
        for key, value in contact.items():
            attributes[key] = value
            
        # Get the node type and set icon accordingly
        node_type = contact.get("type")
        
        # Set different icons and names based on node type
        if node_type == NODE_TYPE_CLIENT:  # Client
            self._attr_icon = "mdi:account"
            self._attr_name = f"{self.contact_name} (Client)"
            attributes["node_type_str"] = "Client"
        elif node_type == NODE_TYPE_REPEATER:  # Repeater
            self._attr_icon = "mdi:radio-tower"
            self._attr_name = f"{self.contact_name} (Repeater)"
            attributes["node_type_str"] = "Repeater"
        else:
            # Default icon if type is unknown
            self._attr_icon = "mdi:help-network"
            self._attr_name = f"{self.contact_name} (Unknown)"
            attributes["node_type_str"] = "Unknown"
        
        # Format last advertisement time if available
        if "last_advert" in attributes and attributes["last_advert"] > 0:
            last_advert_time = datetime.fromtimestamp(attributes["last_advert"])
            attributes["last_advert_formatted"] = last_advert_time.isoformat()
            
        return attributes
        
    @property
    def native_value(self) -> str:
        """Return the contact's status as the state."""
        contact = self._get_contact_data()
        if not contact:
            return "unknown"
            
        # Check last advertisement time for contact status
        last_advert = contact.get("last_advert", 0)
        if last_advert > 0:
            # Calculate time since last advert
            time_since = time.time() - last_advert
            # If less than 12 hour, consider fresh
            if time_since < 3600*12:
                return "fresh"
        
        return "stale"
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the raw contact data as attributes."""
        return self._update_attributes()


class MeshCoreRepeaterSensor(CoordinatorEntity, SensorEntity):
    """Sensor for repeater statistics."""
    
    def __init__(
        self, 
        coordinator: DataUpdateCoordinator,
        description: SensorEntityDescription,
        repeater_name: str,
    ) -> None:
        """Initialize the repeater stat sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.repeater_name = repeater_name
        
        # Create sanitized names
        safe_name = sanitize_name(repeater_name)
        
        # Generate a unique device_id for this repeater
        self.device_id = f"{coordinator.config_entry.entry_id}_repeater_{safe_name}"
        
        # Set unique ID
        self._attr_unique_id = f"{self.device_id}_{description.key}"
        
        # Set friendly name
        self._attr_name = description.name
        
        # Set entity ID
        self.entity_id = format_entity_id(
            ENTITY_DOMAIN_SENSOR,
            safe_name,
            description.key
        )
        
        # Set device info to create a separate device for this repeater
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=f"MeshCore Repeater: {repeater_name}",
            manufacturer="MeshCore",
            model="Mesh Repeater",
            via_device=(DOMAIN, coordinator.config_entry.entry_id),  # Link to the main device
        )
    
    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if not self.coordinator.data or "repeater_stats" not in self.coordinator.data:
            return None
            
        # Get the repeater stats for this repeater
        repeater_stats = self.coordinator.data.get("repeater_stats", {}).get(self.repeater_name, {})
        if not repeater_stats:
            return None
        
        key = self.entity_description.key
        
        # Special handling for battery voltage - convert from mV to V
        if key == "bat":
            bat_value = repeater_stats.get("bat")
            if isinstance(bat_value, (int, float)) and bat_value > 0:
                # Convert from millivolts to volts
                return bat_value / 1000.0
            return None
        elif key == "battery_percentage":
            bat_value = repeater_stats.get("bat")
            if isinstance(bat_value, (int, float)) and bat_value > 0:
                voltage = bat_value / 1000.0  # Convert mV to V
                # Calculate percentage based on min/max voltage range
                percentage = ((voltage - MIN_BATTERY_VOLTAGE) / 
                             (MAX_BATTERY_VOLTAGE - MIN_BATTERY_VOLTAGE)) * 100
                
                # Ensure percentage is within 0-100 range
                percentage = max(0, min(100, percentage))
                return round(percentage, 1)  # Round to 1 decimal place
            return None
        elif key == "uptime":
            # Convert from seconds to minutes
            seconds = repeater_stats.get("uptime")
            if isinstance(seconds, (int, float)) and seconds > 0:
                return round(seconds / 60, 1)  # Convert to minutes and round to 1 decimal
            return None
        elif key == "airtime":
            # Convert from seconds to minutes
            seconds = repeater_stats.get("airtime")
            if isinstance(seconds, (int, float)) and seconds > 0:
                return round(seconds / 60, 1)  # Convert to minutes and round to 1 decimal
            return None
            
        # Get the value from the repeater stats for other sensors
        return repeater_stats.get(key)
        
    @property
    def available(self) -> bool:
        """Return if the sensor is available."""
        # Check if coordinator is available and we have data for this repeater
        if not super().available or not self.coordinator.data:
            return False
            
        # Check if we have stats for this repeater
        repeater_stats = self.coordinator.data.get("repeater_stats", {})
        return self.repeater_name in repeater_stats
        
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data or "repeater_stats" not in self.coordinator.data:
            return {}
            
        # Get the repeater stats for this repeater
        repeater_stats = self.coordinator.data.get("repeater_stats", {}).get(self.repeater_name, {})
        if not repeater_stats:
            return {}
            
        attributes = {}
        key = self.entity_description.key
        
        # Add raw values for certain sensors to help with debugging
        if key == "bat":
            bat_value = repeater_stats.get("bat")
            if isinstance(bat_value, (int, float)) and bat_value > 0:
                attributes["raw_millivolts"] = bat_value
        elif key in ["uptime", "airtime"]:
            seconds = repeater_stats.get(key)
            if isinstance(seconds, (int, float)) and seconds > 0:
                attributes["raw_seconds"] = seconds
                
                # Also add a human-readable format for uptime
                if key == "uptime":
                    days = seconds // 86400
                    hours = (seconds % 86400) // 3600
                    minutes = (seconds % 3600) // 60
                    secs = seconds % 60
                    attributes["human_readable"] = f"{days}d {hours}h {minutes}m {secs}s"
                    
        return attributes






