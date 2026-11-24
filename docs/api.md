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
| `ambilight/cached`, `/measured`, `/processed` | ok | RGB je Zone (`layer1.left/top/right`), 17 Zonen. Im ersten Dump nur Timeout, weil `lounge` die API schon aufgehängt hatte |
| `ambilight/ambihue/power`, `huelamp/power` | 404 | kein Ambilight+Hue |
| `activities/current` | ok, aber nutzlos | immer `{"id":"skype"}`, egal was läuft |
| `activities/tv` | ok | `channel`/`channelList` leer |
| `channeldb/tv` | ok | `{}` |
| `context` | ok | `level1` je nach Ansicht (2026-11-24 ausprobiert): `NetTv` = Homescreen, Disney+, Prime Video · `WatchSatellite` = Satellit · `WatchTv` = Antenne und Streaming-Sender · `WatchExtension` = HDMI 1–3, Titan Channels, Joyn · `NA` = Netflix, YouTube, AirPlay, Bildschirmspiegelung, Medien, Netzwerk. `level2`/`level3`/`data` bisher immer `NA`, dazu `Recording` |
| `applications`, `sources` | 403 | auch mit Scope read/write/control gesperrt |
| `menuitems/settings/structure` | ok | enthält **nur** den Ambilight-Zweig (Bild-Knoten 2 ist leer) |

Zweiter Durchlauf (2026-11-24 21:02) mit gesperrtem `lounge`-GET: alle Endpunkte ohne Absturz.
→ `GET ambilight/lounge` ist mit hoher Wahrscheinlichkeit der Auslöser (danach startet der Fernseher von selbst neu).

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

| `screenstate` | ok, aber veraltet | GET meldete „Off“, während `notifychange` „On“ lieferte |
| `network/devices` | ok | je Schnittstelle `mac`, `ip`, `type`, **`wake-on-lan`** (Enabled/Disabled) → MAC für WoL ohne ARP |
| `channels`, `channels/current`, `sources/current` | 403 | |
| `recordings/list`, `activities/browser`, `HueLamp/power` | 404 | |

Dritter Durchlauf am 2026-11-24 um 22:14, alle Endpunkte einzeln: kein Absturz.

## `notifychange` (Long-Poll)
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
  → Die Integration nutzt `notifychange` nur als Beschleuniger; der Zustand kommt immer aus der Abfrage.

## Andere Dienste auf dem Gerät
| Port | Dienst | Bemerkung |
|---|---|---|
| 1925 / 1926 | JointSpace HTTP / HTTPS | |
| 8008 / 8009 | **Google Cast** | `/setup/eureka_info`: Name `PHILIPS_TV_65PQS8651/12`; HA-Cast-Integration nutzbar (Status nur für Cast-Wiedergaben) |
| 49153 | **UPnP/DLNA MediaRenderer** | AVTransport, RenderingControl, ConnectionManager (`/description.xml`) |
| 49152, 56789 | unbekannt | offen, nicht untersucht |

## `/system`, verschlüsselte Felder
AES-CBC mit den ersten 16 Bytes des gemeinsamen Schlüssels, die ersten 16 Bytes der Daten sind der IV, PKCS7
(wie `haphilipsjs.cbc_decode`): `model` = TPN266E, `serialnumber` lesbar, `softwareversion` = `-000.000.000.000`
(Platzhalter).

## Schreiben (POST)
| Pfad | Status | Bemerkung |
|---|---|---|
| `pair/request`, `pair/grant` | ok | Signatur = base64(HMAC-SHA1(shared_key, timestamp+pin)), Feld `auth_appId` |
| `menuitems/settings/update` | ok | braucht `"version": 1` |
| `menuitems/settings/current` | ok | |
| `ambilight/lounge` | ok | feste Farbe (HSB 0–255), wirkt nur bei Stil „Feste Farbe“ |
| `ambilight/currentconfiguration` | wirkt nicht | der Fernseher setzt sofort den Menüwert wieder durch |
| `input/key` | ok | `{"key":"VolumeUp"}` → Lautstärke +1; Antwort leer |
| `audio/volume` | ok | `current` wird übernommen, **`muted` wird ignoriert** |
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
