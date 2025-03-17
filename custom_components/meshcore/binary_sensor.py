"""Binary sensor platform for MeshCore integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    ENTITY_DOMAIN_BINARY_SENSOR,
    MESSAGES_SUFFIX,
    CHANNEL_PREFIX,
)
from .utils import (
    sanitize_name,
    get_device_name,
    format_entity_id,
    get_channel_entity_id,
    get_contact_entity_id,
    extract_channel_idx,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up MeshCore message entities from config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    _LOGGER.debug("Setting up MeshCore message entities")
    
    entities = []
    
    # Add channel message entities for channels 0-3
    for channel_idx in range(4):  # Channels 0, 1, 2, 3
        safe_channel = f"{CHANNEL_PREFIX}{channel_idx}"
        _LOGGER.debug(f"Creating channel entity for channel {channel_idx} with entity_key {safe_channel}")
        entities.append(MeshCoreMessageEntity(
            coordinator,
            safe_channel,
            f"Channel {channel_idx} Messages"
        ))
    
    # Create an entity for each contact
    contacts = coordinator.data.get("contacts", [])
    if contacts:
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
                
            contact_name = contact.get("adv_name", "")
            if contact_name:
                safe_name = sanitize_name(contact_name)
                _LOGGER.debug(f"Creating contact entity for '{contact_name}' with safe name '{safe_name}'")
                entities.append(MeshCoreMessageEntity(
                    coordinator,
                    safe_name,
                    f"{contact_name} Messages",
                    public_key=contact.get("public_key", "")
                ))
    
    _LOGGER.debug(f"Created entities: {entities}")
    
    # Add the entities
    async_add_entities(entities)


class MeshCoreMessageEntity(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor entity that tracks mesh network messages."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    
    @property
    def state(self) -> str:
        """Return the state of the entity."""
        return "Active" if self.is_on else "Inactive"
    
    def __init__(
        self, 
        coordinator: DataUpdateCoordinator, 
        entity_key: str,
        name: str,
        public_key: str = ""
    ) -> None:
        """Initialize the message entity."""
        super().__init__(coordinator)
        
        # Store entity type and public key if applicable
        self.entity_key = entity_key
        self.public_key = public_key
        
        # Get device name for unique ID and entity_id
        device_name = get_device_name(coordinator)
        
        # Set unique ID with device name included - ensure consistent format with no empty parts
        parts = [part for part in [coordinator.config_entry.entry_id, device_name, entity_key, MESSAGES_SUFFIX] if part]
        self._attr_unique_id = "_".join(parts)
        
        # Manually set entity_id to match logbook entity_id format
        self.entity_id = format_entity_id(
            ENTITY_DOMAIN_BINARY_SENSOR, 
            device_name, 
            entity_key, 
            MESSAGES_SUFFIX
        )
        
        # Debug: Log the entity ID for troubleshooting
        _LOGGER.debug(f"Created entity with ID: {self.entity_id}")
        
        self._attr_name = name
        
        # Set icon based on entity type
        if self.entity_key.startswith(CHANNEL_PREFIX):
            self._attr_icon = "mdi:message-bulleted"
        else:
            self._attr_icon = "mdi:message-text-outline"
        
        # Set device info to link to the main device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        )
    
    @property
    def is_on(self) -> bool:
        """Return true if there are unread messages."""
        if self.entity_key.startswith(CHANNEL_PREFIX):
            # For channel messages
            if hasattr(self.coordinator, "_channel_message_history"):
                try:
                    # Extract channel index from entity_key
                    channel_idx = extract_channel_idx(self.entity_key)
                    
                    # Check if this channel has messages
                    if channel_idx in self.coordinator._channel_message_history:
                        return len(self.coordinator._channel_message_history[channel_idx]) > 0
                except Exception as ex:
                    _LOGGER.warning(f"Error checking channel messages: {ex}")
        else:
            # For contact-specific messages
            if hasattr(self.coordinator, "_client_message_history"):
                # Find messages for this contact
                # The entity_key is the safe version of the contact name
                # We need to find the original contact name
                for contact_name, msgs in self.coordinator._client_message_history.items():
                    safe_name = sanitize_name(contact_name)
                    if safe_name == self.entity_key or contact_name == self.entity_key:
                        return len(msgs) > 0
        
        # Default if no messages found
        return False
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return message details as attributes."""
        attributes = {
            "last_updated": datetime.now().isoformat()
        }
        
        if self.entity_key.startswith(CHANNEL_PREFIX):
            # For channel-specific message entities
            try:
                # Extract channel index from entity_key
                channel_idx = extract_channel_idx(self.entity_key)
                
                # Add channel info to attributes
                attributes["channel_index"] = channel_idx
                
                # Add message count only
                if hasattr(self.coordinator, "_channel_message_history") and channel_idx in self.coordinator._channel_message_history:
                    attributes["message_count"] = len(self.coordinator._channel_message_history[channel_idx])
                else:
                    attributes["message_count"] = 0
                
            except (ValueError, TypeError):
                _LOGGER.warning(f"Could not get channel index from {self.entity_key}")
                
        else:
            # For contact-specific message entities
            message_count = 0
            if hasattr(self.coordinator, "_client_message_history"):
                # Find this contact's messages
                for contact_name, msgs in self.coordinator._client_message_history.items():
                    safe_name = sanitize_name(contact_name)
                    if safe_name == self.entity_key or contact_name == self.entity_key:
                        message_count = len(msgs)
                        break
            
            attributes["message_count"] = message_count
            attributes["public_key"] = self.public_key
            
        return attributes