"""Titan OS MQTT (port 8883): PIN pairing and a read-only look at the topics.

Protocol as documented by github.com/bedirhanyildirim/philips-titan-os-55pml9019-remote
(55PML9019, untested on other models):
  * MQTT v5 over TLS, self-signed CA -> no verification, connect by IP
  * request/response: subscribe to "<topic>/<uuid>", publish to "<topic>" with
    ResponseTopic "<topic>/<uuid>" and the same CorrelationData
  * pairing/start {"type": "mobile"}  -> {"data": {"challenge": ...}}, TV shows a PIN
  * pairing/finish {"username": <uuid>, "challenge_result": hex(HMAC-SHA256(PIN, challenge))}
    -> {"data": {"username": ..., "password": ...}}

    .venv/bin/python scripts/mqtt_probe.py pair      # interactive, writes mqtt_credentials.json
    .venv/bin/python scripts/mqtt_probe.py listen    # subscribe read-only, print messages

`listen` publishes nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import queue
import ssl
import sys
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

HOST = "192.168.178.78"
PORT = 8883
CRED_FILE = Path(__file__).resolve().parents[1] / "mqtt_credentials.json"
LISTEN_TOPICS = ["info", "channels/state", "state/power"]


def make_client(username: str | None = None, password: str | None = None) -> mqtt.Client:
    cid = f"eos-{username or uuid.uuid4().hex[:12]}"
    c = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=cid, protocol=mqtt.MQTTv5)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    c.tls_set_context(ctx)
    if username:
        c.username_pw_set(username, password)
    return c


def request(c: mqtt.Client, inbox: "queue.Queue", topic: str, payload: dict, timeout: float = 10) -> dict:
    corr = uuid.uuid4().hex
    resp_topic = f"{topic}/{corr}"
    c.subscribe(resp_topic, qos=0)
    time.sleep(0.5)
    props = Properties(PacketTypes.PUBLISH)
    props.ResponseTopic = resp_topic
    props.CorrelationData = corr.encode()
    c.publish(topic, json.dumps(payload), qos=0, properties=props)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            t, body = inbox.get(timeout=0.5)
        except queue.Empty:
            continue
        if t == resp_topic:
            return json.loads(body)
    raise TimeoutError(f"no answer on {resp_topic}")


def connect(c: mqtt.Client) -> "queue.Queue":
    inbox: queue.Queue = queue.Queue()
    ready = queue.Queue()
    c.on_connect = lambda cl, u, f, rc, p=None: ready.put(rc)
    c.on_message = lambda cl, u, m: inbox.put((m.topic, m.payload.decode(errors="replace")))
    c.connect(HOST, PORT, keepalive=30)
    c.loop_start()
    rc = ready.get(timeout=10)
    if rc.is_failure:
        raise SystemExit(f"MQTT connect failed: {rc}")
    return inbox


def pair() -> None:
    c = make_client()
    inbox = connect(c)
    start = request(c, inbox, "pairing/start", {"type": "mobile"})
    print("pairing/start ->", {k: ("…" if k == "data" else v) for k, v in start.items()})
    if "error" in start:
        raise SystemExit(f"Fehler: {start['error']}")
    challenge = start["data"]["challenge"]
    pin = input("PIN, die der Fernseher anzeigt: ").strip()
    result = hmac.new(pin.encode(), challenge.encode(), hashlib.sha256).hexdigest()
    finish = request(c, inbox, "pairing/finish", {"username": str(uuid.uuid4()), "challenge_result": result})
    c.loop_stop()
    c.disconnect()
    if "error" in finish:
        raise SystemExit(f"pairing/finish Fehler: {finish['error']}")
    data = finish["data"]
    CRED_FILE.write_text(json.dumps({"host": HOST, "username": data["username"], "password": data["password"]}, indent=2))
    CRED_FILE.chmod(0o600)
    print(f"Gekoppelt. Zugangsdaten in {CRED_FILE}")


def listen(seconds: float = 20) -> None:
    creds = json.loads(CRED_FILE.read_text())
    c = make_client(creds["username"], creds["password"])
    c.on_subscribe = lambda cl, u, mid, rcs, p=None: print("subscribe:", [str(r) for r in rcs], flush=True)
    inbox = connect(c)
    c.subscribe([(t, 0) for t in LISTEN_TOPICS])
    end = time.time() + seconds
    while time.time() < end:
        try:
            topic, body = inbox.get(timeout=0.5)
        except queue.Empty:
            continue
        print(time.strftime("%X"), f"[{topic}]", body[:800], flush=True)
    c.loop_stop()
    c.disconnect()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pair":
        pair()
    elif cmd == "listen":
        listen(float(sys.argv[2]) if len(sys.argv) > 2 else 20)
    else:
        print(__doc__)
