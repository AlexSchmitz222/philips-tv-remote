"""Command line tool for exploring the TV's API.

    titan info                      # unauthenticated /system
    titan pair                      # interactive pairing, writes credentials.json
    titan get ambilight/mode
    titan post ambilight/lounge '{"color": {...}}'   (or @file.json)
    titan dump                      # read-only survey of known endpoints -> dumps/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from .client import TitanConnectionError, TitanError, TitanTV, TitanUnsafeRequestError
from .models import KEYS, STYLES_BY_KEY
from .pairing import pair_grant, pair_request

DEFAULT_HOST = "192.168.178.78"
CRED_FILE = Path("credentials.json")

# Read-only GET endpoints known from other JointSpace v6 clients. Not all of
# them exist on Titan OS – finding out which ones do is the point of `dump`.
DUMP_GET = [
    "system",
    "powerstate",
    "audio/volume",
    "ambilight/power",
    "ambilight/mode",
    "ambilight/topology",
    "ambilight/currentconfiguration",
    "ambilight/supportedstyles",
    # "ambilight/lounge" – GET hängt die API auf, siehe client.UNSAFE_REQUESTS
    "ambilight/cached",
    "ambilight/measured",
    "ambilight/processed",
    "ambilight/ambihue/power",
    "huelamp/power",
    "activities/current",
    "activities/tv",
    "applications",
    "channeldb/tv",
    "sources",
    "context",
    "menuitems/settings/structure",
]


def _load_creds(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = json.loads(path.read_text())
    return data


def _make_tv(args: argparse.Namespace, auth: bool = True) -> TitanTV:
    creds = _load_creds(args.credentials) if auth else {}
    host = args.host or creds.get("host") or DEFAULT_HOST
    return TitanTV(
        host,
        creds.get("username"),
        creds.get("password"),
        min_interval=args.interval,
    )


def _print(data: Any) -> None:
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(data)


def _collect_node_ids(node: Any, out: list[int]) -> None:
    if isinstance(node, dict):
        nid = node.get("node_id", node.get("Nodeid"))
        if isinstance(nid, int):
            out.append(nid)
        for v in node.values():
            _collect_node_ids(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_node_ids(v, out)


async def cmd_info(args: argparse.Namespace) -> None:
    async with _make_tv(args, auth=False) as tv:
        _print(await tv.system())


async def cmd_pair(args: argparse.Namespace) -> None:
    async with _make_tv(args, auth=False) as tv:
        session = await pair_request(tv)
        print(f"PIN wird am Fernseher angezeigt (Timeout: {session.timeout} s).")
        pin = await asyncio.to_thread(input, "PIN: ")
        result = await pair_grant(tv, session, pin)
        _print(result)
        args.credentials.write_text(
            json.dumps(
                {"host": tv.host, "username": session.username, "password": session.password},
                indent=2,
            )
        )
        args.credentials.chmod(0o600)
        print(f"Zugangsdaten gespeichert in {args.credentials.resolve()}")
        tv.set_credentials(session.username, session.password)
        print("Test (ambilight/mode):")
        _print(await tv.get("ambilight/mode"))


async def cmd_get(args: argparse.Namespace) -> None:
    async with _make_tv(args) as tv:
        _print(await tv.get(args.path))


async def cmd_post(args: argparse.Namespace) -> None:
    raw = args.body
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text()
    async with _make_tv(args) as tv:
        _print(await tv.post(args.path, json.loads(raw)))


def _status_of(err: TitanError) -> str:
    if isinstance(err, TitanUnsafeRequestError):
        return "blocked"
    if isinstance(err, TitanConnectionError):
        return "timeout"
    if "HTTP 404" in str(err):
        return "404"
    return "error"


async def cmd_dump(args: argparse.Namespace) -> None:
    """Probe endpoints one by one. Stops at the first timeout, because the
    API is then most likely wedged – continuing only makes it worse.

    --resume DIR continues an earlier dump: endpoints with a final result
    (ok / empty / 404 / blocked) are skipped, timeouts are retried.
    """
    if args.resume:
        out = Path(args.resume)
        summary: dict[str, str] = json.loads((out / "_summary.json").read_text()) \
            if (out / "_summary.json").exists() else {}
    else:
        out = Path(args.out) / time.strftime("%Y%m%d-%H%M%S")
        out.mkdir(parents=True, exist_ok=True)
        summary = {}

    def save_summary() -> None:
        (out / "_summary.json").write_text(json.dumps(summary, indent=2))

    paths = args.only or DUMP_GET
    todo = [p for p in paths if summary.get(p) in (None, "timeout", "error")]
    async with _make_tv(args) as tv:
        for path in todo:
            try:
                data = await tv.get(path)
                status = "ok" if data is not None else "empty"
            except TitanError as err:
                data, status = {"error": str(err)}, _status_of(err)
            summary[path] = status
            save_summary()
            print(f"{status:8} {path}")
            (out / (path.replace("/", "_") + ".json")).write_text(
                json.dumps(data, indent=2, ensure_ascii=False)
            )
            if status == "timeout":
                print(
                    f"\nABBRUCH: {path} hat nicht geantwortet. Vermutlich hängt die API.\n"
                    "Prüfen, ob der Fernseher noch reagiert (Fernbedienung, `titan info`).\n"
                    "Falls nötig Strom trennen. Danach fortsetzen mit:\n"
                    f"  titan dump --resume {out}",
                    file=sys.stderr,
                )
                sys.exit(2)

        structure_file = out / "menuitems_settings_structure.json"
        structure = None
        if summary.get("menuitems/settings/structure") == "ok":
            structure = json.loads(structure_file.read_text())
        if structure and not (out / "menuitems_settings_current.json").exists():
            ids: list[int] = []
            _collect_node_ids(structure, ids)
            ids = sorted(set(ids))
            print(f"menuitems/settings/current für {len(ids)} Knoten …")
            current: dict[str, Any] = {}
            # in Blöcken, damit eine einzelne Antwort nicht riesig wird
            for i in range(0, len(ids), 50):
                chunk = ids[i : i + 50]
                try:
                    current[f"{chunk[0]}-{chunk[-1]}"] = await tv.menu_current(chunk)
                except TitanConnectionError as err:
                    print(f"ABBRUCH bei menuitems/settings/current: {err}", file=sys.stderr)
                    sys.exit(2)
                except TitanError as err:
                    current[f"{chunk[0]}-{chunk[-1]}"] = {"error": str(err)}
            (out / "menuitems_settings_current.json").write_text(
                json.dumps(current, indent=2, ensure_ascii=False)
            )

    print(f"Fertig: {out.resolve()}")


async def cmd_state(args: argparse.Namespace) -> None:
    async with _make_tv(args) as tv:
        st = await tv.ambilight_state()
        vol = await tv.volume()
    print(f"Ambilight: {'an' if st.on else 'aus'}"
          f"{' – ' + st.style.name if st.style else ''}"
          f", Helligkeit {st.brightness}/10, Sättigung {st.saturation}")
    print(f"Lautstärke: {vol.current}/{vol.max}{' (stumm)' if vol.muted else ''}")


async def cmd_style(args: argparse.Namespace) -> None:
    async with _make_tv(args) as tv:
        if args.style == "off":
            await tv.ambilight_off()
        else:
            await tv.set_ambilight_style(args.style, await tv.ambilight_state())


async def cmd_colour(args: argparse.Namespace) -> None:
    # Eingabe wie in HA: Farbton 0–360°, Sättigung 0–100 %, Helligkeit 0–255
    async with _make_tv(args) as tv:
        await tv.set_ambilight_colour(
            round(args.hue * 255 / 360), round(args.sat * 255 / 100), args.brightness,
            await tv.ambilight_state(),
        )


async def cmd_brightness(args: argparse.Namespace) -> None:
    async with _make_tv(args) as tv:
        await tv.set_ambilight_brightness(args.value)


async def cmd_volume(args: argparse.Namespace) -> None:
    async with _make_tv(args) as tv:
        if args.value is None:
            v = await tv.volume()
            print(f"{v.current}/{v.max}{' (stumm)' if v.muted else ''}")
        else:
            await tv.set_volume(args.value)


async def cmd_key(args: argparse.Namespace) -> None:
    async with _make_tv(args) as tv:
        await tv.send_key(args.key)


async def cmd_wake(args: argparse.Namespace) -> None:
    from .wol import wake
    wake(args.mac, args.broadcast)
    print("Magic Packet gesendet (wirkt nur aus dem Netz des Fernsehers)")


def main() -> None:
    p = argparse.ArgumentParser(prog="titan")
    p.add_argument("--host")
    p.add_argument("--credentials", type=Path, default=CRED_FILE)
    p.add_argument("--interval", type=float, default=2.0, help="Pause zwischen Anfragen (s)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info").set_defaults(func=cmd_info)
    sub.add_parser("pair").set_defaults(func=cmd_pair)
    g = sub.add_parser("get")
    g.add_argument("path")
    g.set_defaults(func=cmd_get)
    po = sub.add_parser("post")
    po.add_argument("path")
    po.add_argument("body", help="JSON oder @datei.json")
    po.set_defaults(func=cmd_post)
    d = sub.add_parser("dump")
    d.add_argument("--out", default="dumps")
    d.add_argument("--resume", metavar="DIR", help="früheren Dump fortsetzen")
    d.add_argument("--only", nargs="+", metavar="PATH", help="nur diese Endpunkte")
    d.set_defaults(func=cmd_dump)

    sub.add_parser("state", help="Ambilight + Lautstärke anzeigen").set_defaults(func=cmd_state)
    st = sub.add_parser("style", help="Ambilight-Stil setzen")
    st.add_argument("style", choices=["off", *STYLES_BY_KEY])
    st.set_defaults(func=cmd_style)
    co = sub.add_parser("colour", help="feste Farbe (Farbton 0–360, Sättigung 0–100)")
    co.add_argument("hue", type=float)
    co.add_argument("sat", type=float)
    co.add_argument("brightness", type=int, nargs="?", default=255)
    co.set_defaults(func=cmd_colour)
    br = sub.add_parser("brightness", help="Ambilight-Helligkeit 0–10")
    br.add_argument("value", type=int)
    br.set_defaults(func=cmd_brightness)
    vo = sub.add_parser("volume", help="Lautstärke lesen/setzen")
    vo.add_argument("value", type=int, nargs="?")
    vo.set_defaults(func=cmd_volume)
    k = sub.add_parser("key", help="Taste senden")
    k.add_argument("key", choices=KEYS)
    k.set_defaults(func=cmd_key)
    w = sub.add_parser("wake", help="Wake-on-LAN")
    w.add_argument("mac")
    w.add_argument("--broadcast", default="255.255.255.255")
    w.set_defaults(func=cmd_wake)

    args = p.parse_args()
    try:
        asyncio.run(args.func(args))
    except TitanError as err:
        print(f"Fehler: {err}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
