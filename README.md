# Philips TV (Titan OS) – Home-Assistant-Integration

Lokale Steuerung von Philips-Fernsehern mit **Titan OS**: Ambilight (Stile, feste Farbe, Helligkeit,
Sättigung), Ein/Aus, Lautstärke, Fernbedienungstasten und der aktuelle Eingang. Alles läuft im lokalen Netz,
ohne Cloud.

Die offizielle Integration `philips_js` ist für Android-Fernseher gebaut. Bei Titan OS stürzen die Fernseher
dort beim Ambilight ab. Diese Integration verwendet nur Anfragen, die auf dem Gerät getestet sind
(siehe [docs/api.md](docs/api.md)). Sie hält Mindestabstände zwischen Anfragen ein und sperrt Anfragen, von
denen bekannt ist, dass sie den Fernseher aufhängen.

## Unterstützte Geräte
- **Getestet:** Philips **65PQS8651/12**, Firmware 066.002.126.131, JointSpace API 6.1.
- **Sollte funktionieren:** andere Philips-Fernseher mit Titan OS und JointSpace 6 mit PIN-Kopplung.
  Die Ambilight-Menüknoten werden beim Start aus dem Fernseher gelesen, die Bezeichnungen mit und ohne Vorsilbe
  `MLM_PHM_KEY_` werden erkannt. Rückmeldungen zu anderen Modellen sind willkommen.
- **Nicht unterstützt:** Philips Android/Google TV (dafür gibt es `philips_js`) und ältere Saphi-Modelle.

## Funktionen
| Entität | Funktion |
|---|---|
| `light.…_ambilight` | Ein/Aus, Effekte (Video: AI/Standard/Sports/Cinema/Game, Audio: Lumina/Party/Rhythm, Fixed colour), Farbe (feste Farbe), Helligkeit (gilt je Stil) |
| `media_player.…` | Ein (Wake-on-LAN), Standby, Lautstärke setzen/±, Stummschalten, Play/Pause, Senderwahl, Quelle (`source`) |
| `number.…_volume` | Lautstärke in den Stufen des Fernsehers (0–60); standardmäßig deaktiviert |
| `number.…_ambilight_saturation` | Ambilight-Sättigung −2 … +2; Geräteeinstellung, standardmäßig deaktiviert |
| `sensor.…_input` | aktueller Eingang: Startbildschirm/Web-Apps, Satellit, TV, HDMI/Extension, andere App |
| `remote.…_remote` | Fernbedienungstasten senden, Ein/Aus |
| Diagnose | Gerät → „Diagnose herunterladen“ (ohne Zugangsdaten, MAC, IP, Seriennummer) |

### Aktionen
Die Integration bringt keine eigenen Aktionen mit, sie nutzt die Standardaktionen von HA:
- **Taste senden:** `remote.send_command` mit z. B. `command: ["Home", "CursorDown", "Confirm"]`,
  optional `num_repeats` und `delay_secs`. Erlaubt sind nur bekannte Tasten (z. B. `Standby`, `VolumeUp`,
  `Mute`, `CursorUp/Down/Left/Right`, `Confirm`, `Back`, `Home`, `Source`, `WatchTV`, `ChannelStepUp/Down`,
  `Digit0`–`Digit9`, `Play`, `Pause`, `PlayPause`, `Stop`, `Next`, `Previous`, `FastForward`, `Rewind`,
  Farbtasten). Unbekannte Tasten werden abgelehnt.
- **Sender wählen:** `media_player.play_media` mit `media_content_type: channel`, `media_content_id: "12"`.
- **Ambilight:** `light.turn_on` mit `effect`, `hs_color` und/oder `brightness`.

