# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 petrovichest
"""Bambu M1006 melodies on Klipper's STEP/DIR motors.

Pure parsing/planning code also runs outside Klipper. The hardware backend uses
Klipper's trapq/Cartesian solver, following extras/force_move.py. No GPIO bit
banging, per-step G-code, driver register changes, or MCU firmware patch.
"""

import math
import os
import re
from collections import namedtuple

VOICE_FIELDS = (("A", "B", "L"), ("C", "D", "M"), ("E", "F", "N"))
VOICES = "XYZ"
MAX_LINES = 1024
MAX_FILE_BYTES = 128 * 1024
Tone = namedtuple("Tone", "note duration volume")
Slice = namedtuple("Slice", "tones duration")
Segment = namedtuple("Segment", "time duration position direction velocity")


class MusicError(ValueError):
    pass


def note_frequency(note):
    """Bambu note 37 = MIDI 60 = C4. Zero denotes silence."""
    if not 0 <= note <= 72:
        raise MusicError("Bambu notes must be in 0..72")
    return 0.0 if note == 0 else 440.0 * 2.0 ** ((note - 46) / 12.0)


def select_voices(value, configured):
    """Select configured Bambu voices without remapping their parts."""
    if value is None:
        return tuple(sorted(configured))
    value = value.upper()
    if (not value or any(v not in VOICES for v in value)
            or len(set(value)) != len(value)):
        raise MusicError("VOICES must contain distinct X, Y, Z letters (e.g. X, XY, XYZ)")
    selected = tuple(i for i, name in enumerate(VOICES) if name in value)
    if any(i not in configured for i in selected):
        raise MusicError("VOICES includes a voice that is not configured")
    return selected


def fields_from_line(line):
    """Strict compact/space-separated M1006 fields, including valueless W."""
    line = line.split(";", 1)[0].strip().upper()
    match = re.match(r"^M1006(?=\s|[A-Z]|$)", line)
    if not match:
        raise MusicError("Expected M1006")
    rest, fields = line[match.end():], {}
    while rest.strip():
        match = re.match(r"\s*([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))?", rest)
        if not match:
            raise MusicError("Invalid M1006 field: %s" % rest[:32])
        key, value = match.groups()
        if key not in "S W A B L C D M E F N".split():
            raise MusicError("Unknown M1006 field %s" % key)
        if key in fields:
            raise MusicError("Duplicate M1006 field %s" % key)
        if key == "W":
            if value is not None:
                raise MusicError("M1006 W takes no value")
            fields[key] = None
        else:
            if value is None or not float(value).is_integer():
                raise MusicError("M1006 %s requires an integer" % key)
            fields[key] = int(value)
        rest = rest[match.end():]
    return fields


class Sequence:
    """Transactional buffer: nothing moves until W and full validation."""

    def __init__(self, max_duration=15.0):
        if not math.isfinite(max_duration) or not 0 < max_duration <= 30:
            raise MusicError("max_duration must be finite and in (0, 30]")
        self.max_duration = max_duration
        self.reset()

    def reset(self):
        self.active = False
        self.slices = []
        self.duration = 0.0
        self.volumes = [100, 100, 100]
        self.lines = 0

    def feed(self, fields):
        try:
            return self._feed(fields)
        except (MusicError, OverflowError):
            self.reset()
            raise

    def _feed(self, fields):
        if "S" in fields:
            if fields != {"S": 1}:
                raise MusicError("Only standalone M1006 S1 is supported")
            self.reset()
            self.active = True
            return None
        if not self.active:
            raise MusicError("Begin a melody with M1006 S1")
        if "W" in fields:
            if fields != {"W": None}:
                raise MusicError("M1006 W must be on its own line")
            if not self.slices:
                raise MusicError("The melody is empty")
            result = tuple(self.slices)
            self.reset()
            return result
        self.lines += 1
        if not fields or self.lines > MAX_LINES:
            raise MusicError("Empty command or too many melody lines")
        tones, has_timing = [], False
        for voice, (nk, dk, vk) in enumerate(VOICE_FIELDS):
            if vk in fields:
                if not 0 <= fields[vk] <= 100:
                    raise MusicError("Volume must be in 0..100")
                self.volumes[voice] = fields[vk]
            if (nk in fields) != (dk in fields):
                raise MusicError("%s and %s must occur together" % (nk, dk))
            note, centiseconds = fields.get(nk, 0), fields.get(dk, 0)
            note_frequency(note)
            if not 0 <= centiseconds <= 200:
                raise MusicError("Note duration must be in 0..200 centiseconds")
            has_timing |= nk in fields
            tones.append(Tone(note, centiseconds / 100.0, self.volumes[voice]))
        if not has_timing:
            return None  # Volume-only setup, e.g. L70 M70 N99.
        duration = max(t.duration for t in tones)
        if duration <= 0:
            raise MusicError("A timeline slice must have positive duration")
        if self.duration + duration > self.max_duration + 1e-9:
            raise MusicError("Melody exceeds %.2f seconds" % self.max_duration)
        self.slices.append(Slice(tuple(tones), duration))
        self.duration += duration
        return None


