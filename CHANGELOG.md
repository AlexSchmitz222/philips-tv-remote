# Changelog

## 0.2.0

- **Other Titan models:** the Ambilight menu layout (node ids, string ids with or without the
  `MLM_PHM_KEY_` prefix, list items, slider ranges) is read from the TV once; unknown styles show
  up as effects. Falls back to the layout verified on the 65PQS8651/12.
- **Stability:** setting writes at least 2 s apart, remote keys 1 s, reads 0.5 s; rapid
  commands (clicking, dragging the colour wheel or sliders) are coalesced. The TV crashed
  when settings were written in quick succession.
- Polling interval configurable (default 5 s).
- Media player: play/pause (remote keys, forwarded via HDMI-CEC; stop/next/previous/
  fast-forward/rewind did not reach a set-top box and are only in `remote.send_command`),
  channel numbers via `media_player.play_media` with type `channel`, mute via the Mute key.
- New entities: input sensor (home / satellite / TV / HDMI / other app), volume in TV
  steps (0–60).
- Effects grouped by source: "Video: …", "Audio: …", "Fixed colour".
- No `notifychange` long-poll: abandoned long-polls pile up on the TV until it answers 503
  (an intermediate development version used it).
- MAC address from the TV (`network/devices`), model and serial in the device info.
- Diagnostics download (credentials, MAC, IP and serial redacted).
- Integration icon.
- Blueprints: Ambilight effect per input, lights on when the TV turns off.
- Media player marked as assumed state, so HA shows separate play and pause buttons.

## 0.1.0

- First version: pairing, Ambilight light (styles, fixed colour, brightness per style),
  saturation, media player (Wake-on-LAN, standby, volume), remote.
