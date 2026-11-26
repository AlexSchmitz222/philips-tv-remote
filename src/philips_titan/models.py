"""Device knowledge for Titan OS (verified on 65PQS8651/12, see docs/api.md)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AmbilightStyle:
    key: str          # stable identifier used by the library / HA
    name: str         # display name (as the TV reports it where available)
    category: int     # list node selected via the style node (activenode_id)
    category_sid: str
    item: int         # enum_id inside the category list


# Menu node ids / items are detected per TV, see layout.MenuLayout
# (MenuLayout.default() is the layout verified on the 65PQS8651/12).


@dataclass
class AmbilightState:
    on: bool
    style: AmbilightStyle | None   # None when off or unknown
    brightness: int | None         # menu brightness (0..10 on the 65PQS8651)
    saturation: int | None         # menu saturation (-2..2 on the 65PQS8651)


@dataclass
class Volume:
    current: int
    muted: bool
    min: int = 0
    max: int = 60


# Key names accepted by POST input/key (JointSpace). Only the ones marked
# "tested" have been verified on Titan OS.
KEYS = (
    "Standby",        # tested
    "VolumeUp",       # tested
    "VolumeDown",     # tested
    "Mute",           # tested (toggles; state readable via audio/volume)
    "CursorUp", "CursorDown", "CursorLeft", "CursorRight", "Confirm", "Back",
    "Home", "Options", "Info", "Find", "Adjust", "Source", "WatchTV",
    "ChannelStepUp", "ChannelStepDown",
    # Digits: tested – "5004", "5005" switched streaming channels (1 s apart).
    "Digit0", "Digit1", "Digit2", "Digit3", "Digit4",
    "Digit5", "Digit6", "Digit7", "Digit8", "Digit9", "Dot",
    "PlayPause", "Play", "Pause", "Stop", "Rewind", "FastForward",
    "Next", "Previous", "Record",
    "RedColour", "GreenColour", "YellowColour", "BlueColour",
    "Subtitle", "Teletext", "AmbilightOnOff", "Online", "Viewmode",
)