def parse_gcode(text, max_duration=15.0):
    """Read a complete sound-only export; reject motion/heater commands.

    Bambu's motor-enable/release wrappers and progress metadata are deliberately
    not executed. A sequence's duration is the max of its three voice durations
    on each line, so the voices are simultaneous, never concatenated.
    """
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise MusicError("Melody file is too large")
    sequence, finished = Sequence(max_duration), []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip().upper()
        if not line:
            continue
        try:
            if line.startswith("M1006"):
                if finished:
                    raise MusicError("Only one S1..W sequence is allowed per file")
                if "S" in fields_from_line(line) and sequence.active:
                    raise MusicError("Previous sequence has no M1006 W")
                result = sequence.feed(fields_from_line(line))
                if result is not None:
                    finished.append(result)
            elif re.fullmatch(r"M17", line):
                pass
            elif re.fullmatch(r"M18(?:\s+[XYZE](?:\s+[XYZE])*)?", line):
                pass
            elif re.fullmatch(r"M400(?:\s+S1)?", line):
                pass
            elif re.fullmatch(r"M73\s+P\d+(?:\.\d+)?\s+R\d+(?:\.\d+)?", line):
                pass
            else:
                raise MusicError("Not a sound-only command: %s" % line[:60])
        except MusicError as exc:
            raise MusicError("Line %d: %s" % (number, exc)) from exc
    if not finished or sequence.active:
        raise MusicError("Expected one complete M1006 S1 .. M1006 W sequence")
    return finished[0]


def build_plan(slices, step_distances, amplitude_steps=1, max_frequency=1000.0,
               max_excursion=0.1, max_step_rate=2000.0):
    """Plan integer-microstep out/back cycles. Finish each note at zero.

    No incomplete cycle is emitted; the <1-period remainder is silence. Pitch
    stays exact instead of detuning notes to fit an integer number of periods.
    """
    if (not isinstance(amplitude_steps, int) or not 1 <= amplitude_steps <= 32
            or not math.isfinite(max_frequency) or not 30 <= max_frequency <= 2000
            or not math.isfinite(max_excursion) or not 0 < max_excursion <= 0.5
            or not math.isfinite(max_step_rate) or not 0 < max_step_rate <= 100000):
        raise MusicError("Invalid oscillator limits")
    for voice, distance in step_distances.items():
        if voice not in range(3) or not math.isfinite(distance) or distance <= 0:
            raise MusicError("Invalid voice or step distance")
        if amplitude_steps * distance > max_excursion + 1e-12:
            raise MusicError("Configured amplitude exceeds max_excursion")
    plan = {voice: [] for voice in step_distances}
    offset = 0.0
    for item in slices:
        step_rate = 0.0
        for voice, distance in step_distances.items():
            tone = item.tones[voice]
            if not tone.note or not tone.volume or not tone.duration:
                continue
            frequency = note_frequency(tone.note)
            if frequency > max_frequency:
                raise MusicError("Note %.2f Hz exceeds max_frequency" % frequency)
            steps = max(1, int(amplitude_steps * tone.volume / 100.0 + 0.5))
            excursion = distance * steps
            step_rate += 2.0 * frequency * steps
            half = 0.5 / frequency
            count = int(math.floor(tone.duration * frequency + 1e-9))
            speed = excursion / half
            for cycle in range(count):
                start = offset + cycle / frequency
                plan[voice].append(Segment(start, half, 0.0, 1.0, speed))
                plan[voice].append(Segment(start + half, half, excursion, -1.0, speed))
        if step_rate > max_step_rate:
            raise MusicError("Combined step rate %.0f exceeds max_step_rate" % step_rate)
        offset += item.duration
    return plan, offset


