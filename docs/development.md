# Development

[← Project overview](../README.md)

## Design

The installed extension is one file, `motor_music.py`. Parsing and planning use
the standard library; the motion backend imports Klipper's existing `chelper`.
No extra runtime package is installed.

For frequency `f`, the planner emits paired linear segments
`0 → amplitude → 0`, each lasting `1 / (2f)`. Each note uses complete cycles;
the remaining fraction of a period is silence. Pitch and the timeline are
preserved, with zero net commanded displacement at each note's end.

Selected motors temporarily use separate Cartesian solvers and `trapq` queues.
Parts share a start time. Original solvers/queues are restored and MCU counters
are checked. v0.13 and newer `motion_queuing` backends use their respective step
generation paths. Input shaping is bypassed for the waveform and restored for
normal motion. There is no G-code or RPC per step.

`PRE_HOME` relaxes unknown-coordinate checks under tighter limits, enables
selected motors, and never calls `SET_KINEMATIC_POSITION` or marks axes as homed.
Ordinary playback retains its homing and enable requirements.

## Tests

Pure parser/planner tests need only Python:

```bash
python3 -m unittest discover -s tests -v
python3 tools/inspect_tune.py examples/tunes/a1-start.gcode
```

For real Klipper/C integration, use a **disposable checkout**:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
git clone --depth 1 --branch v0.13.0 https://github.com/Klipper3d/klipper.git /tmp/klipper-music-check
cd /tmp/klipper-music-check
cp test/configs/hostsimulator.config .config
make olddefconfig
make -j2
cd -
python3 tests/run_klipper.py /tmp/klipper-music-check
```

The runner temporarily installs the extension in that checkout, then removes
it. It always uses debug file mode (`-i`, `-o`, `-d`) and never connects to a
printer. Tests decode emitted MCU packets to verify pitch, simultaneous voices,
all seven masks for both tunes, muted motors, zero net steps, restored normal
motion, and pre-homing enable/homing state. Rejection and preview cases must
emit no steps. GitHub Actions runs this on v0.13.0 and `master`.

## Contributions and sources

Keep runtime dependencies unchanged unless necessary. Include a reproducible
offline test for motion changes. Use synthetic or sanitized fixtures, not actual
printer configurations, logs, credentials, or private network details. Document
what was checked in file mode versus on physical hardware.

- [Bambu MIDI guide](https://wiki.bambulab.com/en/A1-mini/Midi)
- [Official MIDI converter](https://midi-to-gcode.bambulab.com/edit)
- [Bambu Studio sound-block source](https://github.com/bambulab/BambuStudio/tree/79df7ae309be398ed30c9f397c13c9911c2edc57/resources/profiles/BBL/machine)
- [Klipper force_move.py](https://github.com/Klipper3d/klipper/blob/v0.13.0/klippy/extras/force_move.py)

Project code is GPL-3.0-or-later. Bundled Bambu sound files retain their AGPL-3.0
license and per-file upstream attribution. Preserve both when redistributing.
