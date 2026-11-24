# Philips TV (Titan OS) – Home-Assistant-Integration

Lokale Steuerung von Philips-Fernsehern mit **Titan OS** (JointSpace API v6, z. B. 65PQS8651/12).
Die offizielle Integration `philips_js` ist für Android TV gebaut und bringt diese Geräte beim
Ambilight zum Absturz. Diese Integration verwendet nur Anfragen, die auf dem Gerät getestet
sind (siehe [docs/api.md](docs/api.md)), und hält immer einen Mindestabstand zwischen Anfragen ein.

## Funktionen
| Entität | Kann |
|---|---|
| `light.…_ambilight` | Ein/Aus, Effekte (Video: AI/Standard/Sports/Cinema/Game, Audio: Lumina/Party/Rhythm, Fixed colour), Farbe, Helligkeit (gilt pro Stil) |
| `media_player.…` | Ein (Wake-on-LAN) / Standby, Lautstärke setzen/±, Stummschalten, Play/Pause (Tasten, per HDMI-CEC auch an eine Set-top-Box; Stop/Weiter/Zurück/Spulen kamen dort nicht an und sind nur über `remote.send_command` verfügbar) |
| `number.…_volume` | Lautstärke in den Stufen des Fernsehers (0–60); der Media Player zeigt Prozent |
| `sensor.…_input` | aktueller Eingang: Startbildschirm/Web-Apps, Satellit, TV, HDMI/Extension, andere App; Rohwerte als Attribute |
| `number.…_ambilight_saturation` | Ambilight-Sättigung −2 … +2 (Geräteeinstellung) |
| Senderwahl | `media_player.play_media` mit `media_content_type: channel`, `media_content_id: "12"` (Zifferntasten) |
| Diagnose | Gerät → „Diagnose herunterladen“ (ohne Zugangsdaten, MAC, IP, Seriennummer) |
| `remote.…_remote` | Tasten senden (`remote.send_command`, z. B. `Home`, `CursorDown`, `Confirm`) |

Der Zustand wird alle 5 s (einstellbar 2–300 s) mit drei Leseanfragen abgefragt. Schreibbefehle haben
mindestens 2 s Abstand, und schnell aufeinanderfolgende Befehle (Klicken, Ziehen am Farbrad) werden
zusammengefasst – der Fernseher ist bei schnellen Einstellungsänderungen abgestürzt. Nach dem Standby sendet die Integration
die feste Farbe erneut, weil der Fernseher sonst seine Menüfarbe zeigt.

## Installation
**Über HACS** (das Repository muss öffentlich sein):
1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/AlexSchmitz222/philips-tv-remote`,
   Typ **Integration**.
2. *Philips TV (Titan OS)* suchen → Herunterladen → Home Assistant neu starten.

**Von Hand:** Ordner `custom_components/philips_titan` nach `/config/custom_components/` kopieren
(Samba- oder SSH-Add-on) und Home Assistant neu starten.

**Einrichten:** Einstellungen → Geräte & Dienste → Integration hinzufügen → **Philips TV (Titan OS)**.
   Der Fernseher muss an sein. IP eingeben und die PIN eintippen, die der Fernseher anzeigt.
   Die MAC-Adresse für Wake-on-LAN wird automatisch ermittelt.

**Wichtig:** Andere Integrationen, die denselben Fernseher abfragen (`philips_js`,
`ha-philips-titanos`), deaktivieren. Parallele Abfragen erhöhen die Last und damit
das Risiko, dass die API hängen bleibt.

## Releases
Versionen stehen in [CHANGELOG.md](CHANGELOG.md). Neue Version:
1. `version` in `custom_components/philips_titan/manifest.json` (und `pyproject.toml`) erhöhen,
   Abschnitt in `CHANGELOG.md` ergänzen, committen.
2. `git tag v0.2.0 && git push && git push --tags` – der Workflow `release.yml` prüft, dass Tag und
   Manifest übereinstimmen, und legt das GitHub-Release an. HACS bietet dann diese Version an.

## Entwicklung
```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest   # Bibliothek + CLI „titan“
.venv/bin/python -m pytest -c /dev/null tests                  # Bibliothek, offline
./scripts/bundle_lib.sh                                         # Bibliothek in die Integration kopieren
.venv-ha/bin/python -m pytest tests_ha                          # Integration, offline (pytest-homeassistant-custom-component)
TITAN_LIVE=1 .venv-ha/bin/python -m pytest -s tests_ha/test_live.py   # gegen den echten Fernseher
```
Die Bibliothek liegt in `src/philips_titan`. `custom_components/philips_titan/titan` ist eine
Kopie davon. Nach jeder Änderung `scripts/bundle_lib.sh` ausführen.

## Bekannte Grenzen
- Im Standby ist die API nicht erreichbar; Einschalten nur per Wake-on-LAN aus demselben Netz.
- `GET ambilight/lounge` hängt die API auf und ist im Client gesperrt.
- Stummschalten läuft über die Taste `Mute` (umschalten); das `muted`-Feld von `audio/volume` ignoriert der Fernseher.
- AI und Cinema melden intern beide „Natural“; unterschieden wird über den Menüknoten.

## Lizenz
MIT, siehe [LICENSE](LICENSE). Nicht mit Philips/TP Vision verbunden; „Philips“ und „Ambilight“ sind Marken ihrer Inhaber.
