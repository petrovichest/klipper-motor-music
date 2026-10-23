#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise real Klippy/C step generation using a disposable Klipper checkout.

Always uses -i/-o/-d debug file mode. Never connects to a serial port or printer.
Build test/configs/hostsimulator.config first (see README).
"""
import argparse
import importlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

CONFIG = """
[mcu]
serial: /dev/null
[printer]
kinematics: cartesian
max_velocity: 100
max_accel: 1000
[stepper_x]
step_pin: 0
dir_pin: 1
enable_pin: !2
endstop_pin: 3
microsteps: 16
rotation_distance: 40
position_endstop: 0
position_max: 250
[stepper_y]
step_pin: 4
dir_pin: 5
enable_pin: !2
endstop_pin: 6
microsteps: 16
rotation_distance: 40
position_endstop: 0
position_max: 250
[stepper_z]
step_pin: 7
dir_pin: 8
enable_pin: !9
endstop_pin: 10
microsteps: 16
rotation_distance: 8
position_endstop: 0
position_max: 200
[force_move]
enable_force_move: True
[input_shaper]
shaper_type_x: ei
shaper_freq_x: 30
shaper_type_y: ei
shaper_freq_y: 26.75
[include {full_config}]
[motor_music]
tune_directory: {tunes}
[gcode_macro CHECK_PRE_HOME]
gcode:
  {{% if printer.toolhead.homed_axes %}}
    {{action_raise_error("PRE_HOME falsely marked axes as homed")}}
  {{% endif %}}
  {{% for axis in params.VOICES|lower %}}
    {{% if not printer.stepper_enable.steppers['stepper_' + axis] %}}
      {{action_raise_error("PRE_HOME did not enable a selected motor")}}
    {{% endif %}}
  {{% endfor %}}
  {{action_respond_info("PRE_HOME state verified")}}