## Installation
**Über HACS:**
1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/AlexSchmitz222/philips-tv-remote`,
   Typ **Integration**.
2. *Philips TV (Titan OS)* suchen → Herunterladen → Home Assistant neu starten.

**Von Hand:** Den Ordner `custom_components/philips_titan` nach `/config/custom_components/` kopieren, zum
Beispiel mit dem Samba- oder SSH-Add-on, und Home Assistant neu starten.

## Einrichtung
Der Fernseher wird im Netz meist **automatisch erkannt** (Zeroconf). Sonst: Einstellungen → Geräte & Dienste →
Integration hinzufügen → **Philips TV (Titan OS)**. Der Fernseher muss dabei **an** sein.

| Feld | Bedeutung |
|---|---|
| Host | IP-Adresse oder Hostname des Fernsehers |
| MAC-Adresse (optional) | Für das Einschalten per Wake-on-LAN. Wird automatisch ermittelt: aus dem ARP-Cache, sonst vom Fernseher (`network/devices`) |
| PIN | Zeigt der Fernseher nach dem ersten Schritt an |

Hat sich die IP-Adresse geändert: Integration → ⋮ → **Neu konfigurieren**. Verwirft der Fernseher die
Kopplung, fordert HA von selbst zur erneuten Kopplung auf.

**Wichtig:** Andere Integrationen, die denselben Fernseher abfragen (`philips_js`, `ha-philips-titanos`),
deaktivieren. Parallele Abfragen erhöhen die Last.

### Optionen
Integration → **Konfigurieren**:

| Option | Standard | Bedeutung |
|---|---|---|
| Abfrageintervall | 5 s | Wie oft der Zustand gelesen wird (2–300 s), drei Leseanfragen pro Abfrage |
| Ein/Aus und Eingangswechsel sofort per MQTT | aus | Zweite Kopplung mit dem MQTT-Dienst des Fernsehers (Port 8883). Der Fernseher zeigt eine PIN und nennt das „Titan OS App“. Danach erscheinen Standby und Eingangswechsel sofort in HA. Häkchen entfernen verwirft die Kopplung |

## Wie die Daten aktualisiert werden
- **Abfrage:** alle 5 s (einstellbar) Ambilight-Zustand (ein Menü-Lesebefehl), Lautstärke und Eingang.
- **Nach Befehlen** zeigt HA das erwartete Ergebnis sofort an, die nächste Abfrage bestätigt es.
- **Schutz des Fernsehers:** Zwischen Leseanfragen liegen mindestens 0,5 s, zwischen Schreibbefehlen 1,5 s,
  zwischen Tasten 1 s. Schnell aufeinanderfolgende Befehle (Klicken, Ziehen am Farbrad oder Regler) werden
  zusammengefasst. Hängt die API, pausiert die Integration mit wachsender Wartezeit (30 s bis 5 min).
- **Optional per MQTT:** Standby und Eingangswechsel kommen per Push.
- **Standby:** Dann ist der Fernseher im Netz nicht erreichbar, HA zeigt ihn als „aus“. Ambilight, Sensor und
  Regler sind dann nicht verfügbar.

## Beispiele und Anwendungsfälle
**Blueprints** zum Importieren (Einstellungen → Automationen → Blueprints → Blueprint importieren):

| Blueprint | Wirkung |
|---|---|
| [Ambilight-Effekt je Eingang](blueprints/automation/philips_titan/ambilight_per_input.yaml) | z. B. HDMI → „Video: Game“, Startbildschirm → „Fixed colour“ |
| [Licht an, wenn der Fernseher ausgeht](blueprints/automation/philips_titan/lights_when_tv_off.yaml) | Lampen/Szene einschalten, optional nur nach Sonnenuntergang |

Import-URLs: `https://github.com/AlexSchmitz222/philips-tv-remote/blob/main/blueprints/automation/philips_titan/ambilight_per_input.yaml`
und `…/lights_when_tv_off.yaml` (funktioniert, wenn das Repository öffentlich ist).

**Automation: Ambilight bei Musik auf Audio umschalten**
```yaml
triggers:
  - trigger: state
    entity_id: media_player.spotify   # anpassen
    to: playing
actions:
  - action: light.turn_on
    target: { entity_id: light.65pqs8651_12_ambilight }
    data: { effect: "Audio: Rhythm" }
```

**Skript: Fernseher an und auf Sender 5004**
```yaml
sequence:
  - action: media_player.turn_on
    target: { entity_id: media_player.65pqs8651_12 }
  - wait_template: "{{ is_state('media_player.65pqs8651_12', 'on') }}"
    timeout: "00:01:00"
  - action: media_player.play_media
    target: { entity_id: media_player.65pqs8651_12 }
    data: { media_content_type: channel, media_content_id: "5004" }
```

## Bekannte Einschränkungen
- **Einschalten:** Im Standby ist der Fernseher nicht erreichbar. Einschalten geht nur per Wake-on-LAN aus
  demselben Netz, und nur wenn die MAC-Adresse bekannt ist. Fehlt sie, meldet HA einen Reparaturhinweis.
