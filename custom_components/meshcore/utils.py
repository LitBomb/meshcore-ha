"""Utility functions for the MeshCore integration."""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DEFAULT_DEVICE_NAME,
    DOMAIN,
    MESSAGES_SUFFIX,
    CHANNEL_PREFIX,
    NodeType,
)

_LOGGER = logging.getLogger(__name__)


def get_node_type_str(node_type: str | None) -> str:
    """Convert NodeType to a human-readable string."""
    if node_type == NodeType.CLIENT:
        return "Client"
    elif node_type == NodeType.REPEATER:
        return "Repeater"
    elif node_type == NodeType.ROOM_SERVER:
        return "Room Server"
    else:
        return "Unknown"


def sanitize_name(name: str, replace_hyphens: bool = True) -> str:
    """Convert a name to a format safe for entity IDs.
    
    Converts to lowercase, replaces spaces with underscores,
    optionally replaces hyphens with underscores, and removes double underscores.
    """
    if not name:
        return ""
        
    safe_name = name.lower().replace(" ", "_")
    if replace_hyphens:
        safe_name = safe_name.replace("-", "_")
    return safe_name.replace("__", "_")

def get_device_key(coordinator: DataUpdateCoordinator, default: str = "") -> str:
    """Get the sanitized device name from coordinator data."""
    if not coordinator or not hasattr(coordinator, "data") or not coordinator.data:
        return sanitize_name(default)
        
    return coordinator.data.get("public_key", default)

def get_device_name(coordinator: DataUpdateCoordinator, default: str = DEFAULT_DEVICE_NAME) -> str:
    """Get the sanitized device name from coordinator data."""
    if not coordinator or not hasattr(coordinator, "data") or not coordinator.data:
        return sanitize_name(default)
        
    raw_name = coordinator.data.get("name", default)
    return sanitize_name(raw_name)


def format_entity_id(domain: str, device_name: str, entity_key: str, suffix: str = "") -> str:
    """Format a consistent entity ID.
    
    Args:
        domain: Entity domain (e.g., 'binary_sensor', 'sensor')
        device_name: Device name (already sanitized)
        entity_key: Entity-specific identifier
        suffix: Optional suffix for the entity ID
        
    Returns:
        Formatted entity ID with proper format: domain.name_parts
    """
    if not domain or not entity_key:
        _LOGGER.warning("Missing required parameters for entity ID formatting")
        return ""
    
    # Build the entity name parts (everything after the domain)
    # Filter out empty strings to prevent double underscores
    name_parts = [part for part in [DOMAIN, device_name, entity_key, suffix] if part]
    
    # Join parts with underscores and clean up any double underscores
    entity_name = "_".join(name_parts).replace("__", "_")
    
    # Format as domain.entity_name
    return f"{domain}.{entity_name}"


def get_channel_entity_id(domain: str, device_name: str, channel_idx: int, suffix: str = MESSAGES_SUFFIX) -> str:
    """Create a consistent entity ID for channel entities."""
    safe_channel = f"{CHANNEL_PREFIX}{channel_idx}"
    return format_entity_id(domain, device_name, safe_channel, suffix)


def get_contact_entity_id(domain: str, device_name: str, pubkey: str, suffix: str = MESSAGES_SUFFIX) -> str:
    """Create a consistent entity ID for contact entities."""
    return format_entity_id(domain, device_name, pubkey, suffix)


def extract_channel_idx(entity_key: str) -> int:
    """Extract channel index from an entity key."""
    try:
        if entity_key and entity_key.startswith(CHANNEL_PREFIX):
            channel_idx_str = entity_key.replace(CHANNEL_PREFIX, "")
            return int(channel_idx_str)
    except (ValueError, TypeError):
        _LOGGER.warning(f"Could not extract channel index from {entity_key}")
    
    return 0  # Default to channel 0 on error


def find_coordinator_with_device_name(hass_data: Dict[str, Any]) -> tuple[Optional[DataUpdateCoordinator], str]:
    """Find a coordinator with device name information.
    
    Returns:
        Tuple of (coordinator, device_name)
    """
    device_name = DEFAULT_DEVICE_NAME
    coordinator = None
    
    # Look through all coordinators to find one with a device name
    if hass_data and DOMAIN in hass_data:
        for entry_id, coord in hass_data[DOMAIN].items():
            if hasattr(coord, "data") and "name" in coord.data:
                coordinator = coord
                device_name = get_device_name(coordinator)
                break
                
    return coordinator, device_name