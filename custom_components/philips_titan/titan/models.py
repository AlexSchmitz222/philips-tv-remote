"""Device knowledge for Titan OS (verified on 65PQS8651/12, see docs/api.md)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AmbilightStyle:
    key: str          # stable identifier used by the library / HA
    name: str         # display name (as the TV reports it where available)
    category: int     # child of menu node 300 (activenode_id)
    category_sid: str
    item: int         # enum_id inside the category list


NODE_STYLE = 300
SID_STYLE = "MAIN_AMBILIGHT_STYLE"
NODE_OFF = 310
NODE_VIDEO, SID_VIDEO = 320, "MAIN_FOLLOW_VIDEO"
NODE_AUDIO, SID_AUDIO = 330, "MAIN_FOLLOW_AUDIO"
NODE_COLOUR, SID_COLOUR = 340, "MAIN_FOLLOW_COLOUR"
NODE_BRIGHTNESS, SID_BRIGHTNESS = 710, "PC_ID_BRIGH_L12"  # 0..10, visibly works
NODE_SATURATION, SID_SATURATION = 720, "ID_AMB_SAT"       # -2..2, effect unverified

BRIGHTNESS_MAX = 10
SATURATION_MIN, SATURATION_MAX = -2, 2

STYLES: tuple[AmbilightStyle, ...] = (
    AmbilightStyle("ai", "AI", NODE_VIDEO, SID_VIDEO, 321),
    AmbilightStyle("standard", "Standard", NODE_VIDEO, SID_VIDEO, 322),
    AmbilightStyle("sports", "Sports", NODE_VIDEO, SID_VIDEO, 323),
    AmbilightStyle("cinema", "Cinema", NODE_VIDEO, SID_VIDEO, 324),
    AmbilightStyle("game", "Game", NODE_VIDEO, SID_VIDEO, 325),
    AmbilightStyle("lumina", "Lumina", NODE_AUDIO, SID_AUDIO, 331),
    AmbilightStyle("party", "Party", NODE_AUDIO, SID_AUDIO, 332),
    AmbilightStyle("rhythm", "Rhythm", NODE_AUDIO, SID_AUDIO, 333),
    AmbilightStyle("fixed_colour", "Fixed colour", NODE_COLOUR, SID_COLOUR, 345),
)
STYLES_BY_KEY = {s.key: s for s in STYLES}
STYLES_BY_ITEM = {s.item: s for s in STYLES}
FIXED_COLOUR = STYLES_BY_KEY["fixed_colour"]

# Read in one menuitems/settings/current request
STATE_NODES = [NODE_STYLE, NODE_VIDEO, NODE_AUDIO, NODE_COLOUR, NODE_BRIGHTNESS, NODE_SATURATION]


@dataclass
class AmbilightState:
    on: bool
    style: AmbilightStyle | None   # None when off or unknown
    brightness: int | None         # 0..10 (menu node 710)
    saturation: int | None         # -2..2 (menu node 720)


@dataclass
class AmbilightColors:
    """Colours the LEDs currently show (GET ambilight/processed)."""

    average: tuple[int, int, int] | None          # over all LEDs
    sides: dict[str, tuple[int, int, int]]        # per side (left/top/right)
    leds: int

    @classmethod
    def from_processed(cls, data: dict) -> "AmbilightColors":
        all_px: list[tuple[int, int, int]] = []
        sides: dict[str, tuple[int, int, int]] = {}
        for layer in (data or {}).values():
            if not isinstance(layer, dict):
                continue
            for side, pixels in layer.items():
                px = [
                    (p["r"], p["g"], p["b"])
                    for p in (pixels or {}).values()
                    if isinstance(p, dict) and {"r", "g", "b"} <= p.keys()
                ]
                if px:
                    sides[side] = _mean(px)
                    all_px += px
        return cls(average=_mean(all_px) if all_px else None, sides=sides, leds=len(all_px))


def _mean(px: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    return tuple(round(sum(p[i] for p in px) / len(px)) for i in range(3))  # type: ignore[return-value]


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
