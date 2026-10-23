# Command reference

[![English](assets/english.svg)](reference.md) [![Русский](assets/russian.svg)](reference.ru.md)

[← Installation and quick start](../README.md)

## Commands

| Command | Purpose |
|---|---|
| `MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode` | Validate and play a sound-only file from `tune_directory`. |
| `VOICES=X` / `XY` / `XYZ` | Optional argument to `MOTOR_MUSIC_PLAY`; select a nonempty subset of configured parts. |
| `PRE_HOME=1` | Optional argument to `MOTOR_MUSIC_PLAY`; allow short, one-microstep playback before homing and enable selected motors. |
| `DRY_RUN=1` | Optional argument to `MOTOR_MUSIC_PLAY` or `MOTOR_MUSIC_TEST`; validate without enabling motors or moving. |
| `MOTOR_MUSIC_TEST VOICE=Y NOTE=46 DURATION=200` | Play A4 / 440 Hz for 200 ms on one configured voice. |
| `M1006 S1` … `M1006 W` | Buffer and play directly; normal homing/enable checks apply. |
| `MOTOR_MUSIC_CLEAR` | Discard a buffered `M1006` sequence. |

`FILENAME` must stay inside `tune_directory`. Voice letters are case-insensitive;
duplicates, unknown letters, and unconfigured voices are rejected. Selection
never remaps a part or changes the saved profile.

`MOTOR_MUSIC_TEST`: `VOICE` defaults to Y; `NOTE` defaults to 46, accepts 1–72;
`DURATION` defaults to 200, accepts 10–1000 **milliseconds**. `PRE_HOME` is an
argument of file playback, not of test notes or raw `M1006`.

## Configuration

| Setting | Default | Meaning |
|---|---:|---|
| `voice_x`, `voice_y`, `voice_z` | Explicit mapping | Bambu part → `stepper_x`, `stepper_y`, or `stepper_z`. Each motor may be used once. |
| `amplitude_steps` | 1 | Maximum excursion in configured microsteps; 1–32. |
| `max_frequency` | 1000 | Maximum selected-note frequency in Hz; configurable range 30–2000. |
| `max_excursion` | 0.1 | Maximum excursion from the starting position in mm; up to 0.5. |
| `max_step_rate` | 2000 | Maximum combined step rate; up to 100000 steps/s. |
| `max_duration` | 15 | Maximum file/sequence length in seconds; up to 30. |
| `position_margin` | 1 | Required clearance from axis limits in mm; at least 0.1. |
| `allow_during_print` | False | Allow playback while printing or paused, including slicer startup code. |
| `tune_directory` | Config directory + `/tunes` | Directory containing sound-only files. |

The [full profile](../examples/motor_music_3voice.cfg) maps three parts to
corresponding motors and sets `max_step_rate: 3000`. Stock A1 start and finish
tunes peak at about 2359 and 2490 combined steps/s with one-microstep amplitude.
The [single-motor profile](../examples/motor_music.cfg) maps only Y to motor X
and uses the default 2000-step limit.

One configured microstep is `rotation_distance / steps_per_rotation`, with
microsteps and gearing included. For typical 200-step, 16-microstep, 40 mm/rev
XY axes it is 0.0125 mm. For an 8 mm/rev Z axis it is 0.0025 mm.

## Operating limits

- Normal playback requires homed XYZ, enabled selected motors, and an interior park.
- `PRE_HOME=1` permits unknown coordinates but never invents them. It enables
  selected motors and leaves them on. Limits: 3 seconds, amplitude 1, and a
  configured microstep no larger than 0.025 mm. Known axes retain limit checks.
- `allow_during_print` is still required for playback from a print job,
  including `PRE_HOME=1`.
- Cartesian only. Independently driven multi-motor axes are rejected. Two
  physical motors on one driver appear as one stepper; their mechanics and
  sound still need testing.
- Reversals create substantial MCU traffic. Step-rate limits do not guarantee
  UART/USB/CAN capacity. Increasing amplitude increases motion and traffic.
- A failure after low-level queuing starts shuts Klipper down rather than letting
  printing resume after a potentially incomplete oscillation. Normal cancel does
  not immediately discard queued steps; `M112` is the emergency stop.

## Bambu M1006 format

| Part | Note | Duration | Volume |
|---|---|---|---|
| X | `A` | `B` | `L` |
| Y | `C` | `D` | `M` |
| Z | `E` | `F` | `N` |

Notes 1–72 map to MIDI `note + 23`; 37 is C4 and 46 is A4. Zero is silence.
Durations are integer centiseconds: `D20` is 200 ms. Each line starts its parts
together and lasts as long as its longest part. Missing parts are silent in
that slice. Volumes 0–100 persist; notes and durations do not.

```gcode
M1006 S1
M1006 C46 D20 M100
M1006 C0 D10
M1006 C49 D20 M100
M1006 W
```

Only `M1006` lines belong in a directly pasted sequence. File playback also
accepts known bare `M17`, `M18` axis wrappers, `M400` / `M400 S1`, and
`M73 P… R…` metadata without executing them. Motion, heating, motor-current
commands, multiple sequences, malformed fields, and incomplete files are rejected.
Files are limited to 128 KiB, 1024 buffered data/setup lines, and 200 centiseconds
per part per slice, plus the configured total-duration limit.

## Troubleshooting

| Symptom | Check |
|---|---|
| Only three notes with `VOICES=X` | This is the stock A1 X part. Use Y for the lead or XYZ for the arrangement. |
| “Voice … is not configured” | Use the full profile for all seven combinations. The single-motor profile exposes only Y. |
| “Home XYZ” / “must already be enabled” | Home and park, or explicitly use `PRE_HOME=1` for short pre-homing file playback. |
| “Park … away from its limits” | Play before the boundary park; preserve `position_margin` and excursion clearance. |
| “Music during a print is disabled” | Set `allow_during_print: True` and reload configuration while idle. |
| “Combined step rate … exceeds …” | Stock three-voice tunes need the full profile's 3000-step limit. More amplitude may need more bandwidth. |
| Updated code seems unchanged | Restart the Klipper service, not just G-code `RESTART`. |
| Uneven loudness or rattling | Equal excursion does not mean equal acoustic output. Compare voices individually; no printer-specific equalization is implemented. |

At amplitude 1, all nonzero volumes round to one microstep. Volume is coarse,
not calibrated loudness control. Frequency-dependent motor/frame resonance and
different mechanics affect sound; Bambu's acoustic tables are not reused for
other printers.
