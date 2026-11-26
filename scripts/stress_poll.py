"""Find out how fast the TV can be polled.

Sends the same requests the HA integration uses for polling (menu state and
volume, alternating) with decreasing spacing. Stops at the first error or
when latency rises clearly above the baseline – that is the warning sign
before the API hangs.

    .venv/bin/python scripts/stress_poll.py [--seconds 90]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from philips_titan.client import TitanError, TitanTV  # noqa: E402
from philips_titan.layout import MenuLayout  # noqa: E402

STATE_NODES = MenuLayout.default().state_nodes

LEVELS = [3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--credentials", default="credentials.json")
    args = ap.parse_args()
    c = json.loads(Path(args.credentials).read_text())

    http_status: list[int] = []

    async def hook(resp: httpx.Response) -> None:
        http_status.append(resp.status_code)

    from philips_titan.client import _ssl_context

    client = httpx.AsyncClient(
        verify=_ssl_context(), timeout=httpx.Timeout(10, connect=4), event_hooks={"response": [hook]}
    )
    tv = TitanTV(c["host"], c["username"], c["password"], min_interval=0, client=client)

    requests = [lambda: tv.menu_current(STATE_NODES), lambda: tv.get("audio/volume")]
    baseline: float | None = None
    results = []
    n = 0
    try:
        for spacing in LEVELS:
            lat: list[float] = []
            http_before = len(http_status)
            end = time.monotonic() + args.seconds
            while time.monotonic() < end:
                t0 = time.monotonic()
                try:
                    await requests[n % 2]()
                except TitanError as err:
                    print(f"\nABBRUCH bei Abstand {spacing}s nach {len(lat)} Anfragen: {err}", flush=True)
                    results.append({"spacing": spacing, "aborted": str(err), "ok": len(lat)})
                    return report(results, 1)
                dt = time.monotonic() - t0
                lat.append(dt)
                n += 1
                if baseline and dt > max(2.0, 5 * baseline):
                    print(f"\nABBRUCH bei Abstand {spacing}s: Antwortzeit {dt:.2f}s "
                          f"(Basis {baseline:.2f}s) – Warnzeichen", flush=True)
                    results.append({"spacing": spacing, "aborted": f"latency {dt:.2f}s", "ok": len(lat)})
                    return report(results, 1)
                await asyncio.sleep(max(0.0, spacing - dt))
            med = statistics.median(lat)
            if baseline is None:
                baseline = med
            http_n = len(http_status) - http_before
            results.append({
                "spacing": spacing, "requests": len(lat), "median": round(med, 3),
                "p95": round(sorted(lat)[int(len(lat) * 0.95) - 1], 3), "max": round(max(lat), 3),
                "http_per_request": round(http_n / len(lat), 2),
            })
            print(f"{time.strftime('%H:%M:%S')} Abstand {spacing:>4}s: {len(lat):3} Anfragen, "
                  f"Median {med:.3f}s, max {max(lat):.3f}s, HTTP/Anfrage {http_n / len(lat):.2f}", flush=True)
        return report(results, 0)
    finally:
        await tv.close()


def report(results, code: int) -> int:
    print("\nERGEBNIS " + json.dumps(results), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
