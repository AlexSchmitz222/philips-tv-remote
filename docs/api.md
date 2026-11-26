# JointSpace v6 auf Titan OS – Endpunkt-Katalog

Gerät: 65PQS8651/12, API 6.1.0, `https://<ip>:1926/6/`, Digest-Auth.
Status: **ok** = getestet und funktioniert · **404** = gibt es nicht · **GEFÄHRLICH** = hängt die API auf.

## Sicherheitsregeln
- Mindestens 1,5–2 s zwischen Anfragen (in `TitanTV` erzwungen).
- Nach einem Timeout keine weiteren Anfragen schicken (Client-Pause 30 s → 300 s).
- Unbekannte Endpunkte **einzeln** testen: `titan dump --only <pfad>`.
- Gefährliche Anfragen stehen in `client.UNSAFE_REQUESTS` und werden vom Client abgelehnt.

## Lesen (GET)
| Pfad | Status | Bemerkung |
|---|---|---|
| `system` | ok | ohne Auth; `featuring` u. a. `ambilight`, `matter`, `pairing_type: digest_auth_pairing` |
| `powerstate` | 404 | gibt es auf Titan OS nicht |
| `audio/volume` | ok | `{"muted","current","min":0,"max":60}`; folgt der **echten Fernbedienung** (auf 5 gestellt → GET meldet 5, 2026-11-24) |
| `ambilight/power` | ok | `{"power":"On"}` |
| `ambilight/mode` | ok | `{"current":"internal"}` |
| `ambilight/topology` | ok | 1 Ebene, links 4 / oben 9 / rechts 4 / unten 0 = 17 Zonen |
| `ambilight/currentconfiguration` | ok | `styleName`, `menuSetting`, `stringValue` – liefert den aktuellen Stil (über `rest_command` kam früher nichts zurück) |
| `ambilight/supportedstyles` | ok | FOLLOW_AUDIO-Algorithmen (9), FOLLOW_COLOR: MANUAL_HUE / AUTOMATIC_HUE |
| `ambilight/lounge` | **GEFÄHRLICH** | GET → Timeout, danach antwortete die API nicht mehr (2026-11-24) |
| `ambilight/cached`, `/measured`, `/processed` | ok, aber **immer 0** | RGB je Zone (`layer1.left/top/right`), 17 Zonen – auf dieser Firmware in jedem Stil (Rhythm, Standard) nur Nullen (2026-11-24). Im ersten Dump nur Timeout, weil `lounge` die API schon aufgehängt hatte |
| `ambilight/ambihue/power`, `huelamp/power` | 404 | kein Ambilight+Hue |
| `activities/current` | ok, aber nutzlos | immer `{"id":"skype"}`, egal was läuft |
| `activities/tv` | ok | `channel`/`channelList` leer |
| `channeldb/tv` | ok | `{}` |
| `context` | ok | `level1` je nach Ansicht (2026-11-24 ausprobiert): `NetTv` = Homescreen, Disney+, Prime Video · `WatchSatellite` = Satellit · `WatchTv` = Antenne und Streaming-Sender · `WatchExtension` = HDMI 1–3, Titan Channels, Joyn · `NA` = Netflix, YouTube, AirPlay, Bildschirmspiegelung, Medien, Netzwerk. `level2`/`level3`/`data` bisher immer `NA`, dazu `Recording` |
| `system/epgsource`, `input/textentry`, `input/pointer` | ok | `no_epg`; Texteingabe-/Zeigerstatus |
| `system/storage/status`, `menuitems/settings/version`, `channeldb/tv/favoriteLists/all` | 404 | |
| `applications`, `sources` | 403 | auch mit Scope read/write/control gesperrt |
| `menuitems/settings/structure` | ok | enthält **nur** den Ambilight-Zweig (Bild-Knoten 2 ist leer) |

Zweiter Durchlauf (2026-11-24 21:02) mit gesperrtem `lounge`-GET: alle Endpunkte ohne Absturz.
→ `GET ambilight/lounge` ist mit hoher Wahrscheinlichkeit der Auslöser (danach startet der Fernseher von selbst neu).

