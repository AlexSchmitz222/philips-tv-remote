"""Constants for the Philips TV (Titan OS) integration."""

import logging

DOMAIN = "philips_titan"
LOGGER = logging.getLogger(__package__)

# Three reads per poll (ambilight state, volume, context). A stress test
# (scripts/stress_poll.py, 2026-11-24) ran 4 requests/s without any
# slowdown, so 5 s is far on the safe side.
DEFAULT_SCAN_INTERVAL = 5
MIN_SCAN_INTERVAL = 2
MAX_SCAN_INTERVAL = 300

# How long after Wake-on-LAN before the first check (TV boot time).
WAKE_REFRESH_DELAY = 15

# Option: read the LED colours (ambilight/processed) on every poll.
CONF_AMBILIGHT_COLORS = "ambilight_colors"
