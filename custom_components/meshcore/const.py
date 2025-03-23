"""Constants for the MeshCore integration."""
from enum import IntEnum
from typing import Final

DOMAIN: Final = "meshcore"

# Connection types
CONF_CONNECTION_TYPE: Final = "connection_type"
CONF_USB_PATH: Final = "usb_path"
CONF_BLE_ADDRESS: Final = "ble_address"
CONF_TCP_HOST: Final = "tcp_host"
CONF_TCP_PORT: Final = "tcp_port"
CONF_BAUDRATE: Final = "baudrate"
DEFAULT_BAUDRATE: Final = 115200
DEFAULT_TCP_PORT: Final = 5000

# Connection type options
CONNECTION_TYPE_USB: Final = "usb"
CONNECTION_TYPE_BLE: Final = "ble"
CONNECTION_TYPE_TCP: Final = "tcp"

# Polling settings
CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds

# Services
SERVICE_SEND_MESSAGE: Final = "send_message"
ATTR_NODE_ID: Final = "node_id"
ATTR_MESSAGE: Final = "message"

# Platform constants
PLATFORM_MESSAGE: Final = "message"

# Entity naming constants
ENTITY_DOMAIN_BINARY_SENSOR: Final = "binary_sensor"
ENTITY_DOMAIN_SENSOR: Final = "sensor"
DEFAULT_DEVICE_NAME: Final = "meshcore"
MESSAGES_SUFFIX: Final = "messages"
CONTACT_SUFFIX: Final = "contact"
CHANNEL_PREFIX: Final = "channel_"

# Repeater subscription constants
CONF_REPEATER_SUBSCRIPTIONS: Final = "repeater_subscriptions"
CONF_REPEATER_NAME: Final = "repeater_name"
CONF_REPEATER_PASSWORD: Final = "repeater_password"
CONF_REPEATER_UPDATE_INTERVAL: Final = "repeater_update_interval"
DEFAULT_REPEATER_UPDATE_INTERVAL: Final = 300  # 5 minutes in seconds

# Update intervals for different data types
CONF_INFO_INTERVAL: Final = "info_interval"  # For both node info and contacts
CONF_MESSAGES_INTERVAL: Final = "messages_interval"

DEFAULT_INFO_INTERVAL: Final = 60  # 1 minute in seconds
DEFAULT_MESSAGES_INTERVAL: Final = 10   # 10 seconds - base polling interval

# Other constants
CONNECTION_TIMEOUT: Final = 10  # seconds

class NodeType(IntEnum):
    CLIENT = 1
    REPEATER = 2