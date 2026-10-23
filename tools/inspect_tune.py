#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspect a Bambu sound-only file without connecting to Klipper."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from motor_music import MusicError, build_plan, parse_gcode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=pathlib.Path)
    parser.add_argument("--voice", choices=list("XYZ"), default="Y")
    parser.add_argument("--step-distance", type=float, default=.0125,
                        help="mm per configured microstep (Ender XY default: 0.0125)")
    args = parser.parse_args()
    try:
        slices = parse_gcode(args.file.read_text())
        voice = "XYZ".index(args.voice)
        plan, duration = build_plan(slices, {voice: args.step_distance})
        print(json.dumps({"duration_seconds": duration, "slices": len(slices),
                          "voice": args.voice, "segments": len(plan[voice]),
                          "maximum_excursion_mm": max((s.position for s in plan[voice]), default=0),
                          "net_distance_mm": sum(s.direction * s.velocity * s.duration
                                                 for s in plan[voice])}, indent=2))
    except (MusicError, OSError) as exc:
        parser.exit(1, "%s\n" % exc)


if __name__ == "__main__":
    main()
