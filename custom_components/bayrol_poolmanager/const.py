"""Constants for the PoolManager integration."""

from __future__ import annotations

DOMAIN = "bayrol_poolmanager"

CONF_CONNECTION = "connection"
CONF_DEVICE_ID = "device_id"
CONF_ACCESS_CODE = "access_code"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_REMOTE_USER = "remote_user"
CONF_REMOTE_PASSWORD = "remote_password"

CONNECTION_CLOUD = "cloud"
CONNECTION_LOCAL = "local"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30

CLOUD_BASE_URL = "https://www.bayrol-poolaccess.de"

# --- WebGUI variable identifiers (webgui.fcgi) ------------------------------
# Mapped on a PoolManager 5 "Chlorine" running firmware v221216-M1 (7.8.3).
# Other models / firmware versions may use different identifiers: please
# attach the integration diagnostics to an issue if something is missing.

ITEM_PH = "34.4001.value"
ITEM_REDOX = "34.4022.value"
ITEM_TEMP = "34.4033.value"
ITEM_PH_SETPOINT = "34.3001.value"
ITEM_REDOX_SETPOINT = "34.3049.value"

ITEM_PUMP_STATUS = "55.17106.status"  # LED: 0 green, 1 off, 2 yellow, 3 red
ITEM_PUMP_OPMODE = "55.17106.opmode"  # icon: 0 auto, 1 on, 2 off
ITEM_PUMP_MODE = "60.5432.value"  # mode setting: 1 on (normal), 2 auto, 4 off

ITEM_DOSING_PH = "14.16601.mode"  # e.g. "No Flow"
ITEM_DOSING_CL = "14.16604.mode"
ITEM_ALARM_COLLECTIVE = "44.2001.value"
ITEM_ALARM_NO_FLOW = "44.2003.value"

ITEM_LOGIN_CODE = "42.8028.code"  # "Customer (Level 2)" access code

# "User Login (remote access)" page shown at the start of every WebGUI session
LOGIN_PAGE = "9.17401.0"
LOGIN_USER = "9.17401.user"
LOGIN_PASS = "9.17401.pass"

# Filter pump programmable timer, intervals 1 to 6
TIMER_INTERVALS = {
    1: {
        "mode": "35.5184.value",
        "days": "36.5203.value",
        "on": "40.8533.value",
        "off": "40.8536.value",
        "label": "1.1257.value",
    },
    2: {
        "mode": "35.5185.value",
        "days": "36.5204.value",
        "on": "40.8534.value",
        "off": "40.8537.value",
        "label": "1.1258.value",
    },
    3: {
        "mode": "35.5186.value",
        "days": "36.5205.value",
        "on": "40.8535.value",
        "off": "40.8538.value",
        "label": "1.1259.value",
    },
    4: {
        "mode": "35.5187.value",
        "days": "36.5206.value",
        "on": "40.8539.value",
        "off": "40.8542.value",
        "label": "1.1260.value",
    },
    5: {
        "mode": "35.5188.value",
        "days": "36.5207.value",
        "on": "40.8540.value",
        "off": "40.8543.value",
        "label": "1.1261.value",
    },
    6: {
        "mode": "35.5189.value",
        "days": "36.5208.value",
        "on": "40.8541.value",
        "off": "40.8544.value",
        "label": "1.1262.value",
    },
}

# Interval pump mode (bit mask)
INTERVAL_MODES = {"off": 1, "normal": 2, "eco": 4, "increased": 8}
INTERVAL_MODES_REV = {v: k for k, v in INTERVAL_MODES.items()}

# Filter pump operating mode
PUMP_MODES = {"on": 1, "auto": 2, "off": 4}
PUMP_MODES_REV = {v: k for k, v in PUMP_MODES.items()}

PUMP_STATUS = {0: "running", 1: "stopped", 2: "warning", 3: "error"}

# Days: Monday = bit 0 ... Sunday = bit 6
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_PRESETS = {"every_day": 127, "weekdays": 31, "weekend": 96, "none": 0}
DAY_PRESETS_REV = {v: k for k, v in DAY_PRESETS.items()}

ALL_ITEMS: list[str] = [
    ITEM_PH,
    ITEM_REDOX,
    ITEM_TEMP,
    ITEM_PH_SETPOINT,
    ITEM_REDOX_SETPOINT,
    ITEM_PUMP_STATUS,
    ITEM_PUMP_OPMODE,
    ITEM_PUMP_MODE,
    ITEM_DOSING_PH,
    ITEM_DOSING_CL,
    ITEM_ALARM_COLLECTIVE,
    ITEM_ALARM_NO_FLOW,
] + [item for iv in TIMER_INTERVALS.values() for item in iv.values()]
