# MAESTRO MIDI Note Pitch & Velocity (uint8)

Native **8-bit** MIDI note data from the MAESTRO v3 piano-performance corpus, organized as
**one family per quantity** with **one sample per performance** — "many series of the same
physical quantity". A non-image source of genuine byte-width numeric data.

- Source: https://magenta.tensorflow.org/datasets/maestro (CC BY-NC-SA 4.0)
- Local raw payload: `${DATA_DIR:-.data}/downloads/maestro_midi_notes/maestro-v3.0.0-midi.zip`

## Families & samples

| family | quantity | type |
|---|---|---|
| `midi_note_pitch_u8` | note number / pitch (0–127) | uint8 |
| `midi_note_velocity_u8` | note velocity / loudness (0–127) | uint8 |

- **A sample** = one performance's sequence of note-on pitches (or velocities), in event
  order. Pitch and velocity come from the same note-on events but are independent families
  (different quantities) — never mixed.
- **Samples/family** = number of performances with `>= MAESTRO_MIN_NOTES` notes (default
  1000); MAESTRO has ~1.3k full piano performances, most with thousands of notes.

## How it's parsed

A pure-stdlib MIDI reader (no external library) walks `MThd`/`MTrk` chunks, variable-length
delta times, running status, and meta/sysex events, collecting note-on events with
velocity > 0. Note-off (and note-on with velocity 0) are not values.

## Run

```sh
bash datasets/maestro_midi_notes/download.sh   # one ~85 MB zip, liveness-checked first
bash datasets/maestro_midi_notes/build.sh
bash datasets/maestro_midi_notes/verify.sh
```

Tuning env vars: `MAESTRO_URL` (override the zip URL), `MAESTRO_MIN_NOTES` (default 1000).
Logs under `${DATA_DIR:-.data}/logs/maestro_midi_notes/`.
