"""Titan OS MQTT pairing and listener with a fake paho client (no network)."""

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from philips_titan import mqtt as tm


class RC:
    def __init__(self, failure=False):
        self.is_failure = failure


class FakeClient:
    """Minimal paho.Client stand-in; answers pairing requests like the TV."""

    instances: list["FakeClient"] = []
    connect_error: Exception | None = None
    connect_rc_failure = False
    answers: dict[str, dict] = {}

    def __init__(self, *a, **kw):
        self.subscribed, self.published = [], []
        self.on_connect = self.on_message = self.on_disconnect = None
        self.creds = None
        FakeClient.instances.append(self)

    def tls_set_context(self, ctx): self.ctx = ctx
    def username_pw_set(self, u, p): self.creds = (u, p)
    def reconnect_delay_set(self, **kw): self.delays = kw

    def connect(self, host, port, keepalive=30):
        if FakeClient.connect_error:
            raise FakeClient.connect_error
        self.on_connect(self, None, {}, RC(FakeClient.connect_rc_failure))

    def connect_async(self, host, port, keepalive=30): self.target = (host, port)
    def loop_start(self): self.looping = True
    def loop_stop(self): self.looping = False
    def disconnect(self): self.disconnected = True

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos=0, properties=None):
        self.published.append((topic, json.loads(payload)))
        if topic in FakeClient.answers:
            msg = SimpleNamespace(topic=properties.ResponseTopic, payload=json.dumps(FakeClient.answers[topic]).encode())
            self.on_message(self, None, msg)


@pytest.fixture(autouse=True)
def fake_paho(monkeypatch):
    FakeClient.instances = []
    FakeClient.connect_error = None
    FakeClient.connect_rc_failure = False
    FakeClient.answers = {
        "pairing/start": {"data": {"challenge": "abc"}},
        "pairing/finish": {"data": {"username": "U", "password": "P"}},
    }
    monkeypatch.setattr(tm.mqtt, "Client", FakeClient)


def test_pairing_success():
    p = tm.MqttPairing("tv", timeout=0.2)
    p.start()
    assert p.finish(" 1234 ") == ("U", "P")
    sent = dict(FakeClient.instances[0].published)
    assert sent["pairing/start"] == {"type": "mobile"}
    expected = hmac.new(b"1234", b"abc", hashlib.sha256).hexdigest()
    assert sent["pairing/finish"]["challenge_result"] == expected
    p.close()


def test_pairing_error_answer():
    FakeClient.answers["pairing/finish"] = {"error": {"code": 3, "message": "wrong"}}
    p = tm.MqttPairing("tv", timeout=0.2)
    p.start()
    with pytest.raises(tm.TitanMqttError, match="pairing/finish"):
        p.finish("0000")


def test_pairing_no_answer_times_out():
    del FakeClient.answers["pairing/start"]
    with pytest.raises(tm.TitanMqttError, match="no answer"):
        tm.MqttPairing("tv", timeout=0.1).start()


def test_pairing_finish_before_start():
    with pytest.raises(tm.TitanMqttError, match="not started"):
        tm.MqttPairing("tv").finish("1")


def test_pairing_unreachable():
    FakeClient.connect_error = OSError("no route")
    with pytest.raises(tm.TitanMqttError, match="cannot connect"):
        tm.MqttPairing("tv").start()


def test_pairing_connect_timeout(monkeypatch):
    monkeypatch.setattr(FakeClient, "connect", lambda self, *a, **k: None)  # never calls on_connect
    with pytest.raises(tm.TitanMqttError, match="timed out"):
        tm.MqttPairing("tv", timeout=0.05).start()


def test_listener_subscribes_and_reports():
    got, conn = [], []
    lst = tm.MqttListener("tv", "U", "P", lambda t, p: got.append((t, p)), conn.append)
    c = FakeClient.instances[0]
    assert c.creds == ("U", "P") and c.delays == {"min_delay": 5, "max_delay": 60}
    lst.start()
    assert c.target == ("tv", 8883) and c.looping
    c.on_connect(c, None, {}, RC())
    assert c.subscribed == [[("state/power", 0), ("channels/state", 0)]] and conn == [True]
    c.on_message(c, None, SimpleNamespace(topic="state/power", payload=b'{"power": "standby"}'))
    c.on_message(c, None, SimpleNamespace(topic="x", payload=b"not json"))
    c.on_message(c, None, SimpleNamespace(topic="x", payload=b"[1, 2]"))
    assert got == [("state/power", {"power": "standby"})]
    c.on_connect(c, None, {}, RC(failure=True))
    c.on_disconnect(c, None, {}, RC())
    assert conn == [True, False, False]
    lst.stop()
    assert c.disconnected and not c.looping


def test_listener_default_connection_callback():
    lst = tm.MqttListener("tv", "U", "P", lambda t, p: None)
    c = FakeClient.instances[0]
    c.on_disconnect(c, None, {}, RC())  # must not raise
