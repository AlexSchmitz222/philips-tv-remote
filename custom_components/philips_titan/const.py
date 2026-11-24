"""Constants for the Philips TV (Titan OS) integration."""

from datetime import timedelta
import logging

DOMAIN = "philips_titan"
LOGGER = logging.getLogger(__package__)

# Two requests per poll (ambilight state + volume). Do not poll faster:
# the TV's API locks up under load.
UPDATE_INTERVAL = timedelta(seconds=30)

# How long after Wake-on-LAN before the first check (TV boot time).
WAKE_REFRESH_DELAY = 15
