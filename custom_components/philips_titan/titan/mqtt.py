"""Titan OS MQTT (port 8883): pairing and a push listener.

Protocol (verified on the 65PQS8651/12, fw 066.002.126.131; see docs/api.md):
* MQTT v5 over TLS, self-signed CA -> no verification, connect by IP.
* request/response: subscribe "<topic>/<id>", publish "<topic>" with
  ResponseTopic "<topic>/<id>" and CorrelationData.
* pairing/start {"type": "mobile"} -> {"data": {"challenge": ...}}, TV shows a PIN;
  pairing/finish {"username": <uuid>, "challenge_result": hex(HMAC-SHA256(PIN, challenge))}
  -> {"data": {"username": ..., "password": ...}}.
* Retained push topics: "state/power" {"power": "on"|"standby"|"semi-standby"|"off"},
  "channels/state" {"state": "launcher"|"inactive", "channel": ...}.

All methods here are blocking (paho runs its own network thread); call them
from an executor in asyncio code.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import hmac
import json
import queue
import ssl
import threading
from typing import Any
import uuid

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

PORT = 8883
PUSH_TOPICS = ("state/power", "channels/state")


class TitanMqttError(Exception):
    """Pairing or connection failed."""


def _tls_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _client(username: str | None = None, password: str | None = None) -> mqtt.Client:
    client = mqtt.Client(
        CallbackAPIVersion.VERSION2,
        client_id=f"eos-{username or uuid.uuid4().hex[:12]}",
        protocol=mqtt.MQTTv5,
    )
    client.tls_set_context(_tls_context())
    if username:
        client.username_pw_set(username, password)
    return client


class MqttPairing:
    """Two-step PIN pairing on one connection: start() -> PIN on TV -> finish(pin)."""

    def __init__(self, host: str, timeout: float = 10) -> None:
        self.host = host
        self.timeout = timeout
        self._client = _client()
        self._inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._challenge: str | None = None

    def _request(self, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        corr = uuid.uuid4().hex
        resp_topic = f"{topic}/{corr}"
        self._client.subscribe(resp_topic, qos=0)
        props = Properties(PacketTypes.PUBLISH)
        props.ResponseTopic = resp_topic
        props.CorrelationData = corr.encode()
        self._client.publish(topic, json.dumps(payload), qos=0, properties=props)
        while True:
            try:
                got_topic, body = self._inbox.get(timeout=self.timeout)
            except queue.Empty as err:
                raise TitanMqttError(f"no answer on {topic}") from err
            if got_topic == resp_topic:
                answer = json.loads(body)
                if "error" in answer:
                    raise TitanMqttError(f"{topic}: {answer['error']}")
                return answer.get("data") or {}

    def start(self) -> None:
        """Connect anonymously and ask the TV to show a PIN."""
        connected = threading.Event()
        self._client.on_connect = lambda c, u, f, rc, p=None: connected.set()
        self._client.on_message = lambda c, u, m: self._inbox.put((m.topic, m.payload))
        try:
            self._client.connect(self.host, PORT, keepalive=30)
        except OSError as err:
            raise TitanMqttError(f"cannot connect to {self.host}:{PORT}: {err}") from err
        self._client.loop_start()
        if not connected.wait(self.timeout):
            self.close()
            raise TitanMqttError("MQTT connect timed out")
        self._challenge = self._request("pairing/start", {"type": "mobile"})["challenge"]

    def finish(self, pin: str) -> tuple[str, str]:
        """Send the PIN answer; returns (username, password)."""
        if not self._challenge:
            raise TitanMqttError("pairing not started")
        result = hmac.new(pin.strip().encode(), self._challenge.encode(), hashlib.sha256).hexdigest()
        data = self._request("pairing/finish", {"username": str(uuid.uuid4()), "challenge_result": result})
        return data["username"], data["password"]

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


class MqttListener:
    """Keeps a connection and reports push messages; reconnects on its own
    (also while the TV is in standby and unreachable)."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        on_message: Callable[[str, dict[str, Any]], None],
        on_connection: Callable[[bool], None] | None = None,
    ) -> None:
        self.host = host
        self._on_message = on_message
        self._on_connection = on_connection or (lambda connected: None)
        self._client = _client(username, password)
        self._client.reconnect_delay_set(min_delay=5, max_delay=60)
        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = lambda c, u, f, rc, p=None: self._on_connection(False)
        self._client.on_message = self._handle_message

    def _handle_connect(self, client, userdata, flags, rc, props=None) -> None:
        if rc.is_failure:
            self._on_connection(False)
            return
        client.subscribe([(t, 0) for t in PUSH_TOPICS])
        self._on_connection(True)

    def _handle_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            return
        if isinstance(payload, dict):
            self._on_message(msg.topic, payload)

    def start(self) -> None:
        # connect_async + loop_start: retries until the TV is reachable
        self._client.connect_async(self.host, PORT, keepalive=30)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()
