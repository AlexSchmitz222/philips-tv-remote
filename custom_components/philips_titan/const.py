"""Constants for the Philips TV (Titan OS) integration."""

import logging

DOMAIN = "philips_titan"
LOGGER = logging.getLogger(__package__)

# Two requests per poll (ambilight state + volume). A stress test
# (scripts/stress_poll.py, 2026-11-24) ran 4 requests/s without any
# slowdown, so 5 s is far on the safe side.
DEFAULT_SCAN_INTERVAL = 5
MIN_SCAN_INTERVAL = 2
MAX_SCAN_INTERVAL = 300

# How long after Wake-on-LAN before the first check (TV boot time).
WAKE_REFRESH_DELAY = 15

# notifychange long-poll: how long one request stays open, pause after an
# error, and minimum time between two long-poll starts (no busy loop).
NOTIFY_TIMEOUT = 30
NOTIFY_RETRY = 15
NOTIFY_MIN_GAP = 1.0
