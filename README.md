# Klipper Motor Music

[![English](docs/assets/english.svg)](README.md) [![Русский](docs/assets/russian.svg)](README.ru.md)

![M1006 music commands become three selectable stepper voices](docs/assets/banner.svg)

**Play Bambu Lab melodies through your Klipper stepper motors.**
Use original `M1006` sound blocks, choose any combination of three voices,
and play a startup melody before homing with `PRE_HOME=1`.

[![Tests](https://github.com/petrovichest/klipper-motor-music/actions/workflows/tests.yml/badge.svg)](https://github.com/petrovichest/klipper-motor-music/actions/workflows/tests.yml)
[GPL-3.0-or-later](LICENSE) · [Reference](docs/reference.md) · [Development](docs/development.md) · [Privacy audit](docs/privacy.md)

## What you get

- **Bambu sound files:** stock A1 start and finish tunes are included.
- **Selectable voices:** `X`, `Y`, `Z`, `XY`, `XZ`, `YZ`, or `XYZ` per playback.
- **Before-homing playback:** enable selected motors, play, then run `G28`.
- **No extra speaker or firmware patch:** one Python extension uses Klipper's existing dependencies.
- **Offline checks:** preview a tune without enabling motors or moving the printer.

**Experimental hardware feature.** One- and three-motor playback, including
the before-homing mode, has been reported working on an Ender-3 Pro. Automated
tests exercise real Klipper v0.13.0 and `master` step generation. Sound quality,
physical position retention, and transport capacity still depend on the printer.
This reproduces notes and rhythm through STEP/DIR micro-oscillations; it does
not reproduce Bambu's proprietary motor-control algorithm or identical timbre.

**Supported:** Cartesian XYZ motors. CoreXY, Delta, extruders, and axes with
multiple independent drivers are not supported. See the [limits](docs/reference.md#operating-limits).

## Install

Run on the Klipper host while the printer is idle. Adjust paths if Klipper
or your configuration directory is elsewhere.
Already installed? Use [Update or uninstall](#update-or-uninstall) instead of
copying a profile over your current settings.

```bash
git clone https://github.com/petrovichest/klipper-motor-music.git ~/klipper-motor-music
ln -s ~/klipper-motor-music/motor_music.py ~/klipper/klippy/extras/motor_music.py
mkdir -p ~/printer_data/config/tunes
cp ~/klipper-motor-music/examples/tunes/*.gcode ~/printer_data/config/tunes/
cp ~/klipper-motor-music/examples/motor_music_3voice.cfg ~/printer_data/config/motor_music.cfg
```

Add to `printer.cfg`:

```ini
[include motor_music.cfg]
```

Restart the **Klipper service** from your printer interface or with:

```bash
sudo systemctl restart klipper
```

The full profile maps voice X → motor X, Y → Y, Z → Z. All seven combinations
are available; choosing `VOICES` never permanently mutes anything.
The symlink command deliberately fails if an extension already exists.

For an initial one-motor setup, use [motor_music.cfg](examples/motor_music.cfg)
instead. It maps **only Bambu's Y voice to motor X**; other voices are not
configured. Install one profile, not both.

## First playback

Preview first. This requires no homing and does not enable motors or move:

```gcode
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XYZ DRY_RUN=1
```

To play **before homing**:

```gcode
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XYZ PRE_HOME=1
G28
```

`PRE_HOME=1` enables selected motors and leaves them on for `G28`. It never marks
axes as homed. Limits: **3 seconds and one configured microstep of at most
0.025 mm**. Unknown positions cannot be checked against physical stops; the
mechanism must be free to make these small oscillations. Known axes still obey
position checks.

For normal playback, home XYZ and use your printer's usual safe interior park
first. Then run:

```gcode
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XYZ
MOTOR_MUSIC_PLAY FILENAME=a1-finish.gcode VOICES=XYZ
```

These are sound files, **not print jobs**. Load them with `MOTOR_MUSIC_PLAY`.
The importer ignores known Bambu enable/release wrappers, rejects motion and
heater commands, and validates the whole file before playback.

## Choose the voices

Run one command at a time to compare the same tune:

```gcode
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=X
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=Y
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=Z
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XY
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XZ
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=YZ
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XYZ
```

`VOICES` selects **original musical parts**, not copies of the lead melody.
The stock A1 start tune has just **three notes in X**; Y carries the lead.
Pauses and the full timeline are preserved. With the full profile, part names
match physical motor names. Custom mappings can change that.

The choice applies to one invocation. Omit `VOICES` to play all configured parts.
It also works with `PRE_HOME=1` and `DRY_RUN=1`.

## Add it to your slicer

In `motor_music.cfg`, allow playback during a print and run `RESTART` while idle:

```ini
allow_during_print: True
```

In OrcaSlicer, open **Printer settings → Machine G-code**. For a melody before
homing, put the sound call before your existing `G28`:

```gcode
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XYZ PRE_HOME=1
G28
```

Keep the rest of your startup sequence. Alternatively, use the normal call
without `PRE_HOME` after homing and an interior park.

In the end G-code or existing end macro, insert:

```gcode
MOTOR_MUSIC_PLAY FILENAME=a1-finish.gcode VOICES=XYZ
```

Place it **after the existing retract/lift and heater shutdown, before the final
park at axis limits and before `M84`/`M18`**. Normal position checks apply.
If your end macro already plays the tune, do not add a second call in the slicer.
Choose start and finish voices independently. Save the preset and **slice again**.

## Update or uninstall

```bash
git -C ~/klipper-motor-music pull --ff-only
sudo systemctl restart klipper
```

Update only while idle. G-code `RESTART` reloads configuration; it does **not**
reload an already imported Python extension. Code updates need a service restart.
Your copied printer configuration is not overwritten by `git pull`.

To uninstall, remove the include line, extension symlink, and sound calls from
your slicer/macros, then restart the Klipper service. Keep your usual homing,
parking, heater shutdown, and motor-off commands.

## More information

- [Commands, configuration, limits, and troubleshooting](docs/reference.md)
- [How it works, tests, and contributing](docs/development.md)
- [Public-history privacy audit](docs/privacy.md)

Project code is [GPL-3.0-or-later](LICENSE). Bundled Bambu Studio sound blocks
retain their [AGPL-3.0 license](LICENSES/AGPL-3.0.txt) and source attribution.
This project is not affiliated with Bambu Lab or the Klipper project.
