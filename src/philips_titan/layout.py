"""Ambilight menu layout – detected from menuitems/settings/structure.

Node ids and string ids differ between models/firmwares (e.g. a 55PML9019
reports "MLM_PHM_KEY_MAIN_AMBILIGHT_STYLE", the 65PQS8651 "MAIN_AMBILIGHT_STYLE").
Nodes are therefore found by their ``context`` field, list items by their
string id with the optional prefix stripped. Anything not found falls back to
the layout verified on the 65PQS8651/12 (``MenuLayout.default()``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import AmbilightStyle

PREFIX = "MLM_PHM_KEY_"

# normalized enum string_id -> (key, display name)
KNOWN_ITEMS: dict[str, tuple[str, str]] = {
    "MISC_AI": ("ai", "AI"),
    "MAIN_AMBILIGHT_STYLE_VIDEO_1_2K20": ("standard", "Standard"),
    "MAIN_AMBILIGHT_STYLE_VIDEO_3_2K20": ("sports", "Sports"),
    "MAIN_AMBILIGHT_CINEMA": ("cinema", "Cinema"),
    "MAIN_AMBILIGHT_GAME_2K23": ("game", "Game"),
    "MAIN_AMBILIGHT_STYLE_AUDIO_1_2K20": ("lumina", "Lumina"),
    "MAIN_FOLLOW_AUDIO_STYLE_3_2K23": ("party", "Party"),
    "MAIN_AMBILIGHT_STYLE_AUDIO_3_2K20": ("rhythm", "Rhythm"),
    "MAIN_AMBILIGHT_FIXED_COLOUR": ("fixed_colour", "Fixed colour"),
}

# context of the menu nodes we need
CTX_STYLE = "ambilight_style"
CTX_OFF = "ambilight_off"
CTX_VIDEO = "ambilight_follow_video"
CTX_AUDIO = "ambilight_follow_audio"
CTX_COLOUR = "ambilight_lounge_light"
CTX_BRIGHTNESS = "ambilight_brightness"
CTX_SATURATION = "ambilight_saturation"


def normalize(string_id: str | None) -> str:
    sid = string_id or ""
    return sid[len(PREFIX):] if sid.startswith(PREFIX) else sid


@dataclass(frozen=True)
class Node:
    id: int
    sid: str


@dataclass(frozen=True)
class Slider(Node):
    min: int
    max: int


@dataclass
class MenuLayout:
    style: Node
    off: int
    video: Node | None
    audio: Node | None
    colour: Node | None
    brightness: Slider | None
    saturation: Slider | None
    styles: tuple[AmbilightStyle, ...]
    detected: bool = False
    _by_key: dict[str, AmbilightStyle] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_key = {s.key: s for s in self.styles}

    # ------------------------------------------------------------ lookups

    @property
    def categories(self) -> tuple[Node, ...]:
        return tuple(n for n in (self.video, self.audio, self.colour) if n)

    @property
    def state_nodes(self) -> list[int]:
        nodes = [self.style.id, *(n.id for n in self.categories)]
        nodes += [n.id for n in (self.brightness, self.saturation) if n]
        return nodes

    def style_by_key(self, key: str) -> AmbilightStyle:
        return self._by_key[key]

    def style_for(self, category: int, item: Any) -> AmbilightStyle | None:
        return next((s for s in self.styles if s.category == category and s.item == item), None)

    @property
    def fixed_colour(self) -> AmbilightStyle | None:
        return next((s for s in self.styles if self.colour and s.category == self.colour.id), None)

    # ------------------------------------------------------------ builders

    @classmethod
    def default(cls) -> MenuLayout:
        """Layout verified on the 65PQS8651/12 (fw 066.002.126.131)."""
        video = Node(320, "MAIN_FOLLOW_VIDEO")
        audio = Node(330, "MAIN_FOLLOW_AUDIO")
        colour = Node(340, "MAIN_FOLLOW_COLOUR")
        items = [(video, 321, "MISC_AI"), (video, 322, "MAIN_AMBILIGHT_STYLE_VIDEO_1_2K20"),
                 (video, 323, "MAIN_AMBILIGHT_STYLE_VIDEO_3_2K20"), (video, 324, "MAIN_AMBILIGHT_CINEMA"),
                 (video, 325, "MAIN_AMBILIGHT_GAME_2K23"), (audio, 331, "MAIN_AMBILIGHT_STYLE_AUDIO_1_2K20"),
                 (audio, 332, "MAIN_FOLLOW_AUDIO_STYLE_3_2K23"), (audio, 333, "MAIN_AMBILIGHT_STYLE_AUDIO_3_2K20"),
                 (colour, 345, "MAIN_AMBILIGHT_FIXED_COLOUR")]
        styles = tuple(AmbilightStyle(*KNOWN_ITEMS[sid], node.id, node.sid, item) for node, item, sid in items)
        return cls(
            style=Node(300, "MAIN_AMBILIGHT_STYLE"),
            off=310,
            video=video,
            audio=audio,
            colour=colour,
            brightness=Slider(710, "PC_ID_BRIGH_L12", 0, 10),
            saturation=Slider(720, "ID_AMB_SAT", -2, 2),
            styles=styles,
        )

    @classmethod
    def from_structure(cls, structure: Any) -> MenuLayout:
        """Build from a GET menuitems/settings/structure answer; missing
        parts fall back to the default layout."""
        nodes: dict[str, dict[str, Any]] = {}

        def walk(o: Any) -> None:
            if isinstance(o, dict):
                ctx = o.get("context")
                if isinstance(o.get("node_id"), int) and isinstance(ctx, str) and ctx not in nodes:
                    nodes[ctx] = o
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(structure)
        base = cls.default()
        if CTX_STYLE not in nodes:
            return base

        def node(ctx: str, fallback: Node | None) -> Node | None:
            n = nodes.get(ctx)
            return Node(n["node_id"], n.get("string_id") or "") if n else fallback

        def slider(ctx: str, fallback: Slider | None) -> Slider | None:
            n = nodes.get(ctx)
            if not n:
                return fallback
            sd = (n.get("data") or {}).get("slider_data") or {}
            return Slider(n["node_id"], n.get("string_id") or "", int(sd.get("min", 0)), int(sd.get("max", 10)))

        video, audio, colour = node(CTX_VIDEO, None), node(CTX_AUDIO, None), node(CTX_COLOUR, None)
        styles: list[AmbilightStyle] = []
        for cat, prefix in ((video, "video"), (audio, "audio"), (colour, "colour")):
            if not cat:
                continue
            enums = (nodes[_ctx_of(nodes, cat.id)].get("data") or {}).get("enums") or []
            for e in enums:
                if not isinstance(e.get("enum_id"), int):
                    continue
                sid = normalize(e.get("string_id"))
                key, name = KNOWN_ITEMS.get(sid, (f"{prefix}_{e['enum_id']}", sid.title().replace("_", " ")))
                styles.append(AmbilightStyle(key, name, cat.id, cat.sid, e["enum_id"]))

        style_node = node(CTX_STYLE, base.style)
        off = nodes.get(CTX_OFF, {}).get("node_id", base.off)
        return cls(
            style=style_node,  # type: ignore[arg-type]
            off=off,
            video=video,
            audio=audio,
            colour=colour,
            brightness=slider(CTX_BRIGHTNESS, base.brightness),
            saturation=slider(CTX_SATURATION, base.saturation),
            styles=tuple(styles) or base.styles,
            detected=True,
        )


def _ctx_of(nodes: dict[str, dict[str, Any]], node_id: int) -> str:
    return next(ctx for ctx, n in nodes.items() if n["node_id"] == node_id)
