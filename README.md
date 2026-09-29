# Lyr for Home Assistant

Lyr zones as Home Assistant media players, driven through the **Lyr Core**
(the server every Lyr app talks to) rather than straight at Lyr Server.

## Do you need this? Home Assistant already sees your zones

Every Lyr zone is a Lyr Server (Lyrion Music Server, LMS) player, and Home
Assistant ships a core **Squeezebox (Lyrion Music Server)** integration that
talks to LMS directly. Point it at your Lyr Server (port 9000) and you get,
with nothing from Lyr:

- a media player per LMS player: play/pause/stop, next/previous, seek,
  volume/mute, shuffle, repeat, power, clear playlist;
- grouping (LMS sync) — `media_player.join` / `unjoin`;
- browse and search over **LMS's own library** and `play_media` with enqueue;
- **announcements** (TTS) — it saves the queue, plays the clip, then resumes;
- `squeezebox.call_method` / `call_query` for raw LMS commands;
- per-player alarm switches, preset and tone buttons, and server sensors.

What it cannot see is everything Lyr adds on top of LMS:

| | Squeezebox integration | This integration |
| --- | --- | --- |
| Zone names | LMS names (e.g. `squeezelite-lounge`) | the names you gave zones in Lyr ("Living Room") |
| Players you hid in Lyr | all shown | created **disabled** |
| Per-zone volume ceiling | bypassed — a slider or an announcement can go to 100% | every volume write clamped by the Core, as in the app |
| Now playing for Qobuz / TIDAL / SoundCloud | LMS's view: often a radio placeholder as artwork and no album | Lyr's metadata and artwork |
| Library | the files LMS scanned | the Lyr library: playlists, albums, artists, genres, local and streaming |
| Liora prompts, artist radio | — | `lyr.play_prompt`, `lyr.start_radio` |
| Explicit filter | — | a switch |
| Announcements | yes | not yet (see below) |

They can run side by side: this one for Lyr's names, library and Lyr-only
features; Squeezebox for announcements until Lyr has its own.

## What you get

- `media_player.<zone>` per Lyr zone: state, volume (0–100%, with
  `volume_limit` as an attribute), mute, shuffle, repeat, power, seek, now
  playing with artwork, grouping (`join` / `unjoin`), browsing and search over
  the Lyr library, and `play_media` of Lyr items, Home Assistant media
  sources and plain http(s) URLs.
- `switch.<core>_skip_explicit_tracks` — the household explicit filter.
  Unavailable while the feature is off in Lyr's Settings.
- Actions, each targeting a Lyr media player:
  - `lyr.play_prompt` — `prompt: "rainy sunday piano"`. Liora builds it on the
    Core: the first track in about ten seconds, the rest about a minute later.
  - `lyr.start_radio` — optional `artist:`; empty means the artist playing now.
  - `lyr.play_search` — `query: "Late Night Tales"`, optional `kind`
    (`playlist`, `album`, `artist`, `track`, `genre`) and `shuffle`. Plays the
    best library match.

## Install

Needs a Lyr Core recent enough to answer `GET /api/zones/now-playing`; the
setup says "too old" otherwise.

**HACS.** HACS → ⋮ → Custom repositories → add
`https://github.com/lyr-app/lyr`, type **Integration**. Install
**Lyr**, then restart Home Assistant.

**By hand.** Copy `custom_components/lyr` into your Home Assistant
`config/custom_components/` folder and restart.

Then Settings → Devices & services → Add integration → **Lyr**: the Lyr
Core's address and port (3000 by default). The API token is only needed if
your Core requires one.

**Discovery.** The Core advertises `_lyrcore._tcp` and the integration listens
for it, but a Core running in Docker on a bridge network is usually not heard
on the LAN. Add it by hand if it is not found.

## Announcements: why not yet

Squeezebox's announce saves the LMS playlist, plays the clip, waits for it to
stop, and reloads the playlist. Whether a Lyr queue survives that intact has
not been tested, and its announce volume is written straight to LMS, past
Lyr's volume ceiling. A Lyr announce will run on the Core and respect the
ceiling.

## Development

```bash
python3.13 -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component && .venv/bin/python -m pytest -q
```

The tests mock the Lyr Core with its real response shapes.