class MotorMusic:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.names = {}
        for voice, key in enumerate(("voice_x", "voice_y", "voice_z")):
            name = config.get(key, None)
            if name is not None:
                if name not in ("stepper_x", "stepper_y", "stepper_z"):
                    raise config.error("%s must name a Cartesian axis stepper" % key)
                self.names[voice] = name
        if not self.names or len(set(self.names.values())) != len(self.names):
            raise config.error("Map at least one voice; each motor may be mapped once")
        if config.getsection("printer").get("kinematics") != "cartesian":
            raise config.error("motor_music currently requires Cartesian kinematics")
        for name in self.names.values():
            if config.has_section(name + "1"):
                raise config.error("motor_music does not support multi-driver axes")
        self.amplitude_steps = config.getint("amplitude_steps", 1, minval=1, maxval=32)
        self.max_frequency = config.getfloat("max_frequency", 1000.0, minval=30, maxval=2000)
        self.max_excursion = config.getfloat("max_excursion", 0.1, above=0, maxval=0.5)
        self.max_step_rate = config.getfloat("max_step_rate", 2000.0, above=0, maxval=100000)
        self.max_duration = config.getfloat("max_duration", 15.0, above=0, maxval=30)
        self.margin = config.getfloat("position_margin", 1.0, minval=0.1)
        self.allow_during_print = config.getboolean("allow_during_print", False)
        config_dir = os.path.dirname(self.printer.get_start_args()["config_file"])
        self.tune_dir = os.path.realpath(os.path.expanduser(
            config.get("tune_directory", os.path.join(config_dir, "tunes"))))
        self.sequence = Sequence(self.max_duration)
        self.last_result = None
        for name in ("M1006", "MOTOR_MUSIC_PLAY", "MOTOR_MUSIC_TEST", "MOTOR_MUSIC_CLEAR"):
            self.gcode.register_command(name, getattr(self, "cmd_" + name))
        self.printer.register_event_handler("klippy:connect", self._connect)
        self.printer.register_event_handler("klippy:shutdown", self.sequence.reset)

    def _connect(self):
        import chelper
        self.ffi, self.lib = chelper.get_ffi()
        self.toolhead = self.printer.lookup_object("toolhead")
        self.enable = self.printer.lookup_object("stepper_enable")
        self.mq = self.printer.lookup_object("motion_queuing", None)
        steppers = {s.get_name(): s for s in self.toolhead.get_kinematics().get_steppers()}
        self.motors, self.queues, self.solvers = {}, {}, {}
        for voice, name in self.names.items():
            stepper = steppers[name]
            self.motors[voice] = stepper
            self.queues[voice] = (self.mq.allocate_trapq() if self.mq is not None else
                                  self.ffi.gc(self.lib.trapq_alloc(), self.lib.trapq_free))
            self.solvers[voice] = self.ffi.gc(self.lib.cartesian_stepper_alloc(b"x"), self.lib.free)
        self.append = (self.mq.lookup_trapq_append() if self.mq is not None
                       else self.lib.trapq_append)
        self.axis_limits = {}
        settings = self.printer.lookup_object("configfile").get_status(0)["settings"]
        for name in self.names.values():
            axis = settings[name]
            self.axis_limits[name] = (axis.get("position_min", 0), axis["position_max"])

    def _plan(self, slices, motors):
        return build_plan(slices, {v: s.get_step_dist() for v, s in motors.items()},
                          self.amplitude_steps, self.max_frequency,
                          self.max_excursion, self.max_step_rate)

    def _check_position(self, motors):
        now = self.printer.get_reactor().monotonic()
        status = self.toolhead.get_status(now)
        if set(status["homed_axes"]) != set("xyz"):
            raise MusicError("Home XYZ and park clear of the endstops before playing")
        stats = self.printer.lookup_object("print_stats", None)
        if (not self.allow_during_print and stats is not None
                and stats.get_status(now)["state"] in ("printing", "paused")):
            raise MusicError("Music during a print is disabled (allow_during_print)")
        position = self.toolhead.get_position()
        for motor in motors.values():
            name = motor.get_name()
            if not self.enable.lookup_enable(name).is_motor_enabled():
                raise MusicError("%s must already be enabled" % name)
            index = "xyz".index(name[-1])
            lower, upper = self.axis_limits[name]
            excursion = self.amplitude_steps * motor.get_step_dist()
            if not lower + self.margin <= position[index] <= upper - self.margin - excursion:
                raise MusicError("Park %s away from its limits before playing" % name)

    def _play(self, slices, gcmd, dry_run=False, voices=None):
        selected = select_voices(voices, self.names)
        motors = {v: self.motors[v] for v in selected}
        voice_names = "".join(VOICES[v] for v in selected)
        plan, duration = self._plan(slices, motors)  # Validate before motion.
        if duration > self.max_duration + 1e-9:
            raise MusicError("Melody exceeds %.2f seconds" % self.max_duration)
        if not any(plan.values()):
            raise MusicError("No audible notes on the configured voices")
        segments = sum(map(len, plan.values()))
        if dry_run:
            gcmd.respond_info("Music preview: %.3fs, %d segments, voices=%s, no motion" %
                              (duration, segments, voice_names))
            return
        self._check_position(motors)
        self.toolhead.wait_moves()
        self.toolhead.flush_step_generation()
        self._check_position(motors)
        saved = []
        try:
            # Attach every voice before queuing so they share the same clock.
            for voice, motor in motors.items():
                old_pos = motor.get_mcu_position()
                old_solver = motor.set_stepper_kinematics(self.solvers[voice])
                old_queue = motor.set_trapq(self.queues[voice])
                saved.append((voice, motor, old_solver, old_queue, old_pos))
                motor.set_position((0.0, 0.0, 0.0))
            start = self.toolhead.get_last_move_time()
            for voice, segments_for_voice in plan.items():
                queue = self.queues[voice]
                for segment in segments_for_voice:
                    self.append(queue, start + segment.time, 0.0, segment.duration, 0.0,
                                segment.position, 0.0, 0.0, segment.direction, 0.0, 0.0,
                                0.0, segment.velocity, 0.0)
            end = start + duration
            if self.mq is None:
                for motor in motors.values():
                    motor.generate_steps(end)
                # v0.13's toolhead calls every registered step generator while
                # advancing its clock. Restore first, exactly as force_move
                # does, so it cannot revisit this already-generated waveform.
                self._restore_motors(saved)
                self.toolhead.note_mcu_movequeue_activity(end)
            else:
                self.mq.note_mcu_movequeue_activity(end)
            self.toolhead.dwell(duration)
            self.toolhead.flush_step_generation()
        except Exception:
            # Once queuing starts an error can leave a partial oscillation.
            # Do not resume printing with potentially stale physical position.
            self.printer.invoke_shutdown("motor_music: interrupted low-level motion")
            raise
        finally:
            self._restore_motors(saved)
        self.toolhead.wait_moves()
        self.last_result = {"duration": duration, "segments": segments, "voices": voice_names}
        gcmd.respond_info("Music complete: %.3fs, %d segments, voices=%s" %
                          (duration, segments, voice_names))

    def _restore_motors(self, saved):
        mismatches = []
        while saved:
            voice, motor, old_solver, old_queue, old_pos = saved.pop()
            motor.set_trapq(old_queue)
            motor.set_stepper_kinematics(old_solver)
            if self.mq is None:
                self.lib.trapq_finalize_moves(self.queues[voice], 1.0e16, 1.0e16)
            else:
                self.mq.wipe_trapq(self.queues[voice])
            if motor.get_mcu_position() != old_pos:
                mismatches.append(motor.get_name())
        if mismatches:
            self.printer.invoke_shutdown("motor_music: nonzero net step count")
            raise MusicError("Nonzero net step count; printer shut down")

    def cmd_M1006(self, gcmd):
        try:
            slices = self.sequence.feed(fields_from_line(gcmd.get_commandline()))
            if slices is not None:
                self._play(slices, gcmd)
        except MusicError as exc:
            self.sequence.reset()
            raise gcmd.error(str(exc))

    def cmd_MOTOR_MUSIC_PLAY(self, gcmd):
        try:
            name = gcmd.get("FILENAME")
            path = os.path.realpath(os.path.join(self.tune_dir, name))
            if os.path.isabs(name) or os.path.commonpath((path, self.tune_dir)) != self.tune_dir:
                raise MusicError("FILENAME must stay inside tune_directory")
            with open(path, "r", encoding="utf-8") as stream:
                text = stream.read(MAX_FILE_BYTES + 1)
            slices = parse_gcode(text, self.max_duration)
            self._play(slices, gcmd, bool(gcmd.get_int("DRY_RUN", 0, minval=0, maxval=1)),
                       voices=gcmd.get("VOICES", None))
        except (MusicError, OSError, UnicodeError) as exc:
            raise gcmd.error(str(exc))

    def cmd_MOTOR_MUSIC_TEST(self, gcmd):
        try:
            voice = gcmd.get("VOICE", "Y").upper()
            if voice not in VOICES or len(voice) != 1 or VOICES.index(voice) not in self.names:
                raise MusicError("VOICE must be a configured X, Y, or Z voice")
            note = gcmd.get_int("NOTE", 46, minval=1, maxval=72)
            duration = gcmd.get_int("DURATION", 200, minval=10, maxval=1000) / 1000.0
            tones = [Tone(0, duration, 0) for _ in range(3)]
            tones[VOICES.index(voice)] = Tone(note, duration, 100)
            self._play((Slice(tuple(tones), duration),), gcmd,
                       bool(gcmd.get_int("DRY_RUN", 0, minval=0, maxval=1)), voices=voice)
        except MusicError as exc:
            raise gcmd.error(str(exc))

    def cmd_MOTOR_MUSIC_CLEAR(self, gcmd):
        self.sequence.reset()
        gcmd.respond_info("Buffered melody cleared")

    def get_status(self, eventtime):
        return {"buffering": self.sequence.active, "buffered_duration": self.sequence.duration,
                "voices": {VOICES[v]: name for v, name in self.names.items()},
                "last_result": self.last_result}


def load_config(config):
    return MotorMusic(config)