## Belastungstest Schreiben (2026-11-25)
| Schreibbefehle | Abstand | Ergebnis |
|---|---|---|
| Helligkeit (710), 15× | 1,5 s / 1,0 s | Median 0,015 s, max 0,07 s |
| Stilwechsel (320 → 322/323), 15× | 1,5 s / 1,0 s | Median 0,024 s, max 0,07 s |
| Kategorie (300: 320 ↔ 340) + Lounge-Farbe, 24× | 1,0 s | Median 0,024 s, **ein Ausreißer 1,2 s** |
→ Abstand zwischen Schreibbefehlen 1,5 s (vorher 2 s). Der Absturz bei 0,5 s fiel mit der damals noch laufenden
`notifychange`-Schleife zusammen; welche der beiden Ursachen den Ausschlag gab, ist offen.

## Menüknoten (Ambilight-Zweig)
| Knoten | string_id | Typ | context | aktueller Wert |
|---|---|---|---|---|
| 300 | MAIN_AMBILIGHT_STYLE | PARENT | – | `activenode_id` 320 |
| 320 | MAIN_FOLLOW_VIDEO | LIST 321–325 | – | 322 |
| 330 | MAIN_FOLLOW_AUDIO | LIST 331–333 | ambilight_follow_audio | 331 |
| 340 | MAIN_FOLLOW_COLOUR | LIST 345 | ambilight_lounge_light | 345 |
| 360 | MAIN_FOLLOW_APP | PARENT | ambilight_follow_app | – |
| 400 | MAIN_LOUNGE_LIGHT | PARENT | ambilight_custom_colour | – |
| 500 | MAIN_AMBISLEEP (510–550) | PARENT | ambisleep | nicht steuerbar (`Controllable: false`) |
| 710 | PC_ID_BRIGH_L12 | SLIDER 0..10 | ambilight_brightness | 5 (Schreiben wirkt) |
| 720 | ID_AMB_SAT | SLIDER -2..2 | ambilight_saturation | 0 |
| 730 | DESC_ID_WALL_L151 | WALL_COLOR | – | – |
| 740 | ID_SWTH_L148 | LIST | ambilight_tv_switch_off | Ausschaltverhalten (beide Einträge haben `enum_id` 1) |

| `screenstate` | ok, aber veraltet | GET meldet immer „Off“ (auch nach POST On). `POST {"screenstate":"Off"/"On"}` → HTTP 200, aber **keine Wirkung** (Bild blieb an, beobachtet 2026-11-25) |
| `network/devices` | ok | je Schnittstelle `mac`, `ip`, `type`, **`wake-on-lan`** (Enabled/Disabled) → MAC für WoL ohne ARP |
| `channels`, `channels/current`, `sources/current` | 403 | |
| `recordings/list`, `activities/browser`, `HueLamp/power` | 404 | |

Dritter Durchlauf am 2026-11-24 um 22:14, alle Endpunkte einzeln: kein Absturz.

