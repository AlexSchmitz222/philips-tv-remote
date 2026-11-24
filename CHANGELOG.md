# Changelog

## 0.2.0

- **Stability:** setting writes at least 2 s apart, remote keys 1 s, reads 0.5 s; rapid
  commands (clicking, dragging the colour wheel or sliders) are coalesced. The TV crashed
  when settings were written in quick succession.
- Polling interval configurable (default 5 s).
- Media player: play/pause/stop/next/previous (remote keys, forwarded via HDMI-CEC),
  channel numbers via `media_player.play_media` with type `channel`, mute via the Mute key.
- New entities: input sensor (home / satellite / TV / HDMI / other app), volume in TV
  steps (0–60), optional Ambilight colour sensor (average LED colour, `rgb_color`).
- No `notifychange` long-poll: abandoned long-polls pile up on the TV until it answers 503
  (an intermediate development version used it).
- MAC address from the TV (`network/devices`), model and serial in the device info.
- Diagnostics download (credentials, MAC, IP and serial redacted).
- Integration icon.

## 0.1.0

- First version: pairing, Ambilight light (styles, fixed colour, brightness per style),
  saturation, media player (Wake-on-LAN, standby, volume), remote.
