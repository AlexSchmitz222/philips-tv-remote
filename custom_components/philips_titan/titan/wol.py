"""Wake-on-LAN. Must be sent from the TV's own L2 network (no routing)."""

from __future__ import annotations

import socket


def magic_packet(mac: str) -> bytes:
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(raw) != 6:
        raise ValueError(f"invalid MAC: {mac!r}")
    return b"\xff" * 6 + raw * 16


def wake(mac: str, broadcast: str = "255.255.255.255", ports: tuple[int, ...] = (7, 9)) -> None:
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in ports:
            s.sendto(packet, (broadcast, port))
