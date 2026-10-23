# SPDX-License-Identifier: GPL-3.0-or-later
import math
import configparser
import pathlib
import unittest

from motor_music import MusicError, Sequence, build_plan, fields_from_line, note_frequency, parse_gcode


def melody(body):
    return "M1006 S1\n" + body + "\nM1006 W\n"


class ParserTests(unittest.TestCase):
    def test_bambu_note_encoding(self):
        self.assertAlmostEqual(note_frequency(37), 261.6255653006)
        self.assertEqual(note_frequency(46), 440)
        self.assertEqual(note_frequency(0), 0)

    def test_compact_parameters_and_comments(self):
        self.assertEqual(fields_from_line("m1006 C37D20M60 ; note"), {"C": 37, "D": 20, "M": 60})

    def test_stereo_timing_uses_longest_voice(self):
        tune = parse_gcode(melody("M1006 A37 B10 C41 D20 E44 F15"))
        self.assertEqual(tune[0].duration, .2)
        self.assertEqual([t.duration for t in tune[0].tones], [.1, .2, .15])

    def test_volumes_persist_but_notes_do_not(self):
        tune = parse_gcode(melody("M1006 L70 M60 N50\nM1006 C37 D10\nM1006 A0 B10"))
        self.assertEqual(tune[0].tones[1].volume, 60)
        self.assertEqual(tune[1].tones[1].note, 0)

    def test_original_wrappers_are_accepted(self):
        text = "M17\nM400 S1\n" + melody("M73 P0 R1\nM1006 C37 D10") + "M18 X Y Z\n"
        self.assertEqual(parse_gcode(text)[0].tones[1].note, 37)

    def test_arbitrary_motion_and_heaters_are_rejected(self):
        for command in ["G1 X100", "M104 S200", "M17 X0.8", "M400 S5", "M84", "M10060 S1"]:
            with self.subTest(command=command), self.assertRaises(MusicError):
                parse_gcode("M17\n" + melody("M1006 C37 D10") + command)

    def test_bad_parameters_fail_before_any_output(self):
        for command in ["M1006 C37 C40 D10", "M1006 C37", "M1006 D10", "M1006 C73 D10",
                        "M1006 C-1 D10", "M1006 C37 D201", "M1006 C37 D-1", "M1006 C37 D0",
                        "M1006 C37.5 D10", "M1006 Cnan D10", "M1006 C37 D10 M101",
                        "M1006 C37 D10 M-1", "M1006 Q1", "M1006", "M1006 W1", "M1006 W C37 D10"]:
            with self.subTest(command=command), self.assertRaises(MusicError):
                parse_gcode(melody(command))

    def test_error_clears_pending_sequence(self):
        seq = Sequence()
        seq.feed({"S": 1})
        seq.feed({"C": 37, "D": 10})
        with self.assertRaises(MusicError):
            seq.feed({"C": 100, "D": 10})
        self.assertFalse(seq.active)
        self.assertEqual(seq.slices, [])

    def test_unterminated_duplicate_and_missing_start_rejected(self):
        texts = ["M1006 C37 D10\nM1006 W", "M1006 S1\nM1006 C37 D10",
                 melody("M1006 C37 D10") * 2, "M1006 S1\n" + melody("M1006 C37 D10")]
        for text in texts:
            with self.subTest(text=text), self.assertRaises(MusicError):
                parse_gcode(text)

    def test_duration_and_file_size_bounds(self):
        with self.assertRaises(MusicError):
            parse_gcode(melody("M1006 C37 D20"), max_duration=.1)
        with self.assertRaises(MusicError):
            parse_gcode(";" * (128 * 1024 + 1))
        for duration in [float("nan"), float("inf"), 0, 31]:
            with self.assertRaises(MusicError):
                Sequence(duration)


class OscillatorTests(unittest.TestCase):
    def test_pitch_exact_and_each_cycle_has_zero_net_distance(self):
        tune = parse_gcode(melody("M1006 C46 D20 M100"))
        plan, duration = build_plan(tune, {1: .0125})
        self.assertEqual(duration, .2)
        segments = plan[1]
        self.assertEqual(len(segments), 176)  # 88 full A4 cycles.
        for up, down in zip(segments[::2], segments[1::2]):
            self.assertAlmostEqual(up.duration + down.duration, 1 / 440)
            self.assertAlmostEqual(up.velocity * up.duration, .0125)
            self.assertAlmostEqual(down.position - down.velocity * down.duration, 0)
        self.assertLessEqual(segments[-1].time + segments[-1].duration, duration + 1e-12)

    def test_three_voices_start_together_and_return_before_next_slice(self):
        tune = parse_gcode(melody("M1006 A37 B10 C41 D20 E44 F15\nM1006 A37 B10 C41 D10 E44 F10"))
        plan, duration = build_plan(tune, {0: .0125, 1: .0125, 2: .0025}, max_step_rate=8000)
        self.assertAlmostEqual(duration, .3)
        for segments in plan.values():
            self.assertEqual(segments[0].time, 0)
            self.assertTrue(any(abs(s.time - .2) < 1e-12 for s in segments))
            self.assertAlmostEqual(sum(s.direction * s.velocity * s.duration for s in segments), 0)

    def test_rests_and_volume_zero_preserve_timeline(self):
        tune = parse_gcode(melody("M1006 C0 D10\nM1006 C46 D10 M0\nM1006 C46 D10 M100"))
        plan, duration = build_plan(tune, {1: .0125})
        self.assertAlmostEqual(duration, .3)
        self.assertAlmostEqual(plan[1][0].time, .2)

    def test_silent_unmapped_high_notes_do_not_trigger_frequency_limit(self):
        tune = parse_gcode(melody("M1006 A72 B10 C46 D10"))
        build_plan(tune, {1: .0125})
        with self.assertRaises(MusicError):
            build_plan(tune, {0: .0125})

    def test_excursion_volume_and_bandwidth_limits(self):
        tune = parse_gcode(melody("M1006 C46 D10 M50"))
        plan, _ = build_plan(tune, {1: .0125}, amplitude_steps=4)
        self.assertEqual(plan[1][1].position, .025)
        for kwargs in [{"max_step_rate": 500}, {"amplitude_steps": 32},
                       {"max_frequency": math.nan}, {"max_excursion": math.inf}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(MusicError):
                build_plan(tune, {1: .0125}, **kwargs)

    def test_stock_a1_melodies_fit_default_single_voice_limits(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        for name in ["a1-start.gcode", "a1-finish.gcode"]:
            with self.subTest(name=name):
                tune = parse_gcode((root / "examples" / "tunes" / name).read_text())
                plan, duration = build_plan(tune, {1: .0125})
                self.assertGreater(len(plan[1]), 0)
                self.assertLess(duration, 3)

    def test_stock_a1_melodies_fit_full_three_voice_profile(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        config = configparser.ConfigParser()
        config.read(str(root / "examples/motor_music_3voice.cfg"))
        settings = config["motor_music"]
        self.assertEqual([settings["voice_" + v] for v in "xyz"],
                         ["stepper_" + v for v in "xyz"])
        for name in ["a1-start.gcode", "a1-finish.gcode"]:
            with self.subTest(name=name):
                tune = parse_gcode((root / "examples/tunes" / name).read_text())
                plan, duration = build_plan(
                    tune, {0: .0125, 1: .0125, 2: .0025},
                    amplitude_steps=settings.getint("amplitude_steps"),
                    max_step_rate=settings.getfloat("max_step_rate"))
                self.assertTrue(all(plan.values()))
                self.assertLess(duration, 3)


if __name__ == "__main__":
    unittest.main()