- **Wiedergabe:** Der Wiedergabestatus wird nicht gemeldet, der Media Player zeigt nur „an“/„aus“. An eine
  Set-top-Box per HDMI-CEC kommen nur Play/Pause an, Stop/Weiter/Zurück/Spulen nicht.
- **Eingang:** Die API unterscheidet HDMI 1–4 nicht. Netflix, YouTube, AirPlay und Medien melden alle „andere App“.
- **Apps und Quellen:** Liste und Umschalten sind von Titan OS gesperrt (403).
- **Ambilight-Farben:** Die Farben der LEDs sind nicht auslesbar (`ambilight/processed` liefert nur Nullen).
  Die feste Farbe wird deshalb gespeichert und nach dem Standby erneut gesendet.
- **Bildschirm aus** (`screenstate`): Der Befehl wird angenommen, aber ignoriert.
- **Stile:** AI und Cinema melden intern beide „Natural“. Unterschieden werden sie über den Menüknoten.
- **Gesperrt:** `GET ambilight/lounge` hängt die API auf und wird von der Bibliothek abgelehnt.

## Fehlerbehebung
| Problem | Lösung |
|---|---|
| Einrichtung: „Keine Verbindung“ | Fernseher einschalten (im Standby ist er nicht erreichbar), IP prüfen |
| „Falsche PIN“ | Der Fernseher zeigt eine neue PIN an, diese eingeben |
| „Kein Philips-Fernseher mit Titan OS“ | Android-/Google-TV-Modelle: `philips_js` verwenden |
| Fernseher reagiert gar nicht mehr | API hängt: Fernseher kurz vom Strom trennen. Die Integration pausiert in der Zwischenzeit von selbst |
| Fernseher lässt sich nicht einschalten | MAC-Adresse fehlt (Reparaturhinweis) oder Wake-on-LAN am Fernseher aus. HA muss im selben Netz sein |
| Werte hinken hinterher | Abfrageintervall in den Optionen verkleinern, oder den MQTT-Push aktivieren |
| Fehlerbericht | Debug-Logging aktivieren (Integration → ⋮), Diagnose herunterladen und beides anhängen |

## Entfernen
1. Einstellungen → Geräte & Dienste → *Philips TV (Titan OS)* → ⋮ → **Löschen**.
2. Über HACS installiert: HACS → *Philips TV (Titan OS)* → ⋮ → **Entfernen**, dann HA neu starten.
   Von Hand installiert: den Ordner `custom_components/philips_titan` löschen.
3. Die Zugangsdaten werden mit dem Eintrag gelöscht. Bietet der Fernseher in seinen Einstellungen eine Liste
   gekoppelter Geräte oder Apps an, lässt sich die Kopplung dort zusätzlich entfernen (nicht geprüft, ob Titan OS
   das anbietet).

## Releases
Versionen stehen in [CHANGELOG.md](CHANGELOG.md). Neue Version:
1. `version` in `custom_components/philips_titan/manifest.json` (und `pyproject.toml`) erhöhen,
   Abschnitt in `CHANGELOG.md` ergänzen, committen.
2. `git tag vX.Y.Z && git push && git push --tags`. Der Workflow `release.yml` prüft, dass Tag und Manifest
   übereinstimmen, und legt das GitHub-Release an.

## Entwicklung
```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest            # Bibliothek + CLI „titan“
python3 -m venv .venv-ha && .venv-ha/bin/pip install -e . pytest-homeassistant-custom-component pytest-cov mypy
./scripts/bundle_lib.sh                                                 # Bibliothek in die Integration kopieren
.venv-ha/bin/python -m pytest tests tests_ha --cov=custom_components/philips_titan --cov=src/philips_titan
.venv-ha/bin/mypy custom_components/philips_titan src/philips_titan     # strict
TITAN_LIVE=1 .venv-ha/bin/python -m pytest -s tests_ha/test_live.py      # gegen den echten Fernseher
```
Die Bibliothek liegt in `src/philips_titan`. `custom_components/philips_titan/titan` ist eine Kopie davon,
die CI prüft, dass beide übereinstimmen. Der Stand der Home-Assistant-Quality-Scale steht in
[quality_scale.yaml](custom_components/philips_titan/quality_scale.yaml).

## Lizenz
MIT, siehe [LICENSE](LICENSE). Nicht mit Philips/TP Vision oder Titan OS verbunden. „Philips“, „Ambilight“ und
„Titan OS“ sind Marken ihrer Inhaber.