## `notifychange` (Long-Poll)
Hintergrund (Recherche 2026-11-24): Laut Homey-App (PR lucasvdh/codes.lucasvdh.philips-jointspace#87) beantwortet
der TV eine Long-Poll-Anfrage ohne Änderung **nie**, sondern schließt die Verbindung nach 60–120 s (einmal ~180 s);
ein korrekter Client hält **eine** Anfrage offen und wartet länger als der TV (`haphilipsjs`: 130 s).
`haphilipsjs` nutzt `notifychange` nur, wenn `/system` ein Feld `notifyChange` meldet – dieser TV meldet es **nicht**.
Unsere Client-Timeouts (12–45 s) lagen darunter → vermutlich gestapelte offene Anfragen → 503.

**Sauberer Test nach Stromtrennen (2026-11-24, 23:31–23:39)**: genau eine Anfrage, Client-Timeout 200 s, nie
abgebrochen, HA-Integration deaktiviert, MQTT parallel mitgelesen:

| Schritt | Ergebnis |
|---|---|
| `{}` (Grundstand) | sofort (0,3 s), 10 Keys |
| Leerlauf | **HTTP 200 nach genau 120 s**, Inhalt unverändert (echte Antwort, kein Verbindungsabbruch) |
| Helligkeit 10 → 3 | Antwort **12 s** nach der Änderung, keine geänderten Keys |
| Lautstärke 5 → 6 | keine Meldung (Antwort erst nach 120 s) |
| Helligkeit → 10 | **keine** Meldung (120 s) |
| Lautstärke → 5 | keine Meldung (120 s) |

Ohne gestapelte Anfragen bleibt der Dienst stabil (kein 503). Für Änderungsmeldungen ist er aber **unbrauchbar**:
eine von zwei Ambilight-Änderungen kam an, und das erst nach 12 s; Lautstärke nie. Ein Client muss länger als
120 s warten, sonst stapeln sich die Anfragen. MQTT meldete in derselben Zeit nichts außer `channels/state` beim
Verbinden: Ambilight- und Lautstärkeänderungen kommen dort nicht.
→ **Fazit:** Abfragen (Polling) bleibt der richtige Weg.

`POST notifychange {"notification": <letzter bekannter Stand>}` – der Fernseher antwortet, sobald sich etwas
vom mitgeschickten Stand unterscheidet, sonst bleibt die Anfrage offen (Read-Timeout auf Client-Seite).
- Leere Notification `{}` → sofortige Antwort mit dem Gesamtstand: `context`, `powerstate` (per GET 404!),
  `activities/tv`, `screenstate`, `network/devices`, `channeldb/tv`, `system/epgsource`,
  `system/storage/status`, `input/textentry`, `input/pointer`.
- **Änderung an einem Menüknoten** (Ambilight-Helligkeit 710) → Meldung nach 0,08 s.
- **Lautstärke** (`audio/volume`) → **keine** Meldung, die braucht weiter Polling.
- Eine Teilmenge als Notification (z. B. nur `audio/volume`, `powerstate`) blieb ohne Antwort offen.
- Eine offene Long-Poll-Anfrage parallel zu normalen Anfragen war unproblematisch.
- **Unzuverlässig:** Ab etwa 22:20, nach einem abgebrochenen HA-Live-Test, kam auf `notifychange` gar keine Antwort mehr:
  weder auf `{}` (drei Versuche, je 45 s) noch auf Ambilight-Änderungen während einer offenen Anfrage (drei Versuche),
  noch auf `menuitems/settings/version: 0`. Die normale API blieb dabei gesund.
  Mögliche Ursachen (ungeprüft): der Fernseher hält pro gekoppeltem Gerät nur eine Long-Poll-Anfrage und hängt noch an
  einer verwaisten, oder eine andere Integration (z. B. `philips_js`, nutzt `notifychange`) beeinflusst den Dienst.
- **Nach dem Stromtrennen (23:12):** leerer Stand sofort beantwortet. Von drei Änderungen kam aber nur eine an
  (die HA-Integration hielt parallel eigene Long-Polls offen). Mit deaktivierter Integration (23:15): leerer Stand
  ohne Antwort, keine Meldungen, dann **HTTP 503**. Die normale API blieb gesund.
- **Erklärung (plausibel, nicht bewiesen):** Bricht ein Client eine wartende Anfrage ab, bleibt sie auf dem Fernseher
  offen. Sie sammeln sich an, bis der Dienst nur noch 503 liefert; ein Neustart räumt auf.
- **Konsequenz:** Die Integration verwendet `notifychange` **nicht** (seit 0.2.0). Nur für Experimente, danach
  am besten Strom trennen.

## Andere Dienste auf dem Gerät
| Port | Dienst | Bemerkung |
|---|---|---|
| 1925 / 1926 | JointSpace HTTP / HTTPS | |
| 8008 / 8009 | **Google Cast** | `/setup/eureka_info`: Name `PHILIPS_TV_65PQS8651/12`; HA-Cast-Integration nutzbar (Status nur für Cast-Wiedergaben) |
| 49153 | **UPnP/DLNA MediaRenderer** | AVTransport, RenderingControl, ConnectionManager (`/description.xml`) |
| 8883 | **Titan OS MQTT** | siehe unten |
| 56789 / 56790 | **DIAL** | siehe unten |
| 49152 | unbekannt | offen, nicht untersucht |

## Titan OS MQTT (Port 8883)
Eigener Dienst neben JointSpace, MQTT v5 über TLS (selbst signiert, Verbindung per IP ohne Prüfung).
Protokoll nach github.com/bedirhanyildirim/philips-titan-os-55pml9019-remote, hier nachgeprüft (2026-11-24):
- **Ohne Anmeldung:** Verbindung ok, `info` und `channels/state` abonnieren → „Not authorized“.
- **Pairing** (`scripts/mqtt_probe.py pair`): `pairing/start` `{"type":"mobile"}` → Challenge + PIN am TV
  (der TV spricht von der „Titan OS App“) → `pairing/finish` mit `hex(HMAC-SHA256(PIN, challenge))` →
  Benutzername/Passwort. **Funktioniert** am 65PQS8651/12.
- **Mit Anmeldung:** `info` und `channels/state` abonnierbar (retained), `#` nicht.
- **`info`:** `mqttv_version` v2.12.0, `fw_version` 066.002.126.131, Modell, Markt DE, MAC-Adressen,
  `capabilities.rc.longpress`, `mqttv_topics`: `keyboard`, `rc`, `deeplink_v2`, `pairing/*`, `proxy_v2`,
  `settings`, `screenshot`, `screencast`, `screencast/keepalive`, `automation/set`.
  (Die Quelle beschreibt `deeplink`/`proxy`; hier heißen sie `_v2`.)
- **`channels/state`:** echte **Push-Meldung**, sofort bei jedem Wechsel: `{"state":"launcher"}` auf dem
  Startbildschirm, `{"state":"inactive"}` in einer App oder auf einer Quelle; `channel` bisher immer `null`.
- **`settings`:** `{}` → Code 10 „Invalid message format“; das Feld heißt `method`. `get`, `GET`, `list`, `read`,
  `query`, `status`, `describe`, `info`, `options`, `get_all`, `set`, `update` → Code 14 „Operation not
  implemented“. Die echten Operationsnamen kennt nur die App.
- Noch nicht untersucht: `automation/set`, `rc`, `deeplink_v2`, `screenshot`.

### Aus der App „Titan OS Mobile“ (`tv.titanos.eos.mobile` 1.5.3, statische Analyse 2026-11-25)
Nur Protokoll-Erkenntnisse, kein Code übernommen.
- **`state/power`** (abonnieren, retained): `{"power": "on" | "standby" | "semi-standby" | "off"}`.
  Am 65PQS8651 bestätigt: `{"power":"on"}`.
- **`channels/state`**: `{"state": "launcher" | "inactive", "channel": …}`; `channel` enthält bei Titan-eigenen
  Sendern u. a. `playback_state` = `playing` / `paused` / `buffering` / `stopped`.
- **`channels/command`**: `{"action": "open" | "toggle_favourite", "channelId": …, "requestId": …}`.
- **`settings`**: `{"method": <name>, "params": {…}}`. Die App kennt nur `wowlan.get`, `wowlan.set`
  (`params: {"enable": bool}`) und `tvname.set` (`params`: neuer Name). Ambilight-, Bild- oder Toneinstellungen gibt
  es dort nicht.
- **`rc`**: Tasten als `key_code`; **`info`**, **`pairing/*`**, **`deeplink_v2`**, **`proxy_v2`** wie oben.

### Aus der App „Philips TV Remote“ (`com.tpvision.philipstvapp2` 3.0.93)
Nutzt JointSpace wie wir: Menüknoten werden über `context` gefunden (`ambilight_style`, `ambilight_follow_video`,
`ambilight_lounge_light`, `ambilight_brightness`, `ambilight_saturation` …), dieselben Endpunkte. Die Lounge-Farbe
sendet sie mit dem Schlüssel `colorDelta` (wir: `colordelta`, funktioniert ebenfalls). Kontexte wie
`ambilight_custom_left_color_set` (Farbe je Seite) kennt die App; das Menü dieses Fernsehers bietet sie nicht an.

## DIAL (Port 56789/56790)
Offen. Laut Quelle ohne Pairing: `POST http://<tv>:56789/apps/<Name>` (YouTube, Netflix,
AmazonInstantVideo …, teils mit `Origin`-Header), Gerätebeschreibung `http://<tv>:56790/dd.xml`. Nicht getestet.

## `/system`, verschlüsselte Felder
AES-CBC mit den ersten 16 Bytes des gemeinsamen Schlüssels, die ersten 16 Bytes der Daten sind der IV, PKCS7
(wie `haphilipsjs.cbc_decode`): `model` = TPN266E, `serialnumber` lesbar, `softwareversion` = `-000.000.000.000`
(Platzhalter).

## Schreiben (POST)
| Pfad | Status | Bemerkung |
|---|---|---|
| `pair/request`, `pair/grant` | ok | Signatur = base64(HMAC-SHA1(shared_key, timestamp+pin)), Feld `auth_appId` |
| `menuitems/settings/update` | ok | `"version": 1` ist **nicht** nötig: `{"values":[{"value":{"Nodeid":320,"data":{"selected_item":323}}}]}` (Form wie in `ha-philipsjs`, ohne `string_id`) wirkt ebenso (geprüft 2026-11-26). Die ursprüngliche Annahme „nur mit version 1“ war falsch oder gilt nicht mehr |
| `menuitems/settings/current` | ok | |
| `ambilight/lounge` | ok | feste Farbe (HSB 0–255), wirkt nur bei Stil „Feste Farbe“ |
| `ambilight/currentconfiguration` | wirkt nicht | der Fernseher setzt sofort den Menüwert wieder durch |
| `input/key` | ok | `{"key":"VolumeUp"}` → Lautstärke +1; Antwort leer |
| `audio/volume` | ok | `current` wird übernommen, **`muted` wird ignoriert** |
| `input/key` `Digit0`–`Digit9` | ok | Senderwahl ohne `Confirm`: „5004“, „5005“ mit 1 s Abstand → Fernseher schaltet um (Streaming, 2026-11-24). `activities/tv` bleibt dabei leer, der Sender ist per API nicht lesbar |
| `input/key` Medientasten | teilweise | an eine Set-top-Box (Spotify) per HDMI-CEC kommen nur `Play`/`Pause`/`PlayPause` an; `Stop`, `Next`, `Previous`, `FastForward`, `Rewind` bewirken dort nichts (2026-11-24) |
| `input/key` `Mute` | ok | schaltet um; Zustand danach in `GET audio/volume` (`muted`) |
| Menü 710 `data.value` | ok | Helligkeit 0–10, wirkt **sichtbar** (getestet 2026-11-24). Der Wert ist offenbar **pro Stil** gespeichert: Standard 5, Kino 10, feste Farbe 5 → nach jedem Stilwechsel neu lesen |
| Menü 720 `data.value` | ok (gespeichert) | Sättigung −2..2, wird zurückgelesen; wirkt **sichtbar** (−2 blass, +2 kräftig; getestet 2026-11-24) |
| Menü 740 | – | `menuitems/settings/current` liefert für 740 **keinen** Wert |

## Stile ↔ Namen (aus `GET ambilight/currentconfiguration`, 2026-11-24)
| Menü | string_id | styleName | menuSetting | stringValue |
|---|---|---|---|---|
| 310 | MAIN_AMBILIGHT_STYLE_OFF | – (leere Antwort) | – | `ambilight/power` = Off |
| 321 | MISC_AI | FOLLOW_VIDEO | NATURAL | Natural |
| 322 | …VIDEO_1_2K20 | FOLLOW_VIDEO | STANDARD | Standard |
| 323 | …VIDEO_3_2K20 | FOLLOW_VIDEO | SPORTS | Sports |
| 324 | MAIN_AMBILIGHT_CINEMA | FOLLOW_VIDEO | NATURAL | Natural |
| 325 | MAIN_AMBILIGHT_GAME_2K23 | FOLLOW_VIDEO | GAME | Game |
| 331 | …AUDIO_1_2K20 | FOLLOW_AUDIO | ENERGY_ADAPTIVE_BRIGHTNESS | Lumina |
| 332 | MAIN_FOLLOW_AUDIO_STYLE_3_2K23 | FOLLOW_AUDIO | PARTY | Party |
| 333 | …AUDIO_3_2K20 | FOLLOW_AUDIO | RANDOM_PIXEL_FLASH | Rhythm |
| 345 | MAIN_AMBILIGHT_FIXED_COLOUR | FOLLOW_COLOR | – | – |

AI (321) und Kino (324) melden beide NATURAL. Über `currentconfiguration` lassen sie sich also nicht unterscheiden; welcher aktiv ist, steht nur in Menüknoten 320 (`selected_item`).

## Ein/Standby
- Im Standby antwortet die API **gar nicht** (auch `/system` nicht). „An“ heißt also „API erreichbar“.
- **Ausschalten:** `POST input/key {"key":"Standby"}` funktioniert. Die Antwort ist leer, nach ≤ 15 s ist die API weg (getestet 2026-11-24).
- Im Standby antwortet der Fernseher auch nicht auf Ping. Der Router meldet „No route to host“, kennt die Adresse also gar nicht mehr.
- Einschalten über die API ist damit nicht möglich. Wake-on-LAN muss aus dem **selben** Netz (192.168.178.0/24) kommen, ein gerouteter Rechner erreicht den Fernseher nicht. **Getestet: WoL funktioniert** (LAN, Magic Packet an Broadcast, Ports 7 und 9).

## Offene Fragen
- Wirkt 710 auch auf Audio-Stile und feste Farbe? Wirkt 720 sichtbar?
- Matter (`featuring.matter`) als zweiter Weg.
- Meldet `notifychange` auch Ambilight-Änderungen, die per Fernbedienung gemacht werden?