"""

GCODE = """
SET_KINEMATIC_POSITION X=100 Y=100 Z=10
SET_STEPPER_ENABLE STEPPER=stepper_x ENABLE=1
SET_STEPPER_ENABLE STEPPER=stepper_y ENABLE=1
SET_STEPPER_ENABLE STEPPER=stepper_z ENABLE=1
GET_POSITION
MOTOR_MUSIC_TEST VOICE=Y NOTE=46 DURATION=200 DRY_RUN=1
MOTOR_MUSIC_TEST VOICE=Y NOTE=46 DURATION=200
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode DRY_RUN=1
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-finish.gcode
GET_POSITION
M1006 S1
M1006 L70 M70 N99
M1006 A37 B10 L100 C41 D20 M100 E44 F15 N100
M1006 A0 B10 C0 D10 E0 F10
M1006 W
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=X
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=Y
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=Z
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XY
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XZ
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=YZ
GET_POSITION
MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XYZ
GET_POSITION
G91
G1 X1 Y1 Z1 F600
G1 X-1 Y-1 Z-1 F600
G90
M400
G4 P1000
GET_POSITION
"""


def decode_output(klipper, dictionary, output):
    sys.path.insert(0, str(klipper / "klippy"))
    msgproto = importlib.import_module("msgproto")
    parser = msgproto.MessageParser()
    parser.process_identify(dictionary.read_bytes(), decompress=False)
    data, commands = output.read_bytes(), []
    while data:
        size = parser.check_packet(data)
        if size <= 0:
            raise AssertionError("Invalid debug protocol packet")
        commands.extend(parser.dump(data[:size]))
        data = data[size:]
    return commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("klipper", type=pathlib.Path)
    args = parser.parse_args()
    klipper = args.klipper.resolve()
    dictionary = klipper / "out/klipper.dict"
    if not dictionary.is_file():
        parser.error("Build the hostsimulator dictionary first")
    target = klipper / "klippy/extras/motor_music.py"
    if target.exists():
        parser.error("Use a disposable checkout without motor_music.py installed")
    shutil.copyfile(ROOT / "motor_music.py", target)
    try:
        with tempfile.TemporaryDirectory(prefix="motor-music-integration-") as tmp:
            work = pathlib.Path(tmp)
            config, gcode = work / "printer.cfg", work / "input.gcode"
            config.write_text(CONFIG.format(tunes=ROOT / "examples/tunes",
                                            full_config=ROOT / "examples/motor_music_3voice.cfg"))
            gcode.write_text(GCODE)
            log, output = work / "klippy.log", work / "commands.bin"
            result = subprocess.run([sys.executable, str(klipper / "klippy/klippy.py"),
                                     str(config), "-i", str(gcode), "-o", str(output),
                                     "-d", str(dictionary), "-l", str(log)],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=60)
            contents = log.read_text() if log.exists() else ""
            if result.returncode or "Music complete:" not in contents:
                print(result.stdout)
                print(contents[-16000:])
                raise AssertionError("Real Klipper integration failed")
            positions = re.findall(r"^mcu:.*$", contents, re.MULTILINE)
            if len(positions) != 13 or len(set(positions)) != 1:
                raise AssertionError("MCU counters changed: %r" % positions)
            if contents.count("Music complete:") != 11 or contents.count("Music preview:") != 2:
                raise AssertionError("Not all playback/preview paths completed")
            commands = decode_output(klipper, dictionary, output)
            queue_steps = [line for line in commands if "queue_step " in line]
            if len(queue_steps) < 1000:
                raise AssertionError("Expected actual compressed MCU steps")
            # Decode direction and signed count from the emitted MCU protocol.
            directions, counts, totals, clocks, steps, by_pin = {}, {}, {}, {}, {}, {}
            for line in commands:
                fields = dict(re.findall(r"(\w+)=(-?\d+)", line))
                if "config_stepper " in line:
                    by_pin[fields["step_pin"]] = fields["oid"]
                    clocks[fields["oid"]] = 0
                elif "reset_step_clock " in line:
                    clocks[fields["oid"]] = int(fields["clock"])
                elif "set_next_step_dir " in line:
                    directions[fields["oid"]] = 1 if fields["dir"] == "1" else -1
                elif "queue_step " in line:
                    oid, count = fields["oid"], int(fields["count"])
                    counts[oid] = counts.get(oid, 0) + directions[oid] * count
                    totals[oid] = totals.get(oid, 0) + count
                    for index in range(count):
                        clocks[oid] += int(fields["interval"]) + index * int(fields["add"])
                        steps.setdefault(oid, []).append(clocks[oid])
            if len(counts) != 3 or any(counts.values()):
                raise AssertionError("Nonzero emitted net steps: %r" % counts)
            frequency = float(json.loads(dictionary.read_text())["config"]["CLOCK_FREQ"])
            y_steps, z_steps = steps[by_pin["4"]], steps[by_pin["7"]]
            for index in range(176):
                expected = y_steps[0] + index * frequency / 880.0
                if abs(y_steps[index] - expected) > 2:
                    raise AssertionError("440 Hz note has incorrect MCU timing")
            if abs(y_steps[176] - z_steps[0]) > 2:
                raise AssertionError("A1's first Y/Z voices did not start together")
            print("Real Klipper integration passed: 11 playbacks, 2 previews, "
                  "%d queue_step commands, zero net steps on all 3 motors, "
                  "440 Hz timing and synchronous voices verified, normal motion restored. "
                  "Total steps: %s" % (len(queue_steps), totals))
            # Negative paths must fail before emitting any motion.
            parked = GCODE[:GCODE.index("GET_POSITION")]
            expected_counts = {"a1-start.gcode": {"X": 222, "Y": 864, "Z": 730},
                               "a1-finish.gcode": {"X": 312, "Y": 1068, "Z": 1084}}
            # Check the emitted packets, not just the Python plan: an omitted
            # voice must send no steps, and every retained part stays intact.
            for filename, voice_counts in expected_counts.items():
                for selection in ["X", "Y", "Z", "XY", "XZ", "YZ", "XYZ"]:
                    gcode.write_text(parked + "MOTOR_MUSIC_PLAY FILENAME=%s VOICES=%s\n" %
                                     (filename, selection))
                    log.unlink()
                    result = subprocess.run([sys.executable, str(klipper / "klippy/klippy.py"),
                                             str(config), "-i", str(gcode), "-o", str(output),
                                             "-d", str(dictionary), "-l", str(log)],
                                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            timeout=60)
                    contents = log.read_text()
                    if result.returncode or "Music complete:" not in contents:
                        raise AssertionError("%s %s failed:\n%s" % (filename, selection, contents[-4000:]))
                    totals_by_oid = {}
                    for line in decode_output(klipper, dictionary, output):
                        if "queue_step " in line:
                            fields = dict(re.findall(r"(\w+)=(-?\d+)", line))
                            oid = fields["oid"]
                            totals_by_oid[oid] = totals_by_oid.get(oid, 0) + int(fields["count"])
                    expected = {by_pin[pin]: voice_counts[v]
                                for v, pin in zip("XYZ", ("0", "4", "7")) if v in selection}
                    if totals_by_oid != expected:
                        raise AssertionError("%s %s: emitted %r, expected %r" %
                                             (filename, selection, totals_by_oid, expected))
            print("All 7 voice combinations passed for both stock tunes; muted motors emitted no steps.")
            # Start from genuine unhomed/disabled state. No SET_KINEMATIC_POSITION
            # or SET_STEPPER_ENABLE is supplied by this test.
            for selection in ["X", "Y", "Z", "XY", "XZ", "YZ", "XYZ"]:
                gcode.write_text("GET_POSITION\nMOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=%s PRE_HOME=1\n"
                                 "GET_POSITION\nCHECK_PRE_HOME VOICES=%s\n" % (selection, selection))
                log.unlink()
                result = subprocess.run([sys.executable, str(klipper / "klippy/klippy.py"),
                                         str(config), "-i", str(gcode), "-o", str(output),
                                         "-d", str(dictionary), "-l", str(log)],
                                        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        timeout=60)
                contents = log.read_text()
                positions = re.findall(r"^mcu:.*$", contents, re.MULTILINE)
                if (result.returncode or "PRE_HOME state verified" not in contents
                        or len(positions) != 2 or len(set(positions)) != 1):
                    raise AssertionError("PRE_HOME %s failed:\n%s" % (selection, contents[-6000:]))
                actual = {}
                for line in decode_output(klipper, dictionary, output):
                    if "queue_step " in line:
                        fields = dict(re.findall(r"(\w+)=(-?\d+)", line))
                        oid = fields["oid"]
                        actual[oid] = actual.get(oid, 0) + int(fields["count"])
                expected = {by_pin[pin]: expected_counts['a1-start.gcode'][v]
                            for v, pin in zip('XYZ', ('0', '4', '7')) if v in selection}
                if actual != expected:
                    raise AssertionError("PRE_HOME %s emitted incorrect parts: %r" % (selection, actual))
            print("All 7 PRE_HOME combinations passed: motors auto-enabled, zero net steps, homing remained unknown.")
            cases = [
                ("unhomed", "MOTOR_MUSIC_TEST", "Home XYZ"),
                ("limit", parked.replace("Y=100", "Y=0") + "MOTOR_MUSIC_TEST", "away from its limits"),
                ("frequency", parked + "MOTOR_MUSIC_TEST NOTE=72", "exceeds max_frequency"),
                ("path", parked + "MOTOR_MUSIC_PLAY FILENAME=../outside.gcode", "inside tune_directory"),
                ("malformed", "M1006 S1\nM1006 C73 D10\nM1006 W", "notes must be in 0..72"),
                ("preview", "MOTOR_MUSIC_TEST DRY_RUN=1", "Music preview:"),
                ("duplicate-voices", parked + "MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XX", "distinct X, Y, Z"),
                ("unknown-voice", parked + "MOTOR_MUSIC_PLAY FILENAME=a1-start.gcode VOICES=XQ", "distinct X, Y, Z"),
            ]
            for name, program, expected in cases:
                gcode.write_text(program + "\n")
                log.unlink()
                result = subprocess.run([sys.executable, str(klipper / "klippy/klippy.py"),
                                         str(config), "-i", str(gcode), "-o", str(output),
                                         "-d", str(dictionary), "-l", str(log)],
                                        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        timeout=60)
                contents = log.read_text()
                if expected not in contents:
                    raise AssertionError("%s: missing expected result: %s\n%s" %
                                         (name, expected, contents[-4000:]))
                if any("queue_step " in line for line in decode_output(klipper, dictionary, output)):
                    raise AssertionError("%s emitted motion" % name)
            print("8 rejection/preview scenarios passed without emitting steps.")
    finally:
        target.unlink()


if __name__ == "__main__":
    main()
